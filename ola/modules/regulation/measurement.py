"""Line and load regulation of a converter or a regulator.

Parameters (``.reg`` file)::

    {"device": {"label": "5 V buck", "nominal_v": 5.0},            # nominal_v is optional
     "supply_channel": 1,                                           # optional
     "output_reading": {"call": "measure_dc_voltage",
                        "args": {"range": "AUTO", "resolution": "DEF", "channels": "103"}},
     "input_reading": {"call": "measure_dc_voltage",                  # optional
                       "args": {"range": "AUTO", "resolution": "DEF", "channels": "101"}},
     "line_test": {"vin_v": {"start": 9, "stop": 15, "points": 7}, "load_a": 1.0},
     "load_test": {"i_a": {"start": 0, "stop": 2, "points": 5}, "vin_v": 12},
     "timing": {"settle_s": 1, "samples": 3, "interval_s": 0.1},
     "safety": {"max_vin_v": 20, "max_load_a": 3},
     "limits": {"max_line_pct": 1, "max_load_pct": 1, "vout_min_v": 4.75, "vout_max_v": 5.25},
     "confirm_setup": true}

A supply feeds the input (role ``supply``), an electronic load draws the current (role ``load``)
and the output voltage is read by a multimeter or one channel of a datalogger (role ``meter``,
which instrument and which channel is in ``output_reading``: any instrument that answers
``measure_dc_voltage``). The arguments of that call are the instrument's: a **datalogger** wants
``range`` and ``resolution`` (``"AUTO"`` and ``"DEF"`` are fine) and the ``channels``; a
**multimeter** has no channels and wants **numbers** (``{"range": 10, "resolution": 0.001}``).
At least one of the two tests is needed.

* **Line regulation** (``line_test``): the input voltage is swept at a fixed load current and the
  output is read at every step. It is given as the **spread** of the output over the sweep (mV), in
  **percent** of the nominal output (``device.nominal_v``, else the mean of the output) and as the
  **slope** (mV per volt, a straight-line fit).
* **Load regulation** (``load_test``): the load current is swept at a fixed input voltage. It is
  ``(V at the lowest current - V at the highest) / reference * 100``, the reference being
  ``device.nominal_v`` or, without it, the output at the highest current (the usual "no load to
  full load"), and the **output resistance** in milliohms (a straight-line fit of the voltage
  against the current: the drop per ampere).

With ``input_reading`` the input voltage used for the line test and the drop in the cables between
the supply and the converter (the *input* at the converter pins, not the supply setpoint) is what is
measured: with a long cable the supply setpoint is not the voltage the converter sees. A reading
with ``role`` ``supply`` takes the voltage the supply itself reports (``read_voltage``).

Safe by construction: the load is set to 0 A before the supply is switched on, ``safety`` refuses a
point above ``max_vin_v`` / ``max_load_a`` before anything is switched on, and the load (set to 0 A
first) and the supply are switched off at the end, also after an error or a stop. The results are
the table ``points`` (every step: set and measured input, load current, output, the spread of the
readings), the table ``summary`` (a row per test with the regulation figures and the verdict), and
the curves ``vout_vs_vin`` and ``vout_vs_load``. Out of limits is a *result*, not an error.
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ola.golden import check_golden_param, finish, recording
from ola.efficiency_spec import Problem
from ola.measurement import Measurement, MeasurementContext, MeasurementError, Stopped
from ola.run_view import format_si
from ola.sweep import SweepError, axis_values
from ola.vna_common import check_asset, is_number

DEFAULT_CALL = "measure_dc_voltage"
LIMIT_KEYS = ("max_line_pct", "max_load_pct", "vout_min_v", "vout_max_v")
MAX_POINTS = 1000
READING_KEYS = ("role", "call", "args", "scale", "offset")


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new regulation measurement (used by the editor)."""
    return {
        "device": {"label": ""},
        "output_reading": {"call": DEFAULT_CALL, "args": {"range": "AUTO", "resolution": "DEF"}},
        "line_test": {"vin_v": {"start": 9, "stop": 15, "points": 7}, "load_a": 1.0},
        "load_test": {"i_a": {"start": 0, "stop": 2, "points": 5}, "vin_v": 12},
        "timing": {"settle_s": 1.0, "samples": 3, "interval_s": 0.1},
        "confirm_setup": True,
    }


