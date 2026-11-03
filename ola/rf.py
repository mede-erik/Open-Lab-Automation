"""Radio-frequency calculations shared by the RF measurements (no Qt, no extra libraries).

Everything works on plain Python lists. A *trace* is a list of values at the frequencies of a list
``freq`` (Hz); a complex trace is a list of ``complex`` numbers (the run files store them as
``[re, im]`` pairs: ``from_pairs`` converts). The functions every VNA measurement needs:

    insertion_loss_db(s21)             # loss of a cable, a filter...: -20 log10 |S21|, positive
    return_loss_db(s11), vswr(s11)     # how well a port is matched
    gamma_to_z(s11, z0=50)             # impedance of what is on the port (R + jX)
    group_delay_s(freq, s21)           # delay of a signal through the device, in seconds
    value_at(freq, y, f)               # the curve at one frequency (linear interpolation)
    crossings(freq, y, level)          # frequencies where the curve crosses a level (-3 dB points)
    level_crossings(freq, y, level)    # the crossings with their direction (edges of a filter)
    bands_where(freq, y, level)        # the bands where the curve is below a level (VSWR <= 2)
    write_touchstone(...) / read_touchstone(...)   # .s1p / .s2p files

A reading of exactly zero has no logarithm: it is shown as ``FLOOR_DB`` (-300 dB), not an error.
"""

from __future__ import annotations

import cmath
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

FLOOR_DB = -300.0
Complex = Union[complex, float, int]
Number = Union[float, int]


class RfError(ValueError):
    """Data that cannot be used (different lengths, unknown format...); the message says what."""


# ----- conversions -----------------------------------------------------------------------------
def from_pairs(pairs: Sequence[Sequence[float]]) -> List[complex]:
    """``[[re, im], ...]`` (how run files store complex traces) -> list of complex numbers."""
    return [complex(re, im) for re, im in pairs]


def to_pairs(values: Sequence[Complex]) -> List[List[float]]:
    """list of complex numbers -> ``[[re, im], ...]``."""
    return [[complex(v).real, complex(v).imag] for v in values]


def db20(value: Complex) -> float:
    """Magnitude in dB (20 log10 |value|); zero gives ``FLOOR_DB``."""
    magnitude = abs(value)
    return 20.0 * math.log10(magnitude) if magnitude > 1e-15 else FLOOR_DB


def magnitude_db(values: Sequence[Complex]) -> List[float]:
    """Magnitude in dB of every point."""
    return [db20(v) for v in values]


def phase_deg(values: Sequence[Complex], unwrap: bool = True) -> List[float]:
    """Phase in degrees. With ``unwrap`` (default) the jumps of 360 degrees are removed, so a delay
    appears as a straight line instead of a saw-tooth."""
    radians = [cmath.phase(v) for v in values]
    if unwrap:
        radians = unwrap_phase(radians)
    return [math.degrees(p) for p in radians]


def unwrap_phase(radians: Sequence[float]) -> List[float]:
    """Remove the jumps of 2 pi between neighbouring points."""
    out: List[float] = []
    offset = 0.0
    for i, p in enumerate(radians):
        if i:
            step = p - radians[i - 1]
            if step > math.pi:
                offset -= 2 * math.pi * math.ceil((step - math.pi) / (2 * math.pi))
            elif step < -math.pi:
                offset += 2 * math.pi * math.ceil((-step - math.pi) / (2 * math.pi))
        out.append(p + offset)
    return out


# ----- what the numbers mean --------------------------------------------------------------------
def insertion_loss_db(s21: Sequence[Complex]) -> List[float]:
    """Loss through a device in dB, positive for a loss: ``-20 log10 |S21|``."""
    return [-db20(v) for v in s21]


def return_loss_db(s11: Sequence[Complex]) -> List[float]:
    """Return loss in dB, positive (bigger is better matched): ``-20 log10 |S11|``."""
    return [-db20(v) for v in s11]


def vswr(s11: Sequence[Complex]) -> List[float]:
    """Voltage standing wave ratio, 1 (perfect match) up to ``inf`` (total reflection)."""
    out = []
    for v in s11:
        g = abs(v)
        out.append(math.inf if g >= 1.0 else (1 + g) / (1 - g))
    return out


def gamma_to_z(gamma: Sequence[Complex], z0: float = 50.0) -> List[complex]:
    """Impedance (ohm, ``R + jX``) from a reflection coefficient: ``z0 (1 + G) / (1 - G)``.
    Total reflection with zero phase (an open circuit) gives ``inf``."""
    out = []
    for g in gamma:
        out.append(complex(math.inf, 0) if abs(1 - g) < 1e-15 else z0 * (1 + g) / (1 - g))
    return out


def z_to_gamma(z: Sequence[Complex], z0: float = 50.0) -> List[complex]:
    """Reflection coefficient from an impedance: ``(z - z0) / (z + z0)``."""
    return [(v - z0) / (v + z0) for v in z]


