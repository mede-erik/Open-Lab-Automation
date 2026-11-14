# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Efficiency of a converter with a **resistive load** made of real resistors.

Parameters (``.rfe`` file)::

    {"device": {"label": "5 V buck"},
     "supply_channel": 1,                                              # optional
     "vin_v": {"values": [9, 12, 15]},                       # or {"start", "stop", "points"}
     "loads": [{"name": "10R", "r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"},
               {"name": "22||47", "parallel": [
                   {"r_ohm": 22, "tol_pct": 1, "power_w": 2, "channel": "202"},
                   {"r_ohm": 47, "tol_pct": 5, "power_w": 2, "channel": "203"}]}],
     "switching": {"mode": "mux", "settle_s": 0.5, "supply_off": true},     # or "manual"
     "vout_reading": {"call": "measure_dc_voltage",
                      "args": {"range": "AUTO", "resolution": "DEF", "channels": "103"}},
     "iin_reading": {"role": "supply", "call": "read_current"},     # or a shunt on a datalogger
     "vin_reading": {"call": "measure_dc_voltage", "args": {"channels": "101"}},  # optional
     "timing": {"settle_s": 1, "samples": 3, "interval_s": 0.1},
     "safety": {"max_vin_v": 20, "max_vout_v": 6, "max_iin_a": 3},
     "limits": {"min_efficiency_pct": 85, "vout_min_v": 4.75, "vout_max_v": 5.25},
     "confirm_setup": true}

A supply feeds the converter (role ``supply``), a multimeter or one channel of a datalogger reads
the output voltage (role ``meter``) and the load is one of the ``loads``: resistors that **you**
write (``ola.resistors``: one resistor, or series / parallel groups, each with its tolerance and its
power rating). For **every load** the measurement connects it and sweeps the input voltage:

* ``switching.mode`` ``"manual"``: the program asks you to connect the load (by its name) and goes
  on when you say so; ``"mux"``: the relays of the multiplexer (a datalogger module or a switch
  unit, role ``switch``) connect it: the ``channel`` of each of its resistors is closed (the ones of
  the load before are opened first). With ``supply_off`` (the default) the supply is switched off
  while the load is changed, which is the safe way for hands and for relays.
* The input current comes from ``iin_reading``: the supply's own readback (``"role": "supply"``) or
  a shunt read by a datalogger (``scale`` = 1 / the shunt in ohms: 0.1 ohm is ``"scale": 10``).
* ``Pin = Vin * Iin``; the output power is ``Pout = Vout**2 / R`` with the resistance of the load,
  and the efficiency ``Pout / Pin``. The tolerances of the resistors make the resistance a range:
  the point gives the nominal efficiency and its **lowest and highest** (``efficiency_min_pct``,
  ``efficiency_max_pct``: the resistance at its lowest gives the highest power).

Safe by construction: ``safety.max_vin_v`` refuses an input above it, ``max_vout_v`` checks the
power ratings of the resistors **before anything is switched on** (an error if one would be above
its rating), ``max_iin_a`` and the ratings are also checked on every reading (a resistor above its
rating stops the measurement: the supply is switched off, the relays opened), and the supply is
switched off at the end, also after an error or a stop. The results are the table ``points`` (a row
for each load and input voltage), the table ``summary`` (a row for each load, with the verdict
against ``limits``; the verdict uses the **lowest** efficiency, the guaranteed one) and the curves
``eff_vs_vin_<load>`` and ``eff_vs_r_<vin>``. Out of limits is a *result*, not an error.
"""

import re
from typing import Any, Dict, List, Sequence

from ola.efficiency_spec import Problem
from ola.golden import check_golden_param, finish, recording
from ola.measurement import Measurement, MeasurementContext, MeasurementError, Stopped
from ola.resistors import Load, LoadError, parse_loads
from ola.sweep import SweepError, axis_values
from ola.vna_common import check_asset, is_number

DEFAULT_CALL = "measure_dc_voltage"
LIMIT_KEYS = ("min_efficiency_pct", "vout_min_v", "vout_max_v")
READING_KEYS = ("role", "call", "args", "scale", "offset")
SWITCH_MODES = ("manual", "mux")
MAX_POINTS = 1000
MIN_POWER_W = 1e-6  # below this input power an efficiency means nothing


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new resistive-efficiency measurement (used by the editor)."""
    return {
        "device": {"label": ""},
        "vin_v": {"values": [9, 12, 15]},
        "loads": [
            {"name": "10R", "r_ohm": 10, "tol_pct": 1, "power_w": 5},
            {"name": "22R", "r_ohm": 22, "tol_pct": 1, "power_w": 5},
        ],
        "switching": {"mode": "manual", "settle_s": 0.5, "supply_off": True},
        "vout_reading": {"call": DEFAULT_CALL, "args": {"range": "AUTO", "resolution": "DEF"}},
        "iin_reading": {"role": "supply", "call": "read_current"},
        "timing": {"settle_s": 1.0, "samples": 3, "interval_s": 0.1},
        "confirm_setup": True,
    }