# ----- checking the parameters ----------------------------------------------------------------
def _axis(spec: Any, path: str, out: List[Problem]) -> Optional[List[float]]:
    try:
        values = axis_values(spec)
    except SweepError as exc:
        out.append(Problem(path, str(exc)))
        return None
    if len(values) > MAX_POINTS:
        out.append(Problem(path, f"too many points (at most {MAX_POINTS})"))
    if any(v < 0 for v in values):
        out.append(Problem(path, "the values must be 0 or more"))
    return values


def _check_reading(spec: Any, path: str, out: List[Problem], roles: Sequence[str]) -> None:
    if not isinstance(spec, dict):
        out.append(Problem(path, "must be an object: call, args, scale, offset"))
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
    if "scale" in spec and is_number(spec["scale"]) and spec["scale"] == 0:
        out.append(Problem(f"{path}.scale", "must not be 0"))


def _check_fixed(spec: Dict[str, Any], key: str, path: str, out: List[Problem], what: str):
    if key not in spec:
        return
    if not is_number(spec[key]) or spec[key] < 0:
        out.append(Problem(f"{path}.{key}", f"{what} must be a number, 0 or more"))


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    device = params.get("device", {})
    if not isinstance(device, dict):
        out.append(Problem("device", "must be an object with a 'label'"))
    else:
        if "label" in device and not isinstance(device["label"], str):
            out.append(Problem("device.label", "the label must be text"))
        if "nominal_v" in device and (
            not is_number(device["nominal_v"]) or device["nominal_v"] <= 0
        ):
            out.append(
                Problem("device.nominal_v", "the nominal voltage must be a number above 0 (V)")
            )
    check_asset(params, "device", out)
    channel = params.get("supply_channel")
    if channel is not None and (
        not isinstance(channel, int) or isinstance(channel, bool) or channel < 1
    ):
        out.append(Problem("supply_channel", "must be a whole number from 1"))
    if "output_reading" not in params:
        out.append(Problem("output_reading", "how the output voltage is read is missing"))
    else:
        _check_reading(params["output_reading"], "output_reading", out, ("meter",))
    if "input_reading" in params:
        _check_reading(params["input_reading"], "input_reading", out, ("meter", "supply"))
    line, load = params.get("line_test"), params.get("load_test")
    safety = params.get("safety") or {}
    if line is None and load is None:
        out.append(Problem("line_test", "give a line_test, a load_test or both"))
    vins: List[float] = []
    currents: List[float] = []
    if line is not None:
        if not isinstance(line, dict):
            out.append(Problem("line_test", "must be an object: vin_v and load_a"))
        else:
            for key in set(line) - {"vin_v", "load_a"}:
                out.append(Problem(f"line_test.{key}", "unknown field: use vin_v, load_a"))
            axis = _axis(line["vin_v"], "line_test.vin_v", out) if "vin_v" in line else None
            if "vin_v" not in line:
                out.append(Problem("line_test.vin_v", "the input voltages to try are missing"))
            vins += axis or []
            _check_fixed(line, "load_a", "line_test", out, "the load current")
            if is_number(line.get("load_a")):
                currents.append(float(line["load_a"]))
    if load is not None:
        if not isinstance(load, dict):
            out.append(Problem("load_test", "must be an object: i_a and vin_v"))
        else:
            for key in set(load) - {"i_a", "vin_v"}:
                out.append(Problem(f"load_test.{key}", "unknown field: use i_a, vin_v"))
            if "i_a" not in load:
                out.append(Problem("load_test.i_a", "the load currents to try are missing"))
            else:
                currents += _axis(load["i_a"], "load_test.i_a", out) or []
            if not is_number(load.get("vin_v")) or load.get("vin_v", -1) < 0:
                out.append(Problem("load_test.vin_v", "the input voltage must be a number (V)"))
            else:
                vins.append(float(load["vin_v"]))
    _check_safety(safety, vins, currents, out)
    _check_timing(params.get("timing"), out)
    limits = params.get("limits")
    if limits is not None:
        if not isinstance(limits, dict):
            out.append(Problem("limits", 'must be an object like {"max_load_pct": 1}'))
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


