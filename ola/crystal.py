# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The equivalent circuit of a quartz crystal or a ceramic resonator, from a VNA (no Qt, no I/O).

The crystal is in series between port 1 and port 2 (series-thru: ``Z = 2 z0 (1 - S21) / S21``),
and the sweep is narrow around its resonance. Its model is the **Butterworth-Van Dyke** circuit: a
motional arm ``Rm``, ``Lm``, ``Cm`` in series, with the capacitance of the electrodes ``C0`` in
parallel.

* ``fs``, the **series resonance**: where the reactance of the crystal crosses zero going up, near
  the peak of ``|S21|``; ``Rm`` is the resistance there.
* ``Lm`` from the slope of the reactance at ``fs``: for a series ``L C`` arm ``dX / dw = 2 Lm``.
* ``Cm = 1 / (ws^2 Lm)``; the quality factor ``Q = ws Lm / Rm``.
* ``fp``, the **parallel resonance** (anti-resonance): the dip of ``|S21|`` above ``fs``;
  ``C0 = Cm fs / (2 (fp - fs))`` (from ``fp = fs (1 + Cm / (2 C0))``).
* With a load capacitance ``CL`` (the one the crystal is specified for), the frequency it runs
  at in a parallel-resonant oscillator: ``fL = fs (1 + Cm / (2 (C0 + CL)))``, and its pulling
  ``dfL / dCL`` in ppm per pF.

The slope is taken over a few points around ``fs``: the sweep must have enough points across the
resonance (``check_sweep_for``).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence


class CrystalError(ValueError):
    """The sweep does not show a resonance that can be measured; the message says why."""


def series_impedance(s21: Sequence[complex], z0: float = 50.0) -> List[complex]:
    """The impedance of a two-terminal part in series between the two ports, from ``S21``:
    ``Z = 2 z0 (1 - S21) / S21`` (``inf`` where nothing passes)."""
    return [complex(math.inf, 0) if abs(s) < 1e-15 else 2 * z0 * (1 - s) / s for s in s21]


def _crossing(freq: Sequence[float], y: Sequence[float], i: int) -> float:
    """The frequency where ``y`` crosses zero between the points ``i`` and ``i + 1``."""
    a, b = y[i], y[i + 1]
    return freq[i] + (freq[i + 1] - freq[i]) * (-a) / (b - a) if b != a else freq[i]


def analyse(
    freq: Sequence[float],
    s21: Sequence[complex],
    z0: float = 50.0,
    load_capacitance_f: Optional[float] = None,
) -> Dict[str, Any]:
    """The equivalent circuit of the crystal from a series-thru ``S21``: ``fs_hz``, ``rm_ohm``,
    ``lm_h``, ``cm_f``, ``q``, ``fp_hz`` and ``c0_f`` (None if the anti-resonance is outside the
    sweep), and with ``load_capacitance_f`` also ``fl_hz`` and ``pulling_ppm_per_pf``.
    ``CrystalError`` if there is no series resonance in the sweep."""
    if len(freq) < 11 or len(freq) != len(s21):
        raise CrystalError("the sweep needs at least 11 points across the resonance")
    z = series_impedance(s21, z0)
    mags = [abs(v) for v in s21]
    peak = max(range(len(mags)), key=mags.__getitem__)
    x = [v.imag for v in z]
    # the rising zero of the reactance nearest the peak of |S21|
    rising = [i for i in range(len(x) - 1) if x[i] < 0 <= x[i + 1]]
    if not rising:
        raise CrystalError(
            "no series resonance in the sweep (the reactance never crosses zero going up): "
            "centre the sweep on the crystal"
        )
    i = min(rising, key=lambda k: abs(k - peak))
    fs = _crossing(freq, x, i)
    t = (fs - freq[i]) / (freq[i + 1] - freq[i]) if freq[i + 1] != freq[i] else 0.0
    rm = z[i].real + t * (z[i + 1].real - z[i].real)
    lo, hi = max(i - 2, 0), min(i + 3, len(freq) - 1)
    slope = (x[hi] - x[lo]) / (2 * math.pi * (freq[hi] - freq[lo]))
    if slope <= 0 or rm <= 0:
        raise CrystalError("the resonance is too narrow for the sweep: use more points")
    lm = slope / 2
    ws = 2 * math.pi * fs
    cm = 1 / (ws * ws * lm)
    out: Dict[str, Any] = {
        "fs_hz": fs,
        "rm_ohm": rm,
        "lm_h": lm,
        "cm_f": cm,
        "q": ws * lm / rm,
        "fp_hz": None,
        "c0_f": None,
    }
    # the parallel resonance: the reactance falls back through zero above fs (the dip of |S21|)
    falling = [k for k in range(i + 1, len(x) - 1) if x[k] > 0 >= x[k + 1]]
    if falling:
        fp = _crossing(freq, x, falling[0])
        if fp > fs:
            out["fp_hz"] = fp
            out["c0_f"] = cm * fs / (2 * (fp - fs))
    if load_capacitance_f and out["c0_f"] is not None:
        c0, cl = out["c0_f"], load_capacitance_f
        out["fl_hz"] = fs * (1 + cm / (2 * (c0 + cl)))
        # dfL/dCL = -fs Cm / (2 (C0 + CL)^2), in ppm of fs per pF
        out["pulling_ppm_per_pf"] = -cm / (2 * (c0 + cl) ** 2) * 1e-12 * 1e6
    return out


def check_sweep_for(start: float, stop: float, points: int, q_guess: float = 20000) -> List[str]:
    """Warnings about a sweep for a crystal of about ``q_guess``: the bandwidth of its resonance
    is ``f / Q``, and at least 10 points should fall across it."""
    out = []
    centre = (start + stop) / 2
    step = (stop - start) / max(points - 1, 1)
    width = centre / q_guess
    if step > width / 10:
        out.append(
            f"the step of the sweep is {step:.3g} Hz and a crystal of Q {q_guess:g} at "
            f"{centre:.6g} Hz is only {width:.3g} Hz wide: narrow the sweep or add points"
        )
    return out
