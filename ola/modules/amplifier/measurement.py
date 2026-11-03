"""An RF amplifier with a VNA: gain, match, isolation, stability and compression.

Parameters (``.amp`` file)::

    {"device": {"label": "LNA #1"},
     "sweep": {"start_hz": 700e6, "stop_hz": 1050e6, "points": 351, "scale": "linear",
               "power_dbm": -30},                       # the VNA source power: keep it LOW
     "input_attenuation_db": 0, "max_input_dbm": 0,      # optional protection (below)
     "passband": {"from_hz": 820e6, "to_hz": 920e6},     # optional, the whole sweep by default
     "gain_edge_db": 3,                                  # optional
     "frequencies_of_interest": [868e6],                 # optional
     "compression": {"frequency_hz": 868e6, "start_dbm": -40, "stop_dbm": -10, "step_db": 1,
                     "compression_db": 1},               # optional: the compression point
     "limits": {"min": 18},                              # optional: a mask on the gain in dB
     "averages": 1, "confirm_setup": true}

The amplifier goes between port 1 and port 2 of the VNA, calibrated beforehand by the user *with
the attenuators that will be in the test*. All four S-parameters are read (see
``docs/vna-calls.md``); the gain is S21 in dB, the input and output return loss are S11 and S22, the
reverse isolation is ``-S12`` in dB, and the **stability** comes from the four together
(``ola.rf.two_port_stability``): the Rollett factor K, |delta| and the geometric factor mu. A value
of mu above 1 at every frequency (equivalently K above 1 and |delta| below 1) means that the
amplifier cannot oscillate with any passive source and load, *inside the sweep*.

**Protection.** A VNA source can overdrive an amplifier and an amplifier can overdrive a VNA
port. ``sweep.power_dbm`` is the source power; with ``input_attenuation_db`` (an attenuator in front
of the amplifier) the power at the amplifier input is lower by that much. If ``max_input_dbm`` is
given, a sweep or a compression test that would go above it is an error and nothing is sent. The
set-up question reminds the user of both limits. After a compression test the source power is put
back to ``sweep.power_dbm``, also if the test is stopped or fails.

**Compression.** At ``compression.frequency_hz`` the source power is stepped from ``start_dbm`` to
``stop_dbm`` (VNA powers; the power at the amplifier is lower by ``input_attenuation_db``) and the
gain read at every step. The small-signal gain is the one at the lowest power; the compression point
is where the gain has fallen ``compression_db`` (1 by default) below it, with the input and the
output power there. If it is not reached the log says to raise ``stop_dbm``.
"""

from typing import Any, Dict, List, Optional

from ola import rf
from ola.efficiency_spec import Problem
from ola.limits import parse_limits
from ola.measurement import Measurement, MeasurementContext, MeasurementError
from ola.run_view import format_si
from ola.vna_common import (
    as_trace,
    acquire,
    ask_setup,
    check_common,
    check_sweep,
    frequency_label,
    is_number,
    set_sweep,
)