def _check_safety(safety: Any, vins: List[float], currents: List[float], out: List[Problem]):
    if not isinstance(safety, dict):
        out.append(Problem("safety", "must be an object: max_vin_v, max_load_a"))
        return
    for key in set(safety) - {"max_vin_v", "max_load_a"}:
        out.append(Problem(f"safety.{key}", "unknown field: use max_vin_v, max_load_a"))
    for key, values, unit in (("max_vin_v", vins, "V"), ("max_load_a", currents, "A")):
        if key not in safety:
            continue
        if not is_number(safety[key]) or safety[key] <= 0:
            out.append(Problem(f"safety.{key}", f"must be a number of {unit} above 0"))
        elif values and max(values) > safety[key]:
            out.append(
                Problem(
                    f"safety.{key}",
                    f"the test goes to {max(values):g} {unit}, above the limit "
                    f"of {safety[key]:g} {unit}",
                )
            )


def _check_timing(timing: Any, out: List[Problem]) -> None:
    if timing is None:
        return
    if not isinstance(timing, dict):
        out.append(Problem("timing", "must be an object: settle_s, samples, interval_s"))
        return
    for key in set(timing) - {"settle_s", "samples", "interval_s"}:
        out.append(Problem(f"timing.{key}", "unknown field: use settle_s, samples, interval_s"))
    for key in ("settle_s", "interval_s"):
        if key in timing and (not is_number(timing[key]) or timing[key] < 0):
            out.append(Problem(f"timing.{key}", "must be a number of seconds, 0 or more"))
    n = timing.get("samples", 1)
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 1000:
        out.append(Problem("timing.samples", "must be a whole number from 1 to 1000"))


# ----- the numbers ----------------------------------------------------------------------------
def fit_line(x: Sequence[float], y: Sequence[float]) -> Tuple[float, float]:
    """``(slope, intercept)`` of the straight line that best fits ``y`` against ``x`` (the slope is
    0 if all the ``x`` are equal)."""
    n = len(x)
    mean_x, mean_y = sum(x) / n, sum(y) / n
    den = sum((a - mean_x) ** 2 for a in x)
    slope = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / den if den else 0.0
    return slope, mean_y - slope * mean_x


def line_figures(vin: Sequence[float], vout: Sequence[float], nominal_v: Optional[float]):
    """The line regulation from the measured input and output voltages. No I/O."""
    reference = nominal_v if nominal_v else sum(vout) / len(vout)
    spread = max(vout) - min(vout)
    slope, _ = fit_line(vin, vout)
    return {
        "points": len(vin),
        "vin_min_v": min(vin),
        "vin_max_v": max(vin),
        "vout_min_v": min(vout),
        "vout_max_v": max(vout),
        "reference_v": reference,
        "span_mv": spread * 1000,
        "line_regulation_pct": spread / reference * 100,
        "line_regulation_mv_per_v": slope * 1000,
    }


def load_figures(current: Sequence[float], vout: Sequence[float], nominal_v: Optional[float]):
    """The load regulation from the load currents and the output voltages. No I/O."""
    order = sorted(range(len(current)), key=current.__getitem__)
    low, high = order[0], order[-1]
    reference = nominal_v if nominal_v else vout[high]
    slope, _ = fit_line(current, vout)
    figures: Dict[str, Any] = {
        "points": len(current),
        "i_min_a": current[low],
        "i_max_a": current[high],
        "vout_min_v": min(vout),
        "vout_max_v": max(vout),
        "v_low_load_v": vout[low],
        "v_high_load_v": vout[high],
        "reference_v": reference,
        "load_regulation_pct": (vout[low] - vout[high]) / reference * 100,
        "output_resistance_mohm": -slope * 1000,
    }
    return figures


def verdict(figures: Dict[str, Any], limits: Dict[str, float], test: str):
    """``("PASS" | "FAIL", reasons)`` of the figures of one test against ``limits``."""
    reasons: List[str] = []
    key = "line_regulation_pct" if test == "line" else "load_regulation_pct"
    cap = limits.get("max_line_pct" if test == "line" else "max_load_pct")
    if cap is not None and abs(figures[key]) > cap:
        reasons.append(f"{test} regulation {figures[key]:.3g} % beyond {cap:g} %")
    if "vout_min_v" in limits and figures["vout_min_v"] < limits["vout_min_v"]:
        reasons.append(
            f"the output goes down to {figures['vout_min_v']:.4g} V, "
            f"below {limits['vout_min_v']:g} V"
        )
    if "vout_max_v" in limits and figures["vout_max_v"] > limits["vout_max_v"]:
        reasons.append(
            f"the output goes up to {figures['vout_max_v']:.4g} V, above {limits['vout_max_v']:g} V"
        )
    return ("FAIL" if reasons else "PASS"), reasons