def group_delay_s(freq: Sequence[float], s21: Sequence[Complex]) -> List[float]:
    """Group delay in seconds, ``-d(phase)/d(omega)``, from the unwrapped phase of ``s21``. A
    cable of length L and velocity factor v gives ``L / (v c)`` at every frequency. Needs at least
    2 points; the ends use the nearest neighbour, the others the two points around."""
    _same_length(freq, s21)
    if len(freq) < 2:
        raise RfError("group delay needs at least 2 frequency points")
    phase = unwrap_phase([cmath.phase(v) for v in s21])
    out = []
    last = len(freq) - 1
    for i in range(len(freq)):
        a, b = max(i - 1, 0), min(i + 1, last)
        d_omega = 2 * math.pi * (freq[b] - freq[a])
        out.append(-(phase[b] - phase[a]) / d_omega if d_omega else 0.0)
    return out


def velocity_factor(delay_s: float, length_m: float) -> float:
    """Velocity factor of a cable (1.0 = speed of light) from its delay and length."""
    if delay_s <= 0 or length_m <= 0:
        raise RfError("velocity factor needs a positive delay and a positive length")
    return length_m / (delay_s * SPEED_OF_LIGHT)


SPEED_OF_LIGHT = 299_792_458.0  # m/s


# ----- reading a curve --------------------------------------------------------------------------
def value_at(freq: Sequence[float], y: Sequence[float], f: float) -> float:
    """The curve at frequency ``f`` by linear interpolation between the two nearest points.
    ``RfError`` if ``f`` is outside the measured range (nothing is invented)."""
    _same_length(freq, y)
    if not freq:
        raise RfError("empty trace")
    lo, hi = min(freq), max(freq)
    if not lo <= f <= hi:
        raise RfError(f"{f:g} Hz is outside the measured range {lo:g} .. {hi:g} Hz")
    pairs = sorted(zip(freq, y))
    for (f0, y0), (f1, y1) in zip(pairs, pairs[1:]):
        if f0 <= f <= f1:
            return y0 if f1 == f0 else y0 + (y1 - y0) * (f - f0) / (f1 - f0)
    return pairs[-1][1]


def crossings(freq: Sequence[float], y: Sequence[float], level: float) -> List[float]:
    """Frequencies where the curve crosses ``level`` (linear interpolation), in order. For the
    -3 dB points of a filter, use the curve in dB relative to its peak."""
    _same_length(freq, y)
    out = []
    pairs = sorted(zip(freq, y))
    for (f0, y0), (f1, y1) in zip(pairs, pairs[1:]):
        if y0 == level:
            out.append(f0)
        elif (y0 - level) * (y1 - level) < 0:
            out.append(f0 + (f1 - f0) * (level - y0) / (y1 - y0))
    if pairs and pairs[-1][1] == level and (len(pairs) < 2 or pairs[-2][1] != level):
        out.append(pairs[-1][0])
    return out


def level_crossings(
    freq: Sequence[float], y: Sequence[float], level: float
) -> List[Tuple[float, str]]:
    """Where the curve crosses ``level``, with the direction: ``[(frequency, "rising" |
    "falling")]`` in order. ``"falling"``: the curve goes from at or above the level to below it.
    The frequency is found by linear interpolation. For the edges of a filter: its -3 dB points
    relative to the peak; the low edge of a band-pass is rising and the high edge falling."""
    _same_length(freq, y)
    out: List[Tuple[float, str]] = []
    pairs = sorted(zip(freq, y))
    for (f0, v0), (f1, v1) in zip(pairs, pairs[1:]):
        if v0 < level <= v1:
            out.append((f0 + (f1 - f0) * (level - v0) / (v1 - v0), "rising"))
        elif v0 >= level > v1:
            out.append((f0 + (f1 - f0) * (level - v0) / (v1 - v0), "falling"))
    return out


def bands_where(
    freq: Sequence[float], y: Sequence[float], level: float, below: bool = True
) -> List[Tuple[float, float]]:
    """The frequency bands where the curve is at or below ``level`` (or at or above it with
    ``below=False``): ``[(from_hz, to_hz), ...]`` in order, the edges found by linear interpolation
    between the points. For the bandwidth of an antenna: the bands where the VSWR is at most 2.
    A band that runs to the end of the sweep ends at the last point."""
    _same_length(freq, y)
    pairs = sorted(zip(freq, y))

    def inside(value: float) -> bool:
        return value <= level if below else value >= level

    bands: List[Tuple[float, float]] = []
    start: Optional[float] = None
    for i, (f, v) in enumerate(pairs):
        if inside(v):
            if start is None:
                if i and not inside(pairs[i - 1][1]):  # entering: where the curve crosses
                    f0, v0 = pairs[i - 1]
                    start = f0 + (f - f0) * (level - v0) / (v - v0)
                else:
                    start = f
        elif start is not None:  # leaving: the crossing is between the previous point and this one
            f0, v0 = pairs[i - 1]
            bands.append((start, f0 + (f - f0) * (level - v0) / (v - v0)))
            start = None
    if start is not None:
        bands.append((start, pairs[-1][0]))
    return bands


def _same_length(a: Sequence, b: Sequence) -> None:
    if len(a) != len(b):
        raise RfError(f"{len(a)} frequencies but {len(b)} values")