DEFAULT_EDGE_DB = 3.0
NARROW_SPAN = 1e-3  # the compression test sweeps +-0.1 % around its frequency (3 points)
MAX_POWER_POINTS = 200


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new amplifier measurement (used by the editor)."""
    return {
        "device": {"label": ""},
        "sweep": {
            "start_hz": 1e6, "stop_hz": 3e9, "points": 401, "scale": "linear", "power_dbm": -30,
        },  # fmt: skip
        "input_attenuation_db": 0,
        "gain_edge_db": DEFAULT_EDGE_DB,
        "frequencies_of_interest": [],
        "averages": 1,
        "confirm_setup": True,
    }


def power_steps(compression: Dict[str, Any]) -> List[float]:
    """The source powers of the compression test: ``start_dbm`` to ``stop_dbm`` in ``step_db``."""
    start, stop, step = compression["start_dbm"], compression["stop_dbm"], compression["step_db"]
    count = int(round((stop - start) / step)) + 1
    return [round(start + k * step, 6) for k in range(count)]


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    start, stop = check_sweep(params, out)
    sweep = params.get("sweep") if isinstance(params.get("sweep"), dict) else {}
    device = params.get("device", {})
    if not isinstance(device, dict):
        out.append(Problem("device", "must be an object with a 'label'"))
    elif "label" in device and not isinstance(device["label"], str):
        out.append(Problem("device.label", "the label must be text"))

    attenuation = params.get("input_attenuation_db", 0)
    if not is_number(attenuation) or attenuation < 0:
        out.append(Problem("input_attenuation_db", "must be a number of dB, 0 or more"))
        attenuation = 0
    limit = params.get("max_input_dbm")
    if limit is not None and not is_number(limit):
        out.append(Problem("max_input_dbm", "must be a number (dBm)"))
        limit = None
    power = sweep.get("power_dbm")
    if power is None and not out_has(out, "sweep.power_dbm"):
        out.append(
            Problem(
                "sweep.power_dbm",
                "no VNA power is set: the instrument keeps whatever it had, and an amplifier can "
                "be overdriven. Give a low power (for example -30 dBm)",
                "warning",
            )
        )
    elif is_number(power) and limit is not None and power - attenuation > limit:
        out.append(
            Problem(
                "sweep.power_dbm",
                f"{power - attenuation:g} dBm reaches the amplifier, above its maximum input of "
                f"{limit:g} dBm",
            )
        )

    band = params.get("passband")
    if band is not None:
        low, high = (
            (band.get("from_hz"), band.get("to_hz")) if isinstance(band, dict) else (None,) * 2
        )
        if not (is_number(low) and is_number(high) and 0 < low < high):
            out.append(Problem("passband", "needs from_hz below to_hz (Hz)"))
        elif start is not None and stop is not None and (low < start or high > stop):
            out.append(Problem("passband", "must be inside the sweep"))
    if "gain_edge_db" in params and (
        not is_number(params["gain_edge_db"]) or params["gain_edge_db"] <= 0
    ):
        out.append(Problem("gain_edge_db", "must be a number of dB above 0 (3 is usual)"))

    comp = params.get("compression")
    if comp is not None:
        out += _check_compression(comp, start, stop, attenuation, limit)
    check_common(params, out, start, stop)
    return out


def out_has(problems: List[Problem], path: str) -> bool:
    """True if a problem about ``path`` has already been found."""
    return any(p.path == path for p in problems)


def _check_compression(
    comp: Any,
    start: Optional[float],
    stop: Optional[float],
    attenuation: float,
    limit: Optional[float],
) -> List[Problem]:
    if not isinstance(comp, dict):
        return [
            Problem("compression", "must be an object (frequency_hz, start_dbm, stop_dbm, step_db)")
        ]
    out: List[Problem] = []
    f = comp.get("frequency_hz")
    if not is_number(f) or f <= 0:
        out.append(Problem("compression.frequency_hz", "must be a frequency above 0 (Hz)"))
    elif start is not None and stop is not None and not start <= f <= stop:
        out.append(Problem("compression.frequency_hz", "must be inside the sweep"))
    low, high, step = comp.get("start_dbm"), comp.get("stop_dbm"), comp.get("step_db")
    numbers = all(is_number(v) for v in (low, high, step))
    for name, value in (("start_dbm", low), ("stop_dbm", high)):
        if not is_number(value):
            out.append(Problem(f"compression.{name}", "must be a power in dBm"))
    if not is_number(step) or step <= 0:
        out.append(Problem("compression.step_db", "must be a number of dB above 0"))
        numbers = False
    if numbers:
        if low >= high:
            out.append(Problem("compression.stop_dbm", "must be above the start power"))
        elif (high - low) / step + 1 > MAX_POWER_POINTS:
            out.append(
                Problem("compression.step_db", f"too small: more than {MAX_POWER_POINTS} powers")
            )
        if limit is not None and high - attenuation > limit:
            out.append(
                Problem(
                    "compression.stop_dbm",
                    f"{high - attenuation:g} dBm would reach the amplifier, above its maximum "
                    f"input of {limit:g} dBm",
                )
            )
    if "compression_db" in comp and (
        not is_number(comp["compression_db"]) or comp["compression_db"] <= 0
    ):
        out.append(
            Problem("compression.compression_db", "must be a number of dB above 0 (1 is usual)")
        )
    return out


def compute_amplifier(
    freq: List[float], s: Dict[str, List[complex]], params: Dict[str, Any]
) -> Dict[str, Any]:
    """Gain, match, isolation and stability from the four S-parameters. No I/O. ``missing`` lists
    what could not be found (a band edge outside the sweep)."""
    band = params.get("passband")
    edge_db = float(params.get("gain_edge_db", DEFAULT_EDGE_DB))
    gain = rf.magnitude_db(s["S21"])
    inside = [i for i, f in enumerate(freq) if not band or band["from_hz"] <= f <= band["to_hz"]]
    peak = max(range(len(freq)), key=lambda i: gain[i])
    input_rl, output_rl = rf.return_loss_db(s["S11"]), rf.return_loss_db(s["S22"])
    isolation = [-v for v in rf.magnitude_db(s["S12"])]
    stability = rf.two_port_stability(s["S11"], s["S21"], s["S12"], s["S22"])
    summary: Dict[str, Any] = {
        "points": len(freq),
        "peak_gain_db": gain[peak],
        "peak_at_hz": freq[peak],
        "gain_flatness_db": max(gain[i] for i in inside) - min(gain[i] for i in inside),
        "worst_input_return_loss_db": min(input_rl[i] for i in inside),
        "worst_output_return_loss_db": min(output_rl[i] for i in inside),
        "min_isolation_db": min(isolation[i] for i in inside),
        "min_k": min(stability["k"]),
        "min_mu": min(stability["mu"]),
        "min_mu_prime": min(stability["mu_prime"]),
    }
    stable = all(m > 1 for m in stability["mu"]) and all(m > 1 for m in stability["mu_prime"])
    summary["unconditionally_stable"] = "yes" if stable else "no"
    unstable = rf.bands_where(
        freq, [min(a, b) for a, b in zip(stability["mu"], stability["mu_prime"])], 1.0
    )
    if unstable and not stable:
        summary["unstable_bands"] = "; ".join(
            f"{format_si(a, 'Hz')} to {format_si(b, 'Hz')}" for a, b in unstable
        )
    edges = rf.level_crossings(freq, gain, gain[peak] - edge_db)
    low = [f for f, d in edges if d == "rising" and f <= freq[peak]]
    high = [f for f, d in edges if d == "falling" and f >= freq[peak]]
    missing: List[str] = []
    if low and high:
        summary["f_low_hz"], summary["f_high_hz"] = low[-1], high[0]
        summary["bandwidth_hz"] = high[0] - low[-1]
    else:
        missing.append("the lower edge" if not low else "the upper edge")
    for f in params.get("frequencies_of_interest") or []:
        name = frequency_label(f)
        summary[f"gain_{name}_db"] = rf.value_at(freq, gain, f)
    return {
        "gain_db": gain,
        "input_return_loss_db": input_rl,
        "output_return_loss_db": output_rl,
        "isolation_db": isolation,
        "stability": stability,
        "summary": summary,
        "missing": missing,
    }


def compression_point(
    pin: List[float], gain: List[float], drop_db: float
) -> Optional[Dict[str, float]]:
    """From the gain at each input power: the small-signal gain (at the lowest power) and the
    input and output power where the gain has fallen ``drop_db`` below it; None if it never does."""
    if len(pin) < 2:
        return None
    reference = gain[0]
    crossing = rf.level_crossings(pin, gain, reference - drop_db)
    falling = [p for p, d in crossing if d == "falling"]
    if not falling:
        return None
    p_in = falling[0]
    g = rf.value_at(pin, gain, p_in)
    return {
        "small_signal_gain_db": reference,
        "p1db_input_dbm": p_in,
        "p1db_output_dbm": p_in + g,
        "gain_at_point_db": g,
    }


class AmplifierResponse(Measurement):
    """An RF amplifier with a VNA; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Nothing to prepare before the question (the source power is set by the sweep)."""
        self._power_changed = False

    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, read the four S-parameters, optionally the compression, report."""
        p = self.params
        handle = ctx.instrument("vna")
        if p.get("confirm_setup", True):
            ask_setup(ctx, self._connect_text(), p["sweep"], mode="transmission")
        freq, traces = acquire(
            ctx, handle, p["sweep"], ["S21", "S11", "S12", "S22"], int(p.get("averages", 1))
        )
        self._report(ctx, freq, traces)
        if p.get("compression"):
            self._compression(ctx, handle)

    def teardown(self, ctx: MeasurementContext) -> None:
        """Put the source power back to the (low) one of the sweep after a compression test."""
        if getattr(self, "_power_changed", False):
            set_sweep(ctx.instrument("vna"), self.params["sweep"])

    def _connect_text(self) -> str:
        p = self.params
        text = (
            "Connect the amplifier between port 1 and port 2 of the VNA, with the attenuators that "
            "were part of the calibration. Check that the amplifier output cannot exceed the "
            "maximum input power of the VNA"
        )
        if p.get("max_input_dbm") is not None:
            text += f" and that no more than {p['max_input_dbm']:g} dBm reaches the amplifier input"
        else:
            text += " and that the source power cannot damage the amplifier input"
        return text + "."

    def _report(self, ctx: MeasurementContext, freq: List[float], s: Dict[str, List[complex]]):
        p = self.params
        label = (p.get("device") or {}).get("label", "")
        base = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": p["sweep"].get("scale") == "log"}
        result = compute_amplifier(freq, s, p)
        limits = parse_limits(p.get("limits"))
        meta = dict(base)
        if not limits.empty:
            meta["limits"] = {"view": "magnitude_db", **limits.lines(freq)}
        ctx.emit_trace("S21", freq, s["S21"], kind="complex", **meta)
        for name in ("S11", "S22", "S12"):
            ctx.emit_trace(name, freq, s[name], kind="complex", hidden=True, **base)
        stability = result["stability"]
        ctx.emit_trace(
            "stability_mu",
            freq,
            stability["mu"],
            hidden=True,
            **dict(base, ylabel="mu (stable above 1)"),
        )
        ctx.emit_trace(
            "stability_k",
            freq,
            stability["k"],
            hidden=True,
            **dict(base, ylabel="K (stable above 1)"),
        )
        for i, f in enumerate(freq):  # the whole sweep as a table, for the CSV export
            ctx.emit_point(
                {
                    "frequency_hz": f,
                    "gain_db": result["gain_db"][i],
                    "input_return_loss_db": result["input_return_loss_db"][i],
                    "output_return_loss_db": result["output_return_loss_db"][i],
                    "isolation_db": result["isolation_db"][i],
                    "k": stability["k"][i],
                    "mu": stability["mu"][i],
                },
                table="sweep",
            )
        self._summary = {"device": label, **result["summary"]}
        if not limits.empty:
            verdict = limits.check(freq, result["gain_db"])
            self._summary["verdict"] = "PASS" if verdict.passed else "FAIL"
            self._summary["margin_db"] = verdict.margin
            ctx.log(f"limit check: {verdict.summary()}", "info" if verdict.passed else "warning")
        for what in result["missing"]:
            ctx.log(f"could not find {what} of the band: widen the sweep", "warning")
        top = result["summary"]
        if top["unconditionally_stable"] == "no":
            where = top.get("unstable_bands", "")
            ctx.log(
                f"the amplifier is not unconditionally stable ({where}): it could oscillate",
                "warning",
            )
        named = f" '{label}'" if label else ""
        ctx.log(
            f"amplifier{named}: peak gain {top['peak_gain_db']:.3g} dB at "
            f"{format_si(top['peak_at_hz'], 'Hz')}, flatness {top['gain_flatness_db']:.3g} dB, "
            f"stable: {top['unconditionally_stable']}"
        )
        if not p.get("compression"):
            ctx.emit_point(self._summary)

    def _compression(self, ctx: MeasurementContext, handle: Any) -> None:
        """Step the source power at one frequency, read the gain, find the compression point."""
        p = self.params
        comp = p["compression"]
        attenuation = float(p.get("input_attenuation_db", 0))
        f0 = float(comp["frequency_hz"])
        nominal = [f0 * (1 - NARROW_SPAN), f0, f0 * (1 + NARROW_SPAN)]
        powers = power_steps(comp)
        pin: List[float] = []
        gain: List[float] = []
        self._power_changed = True
        for n, power in enumerate(powers, 1):
            ctx.checkpoint()
            narrow = {
                "start_hz": nominal[0], "stop_hz": nominal[2], "points": 3, "scale": "linear",
                "power_dbm": power,
            }  # fmt: skip
            if "if_bandwidth_hz" in p["sweep"]:
                narrow["if_bandwidth_hz"] = p["sweep"]["if_bandwidth_hz"]
            set_sweep(handle, narrow)
            _, values = as_trace(handle.call("read_sparameter", parameter="S21"), nominal, "S21")
            if len(values) != 3:
                raise MeasurementError("the compression test needs the 3 points it asked for")
            pin.append(power - attenuation)
            gain.append(rf.db20(values[1]))
            ctx.progress(n, len(powers), f"power {power:g} dBm ({n} of {len(powers)})")
        drop = float(comp.get("compression_db", 1.0))
        point = compression_point(pin, gain, drop)
        pout = [a + g for a, g in zip(pin, gain)]
        meta = {"xlabel": "Input power (dBm)", "x_unit": "dBm"}
        ctx.emit_trace("gain_vs_power_db", pin, gain, hidden=True, **dict(meta, ylabel="Gain (dB)"))
        ctx.emit_trace(
            "pout_dbm", pin, pout, hidden=True, **dict(meta, ylabel="Output power (dBm)")
        )
        for a, g, o in zip(pin, gain, pout):
            ctx.emit_point({"pin_dbm": a, "gain_db": g, "pout_dbm": o}, table="compression")
        if point is None:
            ctx.log(
                f"the gain did not fall {drop:g} dB: raise stop_dbm (compression not reached)",
                "warning",
            )
        else:
            self._summary.update(point)
            self._summary["compression_at_hz"] = f0
            ctx.log(
                f"{drop:g} dB compression at {point['p1db_input_dbm']:.3g} dBm in, "
                f"{point['p1db_output_dbm']:.3g} dBm out (small-signal gain "
                f"{point['small_signal_gain_db']:.3g} dB)"
            )
        if gain[0] - rf.value_at(pin, gain, pin[min(1, len(pin) - 1)]) > 0.3 * drop:
            ctx.log("the gain already falls at the lowest powers: start lower", "warning")
        ctx.emit_point(self._summary)