def build_points(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The steps of the measurement, in order: ``{"test": "line" | "load", "vin": ..., "i": ...}``.
    The line test goes through the input voltages as given, the load test through the currents."""
    points: List[Dict[str, Any]] = []
    line, load = params.get("line_test"), params.get("load_test")
    if line:
        for vin in axis_values(line["vin_v"]):
            points.append({"test": "line", "vin": vin, "i": float(line.get("load_a", 0) or 0)})
    if load:
        for current in axis_values(load["i_a"]):
            points.append({"test": "load", "vin": float(load["vin_v"]), "i": current})
    return points


class Regulation(Measurement):
    """Line and load regulation; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Nothing is switched on before the question."""
        self._supply_on = False
        self._load_on = False

    # ----- running ------------------------------------------------------------------------
    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the connections, step through the points, report the regulation."""
        # with a golden sample: the rows (one for each point) are checked at the end
        ctx = recording(ctx, "regulation", self.params, summary_row=False)
        p = self.params
        points = build_points(p)
        needs_load = any(pt["i"] > 0 for pt in points) or bool(p.get("load_test"))
        loads = ctx.instruments("load")
        if needs_load and not loads:
            raise MeasurementError("this test draws current: bind an electronic load to 'load'")
        supply, meter = ctx.instrument("supply"), ctx.instrument("meter")
        load = loads[0] if loads else None
        if p.get("confirm_setup", True):
            self._ask_setup(ctx, load is not None)
        channel = {"channel_number": p["supply_channel"]} if p.get("supply_channel") else {}
        # the load is at 0 A before the supply is switched on
        if load is not None:
            load.call("set_mode", mode="CC")
            load.call("set_current_level", value=0.0)
        supply.call("set_voltage", value=float(points[0]["vin"]), **channel)
        supply.call("output_on")
        self._supply_on = True
        if load is not None:
            load.call("load_on")
            self._load_on = True
        timing = p.get("timing") or {}
        rows: List[Dict[str, Any]] = []
        last: Dict[str, Optional[float]] = {"vin": None, "i": None}
        for number, point in enumerate(points, 1):
            ctx.checkpoint()
            changed = False
            if point["vin"] != last["vin"]:
                supply.call("set_voltage", value=float(point["vin"]), **channel)
                changed = True
            if load is not None and point["i"] != last["i"]:
                load.call("set_current_level", value=float(point["i"]))
                changed = True
            last = {"vin": point["vin"], "i": point["i"]}
            if changed or number == 1:
                ctx.sleep(float(timing.get("settle_s", 1.0)))
            row = self._read_point(ctx, supply, meter, point, timing)
            rows.append(row)
            ctx.emit_point(row)
            self._draw(ctx, rows)
            ctx.progress(number, len(points), f"{point['test']} test, point {number}")
        self._summary(ctx, rows)
        finish(ctx)

    def teardown(self, ctx: MeasurementContext) -> None:
        """The load back to 0 A and off, then the supply off: always, whatever happened."""
        for what, active, steps in (
            ("load", self._load_on, (("set_current_level", {"value": 0.0}), ("load_off", {}))),
            ("supply", self._supply_on, (("output_off", {}),)),
        ):
            if not active:
                continue
            for name, args in steps:
                try:
                    ctx.instrument(what).call(name, **args)
                except Exception as exc:  # keep going: the other one must still be switched off
                    ctx.log(f"could not switch the {what} off ({name}): {exc}", "error")

    # ----- the steps ----------------------------------------------------------------------
    def _ask_setup(self, ctx: MeasurementContext, with_load: bool) -> None:
        text = (
            "Connect the supply to the input of the converter, the voltmeter (or the datalogger "
            "channel) to its output"
        )
        text += ", the electronic load to the output" if with_load else ""
        text += (
            ". The supply and the load are switched on by the measurement, the load at 0 A first, "
            "and switched off at the end. Then continue."
        )
        if ctx.ask(text, ["continue", "abort"], default="abort") == "abort":
            raise Stopped()

    def _reading(self, ctx, spec, supply, meter) -> float:
        role = spec.get("role", "meter")
        handle = supply if role == "supply" else meter
        call = spec.get("call", "read_voltage" if role == "supply" else DEFAULT_CALL)
        value = handle.call(call, **(spec.get("args") or {}))
        if not is_number(value):
            raise MeasurementError(f"{call} did not return a number: {value!r}")
        return float(value) * float(spec.get("scale", 1.0)) + float(spec.get("offset", 0.0))

    def _read_point(self, ctx, supply, meter, point, timing) -> Dict[str, Any]:
        p = self.params
        n = int(timing.get("samples", 3))
        outs: List[float] = []
        ins: List[float] = []
        for k in range(n):
            ctx.checkpoint()
            outs.append(self._reading(ctx, p["output_reading"], supply, meter))
            if p.get("input_reading"):
                ins.append(self._reading(ctx, p["input_reading"], supply, meter))
            if k + 1 < n:
                ctx.sleep(float(timing.get("interval_s", 0.1)))
        vout = sum(outs) / n
        row: Dict[str, Any] = {
            "test": point["test"],
            "vin_set_v": point["vin"],
            "vin_v": sum(ins) / n if ins else point["vin"],
            "load_a": point["i"],
            "vout_v": vout,
            "vout_spread_mv": (max(outs) - min(outs)) * 1000,
            "samples": n,
        }
        if ins:
            row["vin_drop_v"] = point["vin"] - row["vin_v"]
        return row

    def _draw(self, ctx: MeasurementContext, rows: List[Dict[str, Any]]) -> None:
        line = [r for r in rows if r["test"] == "line"]
        load = [r for r in rows if r["test"] == "load"]
        if line:
            ctx.emit_trace(
                "vout_vs_vin", [r["vin_v"] for r in line], [r["vout_v"] for r in line],
                xlabel="Input voltage", x_unit="V", ylabel="Output voltage (V)",
            )  # fmt: skip
        if load:
            ctx.emit_trace(
                "vout_vs_load", [r["load_a"] for r in load], [r["vout_v"] for r in load],
                xlabel="Load current", x_unit="A", ylabel="Output voltage (V)",
            )  # fmt: skip

    def _summary(self, ctx: MeasurementContext, rows: List[Dict[str, Any]]) -> None:
        p = self.params
        dev = p.get("device") or {}
        nominal = dev.get("nominal_v")
        limits = p.get("limits") or {}
        label = dev.get("label", "")
        named = f" '{label}'" if label else ""
        for test in ("line", "load"):
            part = [r for r in rows if r["test"] == test]
            if not part:
                continue
            if test == "line":
                figures = line_figures(
                    [r["vin_v"] for r in part], [r["vout_v"] for r in part], nominal
                )
                figures["load_a"] = part[0]["load_a"]
                text = (
                    f"line regulation{named}: {figures['line_regulation_pct']:.3g} % "
                    f"({figures['line_regulation_mv_per_v']:.3g} mV/V) for "
                    f"{format_si(figures['vin_min_v'], 'V')} to "
                    f"{format_si(figures['vin_max_v'], 'V')}"
                )
            else:
                figures = load_figures(
                    [r["load_a"] for r in part], [r["vout_v"] for r in part], nominal
                )
                figures["vin_v"] = part[0]["vin_v"]
                text = (
                    f"load regulation{named}: {figures['load_regulation_pct']:.3g} % "
                    f"(output resistance {figures['output_resistance_mohm']:.3g} mOhm) for "
                    f"{format_si(figures['i_min_a'], 'A')} to {format_si(figures['i_max_a'], 'A')}"
                )
            summary: Dict[str, Any] = {"test": test, "device": label, **figures}
            if limits:
                summary["verdict"], reasons = verdict(figures, limits, test)
                for why in reasons:
                    ctx.log(f"limit exceeded ({test} test): {why}", "warning")
            if any("vin_drop_v" in r for r in part):
                summary["max_vin_drop_v"] = max(
                    abs(r["vin_drop_v"]) for r in part if "vin_drop_v" in r
                )
            ctx.log(text)
            ctx.emit_point(summary, table="summary")
        if not math.isfinite(sum(r["vout_v"] for r in rows)):
            ctx.log("a reading is not a finite number", "warning")
