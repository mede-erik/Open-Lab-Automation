# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A component (inductor, capacitor, resistor, ferrite) measured with a VNA: its impedance and
what it is made of.

Parameters (``.cmp`` file)::

    {"device": {"label": "L3, 100 nH 0603"},                  # optional
     "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 801, "scale": "log"},
     "method": "series",                  # reflection | series | shunt (see below)
     "kind": "auto",                      # auto | inductor | capacitor | resistor
     "nominal": {"value": 100e-9, "tolerance_pct": 5, "frequency_hz": 10e6},   # optional
     "frequencies_of_interest": [10e6, 100e6],                                # optional
     "z0": 50, "averages": 1, "confirm_setup": true}

**How it is connected** (``method``), each good for a range of impedance (``ola.component``):

* ``reflection``: from the centre of port 1 to ground (S11); best near 50 ohm.
* ``series``: in series between port 1 and port 2 (S21, series-thru); best for high impedances
  (inductors, small capacitors, ferrites and chokes, up to tens of kilohm).
* ``shunt``: from a thru line between the two ports to ground (S21, shunt-thru); best for low
  impedances (large capacitors and their ESR, milliohm to a few ohm).

The two transmission methods need only S11 and S21, so they work with a forward-only VNA (the
LiteVNA). The log warns about the points where the method is outside its accurate range.

