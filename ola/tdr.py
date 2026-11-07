"""Time domain from a reflection measured in frequency: where along a cable a fault is. No Qt.

A VNA measures the reflection ``S11`` at evenly spaced frequencies. A reflection of coefficient
``rho`` at the delay ``tau`` appears in it as ``rho * exp(-j 2 pi f tau)``: a ripple of period
``1 / tau``. The inverse Fourier transform of the (windowed) ``S11`` turns the ripples back into
**peaks at the delays** ``t``: the **impulse response**, and the distance of each reflection from
the plane of the calibration is ``d = c * vf * t / 2`` (``vf`` the velocity factor of the line,
the 2 for the way there and back).

* ``impulse_response`` gives the envelope ``|h(t)|`` (normalised so that one clean reflection
  reads its own coefficient), for any linear sweep, with a window to keep the sidelobes of a
  strong reflection from hiding a weak one. The **resolution** is ``c vf / (2 B)`` for a sweep of
  bandwidth ``B`` (the wider the sweep, the finer), and the **range** is ``c vf / (2 df)`` for a
  frequency step ``df`` (the more points, the farther).
* ``find_faults`` picks the peaks above a threshold and measures each by summing the data at its
  exact delay: the complex reflection (its size and its sign: positive is a higher impedance,
  an open, negative a lower one, a short), the distance and the impedance there.
* ``step_response`` is the same data as a **step**: the reflection of a step of voltage, whose
  level is the reflection coefficient of what the step has reached, and ``impedance_profile`` the
  impedance along the line (50 ohm, then the value of each section). It needs a sweep that starts at
  its own step (``f0 = k df``) and adds the missing DC point; it is for a cable with sections, not
  for finding small faults.

``numpy`` is used when it is installed; without it ``ola.spectrum.fft`` does the transform.
"""

from __future__ import annotations

import cmath
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import spectrum

try:  # numpy only makes the transform faster
    import numpy as _np
except ImportError:  # pragma: no cover - exercised through ``use_numpy=False``
    _np = None

C = 299_792_458.0
WINDOWS = ("rect", "hann", "hamming", "blackman")
MAX_PAD = 64
STEP_GRID_TOLERANCE = 0.05  # the first frequency must be this near to a multiple of the step


class TdrError(ValueError):
    """The data cannot be turned into the time domain; the message says why."""


def window(name: str, n: int) -> List[float]:
    """A window of ``n`` points (symmetric): ``rect``, ``hann``, ``hamming`` or ``blackman``."""
    if name not in WINDOWS:
        raise TdrError(f"window must be one of {', '.join(WINDOWS)}")
    if n < 2 or name == "rect":
        return [1.0] * n
    out = []
    for k in range(n):
        x = 2 * math.pi * k / (n - 1)
        if name == "hann":
            out.append(0.5 - 0.5 * math.cos(x))
        elif name == "hamming":
            out.append(0.54 - 0.46 * math.cos(x))
        else:
            out.append(0.42 - 0.5 * math.cos(x) + 0.08 * math.cos(2 * x))
    return out


def step_of(freq: Sequence[float]) -> float:
    """The frequency step of an evenly spaced sweep. ``TdrError`` if it is not evenly spaced."""
    if len(freq) < 4:
        raise TdrError("the time domain needs at least 4 frequencies (16 or more are sensible)")
    df = (freq[-1] - freq[0]) / (len(freq) - 1)
    if df <= 0:
        raise TdrError("the frequencies must increase")
    if any(abs((b - a) - df) > 1e-3 * df for a, b in zip(freq, freq[1:])):
        raise TdrError("the sweep must be linear (evenly spaced frequencies)")
    return df


def resolution_m(bandwidth_hz: float, velocity_factor: float) -> float:
    """The smallest distance between two reflections that show as two: ``c vf / (2 B)``."""
    return C * velocity_factor / (2 * bandwidth_hz)


def range_m(step_hz: float, velocity_factor: float) -> float:
    """The distance after which a reflection appears again nearer: ``c vf / (2 df)``."""
    return C * velocity_factor / (2 * step_hz)


