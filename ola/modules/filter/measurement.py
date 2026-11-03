"""Frequency response of a filter with a VNA.

Parameters (``.flt`` file)::

    {"filter": {"type": "bandpass", "label": "868 MHz SAW #4"},   # or lowpass, highpass, bandstop
     "sweep": {"start_hz": 800e6, "stop_hz": 940e6, "points": 561, "scale": "linear"},
     "edge_db": 3,                                     # optional, 3 by default
     "passband": {"from_hz": 863e6, "to_hz": 870e6},   # optional: ripple, reference level
     "frequencies_of_interest": [433e6, 868e6, 915e6], # optional
     "limits": {"bands": [{"from": 863e6, "to": 870e6, "min": -4}]},   # optional mask, in dB
     "also_s11": true, "averages": 1, "confirm_setup": true}

The filter goes between port 1 and port 2 of the VNA, calibrated beforehand by the user. The
measurement reads S21 (and S11 with ``also_s11``), see ``docs/vna-calls.md``.

What is found, relative to the **peak** of the response (or the highest point of the ``passband``)
and the level ``edge_db`` below it:

* low-pass: the cut-off, the first frequency above the peak where the gain falls to that level;
* high-pass: the cut-off, the last frequency below the peak where the gain rises to it;
* band-pass: the lower and upper edge around the peak, the bandwidth, the centre (geometric mean of
  the edges) and the Q (centre / bandwidth);
* band-stop: the depth and frequency of the notch, its edges at that level, the bandwidth and Q.

Also the insertion loss at the peak, the ripple in the ``passband``, the gain at the frequencies of
interest, the group delay, and a verdict against ``limits`` (a mask on the gain in dB, which is
negative: ``min`` -1 means the filter must pass at least -1 dB). When an edge cannot be found in
the sweep (the response never falls that far) the log says so and that figure is left out.
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

TYPES = ("lowpass", "highpass", "bandpass", "bandstop")
DEFAULT_EDGE_DB = 3.0


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new filter measurement (used by the editor)."""
    return {
        "filter": {"type": "lowpass", "label": ""},
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 401, "scale": "linear"},
        "edge_db": DEFAULT_EDGE_DB,
        "frequencies_of_interest": [],
        "averages": 1,
        "confirm_setup": True,
    }


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    start, stop = check_sweep(params, out)
    spec = params.get("filter")
    if not isinstance(spec, dict):
        out.append(Problem("filter", "the filter (its type) is missing"))
    else:
        if spec.get("type") not in TYPES:
            out.append(Problem("filter.type", f"must be one of {', '.join(TYPES)}"))
        if "label" in spec and not isinstance(spec["label"], str):
            out.append(Problem("filter.label", "the label must be text"))
    if "edge_db" in params and (not is_number(params["edge_db"]) or params["edge_db"] <= 0):
        out.append(Problem("edge_db", "must be a number of dB above 0 (3 is usual)"))
    band = params.get("passband")
    if band is not None:
        low, high = (
            (band.get("from_hz"), band.get("to_hz")) if isinstance(band, dict) else (None, None)
        )
        if not (is_number(low) and is_number(high) and 0 < low < high):
            out.append(Problem("passband", "needs from_hz below to_hz (Hz)"))
        elif start is not None and stop is not None and (low < start or high > stop):
            out.append(Problem("passband", "must be inside the sweep"))
    check_asset(params, "filter", out)
    check_common(params, out, start, stop, booleans=("also_s11", "confirm_setup"))
    return out


def _first(edges: List[tuple], direction: str, after: float) -> Optional[float]:
    return next((f for f, d in edges if d == direction and f >= after), None)


def _last(edges: List[tuple], direction: str, before: float) -> Optional[float]:
    found = [f for f, d in edges if d == direction and f <= before]
    return found[-1] if found else None


