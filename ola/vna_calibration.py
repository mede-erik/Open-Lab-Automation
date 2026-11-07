# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Software calibration of a vector network analyzer (reflection and transmission response).

Used by drivers of analyzers that return raw data (the LiteVNA): the raw sweeps of the
calibration standards are measured, the error terms are computed and the correction is applied
to every following sweep. By default the standards are ideal (OPEN reflects +1, SHORT -1, LOAD 0,
THRU transmits 1). A ``CalKit`` describes a real calibration kit (the fringing capacitance of the
OPEN, the inductance of the SHORT, the delay and loss of the offsets and of the THRU) with the usual
polynomial model of a calibration kit file.

Reflection (one port, three error terms per frequency)::

    measured = e00 + e10e01 * G / (1 - e11 * G)

Transmission response: ``S21 = measured / measured_thru``.

No I/O here; values are Python complex numbers.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, fields
from typing import Dict, List, Optional, Sequence

from .call_errors import InvalidArgumentError

Sweep = Sequence[complex]
SYSTEM_Z0 = 50.0  # reference impedance of the analyzer (ohm)


@dataclass(frozen=True)
class CalKit:
    """A calibration kit, in the units of the usual kit files; zero means ideal.

    OPEN: fringing capacitance ``C(f) = C0 + C1 f + C2 f^2 + C3 f^3`` (C0 in fF, C1 in 1e-27 F/Hz,
    C2 in 1e-36 F/Hz^2, C3 in 1e-45 F/Hz^3). SHORT: inductance ``L(f)`` (L0 in pH, L1 in
    1e-24 H/Hz, L2 in 1e-33, L3 in 1e-42). Each of OPEN, SHORT and THRU has an offset with a delay
    (ps), a loss (Gohm/s at 1 GHz) and a characteristic impedance (ohm); the LOAD is ideal (a
    perfect match, whatever its offset).
    """

    open_c0: float = 0.0
    open_c1: float = 0.0
    open_c2: float = 0.0
    open_c3: float = 0.0
    open_delay: float = 0.0
    open_loss: float = 0.0
    open_z0: float = SYSTEM_Z0
    short_l0: float = 0.0
    short_l1: float = 0.0
    short_l2: float = 0.0
    short_l3: float = 0.0
    short_delay: float = 0.0
    short_loss: float = 0.0
    short_z0: float = SYSTEM_Z0
    thru_delay: float = 0.0
    thru_loss: float = 0.0
    thru_z0: float = SYSTEM_Z0

    @staticmethod
    def from_dict(data: Optional[Dict[str, float]]) -> "CalKit":
        """A kit from a dict of the field names above (missing ones are ideal)."""
        known = {f.name for f in fields(CalKit)}
        unknown = sorted(set(data or {}) - known)
        if unknown:
            raise InvalidArgumentError(f"unknown calibration kit values: {', '.join(unknown)}")
        try:
            return CalKit(**{k: float(v) for k, v in (data or {}).items()})
        except (TypeError, ValueError) as exc:
            raise InvalidArgumentError(f"a calibration kit value is not a number: {exc}") from exc

    def to_dict(self) -> Dict[str, float]:
        """The values that differ from an ideal kit (empty for an ideal kit)."""
        ideal = CalKit()
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if getattr(self, f.name) != getattr(ideal, f.name)
        }


def _offset(delay_ps: float, loss: float, z0: float, f: float) -> complex:
    """One-way propagation factor exp(-(alpha + j beta) l) of an offset line at frequency f."""
    td = delay_ps * 1e-12
    alpha = loss * 1e9 * td / (2.0 * z0) * math.sqrt(f / 1e9) if loss and z0 else 0.0
    return cmath.exp(-(alpha + 1j * 2.0 * math.pi * f * td))


def ideal_reflection(standard: str, frequencies: Sequence[float], kit: Optional[CalKit] = None):
    """Reflection coefficient of OPEN, SHORT or LOAD at each frequency, in the plane of the
    test port (the offset line included)."""
    kit = kit or CalKit()
    out = []
    for f in frequencies:
        w = 2.0 * math.pi * f
        if standard == "LOAD":
            out.append(0j)
        elif standard == "OPEN":
            c = (
                kit.open_c0 * 1e-15
                + kit.open_c1 * 1e-27 * f
                + kit.open_c2 * 1e-36 * f**2
                + kit.open_c3 * 1e-45 * f**3
            )
            x = w * c * SYSTEM_Z0
            gamma = (1 - 1j * x) / (1 + 1j * x)
            out.append(gamma * _offset(kit.open_delay, kit.open_loss, kit.open_z0, f) ** 2)
        elif standard == "SHORT":
            ind = (
                kit.short_l0 * 1e-12
                + kit.short_l1 * 1e-24 * f
                + kit.short_l2 * 1e-33 * f**2
                + kit.short_l3 * 1e-42 * f**3
            )
            z = 1j * w * ind
            gamma = (z - SYSTEM_Z0) / (z + SYSTEM_Z0)
            out.append(gamma * _offset(kit.short_delay, kit.short_loss, kit.short_z0, f) ** 2)
        else:
            raise InvalidArgumentError(f"{standard} is not a reflection standard")
    return out


def ideal_transmission(frequencies: Sequence[float], kit: Optional[CalKit] = None):
    """Transmission coefficient S21 of the THRU at each frequency."""
    kit = kit or CalKit()
    return [_offset(kit.thru_delay, kit.thru_loss, kit.thru_z0, f) for f in frequencies]


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


def reflection_terms(
    openm: Sweep,
    shortm: Sweep,
    loadm: Sweep,
    open_gamma: Optional[Sweep] = None,
    short_gamma: Optional[Sweep] = None,
) -> Reflection:
    """Error terms from the measured OPEN, SHORT and LOAD.

    ``open_gamma`` and ``short_gamma`` are the known reflection coefficients of the standards at
    each frequency (``ideal_reflection``); without them they are +1 and -1. The LOAD is a
    perfect match.
    """
    if not (len(openm) == len(shortm) == len(loadm)):
        raise InvalidArgumentError("the three standards must have the same number of points")
    n = len(openm)
    open_gamma = open_gamma if open_gamma is not None else [1 + 0j] * n
    short_gamma = short_gamma if short_gamma is not None else [-1 + 0j] * n
    e00, e11, t = [], [], []
    for mo, ms, ml, go, gs in zip(openm, shortm, loadm, open_gamma, short_gamma):
        a, b = mo - ml, ms - ml  # a = t go / (1 - e11 go), b = t gs / (1 - e11 gs)
        denominator = go * gs * (a - b)
        if denominator == 0 or a == b:
            raise InvalidArgumentError("OPEN and SHORT gave the same value: check the standards")
        s = (a * gs - b * go) / denominator
        e00.append(ml)
        e11.append(s)
        t.append(a * (1 - go * s) / go)
    return Reflection(e00, e11, t)


def transmission_response(
    measured: Sweep, thru: Sweep, thru_ideal: Optional[Sweep] = None
) -> List[complex]:
    """Measured transmission divided by the measured THRU (times the known transmission of the
    THRU, ``ideal_transmission``; 1 if it is not given)."""
    thru_ideal = thru_ideal if thru_ideal is not None else [1 + 0j] * len(thru)
    out = []
    for m, r, ideal in zip(measured, thru, thru_ideal):
        if r == 0:
            raise InvalidArgumentError("the THRU measurement is zero at some frequency")
        out.append(m * ideal / r)
    return out