Results: the curves ``z_abs_ohm`` (the main one), ``r_ohm``, ``x_ohm``, the inductance in nH or the
capacitance in pF (by ``kind``), ``q`` and the measured S-parameter (hidden); the table ``sweep``;
and one row in ``points``: the kind (as given or guessed), the self-resonances (where the
reactance changes sign), the values at the frequencies of interest and, with ``nominal``, the
value at ``nominal.frequency_hz``, its deviation in % and the verdict (PASS when within
``tolerance_pct``). A value outside the tolerance is a *result*, not an error.
"""

import math
from typing import Any, Dict, List, Optional

from ola import component as comp
from ola import rf
from ola.efficiency_spec import Problem
from ola.golden import check_golden_param, recording
from ola.measurement import Measurement, MeasurementContext, MeasurementError
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

# what is reported for each kind: (the curve, its label, its scale, the unit of the summary)
VALUE = {
    "inductor": ("l_nh", "Inductance (nH)", 1e9, "l_h"),
    "capacitor": ("c_pf", "Capacitance (pF)", 1e12, "c_f"),
}
CONNECT = {
    "reflection": "Connect the component from the centre of port 1 of the VNA to ground.",
    "series": "Connect the component in series between port 1 and port 2 of the VNA.",
    "shunt": "Connect the component from a thru line between port 1 and port 2 to ground.",
}


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new component file (used by the editor)."""
    return {
        "device": {"label": ""},
        "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 801, "scale": "log"},
        "method": "series",
        "kind": "auto",
        "frequencies_of_interest": [],
        "averages": 1,
        "confirm_setup": True,
    }


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of its field. Does no I/O."""
    out: List[Problem] = []
    start, stop = check_sweep(params, out)
    if params.get("method", "series") not in comp.METHODS:
        out.append(Problem("method", f"must be one of {', '.join(comp.METHODS)}"))
    if params.get("kind", "auto") not in comp.KINDS:
        out.append(Problem("kind", f"must be one of {', '.join(comp.KINDS)}"))
    nominal = params.get("nominal")
    if nominal is not None:
        if not isinstance(nominal, dict):
            out.append(Problem("nominal", "must be an object with value and frequency_hz"))
        else:
            if not is_number(nominal.get("value")) or nominal["value"] <= 0:
                out.append(Problem("nominal.value", "must be a number above 0 (H, F or ohm)"))
            f = nominal.get("frequency_hz")
            if not is_number(f) or f <= 0:
                out.append(Problem("nominal.frequency_hz", "must be a frequency above 0 (Hz)"))
            elif start is not None and stop is not None and not start <= f <= stop:
                out.append(Problem("nominal.frequency_hz", "must be inside the sweep"))
            tol = nominal.get("tolerance_pct", 10)
            if not is_number(tol) or tol <= 0:
                out.append(Problem("nominal.tolerance_pct", "must be a number of % above 0"))
            if params.get("kind", "auto") == "auto":
                out.append(
                    Problem("kind", "say inductor, capacitor or resistor to check a nominal value")
                )
    if "z0" in params and (not is_number(params["z0"]) or params["z0"] <= 0):
        out.append(Problem("z0", "the reference impedance must be a number above 0 (ohm)"))
    check_asset(params, "device", out)
    check_common(params, out, start, stop)
    check_golden_param(params, out)
    return out


def value_of(kind: str, z: complex, f: float) -> Optional[float]:
    """The value of a component of ``kind`` from its impedance at ``f``: H, F or ohm; None when
    the impedance is of the other sign (an inductor seen above its resonance)."""
    if kind == "resistor":
        return z.real
    w = 2 * math.pi * f
    if kind == "inductor":
        return z.imag / w if z.imag > 0 else None
    return -1 / (w * z.imag) if z.imag < 0 else None


def compute(freq: List[float], z: List[complex], params: Dict[str, Any]) -> Dict[str, Any]:
    """The equivalent values, the resonances and the summary. No I/O."""
    kind = params.get("kind", "auto")
    if kind == "auto":
        kind = comp.guess_kind(z)
    eq = comp.equivalent(freq, z)
    resonances = comp.self_resonances(freq, z)
    summary: Dict[str, Any] = {
        "points": len(freq),
        "method": params.get("method", "series"),
        "kind": kind,
        "min_z_ohm": min(eq["z_abs_ohm"]),
        "min_z_at_hz": freq[eq["z_abs_ohm"].index(min(eq["z_abs_ohm"]))],
        "max_z_ohm": max(eq["z_abs_ohm"]),
    }
    if resonances:
        summary["self_resonance_hz"] = resonances[0]["frequency_hz"]
        summary["self_resonance_kind"] = resonances[0]["kind"]
        summary["resonances"] = "; ".join(
            f"{format_si(r['frequency_hz'], 'Hz')} ({r['kind']})" for r in resonances
        )
    for f in params.get("frequencies_of_interest") or []:
        name = frequency_label(f)
        r, x = rf.value_at(freq, eq["r_ohm"], f), rf.value_at(freq, eq["x_ohm"], f)
        summary[f"z_abs_{name}_ohm"] = math.hypot(r, x)
        summary[f"r_{name}_ohm"], summary[f"x_{name}_ohm"] = r, x
        value = value_of(kind, complex(r, x), f)
        if value is not None and kind in VALUE:
            summary[f"{VALUE[kind][3]}_{name}"] = value
        if r > 0 and kind != "resistor":
            summary[f"q_{name}"] = abs(x) / r
    nominal = params.get("nominal")
    if nominal:
        f = float(nominal["frequency_hz"])
        r, x = rf.value_at(freq, eq["r_ohm"], f), rf.value_at(freq, eq["x_ohm"], f)
        measured = value_of(kind, complex(r, x), f)
        summary["nominal_value"] = float(nominal["value"])
        if measured is None:
            summary["verdict"] = "FAIL"
            summary["deviation_pct"] = None
        else:
            deviation = 100 * (measured - float(nominal["value"])) / float(nominal["value"])
            summary["measured_value"] = measured
            summary["deviation_pct"] = deviation
            tol = float(nominal.get("tolerance_pct", 10))
            summary["verdict"] = "PASS" if abs(deviation) <= tol else "FAIL"
    return {"kind": kind, "equivalent": eq, "resonances": resonances, "summary": summary}


class ComponentImpedance(Measurement):
    """A component's impedance with a VNA; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, sweep, read S11 or S21, compute, report."""
        ctx = recording(ctx, "component", self.params)  # with a golden sample: checked at the end
        p = self.params
        method = p.get("method", "series")
        sweep = p["sweep"]
        handle = ctx.instrument("vna")
        if p.get("confirm_setup", True):
            ask_setup(
                ctx,
                CONNECT[method],
                sweep,
                connect_key=f"run_connect_component_{method}",
                mode="reflection" if method == "reflection" else "transmission",
            )
        name = "S11" if method == "reflection" else "S21"
        freq, traces = acquire(ctx, handle, sweep, [name], int(p.get("averages", 1)))
        self._report(ctx, freq, traces[name], name)

    def _report(self, ctx: MeasurementContext, freq: List[float], s: List[complex], name: str):
        p = self.params
        method = p.get("method", "series")
        z0 = float(p.get("z0", 50))
        try:
            z = comp.impedance(method, s, z0)
        except comp.ComponentError as exc:
            raise MeasurementError(str(exc)) from exc
        result = compute(freq, z, p)
        eq, kind, top = result["equivalent"], result["kind"], result["summary"]
        base = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": p["sweep"].get("scale") == "log"}
        ctx.emit_trace(name, freq, s, kind="complex", hidden=True, **base)
        ctx.emit_trace("z_abs_ohm", freq, eq["z_abs_ohm"], **dict(base, ylabel="|Z| (ohm)"))
        ctx.emit_trace("r_ohm", freq, eq["r_ohm"], hidden=True, **dict(base, ylabel="R (ohm)"))
        ctx.emit_trace("x_ohm", freq, eq["x_ohm"], hidden=True, **dict(base, ylabel="X (ohm)"))
        if kind in VALUE:
            trace, label, scale, key = VALUE[kind]
            values = [v * scale if v is not None else math.nan for v in eq[key]]
            ctx.emit_trace(trace, freq, values, hidden=True, **dict(base, ylabel=label))
        if kind != "resistor":
            q = [v if v is not None else math.nan for v in eq["q"]]
            ctx.emit_trace("q", freq, q, hidden=True, **dict(base, ylabel="Q"))
        for i, f in enumerate(freq):  # the whole sweep as a table, for the CSV export
            row = {k: eq[k][i] for k in ("r_ohm", "x_ohm", "z_abs_ohm", "phase_deg", "q")}
            row["frequency_hz"] = f
            if kind in VALUE:
                row[VALUE[kind][3]] = eq[VALUE[kind][3]][i]
            ctx.emit_point(row, table="sweep")
        poor = comp.inaccurate_points(method, s)
        better = comp.best_method(eq["z_abs_ohm"])
        if poor and better != method:
            ctx.log(
                f"{poor} of {len(freq)} points are outside the accurate range of the {method} "
                f"method (|Z| from {format_si(top['min_z_ohm'], 'ohm')} to "
                f"{format_si(top['max_z_ohm'], 'ohm')}): the {better} method suits this "
                "component better",
                "warning",
            )
        label = (p.get("device") or {}).get("label", "")
        summary = {"device": label, **top}
        named = f" '{label}'" if label else ""
        text = f"component{named}: {kind}"
        if "self_resonance_hz" in top:
            text += f", self-resonance at {format_si(top['self_resonance_hz'], 'Hz')}"
        if "deviation_pct" in top and top["deviation_pct"] is not None:
            text += f", {top['deviation_pct']:+.3g} % from the nominal value ({top['verdict']})"
        elif top.get("verdict") == "FAIL":
            text += ": it is not a " + kind + " at the frequency of the nominal value (FAIL)"
        ctx.log(text, "warning" if top.get("verdict") == "FAIL" else "info")
        ctx.emit_point(summary)
