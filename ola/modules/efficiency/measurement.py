"""Efficiency measurement (see ``ola/efficiency_spec.py`` for the parameters, ``docs/efficiency.md``
for the user guide).

For every point of the sweep:

1. set the parameters that changed, in the order of the list (the first one first); at the very
   first point everything is set, then the ``startup`` calls (outputs on) are made;
2. wait ``settle_s``;
3. take ``samples`` readings of every reading, ``interval_s`` apart (scheduled from the first one,
   so a slow instrument does not shift the others); each one is stored in the ``samples`` table;
4. the point is the **average** of each reading; the formulas are computed on the averages and the
   row goes to the ``points`` table.

A parameter with ``verify`` is compared with the setpoint on every sample; if it is off by more
than the tolerance the measurement stops and asks (retry / abort / skip), or only warns, or fails,
depending on ``on_fail``. *Skip* is remembered while the setpoint stays the same (the points are
still flagged ``verify_skipped``); a new setpoint is checked and asked about again.
At the end, or after any error or stop, the ``shutdown`` calls are made.
"""

import statistics
import time

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
        used = set()
        for var in self._spec.variables.values():
            if var.set:
                used.add(var.set.instrument)
            used.update(r.instrument for r in var.reads.values())
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
        """Walk the sweep: set, settle, sample, average, publish."""
        spec = self._spec
        setters = [v for v in spec.variables.values() if v.set is not None]
        total = spec.point_count()
        last = {}  # last value sent for every parameter
        self._accepted = {}  # parameter -> setpoint whose mismatch the user chose to skip
        started = False
        for index, point in enumerate(iter_points(spec.axes)):
            ctx.checkpoint()
            targets = {v.name: point.get(v.name, v.value) for v in setters}
            attempt = 1
            while True:
                self._apply(setters, targets, last)
                if not started:
                    self._calls(spec.startup)
                    started = True
                ctx.sleep(spec.timing.settle_s)
                result = self._sample_point(ctx, index, attempt, targets)
                if result is not None:
                    break
                last.clear()  # retry: set every parameter again
                attempt += 1
            means, skipped = result
            row = {**targets, **means, "n_samples": spec.timing.samples}
            if skipped:
                row["verify_skipped"] = ",".join(sorted(skipped))
            ctx.emit_point(row)
            ctx.progress(index + 1, total, f"point {index + 1} of {total}")

    def teardown(self, ctx: MeasurementContext) -> None:
        """Make every ``shutdown`` call even if one fails; then raise the first error."""
        spec = getattr(self, "_spec", None)
        if spec is None:
            try:
                spec = parse_params(self.params)
            except SpecError:
                return
        handles = {h.name: h for h in ctx.instruments("instruments")}
        first_error = None
        for call in spec.shutdown:
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