def _ifft(values: Sequence[complex], use_numpy: bool) -> List[complex]:
    """The inverse transform with the ``1 / n`` of the definition (``n`` a power of two)."""
    n = len(values)
    if use_numpy and _np is not None:
        return [complex(v) for v in _np.fft.ifft(_np.asarray(values, dtype=complex))]
    conj = spectrum.fft([v.conjugate() for v in values])
    return [v.conjugate() / n for v in conj]


def _pad(n: int, factor: int) -> int:
    m = 1
    while m < n * factor:
        m <<= 1
    return m


def impulse_response(
    freq: Sequence[float],
    s11: Sequence[complex],
    window_name: str = "hann",
    pad: int = 8,
    use_numpy: bool = True,
) -> Tuple[List[float], List[float]]:
    """``(delays_s, envelope)``: ``|h(t)|`` for ``t = m / (M df)``, ``M`` the padded length (a
    power of two, at least ``pad`` times the number of points). One clean reflection ``rho`` at a
    delay reads ``|rho|`` at its peak (up to the scalloping between samples, which the padding
    keeps small)."""
    if len(freq) != len(s11):
        raise TdrError(f"{len(freq)} frequencies but {len(s11)} values")
    if not 1 <= pad <= MAX_PAD:
        raise TdrError(f"the padding must be from 1 to {MAX_PAD}")
    df = step_of(freq)
    w = window(window_name, len(freq))
    m = _pad(len(freq), pad)
    x = [w[k] * s11[k] for k in range(len(freq))] + [0j] * (m - len(freq))
    h = _ifft(x, use_numpy)
    scale = m / sum(w)
    return [i / (m * df) for i in range(m)], [abs(v) * scale for v in h]


def reflection_at(
    freq: Sequence[float], s11: Sequence[complex], delay_s: float, window_name: str = "hann"
) -> complex:
    """The complex reflection at the delay ``delay_s``: the windowed data summed with the phase
    that a reflection there would have (``rho`` for a clean reflection at that delay)."""
    w = window(window_name, len(freq))
    total = sum(wk * v * cmath.exp(2j * math.pi * f * delay_s) for wk, v, f in zip(w, s11, freq))
    return total / sum(w)


def find_faults(
    freq: Sequence[float],
    s11: Sequence[complex],
    velocity_factor: float,
    z0: float = 50.0,
    min_reflection: float = 0.05,
    window_name: str = "hann",
    pad: int = 8,
    max_distance_m: Optional[float] = None,
    use_numpy: bool = True,
) -> Dict[str, Any]:
    """The reflections along the line: ``{"faults": [...], "delays": [...], "envelope": [...],
    "resolution_m", "range_m"}``. A fault is a dictionary: ``distance_m``, ``delay_s``,
    ``reflection`` (the size ``|rho|``), ``rho`` (complex, with its sign), ``phase_deg``, ``kind``
    (``"higher impedance"``: an open, a thinner section, ``"lower impedance"``: a short, a
    thicker one) and ``impedance_ohm``. Peaks nearer than the resolution to a stronger one are
    sidelobes and are not counted."""
    if not 0 < velocity_factor <= 1:
        raise TdrError("the velocity factor must be above 0 and at most 1")
    df = step_of(freq)
    t, env = impulse_response(freq, s11, window_name, pad, use_numpy)
    scale = C * velocity_factor / 2
    limit = (
        len(t)
        if max_distance_m is None
        else min(len(t), int(max_distance_m / scale * (len(t) * df)) + 2)
    )
    bandwidth = freq[-1] - freq[0] + df
    res = resolution_m(bandwidth, velocity_factor)
    peaks = []
    for m in range(1, max(2, limit) - 1):
        if env[m] >= env[m - 1] and env[m] > env[m + 1] and env[m] >= min_reflection:
            # parabola through the three samples for the delay of the true peak
            a, b, c = env[m - 1], env[m], env[m + 1]
            den = a - 2 * b + c
            shift = 0.5 * (a - c) / den if den else 0.0
            peaks.append((b, t[m] + shift / (len(t) * df)))
    peaks.sort(reverse=True)
    kept: List[Tuple[float, float]] = []
    for amp, delay in peaks:  # the strongest first: what is near it is its sidelobe
        if all(abs(delay - other) * scale >= res * 0.9 for _, other in kept):
            kept.append((amp, delay))
    faults = []
    for amp, delay in sorted(kept, key=lambda p: p[1]):
        rho = reflection_at(freq, s11, delay, window_name)
        real = max(-0.999, min(0.999, rho.real))
        faults.append(
            {
                "distance_m": delay * scale,
                "delay_s": delay,
                "reflection": abs(rho),
                "rho": rho,
                "phase_deg": math.degrees(cmath.phase(rho)),
                "kind": "higher impedance" if rho.real >= 0 else "lower impedance",
                "impedance_ohm": z0 * (1 + real) / (1 - real),
            }
        )
    return {
        "faults": faults,
        "delays": t[:limit],
        "envelope": env[:limit],
        "resolution_m": res,
        "range_m": range_m(df, velocity_factor),
    }


