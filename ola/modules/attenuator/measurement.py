"""How much an attenuator attenuates, as a function of frequency, with a VNA.

Parameters (``.att`` file)::

    {"attenuator": {"label": "10 dB SMA #3", "nominal_db": 10, "tolerance_db": 0.5,
                    "setting": ""},                  # the last three are optional
     "sweep": {"start_hz": 1e6, "stop_hz": 6e9, "points": 401, "scale": "linear"},
     "frequencies_of_interest": [433e6, 2.4e9],      # optional
     "limits": {"bands": [{"from": 0, "to": 6e9, "min": 9, "max": 11}]},   # optional, in dB
     "also_return_loss": true, "averages": 1, "confirm_setup": true}

The attenuator goes between port 1 and port 2 of the VNA, calibrated beforehand by the user (with
the test leads, thru). The measurement reads S21 and, unless ``also_return_loss`` is false, S11 and
S22, see ``docs/vna-calls.md``. The **attenuation** is ``-20 log10 |S21|`` in dB, a *positive*
number (a 10 dB attenuator reads 10), unlike the gain of a filter.

Results: the curves ``attenuation_db`` (the nominal value and its tolerance, or the mask, drawn
on it), ``S21`` (hidden: phase, Smith chart and Touchstone use it), and ``S11`` and ``S22``; the
table ``sweep``; and one row in ``points``: the mean, the lowest and the highest attenuation and
where, the *flatness* (highest minus lowest), the slope (dB per GHz, a straight-line fit), the
deviation from the nominal value (mean and worst), the attenuation at the frequencies of interest,
the worst return loss of each port, and the verdict. The verdict is against ``limits`` if given,
else against ``nominal_db`` with ``tolerance_db`` (the whole sweep must be inside). A value
outside is a *result*, not an error. A step attenuator has one setting per measurement:
``setting`` is only written in the result.
"""

from typing import Any, Dict, List, Optional

