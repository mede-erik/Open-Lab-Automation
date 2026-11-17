# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""S-parameters of a vector network analyzer.

Parameters::

    {"start_hz": 1e6, "stop_hz": 1e9, "points": 201,
     "sparameters": ["S11", "S21"],        # default ["S11"]
     "sweeps": 5, "interval_s": 2.0,        # default one sweep
     "if_bandwidth_hz": 1000, "power_dbm": -10,    # optional, models that have them
     "require_calibration": true}           # stop instead of warning on uncalibrated data

The analyzer is the instrument bound to the ``vna`` role; it is used only through the logical
calls ``set_frequency_sweep``, ``run_sweep`` and ``read_sparameters`` (and, when asked,
``set_if_bandwidth`` and ``set_source_power``), so every VNA of the library works the same way.

Each sweep records one complex trace per S-parameter (``emit_trace``, x in Hz) and one point with
the sweep number, the time and, for each parameter, the minimum and the maximum magnitude in dB
and the frequency of the minimum (the resonance or the matching frequency of a reflection).
The calibration is made beforehand (``calibrate`` of the terminal tool, later a window): the data
say whether they are calibrated.
"""

import math
import time
from typing import Any, Dict, List

from ola.efficiency_spec import Problem
from ola.golden import check_golden_param, finish, recording
from ola.measurement import Measurement, MeasurementContext, MeasurementError

PARAMETERS = ("S11", "S21", "S12", "S22")


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def magnitude_db(value: complex) -> float:
    """20 log10 |value|, with a floor so a zero does not give minus infinity."""
    return 20.0 * math.log10(max(abs(value), 1e-12))


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new S-parameters file (used by the editor)."""
    return {
        "start_hz": 1e6,
        "stop_hz": 1e9,
        "points": 201,
        "sparameters": ["S11"],
        "sweeps": 1,
        "interval_s": 0,
    }


def _integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of its field. Does no I/O."""
    p, out = params, []
    for key in ("start_hz", "stop_hz"):
        if not _number(p.get(key)) or p[key] < 0:
            out.append(Problem(key, "must be a number of Hz, 0 or more"))
    if _number(p.get("start_hz")) and _number(p.get("stop_hz")) and p["stop_hz"] <= p["start_hz"]:
        out.append(Problem("stop_hz", "must be greater than the start frequency"))
    if not _integer(p.get("points")) or p["points"] < 2:
        out.append(Problem("points", "must be a whole number, 2 or more"))
    names = p.get("sparameters", ["S11"])
    if not isinstance(names, list) or not names:
        out.append(Problem("sparameters", "choose at least one S-parameter"))
    else:
        bad = [n for n in names if n not in PARAMETERS]
        if bad:
            out.append(
                Problem("sparameters", f"unknown S-parameters {bad}: use {list(PARAMETERS)}")
            )
        if len(set(names)) != len(names):
            out.append(Problem("sparameters", "an S-parameter is repeated"))
    if not _integer(p.get("sweeps", 1)) or p.get("sweeps", 1) < 1:
        out.append(Problem("sweeps", "must be a whole number, 1 or more"))
    if not _number(p.get("interval_s", 0)) or p.get("interval_s", 0) < 0:
        out.append(Problem("interval_s", "must be a number of seconds, 0 or more"))
    if "if_bandwidth_hz" in p and (not _number(p["if_bandwidth_hz"]) or p["if_bandwidth_hz"] <= 0):
        out.append(Problem("if_bandwidth_hz", "must be a number of Hz greater than 0"))
    if "power_dbm" in p and not _number(p["power_dbm"]):
        out.append(Problem("power_dbm", "must be a number of dBm"))
    if "require_calibration" in p and not isinstance(p["require_calibration"], bool):
        out.append(Problem("require_calibration", "must be true or false"))
    single = _integer(p.get("sweeps", 1)) and p.get("sweeps", 1) == 1
    if single and _number(p.get("interval_s")) and p["interval_s"] > 0:
        out.append(Problem("interval_s", "a single sweep does not use the interval", "warning"))
    check_golden_param(p, out)
    return out


class SParameters(Measurement):
    """Sweep a vector network analyzer and record its S-parameters (see the module docstring)."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """Parameter problems as strings (empty list: the parameters are valid)."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Set the sweep (and, when asked, the IF bandwidth and the power) on the analyzer."""
        self._vna = ctx.instrument("vna")
        p = self.params
        self._vna.call(
            "set_frequency_sweep",
            start_frequency=p["start_hz"],
            stop_frequency=p["stop_hz"],
            points=p["points"],
        )
        if "if_bandwidth_hz" in p:
            self._vna.call("set_if_bandwidth", value=p["if_bandwidth_hz"])
        if "power_dbm" in p:
            self._vna.call("set_source_power", value=p["power_dbm"])
        self._warned = False

    def run(self, ctx: MeasurementContext) -> None:
        """Run the sweeps: one complex trace per S-parameter and one summary point per sweep."""
        # with a golden sample: the rows (one for each sweep) and the curves of the last sweep
        ctx = recording(ctx, "sparameters", self.params, summary_row=False)
        names = list(self.params.get("sparameters", ["S11"]))
        sweeps = int(self.params.get("sweeps", 1))
        interval = float(self.params.get("interval_s", 0))
        t0 = time.monotonic()
        for index in range(sweeps):
            ctx.checkpoint()
            t_sweep = time.monotonic() - t0
            self._vna.call("run_sweep")
            data = self._vna.call("read_sparameters", sparameters=names)
            calibrated = bool(data.get("calibrated"))
            if not calibrated:
                if self.params.get("require_calibration"):
                    raise MeasurementError(
                        "the data are not calibrated: calibrate the analyzer for this sweep first"
                    )
                if not self._warned:
                    ctx.log("the data are not calibrated", "warning")
                    self._warned = True
            frequency = list(data["frequency"])
            point = {"sweep": index + 1, "t_s": t_sweep, "calibrated": calibrated}
            for name in names:
                part = data["parameters"][name]
                values = [complex(re, im) for re, im in zip(part["real"], part["imaginary"])]
                ctx.emit_trace(
                    name, frequency, values, kind="complex", sweep=index + 1, calibrated=calibrated
                )
                db = [magnitude_db(v) for v in values]
                lowest = min(range(len(db)), key=db.__getitem__)
                point[f"{name}_min_db"] = db[lowest]
                point[f"{name}_min_hz"] = frequency[lowest]
                point[f"{name}_max_db"] = max(db)
            ctx.emit_point(point)
            ctx.progress(index + 1, sweeps)
            if index + 1 < sweeps:
                ctx.sleep(max(0.0, t0 + (index + 1) * interval - time.monotonic()))
        finish(ctx)
