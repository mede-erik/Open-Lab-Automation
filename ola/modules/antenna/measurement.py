# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Impedance of an antenna (or any one-port) with a VNA, with the Smith chart in front.

Parameters (``.ant`` file)::

    {"sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 401, "scale": "linear"},
     "device": {"label": "868 MHz whip #2"},                  # optional
     "z0": 50, "vswr_max": 2.0,                                # both optional
     "frequencies_of_interest": [868e6],                       # optional
     "limits": {"min": 10},                  # optional: the return loss must be at least 10 dB
     "correction": {"cable": {"asset_id": "CBL-0042"}},   # optional: the antenna is behind a cable
     "averages": 1, "confirm_setup": true}

The VNA is calibrated by the user at the port the antenna connects to (open / short / load) and the
measurement asks for it once. It then reads S11 (``docs/vna-calls.md``).

What it gives, besides the return loss and the VSWR (the measurement ``return_loss`` makes the same
ones): the **impedance** ``R + jX`` at every frequency; the **resonances**, where the reactance
crosses zero (a series resonance, X going from negative to positive, is where an antenna is matched;
a crossing the other way is an anti-resonance, high resistance); the best match; the bands where the
VSWR stays at or under ``vswr_max``; and, at each frequency of interest, the impedance and the
**series component that would cancel the reactance** there (a capacitor if X is positive, an
inductor if it is negative). The Smith chart is the view the window opens with.

**Through a cable.** An antenna measured at the end of a cable looks better matched than it is.
``correction.cable`` takes the cable that was measured out (by its code in the registry, a run file
of the cable measurement or a Touchstone file; see ``ola.deembed`` and ``docs/return-loss.md``) and
everything above is of the antenna alone, the impedance and the Smith chart included. For that the
cable must be known with its **phase** (measured in transmission, or in reflection with an open or a
short): a cable known only by its loss is refused here (the return loss measurement does correct the
VSWR with the loss alone). The measurement as it came is kept as ``S11_raw`` and ``vswr_raw``.
"""

import math
from typing import Any, Dict, List, Optional

from ola import rf
from ola.efficiency_spec import Problem
from ola.limits import parse_limits
from ola.measurement import Measurement, MeasurementContext
from ola.run_view import format_si
from ola.deembed import check_correction
from ola.vna_common import (
    acquire,
    apply_correction,
    ask_setup,
    check_asset,
    check_common,
    check_sweep,
    frequency_label,
    is_number,
)

VSWR_CAP = 100.0


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new antenna measurement (used by the editor)."""
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
    check_asset(params, "device", out)
    check_correction(params, out, Problem)
    check_common(params, out, start, stop)
    return out


def cancelling_component(reactance: float, f: float) -> str:
    """The series component that cancels a reactance ``X`` (ohm) at ``f`` (Hz), as text: a
    capacitor for a positive reactance (``C = 1 / (2 pi f X)``), an inductor for a negative one
    (``L = -X / (2 pi f)``). ``"none needed"`` if the reactance is negligible."""
    if abs(reactance) < 0.01:
        return "none needed"
    omega = 2 * math.pi * f
    if reactance > 0:
        return f"series capacitor {format_si(1 / (omega * reactance), 'F')}"
    return f"series inductor {format_si(-reactance / omega, 'H')}"


def compute_impedance(
    freq: List[float], s11: List[complex], params: Dict[str, Any]
) -> Dict[str, Any]:
    """Impedance, resonances, best match and the summary from the measured S11. No I/O."""
    z0 = float(params.get("z0", 50))
    vswr_max = float(params.get("vswr_max", 2.0))
    z = rf.gamma_to_z(s11, z0)
    finite = [v if math.isfinite(v.real) else complex(1e9, 0) for v in z]  # an open: huge R
    resistance, reactance = [v.real for v in finite], [v.imag for v in finite]
    loss = rf.return_loss_db(s11)
    vswr = [min(v, VSWR_CAP) for v in rf.vswr(s11)]
    best = vswr.index(min(vswr))
    crossings = rf.level_crossings(freq, reactance, 0.0)
    series = [f for f, d in crossings if d == "rising"]
    anti = [f for f, d in crossings if d == "falling"]
    bands = rf.bands_where(freq, vswr, vswr_max)
    summary: Dict[str, Any] = {
        "points": len(freq),
        "best_match_at_hz": freq[best],
        "min_vswr": vswr[best],
        "best_return_loss_db": loss[best],
        "z_real_ohm": resistance[best],
        "z_imag_ohm": reactance[best],
        "series_resonance_count": len(series),
        "usable_band_count": len(bands),
    }
    if series:  # the resonance with the lowest VSWR is the one the antenna works at
        main = min(series, key=lambda f: rf.value_at(freq, vswr, f))
        summary["series_resonance_hz"] = main
        summary["series_resonance_r_ohm"] = rf.value_at(freq, resistance, main)
        summary["series_resonance_vswr"] = rf.value_at(freq, vswr, main)
        summary["resonances"] = "; ".join(format_si(f, "Hz") for f in series)
    if anti:
        summary["anti_resonances"] = "; ".join(format_si(f, "Hz") for f in anti)
    if bands:
        widest = max(bands, key=lambda b: b[1] - b[0])
        summary["widest_band_from_hz"], summary["widest_band_to_hz"] = widest
        summary["widest_band_hz"] = widest[1] - widest[0]
        centre = (widest[0] + widest[1]) / 2
        summary["fractional_bandwidth_pct"] = 100 * (widest[1] - widest[0]) / centre
        summary["usable_bands"] = "; ".join(
            f"{format_si(a, 'Hz')} to {format_si(b, 'Hz')}" for a, b in bands
        )
    for f in params.get("frequencies_of_interest") or []:
        name = frequency_label(f)
        r, x = rf.value_at(freq, resistance, f), rf.value_at(freq, reactance, f)
        summary[f"r_{name}_ohm"], summary[f"x_{name}_ohm"] = r, x
        summary[f"z_abs_{name}_ohm"] = math.hypot(r, x)
        summary[f"vswr_{name}"] = rf.value_at(freq, vswr, f)
        summary[f"return_loss_{name}_db"] = rf.value_at(freq, loss, f)
        summary[f"cancel_{name}"] = cancelling_component(x, f)
    return {
        "resistance": resistance,
        "reactance": reactance,
        "return_loss_db": loss,
        "vswr": vswr,
        "bands": bands,
        "summary": summary,
    }