# ----- checking the parameters ----------------------------------------------------------------
def _check_reading(spec: Any, path: str, out: List[Problem], roles: Sequence[str]) -> None:
    if not isinstance(spec, dict):
        out.append(Problem(path, "must be an object: role, call, args, scale, offset"))
        return
    for key in set(spec) - set(READING_KEYS):
        out.append(Problem(f"{path}.{key}", "unknown field: use " + ", ".join(READING_KEYS)))
    if "role" in spec and spec["role"] not in roles:
        out.append(Problem(f"{path}.role", f"must be one of {', '.join(roles)}"))
    if "call" in spec and (not isinstance(spec["call"], str) or not spec["call"]):
        out.append(Problem(f"{path}.call", "must be the name of a call"))
    if "args" in spec and not isinstance(spec["args"], dict):
        out.append(Problem(f"{path}.args", "must be an object (for a datalogger channels)"))
    for key in ("scale", "offset"):
        if key in spec and not is_number(spec[key]):
            out.append(Problem(f"{path}.{key}", "must be a number"))
    if is_number(spec.get("scale")) and spec["scale"] == 0:
        out.append(Problem(f"{path}.scale", "must not be 0"))


def _check_switching(spec: Any, loads: List[Load], raw: Any, out: List[Problem]) -> None:
    if spec is None:
        return
    if not isinstance(spec, dict):
        out.append(Problem("switching", "must be an object: mode, settle_s, supply_off"))
        return
    for key in set(spec) - {"mode", "settle_s", "supply_off"}:
        out.append(Problem(f"switching.{key}", "unknown field: use mode, settle_s, supply_off"))
    mode = spec.get("mode", "manual")
    if mode not in SWITCH_MODES:
        out.append(Problem("switching.mode", f"must be one of {', '.join(SWITCH_MODES)}"))
    if "settle_s" in spec and (not is_number(spec["settle_s"]) or spec["settle_s"] < 0):
        out.append(Problem("switching.settle_s", "must be a number of seconds, 0 or more"))
    if "supply_off" in spec and not isinstance(spec["supply_off"], bool):
        out.append(Problem("switching.supply_off", "must be true or false"))
    if mode == "mux":
        for i, load in enumerate(loads):
            if any(not r.channel for r in load.resistors()):
                out.append(
                    Problem(
                        f"loads[{i}]",
                        f"{load.name}: every resistor needs a 'channel' (its relay) when the "
                        "load is connected by the multiplexer",
                    )
                )
        if spec.get("supply_off") is False:
            out.append(
                Problem(
                    "switching.supply_off",
                    "the relays will switch with the converter running (hot switching)",
                    "warning",
                )
            )


