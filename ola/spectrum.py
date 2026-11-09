# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Amplitude spectrum of a sampled signal, and the peaks in it. No Qt, no I/O.

``amplitude_spectrum`` windows the samples (Hann), takes the Fourier transform and returns the
frequencies and the **peak amplitude** of each component, so that a sine of 10 mV gives 10 mV at its
frequency whatever the length of the record. ``numpy`` is used when it is installed; without it a
plain Python transform does the same (slower: use at most ``MAX_POINTS`` samples).

The measurements that look at a signal in the frequency domain (ripple and noise of a supply, later
the spectrum of a signal) use these functions.
"""

from __future__ import annotations

import cmath
import math
from typing import List, Sequence, Tuple

try:  # numpy is optional: it only makes the transform faster
    import numpy as _np
except ImportError:  # pragma: no cover - exercised through ``use_numpy=False``
    _np = None

MAX_POINTS = 1 << 16  # the most samples one transform takes (a longer record is cut)
HANN_NOISE_BINS = 1.5  # noise power bandwidth of the Hann window, in bins


def power_of_two(n: int) -> int:
    """The largest power of two not above ``n`` (0 for ``n`` below 1)."""
    return 1 << (n.bit_length() - 1) if n >= 1 else 0


def hann(n: int) -> List[float]:
    """The Hann window of ``n`` points (periodic form, as used for spectrum estimates)."""
    return [0.5 - 0.5 * math.cos(2 * math.pi * k / n) for k in range(n)]


def fft(values: Sequence[complex]) -> List[complex]:
    """Discrete Fourier transform of a list whose length is a power of two (radix-2)."""
    n = len(values)
    if n == 0 or n & (n - 1):
        raise ValueError(f"the length must be a power of two, not {n}")
    out = [complex(v) for v in values]
    j = 0
    for i in range(1, n):  # bit-reversal permutation
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            out[i], out[j] = out[j], out[i]
    size = 2
    while size <= n:
        step = cmath.exp(-2j * math.pi / size)
        for start in range(0, n, size):
            w = 1 + 0j
            for k in range(start, start + size // 2):
                a, b = out[k], out[k + size // 2] * w
                out[k], out[k + size // 2] = a + b, a - b
                w *= step
        size <<= 1
    return out


def amplitude_spectrum(
    samples: Sequence[float],
    sample_interval_s: float,
    use_numpy: bool = True,
    max_points: int = MAX_POINTS,
) -> Tuple[List[float], List[float]]:
    """``(frequencies, amplitudes)`` from DC to the Nyquist frequency.

    The mean is removed first, so the DC bin is 0. The record is cut to the largest power of two
    (at most ``max_points``). The amplitude is the peak value of a sine at that frequency, in the
    unit of ``samples``. ``ValueError`` for fewer than 8 samples or a non-positive interval."""
    if sample_interval_s <= 0:
        raise ValueError("the sample interval must be above 0")
    n = min(power_of_two(len(samples)), power_of_two(max_points))
    if n < 8:
        raise ValueError("a spectrum needs at least 8 samples")
    mean = sum(samples[:n]) / n
    window = hann(n)
    gain = sum(window)
    if use_numpy and _np is not None:
        x = (_np.asarray(samples[:n], dtype=float) - mean) * _np.asarray(window)
        bins = _np.abs(_np.fft.rfft(x))
        amps = (2.0 * bins / gain).tolist()
    else:
        x = [(samples[k] - mean) * window[k] for k in range(n)]
        bins = [abs(v) for v in fft(x)[: n // 2 + 1]]
        amps = [2.0 * b / gain for b in bins]
    amps[0] = 0.0
    df = 1.0 / (n * sample_interval_s)
    return [k * df for k in range(len(amps))], amps


def fit_sine(
    samples: Sequence[float],
    sample_interval_s: float,
    frequency_hz: float,
    use_numpy: bool = True,
) -> dict:
    """Fit ``a cos(wt) + b sin(wt) + c`` to the samples at the **known** frequency (least squares,
    ``t = k * sample_interval_s``) and give ``amplitude``, ``phase_rad`` (the signal is
    ``amplitude * cos(wt + phase)``), ``offset`` and ``residual_rms`` (what the sine does not
    explain: noise and distortion). Two channels sampled together share the time base, so the
    difference of their phases is the phase between them. ``ValueError`` for fewer than 8 samples
    or a frequency that is not above 0."""
    n = len(samples)
    if n < 8:
        raise ValueError("a sine fit needs at least 8 samples")
    if frequency_hz <= 0 or sample_interval_s <= 0:
        raise ValueError("the frequency and the sample interval must be above 0")
    w = 2 * math.pi * frequency_hz * sample_interval_s
    if use_numpy and _np is not None:
        k = _np.arange(n)
        c, s_ = _np.cos(w * k), _np.sin(w * k)
        y = _np.asarray(samples, dtype=float)
        gram = [
            [float((c * c).sum()), float((c * s_).sum()), float(c.sum())],
            [float((c * s_).sum()), float((s_ * s_).sum()), float(s_.sum())],
            [float(c.sum()), float(s_.sum()), float(n)],
        ]
        rhs = [float((y * c).sum()), float((y * s_).sum()), float(y.sum())]
    else:
        cs = [math.cos(w * k) for k in range(n)]
        sn = [math.sin(w * k) for k in range(n)]
        gram = [
            [sum(a * a for a in cs), sum(a * b for a, b in zip(cs, sn)), sum(cs)],
            [sum(a * b for a, b in zip(cs, sn)), sum(b * b for b in sn), sum(sn)],
            [sum(cs), sum(sn), float(n)],
        ]
        rhs = [
            sum(y * a for y, a in zip(samples, cs)),
            sum(y * b for y, b in zip(samples, sn)),
            float(sum(samples)),
        ]
    a, b, offset = _solve3(gram, rhs)
    if use_numpy and _np is not None:
        fit = a * c + b * s_ + offset
        residual = float(_np.sqrt(((y - fit) ** 2).mean()))
    else:
        residual = math.sqrt(
            sum((y - (a * cs[k] + b * sn[k] + offset)) ** 2 for k, y in enumerate(samples)) / n
        )
    return {
        "amplitude": math.hypot(a, b),
        "phase_rad": math.atan2(-b, a),
        "offset": offset,
        "residual_rms": residual,
    }


def _solve3(m: Sequence[Sequence[float]], rhs: Sequence[float]) -> Tuple[float, float, float]:
    """Solve a 3 x 3 linear system (Gaussian elimination with pivoting)."""
    a = [list(m[i]) + [rhs[i]] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12 * max(1.0, abs(a[0][0])):
            raise ValueError(
                "the samples do not cover the frequency (less than a few points a cycle)"
            )
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(col + 1, 3):
            f = a[r][col] / a[col][col]
            for c2 in range(col, 4):
                a[r][c2] -= f * a[col][c2]
    x = [0.0, 0.0, 0.0]
    for r in (2, 1, 0):
        x[r] = (a[r][3] - sum(a[r][c2] * x[c2] for c2 in range(r + 1, 3))) / a[r][r]
    return x[0], x[1], x[2]


def to_dbv(amplitude_peak: float, floor: float = 1e-12) -> float:
    """A peak amplitude in volts as dBV rms: ``20 log10 (A / sqrt 2)``; ``floor`` avoids log 0."""
    return 20 * math.log10(max(amplitude_peak, floor) / math.sqrt(2))


def find_peaks(
    freq: Sequence[float], amp: Sequence[float], count: int = 5, min_ratio: float = 0.05
) -> List[Tuple[float, float]]:
    """The ``count`` highest local maxima as ``(frequency, amplitude)``, highest first. A peak must
    be at least ``min_ratio`` of the highest one, and a peak next to a higher one (the leakage of
    the window) is not counted. The frequency is refined by a parabola through the logarithm of
    the three bins (this also corrects the amplitude for a frequency between two bins)."""
    if len(freq) != len(amp):
        raise ValueError("freq and amp must have the same length")
    if len(amp) < 3 or max(amp) <= 0:
        return []
    top = max(amp)
    found: List[Tuple[float, float]] = []
    for k in range(1, len(amp) - 1):
        if amp[k] >= amp[k - 1] and amp[k] > amp[k + 1] and amp[k] >= min_ratio * top:
            tiny = 1e-300
            a, b, c = (math.log(max(v, tiny)) for v in (amp[k - 1], amp[k], amp[k + 1]))
            denom = a - 2 * b + c
            shift = 0.5 * (a - c) / denom if denom else 0.0
            df = freq[k] - freq[k - 1]
            found.append((freq[k] + shift * df, math.exp(b - 0.25 * (a - c) * shift)))
    found.sort(key=lambda p: p[1], reverse=True)
    return found[:count]


def rms_outside(
    freq: Sequence[float], amp: Sequence[float], peaks: Sequence[float], width_bins: int = 4
) -> float:
    """The rms of what is left when the bins within ``width_bins`` of each peak frequency are
    removed: the noise that is not the ripple and its harmonics (volts rms from the peak
    amplitudes of ``amplitude_spectrum``; the Hann window spreads noise over 1.5 bins, which is
    divided out)."""
    if len(freq) < 2:
        return 0.0
    df = freq[1] - freq[0]
    skip = set()
    for f in peaks:
        centre = int(round(f / df))
        skip.update(range(centre - width_bins, centre + width_bins + 1))
    power = sum((a * a) / 2 for k, a in enumerate(amp) if k not in skip)
    return math.sqrt(power / HANN_NOISE_BINS)