def compute_response(
    freq: List[float],
    s21: List[complex],
    params: Dict[str, Any],
    s11: Optional[List[complex]] = None,
) -> Dict[str, Any]:
    """Gain, the edges, bandwidth, Q, ripple... from the measured S21. No I/O. ``summary`` holds
    the numbers; ``missing`` lists what could not be found (an edge outside the sweep)."""
    kind = params["filter"]["type"]
    edge_db = float(params.get("edge_db", DEFAULT_EDGE_DB))
    band = params.get("passband")
    gain = rf.magnitude_db(s21)
    in_band = [i for i, f in enumerate(freq) if not band or band["from_hz"] <= f <= band["to_hz"]]
    peak = max(in_band, key=lambda i: gain[i])
    reference = gain[peak]
    level = reference - edge_db
    edges = rf.level_crossings(freq, gain, level)
    summary: Dict[str, Any] = {
        "points": len(freq),
        "insertion_loss_db": -reference,
        "peak_at_hz": freq[peak],
    }
    missing: List[str] = []

    def put(name: str, value: Optional[float], what: str) -> None:
        if value is None:
            missing.append(what)
        else:
            summary[name] = value

    if kind == "lowpass":
        put(
            "cutoff_hz",
            _first(edges, "falling", freq[peak]),
            "the cut-off (the gain never falls enough)",
        )
    elif kind == "highpass":
        put(
            "cutoff_hz",
            _last(edges, "rising", freq[peak]),
            "the cut-off (the gain is never low enough below)",
        )
    elif kind == "bandpass":
        low, high = _last(edges, "rising", freq[peak]), _first(edges, "falling", freq[peak])
        put("f_low_hz", low, "the lower edge")
        put("f_high_hz", high, "the upper edge")
        if low is not None and high is not None:
            summary["bandwidth_hz"] = high - low
            summary["center_hz"] = (low * high) ** 0.5
            summary["q_factor"] = summary["center_hz"] / summary["bandwidth_hz"]
    else:  # bandstop: the notch is the lowest point, the edges are around it
        notch = min(range(len(gain)), key=lambda i: gain[i])
        summary["notch_depth_db"] = reference - gain[notch]
        summary["notch_at_hz"] = freq[notch]
        low, high = _last(edges, "falling", freq[notch]), _first(edges, "rising", freq[notch])
        put("f_low_hz", low, "the lower edge of the notch")
        put("f_high_hz", high, "the upper edge of the notch")
        if low is not None and high is not None:
            summary["bandwidth_hz"] = high - low
            summary["q_factor"] = freq[notch] / summary["bandwidth_hz"]
    if band:
        inside = [gain[i] for i in in_band]
        summary["passband_ripple_db"] = max(inside) - min(inside)
    for f in params.get("frequencies_of_interest") or []:
        summary[f"gain_{frequency_label(f)}_db"] = rf.value_at(freq, gain, f)
    if s11 is not None:
        return_loss = rf.return_loss_db(s11)
        scope = [return_loss[i] for i in in_band] if band else return_loss
        summary["min_return_loss_db"] = min(scope)
    delay = rf.group_delay_s(freq, s21) if len(freq) >= 2 else []
    return {"gain_db": gain, "delay_s": delay, "summary": summary, "missing": missing}


class FilterResponse(Measurement):
    """Frequency response of a filter with a VNA; see the module docstring."""

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
                "Connect the filter under test between port 1 and port 2 of the VNA.",
                p["sweep"],
                mode="transmission",
            )
        wanted = ["S21"] + (["S11"] if p.get("also_s11") else [])
        freq, traces = acquire(ctx, handle, p["sweep"], wanted, int(p.get("averages", 1)))
        self._report(ctx, freq, traces)

    def _report(self, ctx: MeasurementContext, freq: List[float], traces: Dict[str, List[complex]]):
        p = self.params
        spec = p["filter"]
        label = spec.get("label", "")
        base = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": p["sweep"].get("scale") == "log"}
        result = compute_response(freq, traces["S21"], p, traces.get("S11"))
        limits = parse_limits(p.get("limits"))
        meta = dict(base)
        if not limits.empty:  # the mask is drawn on the magnitude view of S21
            meta["limits"] = {"view": "magnitude_db", **limits.lines(freq)}
        ctx.emit_trace("S21", freq, traces["S21"], kind="complex", **meta)
        if "S11" in traces:
            ctx.emit_trace("S11", freq, traces["S11"], kind="complex", hidden=True, **base)
        if result["delay_s"]:
            delay_meta = dict(base, ylabel="Group delay (ns)")
            ctx.emit_trace(
                "group_delay_ns",
                freq,
                [d * 1e9 for d in result["delay_s"]],
                hidden=True,
                **delay_meta,
            )
        phase = rf.phase_deg(traces["S21"])
        for i, f in enumerate(freq):  # the whole sweep as a table, for the CSV export
            row = {"frequency_hz": f, "gain_db": result["gain_db"][i], "phase_deg": phase[i]}
            ctx.emit_point(row, table="sweep")
        summary = {"filter": label, "type": spec["type"], **result["summary"]}
        if not limits.empty:
            verdict = limits.check(freq, result["gain_db"])
            summary["verdict"] = "PASS" if verdict.passed else "FAIL"
            summary["margin_db"] = verdict.margin
            ctx.log(f"limit check: {verdict.summary()}", "info" if verdict.passed else "warning")
        for what in result["missing"]:
            ctx.log(f"could not find {what}: widen the sweep", "warning")
        top = result["summary"]
        named = f" '{label}'" if label else ""
        ctx.log(
            f"filter{named} ({spec['type']}): insertion loss {top['insertion_loss_db']:.3g} dB "
            f"at {format_si(top['peak_at_hz'], 'Hz')}"
        )
        ctx.emit_point(summary)
