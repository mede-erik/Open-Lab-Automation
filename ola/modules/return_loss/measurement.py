"""Return loss and VSWR of a device (an antenna, an adapter, an input...) with a VNA.

Parameters (``.rtl`` file)::

    {"sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 401, "scale": "linear",
               "if_bandwidth_hz": 1000, "power_dbm": -10},          # the last two are optional
     "device": {"label": "868 MHz antenna #2"},                     # optional
     "z0": 50, "vswr_max": 2.0,                                     # both optional
     "frequencies_of_interest": [868e6],                            # optional
     "limits": {"min": 10},                      # optional: the return loss must be at least 10 dB
     "averages": 1, "confirm_setup": true}

The VNA is calibrated by the user at the port the device connects to (open / short / load, one
port) and the measurement asks for it once. It then reads S11 (see ``docs/vna-calls.md``).

Results: the curves ``return_loss_db`` (bigger is a better match; the limit is drawn on it) and
``vswr`` (hidden at first) plus the raw ``S11`` (hidden: the Smith chart and the Touchstone export
use it); the table ``sweep``; and one row in ``points``: the best and the worst match and where, the
return loss and VSWR at the frequencies of interest, the impedance at the best match, the bands
where the VSWR stays at or under ``vswr_max`` (the usable bandwidth of an antenna), and the verdict.
A failed limit is a *result*, not an error.
"""

from typing import Any, Dict, List

from ola import rf
from ola.efficiency_spec import Problem
from ola.limits import parse_limits
from ola.measurement import Measurement, MeasurementContext
from ola.run_view import format_si
from ola.vna_common import (
    acquire,
    ask_setup,
    check_common,
    check_sweep,
    frequency_label,
    is_number,
)

VSWR_CAP = 100.0  # a total reflection has an infinite VSWR; curves and tables stop here


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new return-loss measurement (used by the editor)."""
    return {
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 401, "scale": "linear"},
        "device": {"label": ""},
        "z0": 50,
        "vswr_max": 2.0,
        "frequencies_of_interest": [],
        "averages": 1,
        "confirm_setup": True,
    }


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    start, stop = check_sweep(params, out)
    device = params.get("device", {})
    if not isinstance(device, dict):
        out.append(Problem("device", "must be an object with a 'label'"))
    elif "label" in device and not isinstance(device["label"], str):
        out.append(Problem("device.label", "the label must be text"))
    if "z0" in params and (not is_number(params["z0"]) or params["z0"] <= 0):
        out.append(Problem("z0", "the reference impedance must be a number above 0 (ohm)"))
    if "vswr_max" in params and (not is_number(params["vswr_max"]) or params["vswr_max"] <= 1):
        out.append(Problem("vswr_max", "the VSWR limit must be a number above 1 (2 is common)"))
    check_common(params, out, start, stop)
    return out


def compute_match(freq: List[float], s11: List[complex], params: Dict[str, Any]) -> Dict[str, Any]:
    """Return loss, VSWR, impedance and the summary from the measured S11. No I/O."""
    z0 = float(params.get("z0", 50))
    vswr_max = float(params.get("vswr_max", 2.0))
    loss = rf.return_loss_db(s11)
    vswr = [min(v, VSWR_CAP) for v in rf.vswr(s11)]
    z = rf.gamma_to_z(s11, z0)
    best, worst = loss.index(max(loss)), loss.index(min(loss))
    bands = rf.bands_where(freq, vswr, vswr_max)
    summary: Dict[str, Any] = {
        "points": len(freq),
        "best_return_loss_db": loss[best],
        "best_at_hz": freq[best],
        "min_vswr": vswr[best],
        "z_real_ohm": z[best].real,
        "z_imag_ohm": z[best].imag,
        "worst_return_loss_db": loss[worst],
        "worst_at_hz": freq[worst],
        "max_vswr": max(vswr),
        "usable_band_count": len(bands),
    }
    if bands:
        widest = max(bands, key=lambda b: b[1] - b[0])
        summary["widest_band_from_hz"], summary["widest_band_to_hz"] = widest
        summary["widest_band_hz"] = widest[1] - widest[0]
        summary["usable_bands"] = "; ".join(
            f"{format_si(a, 'Hz')} to {format_si(b, 'Hz')}" for a, b in bands
        )
    for f in params.get("frequencies_of_interest") or []:
        name = frequency_label(f)
        summary[f"return_loss_{name}_db"] = rf.value_at(freq, loss, f)
        summary[f"vswr_{name}"] = rf.value_at(freq, vswr, f)
    return {"return_loss_db": loss, "vswr": vswr, "z": z, "bands": bands, "summary": summary}


class ReturnLoss(Measurement):
    """Return loss and VSWR with a VNA; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, sweep, read S11, compute, report."""
        p = self.params
        sweep = p["sweep"]
        handle = ctx.instrument("vna")
        if p.get("confirm_setup", True):
            ask_setup(
                ctx, "Connect the device under test to port 1 of the VNA.", sweep, mode="reflection"
            )
        freq, traces = acquire(ctx, handle, sweep, ["S11"], int(p.get("averages", 1)))
        self._report(ctx, freq, traces["S11"])

    def _report(self, ctx: MeasurementContext, freq: List[float], s11: List[complex]) -> None:
        p = self.params
        label = (p.get("device") or {}).get("label", "")
        base = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": p["sweep"].get("scale") == "log"}
        ctx.emit_trace("S11", freq, s11, kind="complex", hidden=True, **base)
        result = compute_match(freq, s11, p)
        limits = parse_limits(p.get("limits"))
        meta = dict(base, ylabel="Return loss (dB)")
        if not limits.empty:
            meta["limits"] = {"view": "value", **limits.lines(freq)}
        ctx.emit_trace("return_loss_db", freq, result["return_loss_db"], **meta)
        ctx.emit_trace("vswr", freq, result["vswr"], hidden=True, **dict(base, ylabel="VSWR"))
        for i, f in enumerate(freq):  # the whole sweep as a table, for the CSV export
            ctx.emit_point(
                {
                    "frequency_hz": f,
                    "return_loss_db": result["return_loss_db"][i],
                    "vswr": result["vswr"][i],
                    "z_real_ohm": result["z"][i].real,
                    "z_imag_ohm": result["z"][i].imag,
                },
                table="sweep",
            )
        summary = {"device": label, **result["summary"]}
        if not limits.empty:
            verdict = limits.check(freq, result["return_loss_db"])
            summary["verdict"] = "PASS" if verdict.passed else "FAIL"
            summary["margin_db"] = verdict.margin
            ctx.log(f"limit check: {verdict.summary()}", "info" if verdict.passed else "warning")
        top = result["summary"]
        named = f" '{label}'" if label else ""
        ctx.log(
            f"device{named}: best match {top['best_return_loss_db']:.3g} dB "
            f"(VSWR {top['min_vswr']:.3g}) at {format_si(top['best_at_hz'], 'Hz')}"
        )
        if not result["bands"]:
            ctx.log(
                f"the VSWR is above {p.get('vswr_max', 2.0):g} everywhere in the sweep", "warning"
            )
        ctx.emit_point(summary)
