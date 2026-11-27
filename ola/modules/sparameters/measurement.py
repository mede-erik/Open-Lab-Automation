# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""S-parameters of a vector network analyzer.

Parameters::

    {"sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 201, "scale": "linear",
               "if_bandwidth_hz": 1000, "power_dbm": -10},   # the last three optional
     "sparameters": ["S11", "S21"],        # default ["S11"]
     "sweeps": 5, "interval_s": 2.0,        # default one sweep (more: the same sweep repeated)
     "averages": 1,                         # sweeps averaged into each recorded one
     "z0": 50,                              # the reference impedance of the VNA (Touchstone)
     "require_calibration": true,           # stop instead of warning on uncalibrated data
     "confirm_setup": true}                 # ask once whether the VNA is calibrated

The sweep is the ``sweep`` block of every VNA measurement. A file written before, with
``start_hz``, ``stop_hz``, ``points``, ``if_bandwidth_hz`` and ``power_dbm`` at the top, is read
the same way (``upgrade_params``) and the editor writes the new form.

The analyzer is the instrument bound to the ``vna`` role. Every recorded sweep goes through
``ola.vna_common.acquire``, as in the other VNA measurements: the same calls for every VNA of the
library (and the simple calls of the simulation), the averaging, the log scale, the notes on what
the instrument cannot do and the check of the calibration.

Each recorded sweep gives one complex trace per S-parameter (``emit_trace``, x in Hz) and one point
with the sweep number, the time and, for each parameter, the minimum and the maximum magnitude in
dB and the frequency of the minimum (the resonance or the matching frequency of a reflection).
"""

import math
import time
from typing import Any, Dict, List

from ola.efficiency_spec import Problem
from ola.golden import check_golden_param, finish, recording
from ola.measurement import Measurement, MeasurementContext
from ola.run_view import format_si
from ola.vna_common import (
    acquire,
    ask_setup,
    check_common,
    check_sweep,
    upgrade_params as _upgrade,
    upgraded,
)

PARAMETERS = ("S11", "S21", "S12", "S22")


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def magnitude_db(value: complex) -> float:
    """20 log10 |value|, with a floor so a zero does not give minus infinity."""
    return 20.0 * math.log10(max(abs(value), 1e-12))


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new S-parameters file (used by the editor)."""
    return {
        "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 201, "scale": "linear"},
        "sparameters": ["S11"],
        "sweeps": 1,
        "interval_s": 0,
        "averages": 1,
        "confirm_setup": True,
    }


def upgrade_params(params: Dict[str, Any]) -> bool:
    """Move the sweep of a file written before (keys at the top) into ``sweep``, in place (the
    editor calls it when it opens a file); True if anything changed."""
    return _upgrade(params, flat_sweep=True)


def _integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of its field. Does no I/O."""
    p, out = upgraded(params, flat_sweep=True), []
    start, stop = check_sweep(p, out)
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
    check_common(p, out, start, stop)
    single = _integer(p.get("sweeps", 1)) and p.get("sweeps", 1) == 1
    if single and _number(p.get("interval_s")) and p["interval_s"] > 0:
        out.append(Problem("interval_s", "a single sweep does not use the interval", "warning"))
    check_golden_param(p, out)
    return out


class SParameters(Measurement):
    """Sweep a vector network analyzer and record its S-parameters (see the module docstring)."""

    def __init__(self, params: Dict[str, Any]):
        super().__init__(upgraded(params, flat_sweep=True))  # a file written before works too

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """Parameter problems as strings (empty list: the parameters are valid)."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Take the analyzer of the ``vna`` role (the sweep is set before each recorded one)."""
        self._vna = ctx.instrument("vna")

    def run(self, ctx: MeasurementContext) -> None:
        """Run the sweeps: one complex trace per S-parameter and one summary point per sweep."""
        # with a golden sample: the rows (one for each sweep) and the curves of the last sweep
        ctx = recording(ctx, "sparameters", self.params, summary_row=False)
        p = self.params
        sweep = p["sweep"]
        names = list(p.get("sparameters", ["S11"]))
        sweeps = int(p.get("sweeps", 1))
        interval = float(p.get("interval_s", 0))
        if p.get("confirm_setup", True):
            ask_setup(
                ctx,
                f"Connect the device for {', '.join(names)}.",
                sweep,
                connect_key="run_connect_sparameters",
                connect_args={"parameters": ", ".join(names)},
                mode="transmission" if set(names) - {"S11", "S22"} else "reflection",
            )
        t0 = time.monotonic()
        for index in range(sweeps):
            ctx.checkpoint()
            t_sweep = time.monotonic() - t0
            status: Dict[str, Any] = {}
            frequency, traces = acquire(
                ctx,
                self._vna,
                sweep,
                names,
                int(p.get("averages", 1)),
                notes=index == 0,  # the notes on the sweep once, not at every repetition
                require_calibration=bool(p.get("require_calibration", False)),
                status=status,
            )
            calibrated = status.get("calibrated")  # acquire warns once if it is False
            if calibrated is None:
                calibrated = True  # the simple calls do not say: taken as calibrated, as before
            point = {"sweep": index + 1, "t_s": t_sweep, "calibrated": calibrated}
            for name in names:
                values = traces[name]
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
        if sweeps:
            ctx.log(
                f"{sweeps} sweep(s) of {format_si(sweep['start_hz'], 'Hz')} to "
                f"{format_si(sweep['stop_hz'], 'Hz')} recorded"
            )
