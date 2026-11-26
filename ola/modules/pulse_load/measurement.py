# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A current pulse on an electronic load.

Parameters (``.pls`` file)::

    {"amplitude_a": 1.0, "base_level_a": 0.0, "width_us": 100, "frequency_hz": 1000,
     "rise_time_us": 10, "fall_time_us": 10,       # the edges: for the drawing only
     "voltage_v": 12,                              # across the load: the power check
     "duration_s": 10, "read_interval_s": 0.5}     # duration is optional: without it, until Stop

The load (role ``load``) makes the pulse itself, in its dynamic mode: the measurement sets the
high and the low level, the repetition frequency and the duty cycle, switches the dynamic mode on
and then the load input on. It uses only the logical calls ``set_dynamic_level_high``,
``set_dynamic_level_low``, ``set_dynamic_timing``, ``enable_dynamic_mode``, ``load_on``,
``disable_dynamic_mode`` and ``load_off`` (and ``read_voltage`` / ``read_current``), so every load
of the library that has them works the same way.

Safe by construction: before anything is switched on the peak and the average power of the pulse
(current x voltage) are checked against the power limit of the load, with the larger of the
entered working voltage and the voltage read from the load; a pulse above the limit, or a power
limit with no known voltage, is refused. The dynamic mode and the load input are switched off at
the end, also after an error or a stop.

The results are the table ``points`` (the time, the voltage and the current read from the load,
and their product) and the curve ``profile``, the shape of the pulse that was asked for.
"""

import time
from typing import Any, List

from ola.compat import CURRENT, POWER, handle_characteristics
from ola.efficiency_spec import Problem
from ola.measurement import Measurement, MeasurementContext, MeasurementError
from ola.pulse_load import (
    REQUIRED_CALLS,
    check_params,
    duty_percent,
    power_message,
    power_of,
    pulse_profile,
)

READINGS = ("read_voltage", "read_current")


class PulseLoad(Measurement):
    """A pulse on an electronic load; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Check the model, the current and the power: nothing is switched on if one fails."""
        self._load = ctx.instrument("load")
        self._touched = False  # becomes True just before the first call that changes the load
        supports = getattr(self._load, "supports", None)
        if supports is not None:
            missing = [call for call in REQUIRED_CALLS if not supports(call)]
            if missing:
                raise MeasurementError(
                    f"the load does not have the calls the pulse needs: {', '.join(missing)}"
                )
        limits = handle_characteristics(self._load)
        problems = check_params(self.params, limits.get(CURRENT))
        errors = [p for p in problems if p.severity == "error"]
        if errors:
            raise MeasurementError("; ".join(str(p) for p in errors))
        self._check_power(limits.get(POWER))

    def _check_power(self, max_power: Any) -> None:
        """Refuse a pulse above the power limit of the load (no limit in the library: no check)."""
        if not max_power:
            return
        voltage = float(self.params.get("voltage_v") or 0.0)
        try:
            voltage = max(voltage, float(self._load.call("read_voltage")))
        except Exception:  # the load could not be read: only the entered voltage is known
            pass
        if voltage <= 0:
            raise MeasurementError(
                "the voltage across the load is not known: enter the working voltage, "
                "the power of the pulse cannot be checked without it"
            )
        result = power_of(self.params, voltage, max_power)
        if result.exceeded:
            raise MeasurementError(power_message(result, max_power))

    def run(self, ctx: MeasurementContext) -> None:
        """Start the pulse and read the voltage and the current until the end or a stop."""
        p, load = self.params, self._load
        times, currents = pulse_profile(
            p["amplitude_a"], p["base_level_a"], p["width_us"], p["frequency_hz"],
            p.get("rise_time_us", 10.0), p.get("fall_time_us", 10.0),
        )  # fmt: skip
        ctx.emit_trace(
            "profile", times, currents, kind="real",
            xlabel="Time", x_unit="s", ylabel="Current (A)",
        )  # fmt: skip
        self._touched = True
        load.call("set_dynamic_level_high", value=p["amplitude_a"])
        load.call("set_dynamic_level_low", value=p["base_level_a"])
        load.call(
            "set_dynamic_timing",
            frequency=p["frequency_hz"],
            duty=duty_percent(p["width_us"], p["frequency_hz"]),
        )
        load.call("enable_dynamic_mode")
        load.call("load_on")
        ctx.log(f"pulse started: {p['amplitude_a']:g} A over {p['base_level_a']:g} A, "
                f"{p['frequency_hz']:g} Hz")  # fmt: skip

        duration = p.get("duration_s")
        interval = float(p.get("read_interval_s", 0.5))
        supports = getattr(load, "supports", None)
        can_read = supports is None or all(supports(call) for call in READINGS)
        if not can_read:
            ctx.log("the load cannot be read: the pulse runs without readings", "warning")
        start = time.monotonic()
        while True:
            ctx.checkpoint()
            elapsed = time.monotonic() - start
            if duration is not None and elapsed >= duration:
                break
            if can_read:
                voltage = float(load.call("read_voltage"))
                current = float(load.call("read_current"))
                ctx.emit_point(
                    {"t_s": elapsed, "voltage_v": voltage, "current_a": current,
                     "power_w": voltage * current}
                )  # fmt: skip
            ctx.progress(min(elapsed, duration) if duration else elapsed, duration, "pulse running")
            ctx.sleep(interval if duration is None else min(interval, max(duration - elapsed, 0.0)))

    def teardown(self, ctx: MeasurementContext) -> None:
        """The dynamic mode and the load input off: always, whatever happened."""
        if not getattr(self, "_touched", False):
            return
        for name in ("disable_dynamic_mode", "load_off"):
            try:
                self._load.call(name)
            except Exception as exc:  # keep going: the load must still be switched off
                ctx.log(f"could not switch the load off ({name}): {exc}", "error")