def _extend_down(
    freq: Sequence[float], s11: Sequence[complex], k0: int, df: float
) -> List[complex]:
    """The spectrum below the first frequency, for ``k = 0 .. k0 - 1`` (``k = 0`` is DC and real):
    the size of the first point, with the phase continued backwards along the straight line that
    the first points follow (the phase of a delay is a straight line of the frequency)."""
    n = min(8, len(s11))
    phase = [cmath.phase(s11[0])]
    for k in range(1, n):
        step = cmath.phase(s11[k] / s11[k - 1])
        phase.append(phase[-1] + step)
    fm, pm = sum(freq[:n]) / n, sum(phase) / n
    den = sum((f - fm) ** 2 for f in freq[:n])
    slope = sum((f - fm) * (p - pm) for f, p in zip(freq[:n], phase)) / den if den else 0.0
    out = []
    for k in range(k0):
        f = k * df
        value = abs(s11[0]) * cmath.exp(1j * (pm + slope * (f - fm)))
        out.append(complex(value.real) if k == 0 else value)
    return out


def step_response(
    freq: Sequence[float], s11: Sequence[complex], pad: int = 8, use_numpy: bool = True
) -> Tuple[List[float], List[float]]:
    """``(delays_s, step)``: the reflection of a step of voltage. It needs a sweep whose first
    frequency is a multiple of the step (the data below it is the first point with its phase
    continued backwards, and the DC value its real part). ``TdrError`` for another sweep."""
    df = step_of(freq)
    k0 = round(freq[0] / df)
    if k0 < 1 or abs(freq[0] - k0 * df) > STEP_GRID_TOLERANCE * df:
        raise TdrError(
            "the step response needs a sweep that starts at a multiple of its step "
            f"(start {freq[0]:g} Hz, step {df:g} Hz): start at the step, for example"
        )
    top = k0 + len(freq) - 1
    # half a Hann window from DC to the last frequency: no step at the edge of the band
    spectrum_half = _extend_down(freq, s11, k0, df) + list(s11)
    w = [0.5 + 0.5 * math.cos(math.pi * k / (top + 1)) for k in range(top + 1)]
    half = [w[k] * spectrum_half[k] for k in range(top + 1)]
    m = _pad(2 * top + 2, pad)
    full = [0j] * m
    full[0] = complex(half[0].real)
    for k in range(1, top + 1):
        full[k] = half[k]
        full[m - k] = half[k].conjugate()
    h = [v.real for v in _ifft(full, use_numpy)]
    step, total = [], 0.0
    for v in h:
        total += v
        step.append(total)
    return [i / (m * df) for i in range(m)], step


def impedance_profile(step: Sequence[float], z0: float = 50.0) -> List[float]:
    """The impedance along the line from a step response: ``z0 (1 + s) / (1 - s)`` (``s`` kept
    inside -0.999 .. 0.999)."""
    return [z0 * (1 + max(-0.999, min(0.999, s))) / (1 - max(-0.999, min(0.999, s))) for s in step]


__all__ = [
    "C", "TdrError", "find_faults", "impedance_profile", "impulse_response", "range_m",
    "reflection_at", "resolution_m", "step_of", "step_response", "window",
]  # fmt: skip