def _check_safety(safety: Any, vins: List[float], loads: List[Load], out: List[Problem]) -> None:
    if safety is None:
        return
    if not isinstance(safety, dict):
        out.append(Problem("safety", "must be an object: max_vin_v, max_vout_v, max_iin_a"))
        return
    for key in set(safety) - {"max_vin_v", "max_vout_v", "max_iin_a"}:
        out.append(Problem(f"safety.{key}", "unknown field: use max_vin_v, max_vout_v, max_iin_a"))
    for key, unit in (("max_vin_v", "V"), ("max_vout_v", "V"), ("max_iin_a", "A")):
        if key in safety and (not is_number(safety[key]) or safety[key] <= 0):
            out.append(Problem(f"safety.{key}", f"must be a number of {unit} above 0"))
    cap = safety.get("max_vin_v")
    if is_number(cap) and vins and max(vins) > cap:
        out.append(
            Problem(
                "safety.max_vin_v",
                f"the sweep goes to {max(vins):g} V, above the limit of {cap:g} V",
            )
        )
    vmax = safety.get("max_vout_v")
    if is_number(vmax) and vmax > 0:
        for i, load in enumerate(loads):
            resistor, fraction = load.most_loaded(float(vmax))
            if resistor is not None and fraction > 1:
                out.append(
                    Problem(
                        f"loads[{i}]",
                        f"{load.name}: at {vmax:g} V the resistor {resistor.name} dissipates "
                        f"{fraction * 100:.0f} % of its {resistor.power_w:g} W rating",
                    )
                )


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    device = params.get("device", {})
    if not isinstance(device, dict):
        out.append(Problem("device", "must be an object with a 'label'"))
    elif "label" in device and not isinstance(device["label"], str):
        out.append(Problem("device.label", "the label must be text"))
    check_asset(params, "device", out)
    channel = params.get("supply_channel")
    if channel is not None and (
        not isinstance(channel, int) or isinstance(channel, bool) or channel < 1
    ):
        out.append(Problem("supply_channel", "must be a whole number from 1"))
    vins: List[float] = []
    if "vin_v" not in params:
        out.append(Problem("vin_v", "the input voltages to try are missing"))
    else:
        try:
            vins = axis_values(params["vin_v"])
        except SweepError as exc:
            out.append(Problem("vin_v", str(exc)))
        if len(vins) > MAX_POINTS:
            out.append(Problem("vin_v", f"too many points (at most {MAX_POINTS})"))
        if any(v <= 0 for v in vins):
            out.append(Problem("vin_v", "the input voltages must be above 0"))
    loads: List[Load] = []
    try:
        loads = parse_loads(params.get("loads"))
    except LoadError as exc:
        text = str(exc)
        match = re.match(r"(loads(?:\[\d+\])?[\w.\[\]]*)", text)
        out.append(Problem(match.group(1) if match else "loads", text))
    if "vout_reading" not in params:
        out.append(Problem("vout_reading", "how the output voltage is read is missing"))
    else:
        _check_reading(params["vout_reading"], "vout_reading", out, ("meter",))
    if "iin_reading" not in params:
        out.append(Problem("iin_reading", "how the input current is read is missing"))
    else:
        _check_reading(params["iin_reading"], "iin_reading", out, ("meter", "supply"))
    if "vin_reading" in params:
        _check_reading(params["vin_reading"], "vin_reading", out, ("meter", "supply"))
    _check_switching(params.get("switching"), loads, params.get("loads"), out)
    _check_safety(params.get("safety"), vins, loads, out)
    rated = any(r.power_w for load in loads for r in load.resistors())
    safety = params.get("safety")
    if rated and not (isinstance(safety, dict) and "max_vout_v" in safety):
        out.append(
            Problem(
                "safety.max_vout_v",
                "the power ratings are only checked on the readings; give max_vout_v to check "
                "them before anything is switched on",
                "warning",
            )
        )
    timing = params.get("timing")
    if timing is not None:
        if not isinstance(timing, dict):
            out.append(Problem("timing", "must be an object: settle_s, samples, interval_s"))
        else:
            for key in set(timing) - {"settle_s", "samples", "interval_s"}:
                out.append(
                    Problem(f"timing.{key}", "unknown field: use settle_s, samples, interval_s")
                )
            for key in ("settle_s", "interval_s"):
                if key in timing and (not is_number(timing[key]) or timing[key] < 0):
                    out.append(Problem(f"timing.{key}", "must be a number of seconds, 0 or more"))
            n = timing.get("samples", 1)
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 1000:
                out.append(Problem("timing.samples", "must be a whole number from 1 to 1000"))
    limits = params.get("limits")
    if limits is not None:
        if not isinstance(limits, dict):
            out.append(Problem("limits", 'must be an object like {"min_efficiency_pct": 85}'))
        else:
            for key, value in limits.items():
                if key not in LIMIT_KEYS:
                    out.append(
                        Problem("limits", f"unknown limit {key!r}: use {', '.join(LIMIT_KEYS)}")
                    )
                elif not is_number(value) or value <= 0:
                    out.append(Problem("limits", f"{key} must be a number above 0"))
    if "confirm_setup" in params and not isinstance(params["confirm_setup"], bool):
        out.append(Problem("confirm_setup", "must be true or false"))
    check_golden_param(params, out)
    return out


