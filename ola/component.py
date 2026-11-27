# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The impedance of a component measured with a VNA, and what it is made of (no Qt, no I/O).

Three ways to put a two-terminal component (an inductor, a capacitor, a resistor, a ferrite) on a
VNA, each good for a range of impedance (``METHODS``):

* ``reflection``: the component from the centre of port 1 to ground. ``Z = z0 (1 + S11) / (1 -
  S11)``. Best near ``z0`` (a few ohm to a few hundred ohm): far from it ``|S11|`` is close to 1
  and a small error of the VNA is a large error of ``Z``.
* ``series``: the component in series between port 1 and port 2 (series-thru).
  ``Z = 2 z0 (1 - S21) / S21``. Best for **high** impedances (tens of ohm to tens of kilohm:
  inductors, small capacitors, ferrites, common-mode chokes).
* ``shunt``: the component from a thru line to ground (shunt-thru). ``Z = z0 S21 / (2 (1 -
  S21))``. Best for **low** impedances (milliohm to a few ohm: large capacitors, their ESR, the
  impedance of a power plane).

From ``Z = R + jX`` at the angular frequency ``w``: an inductance ``L = X / w`` (``X > 0``), a
capacitance ``C = -1 / (w X)`` (``X < 0``), the quality factor ``Q = |X| / R`` and the
dissipation factor ``D = 1 / Q``; the **self-resonance** is where ``X`` changes sign (an
inductor becomes a capacitor above it, a capacitor an inductor).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from . import rf

METHODS = ("reflection", "series", "shunt")
KINDS = ("auto", "inductor", "capacitor", "resistor")
# the size of the measured coefficient beyond which the method loses its accuracy
EDGE = {"reflection": 0.9, "series": 0.03, "shunt": 0.97}


class ComponentError(ValueError):
    """The measurement cannot give an impedance; the message says why."""


def impedance(method: str, values: Sequence[complex], z0: float = 50.0) -> List[complex]:
    """The impedance of the component from what was measured: ``S11`` for ``reflection``, ``S21``
    for ``series`` and ``shunt``. A value that cannot be turned into an impedance (a series S21 of
    0: an open; a shunt S21 of 1: nothing there) gives ``inf`` or 0 as the physics says."""
    if method not in METHODS:
        raise ComponentError(f"the method must be one of {', '.join(METHODS)}")
    if method == "reflection":
        return rf.gamma_to_z(values, z0)
    out: List[complex] = []
    for s in values:
        if method == "series":
            out.append(complex(math.inf, 0) if abs(s) < 1e-15 else 2 * z0 * (1 - s) / s)
        else:
            out.append(complex(math.inf, 0) if abs(1 - s) < 1e-15 else z0 * s / (2 * (1 - s)))
    return out


def inaccurate_points(method: str, values: Sequence[complex]) -> int:
    """How many points are outside the range where ``method`` is accurate (``EDGE``): a reflection
    close to total, a series transmission close to 0 (a very high impedance), a shunt one close to
    1 (a very low impedance seen as nothing)."""
    edge = EDGE[method]
    if method == "series":
        return sum(1 for v in values if abs(v) < edge)
    return sum(1 for v in values if abs(v) > edge)


def best_method(z_abs: Sequence[float]) -> str:
    """The method that suits a component of these impedances: ``shunt`` for a median ``|Z|``
    below 5 ohm, ``series`` above 500 ohm, ``reflection`` in between."""
    middle = sorted(z_abs)[len(z_abs) // 2] if z_abs else 50.0
    if middle < 5:
        return "shunt"
    return "series" if middle > 500 else "reflection"


def equivalent(freq: Sequence[float], z: Sequence[complex]) -> Dict[str, List[Optional[float]]]:
    """Per frequency: ``r_ohm``, ``x_ohm``, ``z_abs_ohm``, ``phase_deg``, ``l_h`` (None where the
    component is capacitive), ``c_f`` (None where it is inductive), ``q`` and ``d`` (None for a
    pure reactance or a pure resistance where they are not defined)."""
    out: Dict[str, List[Optional[float]]] = {
        k: [] for k in ("r_ohm", "x_ohm", "z_abs_ohm", "phase_deg", "l_h", "c_f", "q", "d")
    }
    for f, v in zip(freq, z):
        w = 2 * math.pi * f
        r, x = v.real, v.imag
        out["r_ohm"].append(r)
        out["x_ohm"].append(x)
        out["z_abs_ohm"].append(abs(v))
        out["phase_deg"].append(math.degrees(math.atan2(x, r)))
        out["l_h"].append(x / w if x > 0 and w else None)
        out["c_f"].append(-1 / (w * x) if x < 0 and w else None)
        out["q"].append(abs(x) / r if r > 0 else None)
        out["d"].append(r / abs(x) if x != 0 and r >= 0 else None)
    return out


def self_resonances(freq: Sequence[float], z: Sequence[complex]) -> List[Dict[str, Any]]:
    """Where the reactance changes sign: ``[{"frequency_hz", "kind"}]``, ``kind`` ``series``
    (``X`` rising through 0: the impedance is at a minimum, a capacitor's resonance with its
    lead inductance) or ``parallel`` (``X`` falling through 0 with a peak of ``|Z|``: an
    inductor's resonance with its winding capacitance)."""
    x = [v.imag for v in z]
    return [
        {"frequency_hz": f, "kind": "series" if d == "rising" else "parallel"}
        for f, d in rf.level_crossings(list(freq), x, 0.0)
    ]


def guess_kind(z: Sequence[complex]) -> str:
    """``inductor``, ``capacitor`` or ``resistor`` from the measured impedance below the first
    resonance: mostly positive reactance, mostly negative, or a reactance small against the
    resistance."""
    x = [v.imag for v in z]
    r = [abs(v.real) for v in z]
    first = len(x)
    for i in range(1, len(x)):
        if (x[i - 1] > 0) != (x[i] > 0):
            first = i
            break
    lows = range(max(first, 1))
    if sum(abs(x[i]) for i in lows) < 0.2 * sum(r[i] for i in lows):
        return "resistor"
    return "inductor" if sum(x[i] for i in lows) > 0 else "capacitor"
