# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Power of a current pulse on an electronic load: peak and average, and the largest value of a
parameter that keeps both within the power limit of the load.

The pulse switches between a high level (the amplitude) and a base level, with a duty cycle.
The voltage is the one across the load (the circuit under test decides it). Rise and fall times
are ignored, which is the safe side for the peak and a small error for the average.

No Qt here: the pulse generator dialog uses these functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class PulsePower:
    """Powers of a pulse in watts and which limits they exceed."""

    peak: float
    average: float
    exceeded: List[str]  # "peak" and/or "average"; empty when both are within the limit

    @property
    def worst(self) -> float:
        """The larger of the two powers."""
        return max(self.peak, self.average)


def pulse_powers(amplitude: float, base_level: float, duty: float, voltage: float):
    """(peak, average) power in W of a pulse of ``amplitude`` A over ``base_level`` A.

    ``duty`` is the percentage of the period at the amplitude; ``voltage`` is in V.
    """
    high, low = max(amplitude, base_level), min(amplitude, base_level)
    fraction = min(max(duty, 0.0), 100.0) / 100.0
    average_current = low + (high - low) * fraction
    return voltage * high, voltage * average_current


def check_pulse_power(
    amplitude: float, base_level: float, duty: float, voltage: float, max_power: Optional[float]
) -> PulsePower:
    """Peak and average power of a pulse against the power limit of the load (None: no limit)."""
    peak, average = pulse_powers(amplitude, base_level, duty, voltage)
    exceeded = []
    if max_power:
        if peak > max_power:
            exceeded.append("peak")
        if average > max_power:
            exceeded.append("average")
    return PulsePower(peak, average, exceeded)


def max_amplitude(base_level: float, duty: float, voltage: float, max_power: float) -> float:
    """Largest amplitude (A) that keeps the peak and the average power within ``max_power``."""
    limit = max_power / voltage  # current at the power limit
    fraction = min(max(duty, 0.0), 100.0) / 100.0
    if fraction > 0:
        limit = min(limit, base_level + (limit - base_level) / fraction)
    return max(limit, 0.0)


def max_base_level(amplitude: float, duty: float, voltage: float, max_power: float) -> float:
    """Largest base level (A) that keeps the average power within ``max_power``
    (and not above the amplitude)."""
    limit = max_power / voltage
    fraction = min(max(duty, 0.0), 100.0) / 100.0
    if fraction < 1.0:
        limit = min(limit, (limit - amplitude * fraction) / (1.0 - fraction))
    return max(min(limit, amplitude), 0.0)


def max_duty(amplitude: float, base_level: float, voltage: float, max_power: float) -> float:
    """Largest duty cycle (percent) that keeps the average power within ``max_power``."""
    limit = max_power / voltage
    if amplitude <= base_level:
        return 100.0
    return min(max((limit - base_level) / (amplitude - base_level), 0.0), 1.0) * 100.0
