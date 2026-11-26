# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The parameters of a current pulse on an electronic load (no Qt): defaults, checks, the shape of
the pulse and the power of it.

The load makes the pulse itself (its dynamic mode): the measurement sets the two levels, the
repetition frequency and the duty cycle, switches the load on, and reads the voltage and the
current while it runs (``ola/modules/pulse_load``). The editor of the file draws the same shape
(``pulse_profile``) and corrects a parameter that would exceed the power of the load
(``ola.pulse_power.corrected_parameter``); the run window shows it as a curve.

Parameters of a ``.pls`` file::

    {"amplitude_a": 1.0,        # the high level, A
     "base_level_a": 0.0,       # the low level, A
     "width_us": 100.0,         # time at the high level, microseconds
     "frequency_hz": 1000.0,    # repetition frequency
     "rise_time_us": 10.0,      # edges, for the drawing only
     "fall_time_us": 10.0,
     "voltage_v": 12.0,         # voltage across the load: the circuit decides it (the power check)
     "duration_s": 10.0,        # optional: the run ends after this time, else it runs until Stop
     "read_interval_s": 0.5}    # time between two readings of the load
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .efficiency_spec import Problem
from .pulse_power import PulsePower, check_pulse_power

# the logical calls of the load that the pulse needs: a model without them cannot make it
REQUIRED_CALLS = (
    "load_on",
    "load_off",
    "set_dynamic_level_high",
    "set_dynamic_level_low",
    "set_dynamic_timing",
    "enable_dynamic_mode",
    "disable_dynamic_mode",
)
MIN_INTERVAL_S = 0.05


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new pulse file (used by the editor)."""
    return {
        "amplitude_a": 1.0,
        "base_level_a": 0.0,
        "width_us": 100.0,
        "frequency_hz": 1000.0,
        "rise_time_us": 10.0,
        "fall_time_us": 10.0,
        "voltage_v": 0.0,
        "duration_s": 10.0,
        "read_interval_s": 0.5,
    }


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def duty_percent(width_us: float, frequency_hz: float) -> float:
    """The duty cycle, the percent of the period at the high level."""
    return width_us * frequency_hz / 10000.0


def check_params(
    params: Mapping[str, Any], max_current: Optional[float] = None
) -> List[Problem]:
    """What is wrong with the parameters, each with the path of its field. ``max_current`` is the
    limit of the load, when known. Does no I/O."""
    p, out = params, []
    for key, unit in (("amplitude_a", "A"), ("base_level_a", "A")):
        if not _number(p.get(key)) or p[key] < 0:
            out.append(Problem(key, f"must be a number of {unit}, 0 or more"))
        elif max_current and p[key] > max_current:
            out.append(
                Problem(key, f"{p[key]} A is above the maximum of the load ({max_current} A)")
            )
    for key, low in (("width_us", 1.0), ("rise_time_us", 0.1), ("fall_time_us", 0.1)):
        if not _number(p.get(key)) or p[key] < low:
            out.append(Problem(key, f"must be a number of microseconds, {low:g} or more"))
    if not _number(p.get("frequency_hz")) or p["frequency_hz"] <= 0:
        out.append(Problem("frequency_hz", "must be a number of Hz greater than 0"))
    if not _number(p.get("voltage_v", 0)) or p.get("voltage_v", 0) < 0:
        out.append(Problem("voltage_v", "must be a number of volts, 0 or more"))
    if _number(p.get("width_us")) and _number(p.get("frequency_hz")) and p["frequency_hz"] > 0:
        duty = duty_percent(p["width_us"], p["frequency_hz"])
        if not 0.0 < duty < 100.0:
            out.append(
                Problem(
                    "width_us",
                    f"a width of {p['width_us']:g} us does not fit in the period of "
                    f"{p['frequency_hz']:g} Hz",
                )
            )
    if "duration_s" in p and (not _number(p["duration_s"]) or p["duration_s"] <= 0):
        out.append(Problem("duration_s", "must be a number of seconds greater than 0"))
    interval = p.get("read_interval_s", 0.5)
    if not _number(interval) or interval < MIN_INTERVAL_S:
        out.append(Problem("read_interval_s", f"must be {MIN_INTERVAL_S:g} s or more"))
    return out


def pulse_profile(
    amplitude: float,
    base_level: float,
    width_us: float,
    frequency_hz: float,
    rise_time_us: float,
    fall_time_us: float,
    periods: int = 2,
    points: int = 1000,
) -> Tuple[List[float], List[float]]:
    """The shape of the pulse, ``periods`` of it: ``(time in seconds, current in A)``, with
    straight rising and falling edges. The widths and the edges are in microseconds."""
    period = 1_000_000.0 / frequency_hz if frequency_hz > 0 else 1000.0  # microseconds
    times, currents = [], []
    for k in range(points):
        t = periods * period * k / (points - 1)
        inside = t % period
        if inside < rise_time_us:
            value = base_level + (amplitude - base_level) * (inside / rise_time_us)
        elif inside < rise_time_us + width_us:
            value = amplitude
        elif inside < rise_time_us + width_us + fall_time_us:
            fall = inside - (rise_time_us + width_us)
            value = amplitude - (amplitude - base_level) * (fall / fall_time_us)
        else:
            value = base_level
        times.append(t * 1e-6)
        currents.append(value)
    return times, currents


def power_of(
    params: Mapping[str, Any], voltage: float, max_power: Optional[float]
) -> PulsePower:
    """Peak and average power of the pulse of ``params`` at ``voltage`` against ``max_power``."""
    duty = duty_percent(params["width_us"], params["frequency_hz"])
    return check_pulse_power(
        params["amplitude_a"], params["base_level_a"], duty, voltage, max_power
    )


def power_message(result: PulsePower, max_power: float) -> str:
    """The sentence for a pulse that exceeds the power limit of the load."""
    return (
        f"the pulse needs {round(result.worst, 3)} W: the load is limited to {max_power} W "
        f"(peak {round(result.peak, 3)} W, average {round(result.average, 3)} W)"
    )