# ----- the numbers ----------------------------------------------------------------------------
def figures(vin: float, iin: float, vout: float, load: Load) -> Dict[str, Any]:
    """Powers and efficiency of one reading, with the range the tolerance of the load gives.
    ``efficiency_*`` are None when the input power is too small to mean anything. No I/O."""
    nominal, low, high = load.resistance()
    pin = vin * iin
    pout, pout_min, pout_max = vout**2 / nominal, vout**2 / high, vout**2 / low
    row: Dict[str, Any] = {
        "iout_a": vout / nominal,
        "pin_w": pin,
        "pout_w": pout,
        "pout_min_w": pout_min,
        "pout_max_w": pout_max,
        "efficiency_pct": None,
        "efficiency_min_pct": None,
        "efficiency_max_pct": None,
    }
    if pin > MIN_POWER_W:
        row["efficiency_pct"] = pout / pin * 100.0
        row["efficiency_min_pct"] = pout_min / pin * 100.0
        row["efficiency_max_pct"] = pout_max / pin * 100.0
    return row


def point_verdict(row: Dict[str, Any], limits: Dict[str, float]) -> List[str]:
    """The reasons a row is out of ``limits`` (empty: it passes). The efficiency is judged by its
    **lowest** value, the one the tolerances of the resistors guarantee."""
    reasons: List[str] = []
    cap = limits.get("min_efficiency_pct")
    if cap is not None:
        low = row.get("efficiency_min_pct")
        if low is None:
            reasons.append("no input power: the efficiency cannot be worked out")
        elif low < cap:
            reasons.append(f"efficiency {low:.3g} % (lowest) below {cap:g} %")
    if "vout_min_v" in limits and row["vout_v"] < limits["vout_min_v"]:
        reasons.append(f"output {row['vout_v']:.4g} V below {limits['vout_min_v']:g} V")
    if "vout_max_v" in limits and row["vout_v"] > limits["vout_max_v"]:
        reasons.append(f"output {row['vout_v']:.4g} V above {limits['vout_max_v']:g} V")
    return reasons


def _slug(text: str) -> str:
    return re.sub(r"\W+", "_", text).strip("_") or "load"