from ola import rf
from ola.efficiency_spec import Problem
from ola.limits import parse_limits
from ola.measurement import Measurement, MeasurementContext
from ola.run_view import format_si
from ola.vna_common import (
    acquire,
    ask_setup,
    check_asset,
    check_common,
    check_sweep,
    frequency_label,
    is_number,
)


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new attenuator measurement (used by the editor)."""
    return {
        "attenuator": {"label": "", "nominal_db": 10, "tolerance_db": 0.5},
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 401, "scale": "linear"},
        "frequencies_of_interest": [],
        "also_return_loss": True,
        "averages": 1,
        "confirm_setup": True,
    }


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    start, stop = check_sweep(params, out)
    spec = params.get("attenuator")
    if not isinstance(spec, dict):
        out.append(Problem("attenuator", "the attenuator (a label, the nominal value) is missing"))
    else:
        for key in ("label", "setting"):
            if key in spec and not isinstance(spec[key], str):
                out.append(Problem(f"attenuator.{key}", "must be text"))
        if "nominal_db" in spec and (not is_number(spec["nominal_db"]) or spec["nominal_db"] < 0):
            out.append(Problem("attenuator.nominal_db", "must be a number of dB, 0 or more"))
        if "tolerance_db" in spec and (
            not is_number(spec["tolerance_db"]) or spec["tolerance_db"] < 0
        ):
            out.append(Problem("attenuator.tolerance_db", "must be a number of dB, 0 or more"))
        if "tolerance_db" in spec and "nominal_db" not in spec and not params.get("limits"):
            out.append(Problem("attenuator.nominal_db", "the tolerance needs the nominal value"))
    check_asset(params, "attenuator", out)
    check_common(params, out, start, stop, booleans=("also_return_loss", "confirm_setup"))
    return out


def tolerance_limits(spec: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """``{"min": nominal - tol, "max": nominal + tol}``, or None without a nominal value."""
    if not is_number(spec.get("nominal_db")):
        return None
    nominal, tol = float(spec["nominal_db"]), float(spec.get("tolerance_db", 0) or 0)
    return {"min": nominal - tol, "max": nominal + tol}


def slope_db_per_ghz(freq: List[float], y: List[float]) -> float:
    """Slope of the straight line that best fits ``y`` against the frequency, in dB per GHz."""
    n = len(freq)
    mean_f, mean_y = sum(freq) / n, sum(y) / n
    den = sum((f - mean_f) ** 2 for f in freq)
    if den == 0:
        return 0.0
    return sum((f - mean_f) * (v - mean_y) for f, v in zip(freq, y)) / den * 1e9


def compute_attenuation(
    freq: List[float],
    s21: List[complex],
    params: Dict[str, Any],
    s11: Optional[List[complex]] = None,
    s22: Optional[List[complex]] = None,
) -> Dict[str, Any]:
    """The attenuation and the summary from the measured S-parameters. No I/O."""
    att = rf.insertion_loss_db(s21)
    low, high = att.index(min(att)), att.index(max(att))
    summary: Dict[str, Any] = {
        "points": len(freq),
        "mean_attenuation_db": sum(att) / len(att),
        "min_attenuation_db": att[low],
        "min_at_hz": freq[low],
        "max_attenuation_db": att[high],
        "max_at_hz": freq[high],
        "flatness_db": att[high] - att[low],
    }
    if len(freq) >= 2:
        summary["slope_db_per_ghz"] = slope_db_per_ghz(freq, att)
    nominal = (params.get("attenuator") or {}).get("nominal_db")
    if is_number(nominal):
        deviations = [a - nominal for a in att]
        summary["nominal_db"] = float(nominal)
        summary["mean_deviation_db"] = summary["mean_attenuation_db"] - nominal
        summary["worst_deviation_db"] = max(deviations, key=abs)
    for f in params.get("frequencies_of_interest") or []:
        summary[f"attenuation_{frequency_label(f)}_db"] = rf.value_at(freq, att, f)
    if s11 is not None:
        summary["min_input_return_loss_db"] = min(rf.return_loss_db(s11))
    if s22 is not None:
        summary["min_output_return_loss_db"] = min(rf.return_loss_db(s22))
    return {"attenuation_db": att, "summary": summary}


class AttenuatorSweep(Measurement):
    """Attenuation of an attenuator against frequency; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, sweep, read, compute, report."""
        p = self.params
        handle = ctx.instrument("vna")
        if p.get("confirm_setup", True):
            ask_setup(
                ctx,
                "Connect the attenuator under test between port 1 and port 2 of the VNA.",
                p["sweep"],
                mode="transmission",
            )
        wanted = ["S21"] + (["S11", "S22"] if p.get("also_return_loss", True) else [])
        freq, traces = acquire(ctx, handle, p["sweep"], wanted, int(p.get("averages", 1)))
        self._report(ctx, freq, traces)

    def _report(self, ctx: MeasurementContext, freq: List[float], traces: Dict[str, List[complex]]):
        p = self.params
        spec = p["attenuator"]
        label = spec.get("label", "")
        base = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": p["sweep"].get("scale") == "log"}
        result = compute_attenuation(freq, traces["S21"], p, traces.get("S11"), traces.get("S22"))
        explicit = parse_limits(p.get("limits"))
        derived = tolerance_limits(spec)
        limits = explicit if not explicit.empty else parse_limits(derived)
        meta = dict(base, ylabel="Attenuation (dB)")
        if not limits.empty:
            meta["limits"] = {"view": "value", **limits.lines(freq)}
        ctx.emit_trace("attenuation_db", freq, result["attenuation_db"], **meta)
        ctx.emit_trace("S21", freq, traces["S21"], kind="complex", hidden=True, **base)
        for name in ("S11", "S22"):
            if name in traces:
                ctx.emit_trace(name, freq, traces[name], kind="complex", hidden=True, **base)
        phase = rf.phase_deg(traces["S21"])
        rl_in = rf.return_loss_db(traces["S11"]) if "S11" in traces else None
        rl_out = rf.return_loss_db(traces["S22"]) if "S22" in traces else None
        for i, f in enumerate(freq):  # the whole sweep as a table, for the CSV export
            row = {
                "frequency_hz": f,
                "attenuation_db": result["attenuation_db"][i],
                "phase_deg": phase[i],
            }
            if rl_in is not None and rl_out is not None:
                row["input_return_loss_db"], row["output_return_loss_db"] = rl_in[i], rl_out[i]
            ctx.emit_point(row, table="sweep")
        summary: Dict[str, Any] = {"attenuator": label, **result["summary"]}
        if spec.get("setting"):
            summary["setting"] = spec["setting"]
        if not limits.empty:
            verdict = limits.check(freq, result["attenuation_db"])
            summary["verdict"] = "PASS" if verdict.passed else "FAIL"
            summary["margin_db"] = verdict.margin
            ctx.log(f"limit check: {verdict.summary()}", "info" if verdict.passed else "warning")
        top = result["summary"]
        named = f" '{label}'" if label else ""
        ctx.log(
            f"attenuator{named}: {top['mean_attenuation_db']:.3g} dB on average, "
            f"from {top['min_attenuation_db']:.3g} dB at {format_si(top['min_at_hz'], 'Hz')} "
            f"to {top['max_attenuation_db']:.3g} dB at {format_si(top['max_at_hz'], 'Hz')}"
        )
        ctx.emit_point(summary)
