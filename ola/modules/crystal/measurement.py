# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A quartz crystal (or a ceramic resonator) measured with a VNA: its equivalent circuit.

Parameters (``.xtl`` file)::

    {"device": {"label": "Y1, 10 MHz HC-49"},                       # optional
     "sweep": {"start_hz": 9.99e6, "stop_hz": 10.04e6, "points": 2001},
     "nominal_frequency_hz": 10e6,         # optional: the offset in ppm and the check
     "tolerance_ppm": 30,                  # optional (with the nominal frequency)
     "load_capacitance_pf": 18,            # optional: the frequency with that load
     "z0": 50, "averages": 1, "confirm_setup": true}

The crystal is in series between port 1 and port 2 (series-thru), the VNA calibrated with a one-port
calibration on port 1 and a thru. The sweep must be **narrow** around the resonance and fine (a
crystal of Q 30000 at 10 MHz is a few hundred hertz wide): it should cover the series resonance
``fs`` and, to find ``C0``, the parallel resonance ``fp`` a few tens of kilohertz above it.

Results (``ola.crystal``): the curves ``s21_db`` (the peak is ``fs``, the dip ``fp``), ``x_ohm`` and
``r_ohm`` (hidden) and the raw ``S21``; one row in ``points``: ``fs_hz``, ``rm_ohm``, ``lm_h``,
``cm_f``, ``q``, ``fp_hz`` and ``c0_f`` (when ``fp`` is in the sweep), with a load capacitance
``fl_hz`` and ``pulling_ppm_per_pf``, and with a nominal frequency ``offset_ppm`` (of ``fl`` if a
load is given, else of ``fs``) and the ``verdict``. A crystal off its frequency is a *result*.
"""

from typing import Any, Dict, List

from ola import crystal, rf
from ola.efficiency_spec import Problem
from ola.golden import check_golden_param, recording
from ola.measurement import Measurement, MeasurementContext, MeasurementError
from ola.run_view import format_si
from ola.vna_common import acquire, ask_setup, check_asset, check_common, check_sweep, is_number

CONNECT = "Connect the crystal in series between port 1 and port 2 of the VNA."


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new crystal file (used by the editor)."""
    return {
        "device": {"label": ""},
        "sweep": {"start_hz": 9.99e6, "stop_hz": 10.04e6, "points": 2001, "scale": "linear"},
        "nominal_frequency_hz": 10e6,
        "averages": 1,
        "confirm_setup": True,
    }


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of its field. Does no I/O."""
    out: List[Problem] = []
    start, stop = check_sweep(params, out)
    sweep = params.get("sweep") or {}
    if sweep.get("scale", "linear") != "linear":
        out.append(Problem("sweep.scale", "a crystal needs a linear sweep (a narrow one)"))
    nominal = params.get("nominal_frequency_hz")
    if nominal is not None:
        if not is_number(nominal) or nominal <= 0:
            out.append(Problem("nominal_frequency_hz", "must be a frequency above 0 (Hz)"))
        elif start is not None and stop is not None and not start <= nominal <= stop:
            out.append(Problem("nominal_frequency_hz", "must be inside the sweep"))
    if "tolerance_ppm" in params:
        if not is_number(params["tolerance_ppm"]) or params["tolerance_ppm"] <= 0:
            out.append(Problem("tolerance_ppm", "must be a number of ppm above 0"))
        elif nominal is None:
            out.append(Problem("tolerance_ppm", "needs the nominal frequency"))
    load = params.get("load_capacitance_pf")
    if load is not None and (not is_number(load) or load < 0):
        out.append(Problem("load_capacitance_pf", "must be a number of pF, 0 or more"))
    if "z0" in params and (not is_number(params["z0"]) or params["z0"] <= 0):
        out.append(Problem("z0", "the reference impedance must be a number above 0 (ohm)"))
    points = sweep.get("points")
    if start is not None and stop is not None and isinstance(points, int) and points > 1:
        for text in crystal.check_sweep_for(start, stop, points):
            out.append(Problem("sweep.points", text, "warning"))
    check_asset(params, "device", out)
    check_common(params, out, start, stop)
    check_golden_param(params, out)
    return out


def summarise(result: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    """The row of the results: the equivalent circuit, and the offset and verdict against the
    nominal frequency. No I/O."""
    summary = dict(result)
    nominal = params.get("nominal_frequency_hz")
    if nominal:
        running = result.get("fl_hz") or result["fs_hz"]
        summary["offset_ppm"] = (running - nominal) / nominal * 1e6
        if "tolerance_ppm" in params:
            ok = abs(summary["offset_ppm"]) <= float(params["tolerance_ppm"])
            summary["verdict"] = "PASS" if ok else "FAIL"
    return summary


class CrystalResonator(Measurement):
    """A crystal's equivalent circuit with a VNA; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, sweep, read S21, compute, report."""
        ctx = recording(ctx, "crystal", self.params)  # with a golden sample: checked at the end
        p = self.params
        sweep = p["sweep"]
        handle = ctx.instrument("vna")
        if p.get("confirm_setup", True):
            ask_setup(ctx, CONNECT, sweep, connect_key="run_connect_crystal", mode="transmission")
        freq, traces = acquire(ctx, handle, sweep, ["S21"], int(p.get("averages", 1)))
        self._report(ctx, freq, traces["S21"])

    def _report(self, ctx: MeasurementContext, freq: List[float], s21: List[complex]) -> None:
        p = self.params
        z0 = float(p.get("z0", 50))
        load = p.get("load_capacitance_pf")
        try:
            result = crystal.analyse(
                freq, s21, z0, float(load) * 1e-12 if load is not None else None
            )
        except crystal.CrystalError as exc:
            raise MeasurementError(f"crystal: {exc}") from exc
        z = crystal.series_impedance(s21, z0)
        base = {"xlabel": "Frequency", "x_unit": "Hz"}
        ctx.emit_trace("S21", freq, s21, kind="complex", hidden=True, **base)
        ctx.emit_trace("s21_db", freq, rf.magnitude_db(s21), **dict(base, ylabel="S21 (dB)"))
        ctx.emit_trace(
            "x_ohm", freq, [v.imag for v in z], hidden=True, **dict(base, ylabel="X (ohm)")
        )
        ctx.emit_trace(
            "r_ohm", freq, [v.real for v in z], hidden=True, **dict(base, ylabel="R (ohm)")
        )
        summary = {"device": (p.get("device") or {}).get("label", ""), **summarise(result, p)}
        if result["fp_hz"] is None:
            ctx.log(
                "the parallel resonance is not in the sweep: C0 and the frequency with a load are "
                "not found (widen the sweep above the series resonance)",
                "warning",
            )
        text = (
            f"crystal: fs {format_si(result['fs_hz'], 'Hz')}, Rm {result['rm_ohm']:.3g} ohm, "
            f"Lm {format_si(result['lm_h'], 'H')}, Cm {format_si(result['cm_f'], 'F')}, "
            f"Q {result['q']:.3g}"
        )
        if result["c0_f"] is not None:
            text += f", C0 {format_si(result['c0_f'], 'F')}"
        if "offset_ppm" in summary:
            text += f", {summary['offset_ppm']:+.3g} ppm"
        if "verdict" in summary:
            text += f" ({summary['verdict']})"
        ctx.log(text, "warning" if summary.get("verdict") == "FAIL" else "info")
        ctx.emit_point(summary)
