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

from ola.measurement import Measurement, MeasurementContext, MeasurementError

PARAMETERS = ("S11", "S21", "S12", "S22")


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def magnitude_db(value: complex) -> float:
    """20 log10 |value|, with a floor so a zero does not give minus infinity."""
    return 20.0 * math.log10(max(abs(value), 1e-12))


class SParameters(Measurement):
    """Sweep a vector network analyzer and record its S-parameters (see the module docstring)."""

    def validate(self):
        """Parameter problems as strings (empty list: the parameters are valid)."""
        p, problems = self.params, []
        for key in ("start_hz", "stop_hz"):
            if not _number(p.get(key)) or p[key] < 0:
                problems.append(f"{key} must be a number >= 0")
        if (
            _number(p.get("start_hz"))
            and _number(p.get("stop_hz"))
            and p["stop_hz"] <= p["start_hz"]
        ):
            problems.append("stop_hz must be greater than start_hz")
        points = p.get("points")
        if not isinstance(points, int) or isinstance(points, bool) or points < 2:
            problems.append("points must be an integer >= 2")
        names = p.get("sparameters", ["S11"])
        if not isinstance(names, list) or not names:
            problems.append("sparameters must be a non-empty list")
        else:
            bad = [n for n in names if n not in PARAMETERS]
            if bad:
                problems.append(f"unknown S-parameters {bad}: use {list(PARAMETERS)}")
            if len(set(names)) != len(names):
                problems.append("sparameters has a repeated parameter")
        sweeps = p.get("sweeps", 1)
        if not isinstance(sweeps, int) or isinstance(sweeps, bool) or sweeps < 1:
            problems.append("sweeps must be an integer >= 1")
        if not _number(p.get("interval_s", 0)) or p.get("interval_s", 0) < 0:
            problems.append("interval_s must be a number >= 0")
        if "if_bandwidth_hz" in p and (
            not _number(p["if_bandwidth_hz"]) or p["if_bandwidth_hz"] <= 0
        ):
            problems.append("if_bandwidth_hz must be a number > 0")
        if "power_dbm" in p and not _number(p["power_dbm"]):
            problems.append("power_dbm must be a number")
        if "require_calibration" in p and not isinstance(p["require_calibration"], bool):
            problems.append("require_calibration must be true or false")
        return problems

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