class ResistiveEfficiency(Measurement):
    """Efficiency with a resistive load; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Nothing is switched on or connected before the question."""
        self._supply_on = False
        self._closed: List[str] = []

    # ----- running ------------------------------------------------------------------------
    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the connections, connect every load, sweep the input, report."""
        # with a golden sample: the rows (a load and an input voltage each) are checked at the end
        ctx = recording(ctx, "resistive_efficiency", self.params, summary_row=False)
        p = self.params
        loads = parse_loads(p["loads"])
        vins = axis_values(p["vin_v"])
        mode = (p.get("switching") or {}).get("mode", "manual")
        supply, meter = ctx.instrument("supply"), ctx.instrument("meter")
        switch = None
        if mode == "mux":
            if not ctx.instruments("switch"):
                raise MeasurementError(
                    "the loads are connected by the multiplexer: bind a datalogger or a switch "
                    "unit to 'switch'"
                )
            switch = ctx.instrument("switch")
        if p.get("confirm_setup", True):
            self._ask_setup(ctx, mode)
        rows: List[Dict[str, Any]] = []
        total = len(loads) * len(vins)
        limits = p.get("limits") or {}
        for load_no, load in enumerate(loads):
            ctx.checkpoint()
            self._connect(ctx, supply, switch, load, mode)
            for vin_no, vin in enumerate(vins):
                ctx.checkpoint()
                row = self._measure(ctx, supply, meter, load, vin)
                reasons = point_verdict(row, limits)
                if limits:
                    row["verdict"] = "FAIL" if reasons else "PASS"
                rows.append(row)
                ctx.emit_point(row)
                self._draw(ctx, rows, loads, vins)
                done = load_no * len(vins) + vin_no + 1
                ctx.progress(done, total, f"{load.name}, {vin:g} V ({done} of {total})")
                self._guard(row, load)
        self._summary(ctx, rows, loads, limits)
        finish(ctx)

    def teardown(self, ctx: MeasurementContext) -> None:
        """The supply off, then the relays open: always, whatever happened."""
        if getattr(self, "_supply_on", False):
            try:
                ctx.instrument("supply").call("output_off")
                self._supply_on = False
            except Exception as exc:
                ctx.log(f"could not switch the supply off: {exc}", "error")
        closed = getattr(self, "_closed", [])
        if closed:
            try:
                ctx.instrument("switch").call("open_channels", channels=",".join(closed))
                self._closed = []
            except Exception as exc:
                ctx.log(f"could not open the relays {','.join(closed)}: {exc}", "error")

    # ----- the steps ----------------------------------------------------------------------
    def _ask_setup(self, ctx: MeasurementContext, mode: str) -> None:
        text = (
            "Connect the supply to the input of the converter, the voltmeter (or the datalogger "
            "channel) to its output and the current reading (the supply's own, or the shunt)"
        )
        text += (
            ", and the resistors to the multiplexer; the relays connect them"
            if mode == "mux"
            else ". You will be asked to connect each load by hand"
        )
        text += (
            ". The supply is switched on by the measurement and switched off at the end. "
            "Then continue."
        )
        if ctx.ask(text, ["continue", "abort"], default="abort") == "abort":
            raise Stopped()

    def _connect(self, ctx, supply, switch, load: Load, mode: str) -> None:
        """Put ``load`` on the output: the supply off first (unless told not to)."""
        p = self.params
        spec = p.get("switching") or {}
        if self._supply_on and spec.get("supply_off", True):
            supply.call("output_off")
            self._supply_on = False
        if mode == "mux":
            if self._closed:
                switch.call("open_channels", channels=",".join(self._closed))
                self._closed = []
            channels = load.channels()
            switch.call("close_channel", channels=",".join(channels))
            self._closed = channels
            ctx.sleep(float(spec.get("settle_s", 0.5)))
            return
        nominal = load.resistance()[0]
        answer = ctx.ask(
            f"Connect the load '{load.name}' ({nominal:.4g} ohm) to the output of the converter. "
            "The supply is off. Then continue.",
            ["continue", "abort"],
            default="abort",
            data={"load": load.name, "r_ohm": nominal},
        )
        if answer == "abort":
            raise Stopped()

    def _reading(
        self, spec: Dict[str, Any], supply, meter, supply_call: str = "read_voltage"
    ) -> float:
        role = spec.get("role", "meter")
        handle = supply if role == "supply" else meter
        call = spec.get("call", supply_call if role == "supply" else DEFAULT_CALL)
        value = handle.call(call, **(spec.get("args") or {}))
        if not is_number(value):
            raise MeasurementError(f"{call} did not return a number: {value!r}")
        return float(value) * float(spec.get("scale", 1.0)) + float(spec.get("offset", 0.0))

    def _measure(self, ctx, supply, meter, load: Load, vin: float) -> Dict[str, Any]:
        p = self.params
        timing = p.get("timing") or {}
        channel = {"channel_number": p["supply_channel"]} if p.get("supply_channel") else {}
        supply.call("set_voltage", value=float(vin), **channel)
        if not self._supply_on:
            supply.call("output_on")
            self._supply_on = True
        ctx.sleep(float(timing.get("settle_s", 1.0)))
        n = int(timing.get("samples", 3))
        vouts: List[float] = []
        iins: List[float] = []
        vins: List[float] = []
        for k in range(n):
            ctx.checkpoint()
            vouts.append(self._reading(p["vout_reading"], supply, meter))
            iins.append(self._reading(p["iin_reading"], supply, meter, "read_current"))
            if p.get("vin_reading"):
                vins.append(self._reading(p["vin_reading"], supply, meter))
            if k + 1 < n:
                ctx.sleep(float(timing.get("interval_s", 0.1)))
        vout, iin = sum(vouts) / n, sum(iins) / n
        vin_real = sum(vins) / n if vins else vin
        nominal, low, high = load.resistance()
        row: Dict[str, Any] = {
            "load": load.name,
            "r_nom_ohm": nominal,
            "r_min_ohm": low,
            "r_max_ohm": high,
            "vin_set_v": vin,
            "vin_v": vin_real,
            "iin_a": iin,
            "vout_v": vout,
            "n_samples": n,
            **figures(vin_real, iin, vout, load),
        }
        resistor, fraction = load.most_loaded(vout)
        row["loading_pct"] = fraction * 100.0
        row["loading_resistor"] = resistor.name if resistor else ""
        if row["efficiency_pct"] is None:
            ctx.log(
                f"{load.name} at {vin:g} V: no input power, the efficiency is not worked out",
                "warning",
            )
        return row

    def _guard(self, row: Dict[str, Any], load: Load) -> None:
        """Stop (the teardown switches everything off) if a resistor or the input is overloaded."""
        safety = self.params.get("safety") or {}
        if row["loading_pct"] > 100.0:
            raise MeasurementError(
                f"the resistor {row['loading_resistor']} of the load {load.name} dissipates "
                f"{row['loading_pct']:.0f} % of its rating at {row['vout_v']:.4g} V: "
                "stopped"
            )
        cap = safety.get("max_iin_a")
        if is_number(cap) and row["iin_a"] > cap:
            raise MeasurementError(
                f"the input current {row['iin_a']:.4g} A is above the limit of {cap:g} A: stopped"
            )

    def _draw(self, ctx, rows: List[Dict[str, Any]], loads: List[Load], vins: List[float]) -> None:
        base = {"ylabel": "Efficiency (%)"}
        for load in loads:
            mine = [r for r in rows if r["load"] == load.name and r["efficiency_pct"] is not None]
            if mine:
                ctx.emit_trace(
                    f"eff_vs_vin_{_slug(load.name)}",
                    [r["vin_v"] for r in mine],
                    [r["efficiency_pct"] for r in mine],
                    hidden=len(vins) < 2,
                    xlabel="Input voltage",
                    x_unit="V",
                    **base,
                )
        if len(loads) > 1:
            for vin in vins:
                mine = [
                    r for r in rows if r["vin_set_v"] == vin and r["efficiency_pct"] is not None
                ]
                if mine:
                    ctx.emit_trace(
                        f"eff_vs_r_{_slug(f'{vin:g}V')}",
                        [r["r_nom_ohm"] for r in mine],
                        [r["efficiency_pct"] for r in mine],
                        hidden=True,
                        xlabel="Load resistance",
                        x_unit="Ω",
                        **base,
                    )

    def _summary(self, ctx, rows: List[Dict[str, Any]], loads: List[Load], limits) -> None:
        worst = "PASS"
        for load in loads:
            mine = [r for r in rows if r["load"] == load.name]
            good = [r for r in mine if r["efficiency_pct"] is not None]
            summary: Dict[str, Any] = {
                "load": load.name,
                "r_nom_ohm": load.resistance()[0],
                "points": len(mine),
            }
            if good:
                best = max(good, key=lambda r: r["efficiency_pct"])
                summary.update(
                    {
                        "efficiency_mean_pct": sum(r["efficiency_pct"] for r in good) / len(good),
                        "efficiency_min_pct": min(r["efficiency_pct"] for r in good),
                        "efficiency_max_pct": best["efficiency_pct"],
                        "best_vin_v": best["vin_v"],
                    }
                )
            if limits:
                reasons = sorted({x for r in mine for x in point_verdict(r, limits)})
                summary["verdict"] = "FAIL" if reasons else "PASS"
                if reasons:
                    worst = "FAIL"
                    ctx.log(f"{load.name}: " + "; ".join(reasons), "warning")
            ctx.emit_point(summary, table="summary")
            if good:
                ctx.log(
                    f"{load.name} ({load.resistance()[0]:.4g} ohm): efficiency "
                    f"{summary['efficiency_min_pct']:.3g} to {summary['efficiency_max_pct']:.3g} %"
                )
        if limits:
            ctx.log(f"efficiency check: {worst}", "info" if worst == "PASS" else "warning")