class AntennaImpedance(Measurement):
    """Impedance of an antenna with a VNA; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, sweep, read S11, compute, report."""
        p = self.params
        handle = ctx.instrument("vna")
        if p.get("confirm_setup", True):
            connect = "Connect the antenna to port 1 of the VNA."
            if (p.get("correction") or {}).get("cable"):
                connect = (
                    "The antenna is behind the cable that was measured: connect that cable to "
                    "port 1 of the VNA (calibrated at the end of the test lead, WITHOUT the "
                    "cable) and the antenna to its other end."
                )
            ask_setup(ctx, connect, p["sweep"], mode="reflection")
        freq, traces = acquire(ctx, handle, p["sweep"], ["S11"], int(p.get("averages", 1)))
        s11, info = apply_correction(ctx, p, freq, traces["S11"], needs_phase=True)
        self._report(ctx, freq, s11, traces["S11"], info)

    def _report(
        self,
        ctx: MeasurementContext,
        freq: List[float],
        s11: List[complex],
        raw: Optional[List[complex]] = None,
        info: Optional[Dict[str, Any]] = None,
    ) -> None:
        p = self.params
        label = (p.get("device") or {}).get("label", "")
        base = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": p["sweep"].get("scale") == "log"}
        result = compute_impedance(freq, s11, p)
        limits = parse_limits(p.get("limits"))
        ctx.emit_trace("S11", freq, s11, kind="complex", default_view="smith", **base)
        raw_vswr = rf.vswr(raw) if info else None
        if info:  # the measurement as it came, for the comparison
            ctx.emit_trace("S11_raw", freq, raw, kind="complex", hidden=True, **base)
            ctx.emit_trace(
                "vswr_raw",
                freq,
                [min(v, VSWR_CAP) for v in raw_vswr],
                hidden=True,
                **dict(base, ylabel="VSWR (as measured)"),
            )
        ctx.emit_trace(
            "resistance_ohm",
            freq,
            result["resistance"],
            hidden=True,
            **dict(base, ylabel="R (ohm)"),
        )
        ctx.emit_trace(
            "reactance_ohm", freq, result["reactance"], hidden=True, **dict(base, ylabel="X (ohm)")
        )
        meta = dict(base, ylabel="Return loss (dB)")
        if not limits.empty:
            meta["limits"] = {"view": "value", **limits.lines(freq)}
        ctx.emit_trace("return_loss_db", freq, result["return_loss_db"], hidden=True, **meta)
        ctx.emit_trace("vswr", freq, result["vswr"], hidden=True, **dict(base, ylabel="VSWR"))
        for i, f in enumerate(freq):  # the whole sweep as a table, for the CSV export
            row = {
                "frequency_hz": f,
                "r_ohm": result["resistance"][i],
                "x_ohm": result["reactance"][i],
                "vswr": result["vswr"][i],
                "return_loss_db": result["return_loss_db"][i],
            }
            ctx.emit_point(row, table="sweep")
        summary = {"device": label, **result["summary"]}
        if info:
            summary.update(
                corrected=True,
                correction_source=info["code"] or info["source"],
                correction_mode=info["mode"],
                cable_loss_one_way_db=info["mean_one_way_loss_db"],
                raw_min_vswr=min(min(v, VSWR_CAP) for v in raw_vswr),
                raw_max_vswr=min(max(raw_vswr), VSWR_CAP),
            )
        if not limits.empty:
            verdict = limits.check(freq, result["return_loss_db"])
            summary["verdict"] = "PASS" if verdict.passed else "FAIL"
            summary["margin_db"] = verdict.margin
            ctx.log(f"limit check: {verdict.summary()}", "info" if verdict.passed else "warning")
        top = result["summary"]
        named = f" '{label}'" if label else ""
        found = (
            f"series resonance at {format_si(top['series_resonance_hz'], 'Hz')}"
            if "series_resonance_hz" in top
            else "no series resonance in the sweep"
        )
        ctx.log(
            f"antenna{named}: best match VSWR {top['min_vswr']:.3g} at "
            f"{format_si(top['best_match_at_hz'], 'Hz')}; {found}"
        )
        if not result["bands"]:
            ctx.log(
                f"the VSWR is above {p.get('vswr_max', 2.0):g} everywhere in the sweep", "warning"
            )
        ctx.emit_point(summary)
