"""Software calibration of a vector network analyzer (reflection and transmission response).

Used by drivers of analyzers that return raw data (the LiteVNA): the raw sweeps of the
calibration standards are measured, the error terms are computed and the correction is applied
to every following sweep. The standards are ideal (OPEN reflects +1, SHORT -1, LOAD 0, THRU
transmits 1): the offsets and the fringing capacitance of a real calibration kit are ignored.

Reflection (one port, three error terms per frequency)::

    measured = e00 + e10e01 * G / (1 - e11 * G)

Transmission response: ``S21 = measured / measured_thru``.

No I/O here; values are Python complex numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from .call_errors import InvalidArgumentError

Sweep = Sequence[complex]


@dataclass(frozen=True)
class Reflection:
    """Error terms of the reflection calibration (one value per frequency)."""

    e00: List[complex]  # directivity
    e11: List[complex]  # source match
    e10e01: List[complex]  # reflection tracking

    def correct(self, measured: Sweep) -> List[complex]:
        """Calibrated reflection coefficient of a measured sweep."""
        out = []
        for m, d, s, t in zip(measured, self.e00, self.e11, self.e10e01):
            x = m - d
            out.append(x / (t + s * x))
        return out


def reflection_terms(openm: Sweep, shortm: Sweep, loadm: Sweep) -> Reflection:
    """Error terms from the measured OPEN, SHORT and LOAD (ideal standards)."""
    if not (len(openm) == len(shortm) == len(loadm)):
        raise InvalidArgumentError("the three standards must have the same number of points")
    e00, e11, t = [], [], []
    for mo, ms, ml in zip(openm, shortm, loadm):
        a, b = mo - ml, ms - ml  # a = t / (1 - e11), b = -t / (1 + e11)
        if a == b:
            raise InvalidArgumentError("OPEN and SHORT gave the same value: check the standards")
        s = (a + b) / (a - b)
        e00.append(ml)
        e11.append(s)
        t.append(-2 * a * b / (a - b))
    return Reflection(e00, e11, t)


def transmission_response(measured: Sweep, thru: Sweep) -> List[complex]:
    """Measured transmission divided by the measured THRU."""
    out = []
    for m, r in zip(measured, thru):
        if r == 0:
            raise InvalidArgumentError("the THRU measurement is zero at some frequency")
        out.append(m / r)
    return out