# ----- Touchstone files -------------------------------------------------------------------------
UNITS = {"HZ": 1.0, "KHZ": 1e3, "MHZ": 1e6, "GHZ": 1e9}
FORMATS = ("RI", "MA", "DB")  # real/imaginary, magnitude/angle, dB/angle
# order of the parameters on a line: 1 port S11; 2 ports S11 S21 S12 S22 (the Touchstone convention)
PORT_ORDER = {1: ["S11"], 2: ["S11", "S21", "S12", "S22"]}


def write_touchstone(
    path: Union[str, Path],
    freq: Sequence[float],
    params: Dict[str, Sequence[Complex]],
    z0: float = 50.0,
    fmt: str = "RI",
    unit: str = "HZ",
    comment: str = "",
) -> None:
    """Write a ``.s1p`` / ``.s2p`` file. ``params`` is ``{"S11": [...]}`` for one port or with
    ``S11 S21 S12 S22`` for two (a missing one is written as zero: a one-way measurement of S21
    only is common). ``fmt``: ``RI``, ``MA`` or ``DB``; ``unit``: ``HZ`` ``KHZ`` ``MHZ`` ``GHZ``."""
    fmt, unit = fmt.upper(), unit.upper()
    if fmt not in FORMATS:
        raise RfError(f"format must be one of {FORMATS}, not {fmt!r}")
    if unit not in UNITS:
        raise RfError(f"unit must be one of {sorted(UNITS)}, not {unit!r}")
    ports = 2 if any(k in params for k in ("S21", "S12", "S22")) else 1
    unknown = [k for k in params if k not in PORT_ORDER[ports]]
    if unknown:
        raise RfError(f"unknown parameter(s) {unknown} for a {ports}-port file")
    if "S11" not in params and ports == 1:
        raise RfError("a one-port file needs S11")
    for name, values in params.items():
        _same_length(freq, values)
    lines = [f"! {text}" for text in comment.splitlines()] if comment else []
    lines.append(f"# {unit} S {fmt} R {z0:g}")
    scale = UNITS[unit]
    for i, f in enumerate(freq):
        fields = [f"{f / scale:.12g}"]
        for name in PORT_ORDER[ports]:
            value = complex(params[name][i]) if name in params else 0j
            a, b = _encode(value, fmt)
            fields += [f"{a:.9g}", f"{b:.9g}"]
        lines.append(" ".join(fields))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_touchstone(
    path: Union[str, Path],
) -> Tuple[List[float], Dict[str, List[complex]], float]:
    """Read a ``.s1p`` / ``.s2p`` file: ``(freq_hz, {"S11": [...], ...}, z0)``. Comments (``!``) are
    skipped; the option line sets unit, format and reference impedance."""
    ext = Path(path).suffix.lower()
    ports = {".s1p": 1, ".s2p": 2}.get(ext)
    if ports is None:
        raise RfError(f"{path}: only .s1p and .s2p files are read")
    unit, fmt, z0 = "GHZ", "MA", 50.0  # the defaults of the Touchstone standard
    numbers: List[float] = []
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            tokens = line[1:].upper().split()
            if "R" in tokens and tokens.index("R") + 1 < len(tokens):
                z0 = float(tokens[tokens.index("R") + 1])
            unit = next((t for t in tokens if t in UNITS), unit)
            fmt = next((t for t in tokens if t in FORMATS), fmt)
            continue
        try:
            numbers += [float(t) for t in line.split()]
        except ValueError as exc:
            raise RfError(f"{path}: not a number in {line!r}") from exc
    width = 1 + 2 * len(PORT_ORDER[ports])
    if len(numbers) % width:
        raise RfError(f"{path}: {len(numbers)} numbers do not fit rows of {width}")
    freq: List[float] = []
    params: Dict[str, List[complex]] = {name: [] for name in PORT_ORDER[ports]}
    for start in range(0, len(numbers), width):
        stop = start + width
        row = numbers[start:stop]
        freq.append(row[0] * UNITS[unit])
        for n, name in enumerate(PORT_ORDER[ports]):
            params[name].append(_decode(row[1 + 2 * n], row[2 + 2 * n], fmt))
    return freq, params, z0


def _encode(value: complex, fmt: str) -> Tuple[float, float]:
    if fmt == "RI":
        return value.real, value.imag
    angle = math.degrees(cmath.phase(value))
    return (abs(value) if fmt == "MA" else db20(value)), angle


def _decode(a: float, b: float, fmt: str) -> complex:
    if fmt == "RI":
        return complex(a, b)
    magnitude = a if fmt == "MA" else 10 ** (a / 20.0)
    return cmath.rect(magnitude, math.radians(b))


def span_text(freq: Sequence[float]) -> Optional[str]:
    """``"1 MHz .. 6 GHz, 401 points"`` for a title or a log line; None if there are no points."""
    if not freq:
        return None
    return f"{_hz(min(freq))} .. {_hz(max(freq))}, {len(freq)} points"


def _hz(f: float) -> str:
    for unit, scale in (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3)):
        if abs(f) >= scale:
            return f"{f / scale:g} {unit}"
    return f"{f:g} Hz"
