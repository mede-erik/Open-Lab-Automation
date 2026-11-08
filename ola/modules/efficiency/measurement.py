"""Efficiency measurement (see ``ola/efficiency_spec.py`` for the parameters, ``docs/efficiency.md``
for the user guide).

Before touching anything: if an output that this measurement will switch off at the end is already
on (it needs a ``state`` call to know), the user is asked -- continue, or stop to change the file.
If the user stops here nothing has been touched and nothing is switched off.

Start (before the first point): every parameter is set; the outputs marked ``always_on`` are
checked and switched on only if they are off (an output that is already on is left alone); then the
other outputs are switched on in the ``power_order``; then the ``startup`` calls.

For every point of the sweep:

1. set the parameters that changed, in the order of the list (the first one first);
2. wait ``settle_s``;
3. take ``samples`` readings of every reading, ``interval_s`` apart (scheduled from the first one,
   so a slow instrument does not shift the others); each one is stored in the ``samples`` table;
4. the point is the **average** of each reading; the formulas are computed on the averages and the
   row goes to the ``points`` table.

Cooldown: each time the innermost sweep has done its whole run and an outer parameter advances
(never between the points of the innermost sweep), if ``cooldown_s`` is set, the outputs marked
``off_during_cooldown`` are switched off, the measurement waits ``cooldown_s`` (a stop interrupts
it), then those parameters are set again and switched on again.

A parameter with ``verify`` is compared with the setpoint on every sample; if it is off by more
than the tolerance the measurement stops and asks (retry / abort / skip), or only warns, or fails,
depending on ``on_fail``. *Skip* is remembered while the setpoint stays the same (the points are
still flagged ``verify_skipped``); a new setpoint is checked and asked about again.

At the end, and after any error or stop, the ``shutdown`` calls are made and the outputs are
switched off in the reverse ``power_order`` -- except those marked ``always_on``, which this
measurement never switches off (for example an auxiliary supply that keeps a microcontroller
without non-volatile memory alive).
"""

import statistics
import time

from ola.golden import finish, recording
from ola.efficiency_spec import SpecError, parse_params, validate_params
from ola.measurement import Measurement, MeasurementContext, MeasurementError, Stopped
from ola.sweep import iter_points


class Efficiency(Measurement):
    """Efficiency (or any quantity computed from set and read parameters) over a sweep."""

    def validate(self):
        """Parameter problems that stop the measurement from starting, as text."""
        return [str(p) for p in validate_params(self.params) if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Parse the parameters and find the instrument of every call, before touching anything."""
        try:
            self._spec = parse_params(self.params)
        except SpecError as exc:
            raise MeasurementError(str(exc)) from exc
        self._handles = {h.name: h for h in ctx.instruments("instruments")}
        self._touched = False  # becomes True when the first instrument is changed
        used = set()
        for var in self._spec.variables.values():
            if var.set:
                used.add(var.set.instrument)
            used.update(r.instrument for r in var.reads.values())
        for var in self._spec.variables.values():
            if var.output:
                used.update(
                    c.instrument for c in (var.output.on, var.output.off, var.output.state) if c
                )
        used.update(c.instrument for c in self._spec.startup + self._spec.shutdown)
        missing = sorted(used - set(self._handles))
        if missing:
            raise MeasurementError(
                f"these instruments are not bound to the measurement: {', '.join(missing)} "
                f"(bound: {', '.join(sorted(self._handles)) or 'none'})"
            )

    def derived(self, values):
        """The formulas of the ``derived`` section, computed on the averaged point."""
        spec = getattr(self, "_spec", None)
        if spec is None:
            return {}
        env = dict(values)
        out = {}
        for name, formula in spec.derived.items():
            env[name] = out[name] = formula.evaluate(env)  # None if it cannot be computed
        return out

    # ----- the measurement ------------------------------------------------------------------
    def run(self, ctx: MeasurementContext) -> None:
        """Walk the sweep: set, settle, sample, average, publish; rest between the sweeps."""
        # with a golden sample: the averaged points (with the derived columns) at the end
        ctx = recording(ctx, "efficiency", self.params, summary_row=False, derive=self.derived)
        spec = self._spec
        setters = [v for v in spec.variables.values() if v.set is not None]
        total = spec.point_count()
        last = {}  # last value sent for every parameter
        self._accepted = {}  # parameter -> setpoint whose mismatch the user chose to skip
        always_on = [
            v for v in spec.variables.values() if v.output and v.output.mode == "always_on"
        ]
        managed = [spec.variables[name] for name in spec.power_order]
        cooled = [v for v in managed if v.output.mode == "off_during_cooldown"]
        sweep_length = spec.sweep_length()
        powered_down = False
        started = False
        self._confirm_outputs_already_on(ctx)
        self._touched = True  # from here on teardown has things to put back
        for index, point in enumerate(iter_points(spec.axes)):
            ctx.checkpoint()
            if index and spec.cooldown_count() and index % sweep_length == 0:
                self._cooldown(ctx, cooled, last, index // sweep_length, total)
                powered_down = bool(cooled)
            targets = {v.name: point.get(v.name, v.value) for v in setters}
            attempt = 1
            while True:
                self._apply(setters, targets, last)
                if not started:
                    for var in always_on + managed:
                        self._ensure_on(ctx, var)
                    self._calls(spec.startup)
                    started = True
                elif powered_down:
                    self._outputs_on(cooled)
                    powered_down = False
                ctx.sleep(spec.timing.settle_s)
                result = self._sample_point(ctx, index, attempt, targets)
                if result is not None:
                    break
                last.clear()  # retry: set every parameter again
                attempt += 1
            means, skipped = result
            row = {**targets, **means, "n_samples": spec.timing.samples}
            if sweep_length:
                row["sweep"] = index // sweep_length
            if skipped:
                row["verify_skipped"] = ",".join(sorted(skipped))
            ctx.emit_point(row)
            ctx.progress(index + 1, total, f"point {index + 1} of {total}")
        finish(ctx)

    def teardown(self, ctx: MeasurementContext) -> None:
        """Make the ``shutdown`` calls, then switch the outputs off in reverse order.

        Every call is made even if an earlier one fails (the other outputs must still be switched
        off); the first error is raised at the end. Outputs marked ``always_on`` are never touched.
        """
        if not getattr(self, "_touched", False):
            return  # nothing was changed (set-up failed, or the user stopped at the first question)
        spec = self._spec
        handles = {h.name: h for h in ctx.instruments("instruments")}
        calls = list(spec.shutdown)
        for name in reversed(spec.power_order):
            output = spec.variables[name].output
            if output.mode != "always_on" and output.off:
                calls.append(output.off)
        # (outputs that have an 'off' call but no 'on' call are not in the power order)
        for var in reversed(list(spec.variables.values())):
            output = var.output
            if output and output.mode != "always_on" and output.off and not output.on:
                calls.append(output.off)
        first_error = None
        for call in calls:
            try:
                handles[call.instrument].call(call.call, **call.args)
            except Exception as exc:  # keep going: the other outputs must still be switched off
                ctx.log(f"shutdown {call.instrument}.{call.call} failed: {exc}", "error")
                first_error = first_error or exc
        if first_error is not None:
            raise first_error

    # ----- steps of a point -------------------------------------------------------------------
    def _calls(self, calls) -> None:
        for call in calls:
            self._handles[call.instrument].call(call.call, **call.args)

    def _confirm_outputs_already_on(self, ctx) -> None:
        """Warn the user about outputs that are on now but will be switched off at the end.

        Only outputs with a ``state`` call can be checked. One question lists them all; the choices
        are ``continue`` or ``abort`` (to change the file). Nothing has been changed yet."""
        already = [
            var
            for var in self._spec.variables.values()
            if var.output
            and var.output.mode != "always_on"
            and var.output.off
            and var.output.state
            and self._is_on(var, var.output.state)
        ]
        if not already:
            return
        names = ", ".join(f"'{v.name}' ({v.output.off.instrument})" for v in already)
        text = (
            f"These outputs are already on and will be switched off when the measurement ends: "
            f"{names}. Continue, or stop to change the file?"
        )
        data = {
            "outputs": [
                {
                    "variable": v.name,
                    "instrument": v.output.off.instrument,
                    "off": v.output.off.call,
                }
                for v in already
            ]
        }
        if ctx.ask(text, ["continue", "abort"], default="abort", data=data) == "abort":
            raise Stopped()

    def _outputs_on(self, variables) -> None:
        """Switch the outputs on, in the given order (no question asked)."""
        for var in variables:
            if var.output.on:
                self._calls([var.output.on])

    def _outputs_off(self, variables) -> None:
        """Switch the outputs off, in the reverse of the given order."""
        for var in reversed(variables):
            if var.output.off:
                self._calls([var.output.off])

    def _ensure_on(self, ctx, var) -> None:
        """Switch the output of ``var`` on, unless it is already on (if it can be asked)."""
        output = var.output
        if output.state is not None and self._is_on(var, output.state):
            ctx.log(f"output of '{var.name}' is already on: left as it is")
            return
        if output.on:
            self._calls([output.on])

    def _is_on(self, var, state_call) -> bool:
        """Ask an output whether it is on. Understands booleans, numbers and ON/OFF, 1/0 text."""
        value = self._handles[state_call.instrument].call(state_call.call, **state_call.args)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str) and value.strip().upper() in ("1", "ON", "TRUE"):
            return True
        if isinstance(value, str) and value.strip().upper() in ("0", "OFF", "FALSE"):
            return False
        raise MeasurementError(
            f"cannot tell if the output of '{var.name}' is on: {state_call.instrument}."
            f"{state_call.call} answered {value!r}"
        )

    def _cooldown(self, ctx, cooled, last, sweeps_done, total) -> None:
        """Rest between two sweeps: switch the cooled outputs off and wait (back on afterwards)."""
        seconds = self._spec.timing.cooldown_s
        ctx.log(f"cooldown of {seconds:g} s after sweep {sweeps_done} of the innermost parameter")
        self._outputs_off(cooled)
        for var in cooled:
            last.pop(var.name, None)  # set again before it is switched on again
        ctx.progress(self._done_points(sweeps_done), total, f"cooling down {seconds:g} s")
        ctx.sleep(seconds)

    def _done_points(self, sweeps_done) -> int:
        return sweeps_done * self._spec.sweep_length()

    def _apply(self, setters, targets, last) -> None:
        """Set the parameters whose value changed, in the order of the list."""
        for var in setters:
            value = targets[var.name]
            if var.name in last and last[var.name] == value:
                continue
            s = var.set
            self._handles[s.instrument].call(s.call, **{**s.args, s.value_arg: value})
            last[var.name] = value

    def _read_all(self) -> dict:
        reading = {}
        for var in self._spec.variables.values():
            for label, r in var.reads.items():
                raw = self._handles[r.instrument].call(r.call, **r.args)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    raise MeasurementError(
                        f"reading {var.name}@{label} ({r.instrument}.{r.call}): "
                        f"expected a number, got {raw!r}"
                    )
                reading[f"{var.name}@{label}"] = raw * r.scale + r.offset
        return reading

    def _sample_point(self, ctx, index, attempt, targets):
        """Take the samples of one point. Returns ``(means, skipped)``, or ``None`` to retry."""
        timing = self._spec.timing
        samples, skipped = [], set()
        first = time.monotonic()
        for k in range(timing.samples):
            ctx.checkpoint()
            reading = self._read_all()
            samples.append(reading)
            ctx.emit_point(
                {"point": index, "attempt": attempt, "sample": k, **targets, **reading},
                table="samples",
            )
            if self._verify(ctx, index, k, targets, reading, skipped) == "retry":
                return None
            if k < timing.samples - 1:
                ctx.sleep(max(0.0, first + (k + 1) * timing.interval_s - time.monotonic()))
        means = {key: statistics.fmean(s[key] for s in samples) for key in samples[0]}
        return means, skipped

    def _verify(self, ctx, index, k, targets, reading, skipped):
        """Compare the verified parameters with their setpoint; ask / warn / stop if they differ."""
        for var in self._spec.variables.values():
            v = var.verify
            if v is None or var.name in skipped:
                continue
            set_value, read_value = targets[var.name], reading[f"{var.name}@{v.read}"]
            error = abs(read_value - set_value)
            if error <= v.tol_abs + v.tol_rel * abs(set_value):
                continue
            if self._accepted.get(var.name) == set_value:
                skipped.add(var.name)  # already skipped for this setpoint: flag it, do not ask
                continue
            relative = error / abs(set_value) if set_value else None
            how = f"{relative * 100:.1f}%" if relative is not None else f"{error:g} (set value 0)"
            text = (
                f"'{var.name}' read by {v.read} ({read_value:g}) differs from the set value "
                f"({set_value:g}) by {how}; allowed: {v.tol_abs:g} + {v.tol_rel * 100:g}%"
            )
            data = {
                "variable": var.name, "reading": v.read, "set_value": set_value,
                "read_value": read_value, "error_abs": error, "error_rel": relative,
                "tol_abs": v.tol_abs, "tol_rel": v.tol_rel, "point": index, "sample": k,
            }  # fmt: skip
            if v.on_fail == "stop":
                raise MeasurementError(text)
            if v.on_fail == "warn":
                ctx.log(text, "warning")
                skipped.add(var.name)
                continue
            choice = ctx.ask(text, ["retry", "abort", "skip"], default="abort", data=data)
            if choice == "retry":
                return "retry"
            if choice == "abort":
                raise Stopped()
            skipped.add(var.name)  # skip: carry on; ask again only if the setpoint changes
            self._accepted[var.name] = set_value
        return None
