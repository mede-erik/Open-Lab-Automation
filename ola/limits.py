# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Pass / fail limits on a curve (no Qt): "this cable must lose less than 1.5 dB up to 3 GHz".

A limit is written in a measurement's parameters (``"limits": {...}``), which makes a result a
**verdict** and not only a curve. The forms, which can be combined:

    {"max": 1.5}                                      # never above 1.5 (a constant)
    {"min": -3}                                       # never below -3
    {"max": [[1e6, 0.5], [3e9, 1.5]]}                 # a line: points (Hz, value), straight
                                                      # between them (and flat outside)
    {"bands": [{"from": 1e6, "to": 1e9, "max": 1.0},  # a different limit in each band
               {"from": 1e9, "to": 3e9, "max": 1.5, "min": 0}]}

``parse_limits(spec)`` checks it (raising ``LimitError`` with a sentence that says what is wrong),
``Limits.check(freq, y)`` gives a ``Verdict``, and ``Limits.lines(freq)`` gives the limit as curves
for a plot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

Point = Tuple[float, float]


class LimitError(ValueError):
    """The limit as written cannot be used."""


@dataclass
class Verdict:
    """The result of checking a curve against its limits."""

    passed: bool
    margin: Optional[float] = None  # smallest distance to a limit; negative if it fails
    worst_freq: Optional[float] = None  # where the margin is smallest
    worst_value: Optional[float] = None  # the value of the curve there
    failing: List[float] = field(default_factory=list)  # frequencies out of limits
    checked: int = 0  # points that had a limit

    def summary(self) -> str:
        """One line for a log or a label."""
        if not self.checked:
            return "no limit applies to this curve"
        where = f" at {self.worst_freq:g} Hz" if self.worst_freq is not None else ""
        if self.passed:
            return f"PASS (margin {self.margin:.3g}{where})"
        return (
            f"FAIL ({len(self.failing)} of {self.checked} points; worst {self.margin:.3g}{where})"
        )


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LimitError(f"{what} must be a number, not {value!r}")
    return float(value)


def _line(value: Any, what: str) -> Union[float, List[Point]]:
    """A constant, or a list of (frequency, value) points sorted by frequency."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, (list, tuple)) or not value:
        raise LimitError(f"{what} must be a number or a list of [frequency, value] points")
    points: List[Point] = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise LimitError(f"{what}: each point must be [frequency, value], not {item!r}")
        points.append((_number(item[0], what + " frequency"), _number(item[1], what + " value")))
    freqs = [f for f, _ in points]
    if len(set(freqs)) != len(freqs):
        raise LimitError(f"{what}: two points have the same frequency")
    return sorted(points)


def _at(line: Union[float, List[Point]], f: float) -> float:
    if isinstance(line, float):
        return line
    if f <= line[0][0]:
        return line[0][1]
    if f >= line[-1][0]:
        return line[-1][1]
    for (f0, v0), (f1, v1) in zip(line, line[1:]):
        if f0 <= f <= f1:
            return v0 + (v1 - v0) * (f - f0) / (f1 - f0)
    return line[-1][1]


@dataclass
class Band:
    """A frequency band with its own limits."""

    start: float
    stop: float
    low: Optional[float] = None
    high: Optional[float] = None


class Limits:
    """The limits of a curve; build with ``parse_limits``."""

    def __init__(
        self,
        low: Optional[Union[float, List[Point]]] = None,
        high: Optional[Union[float, List[Point]]] = None,
        bands: Sequence[Band] = (),
    ):
        self.low, self.high, self.bands = low, high, list(bands)

    @property
    def empty(self) -> bool:
        """True if there is no limit at all."""
        return self.low is None and self.high is None and not self.bands

    def bounds(self, f: float) -> Tuple[Optional[float], Optional[float]]:
        """``(lowest, highest)`` allowed at frequency ``f``; None where there is no limit. A band
        and a general limit both apply: the stricter wins."""
        low = _at(self.low, f) if self.low is not None else None
        high = _at(self.high, f) if self.high is not None else None
        for band in self.bands:
            if band.start <= f <= band.stop:
                if band.low is not None:
                    low = band.low if low is None else max(low, band.low)
                if band.high is not None:
                    high = band.high if high is None else min(high, band.high)
        return low, high

    def check(self, freq: Sequence[float], y: Sequence[float]) -> Verdict:
        """Check every point of a curve."""
        if len(freq) != len(y):
            raise LimitError(f"{len(freq)} frequencies but {len(y)} values")
        verdict = Verdict(True)
        for f, v in zip(freq, y):
            low, high = self.bounds(f)
            margins = []
            if low is not None:
                margins.append(v - low)
            if high is not None:
                margins.append(high - v)
            if not margins:
                continue
            verdict.checked += 1
            margin = min(margins)
            if margin < 0:
                verdict.failing.append(f)
            if verdict.margin is None or margin < verdict.margin:
                verdict.margin, verdict.worst_freq, verdict.worst_value = margin, f, v
        verdict.passed = not verdict.failing
        return verdict

    def lines(self, freq: Sequence[float]) -> Dict[str, List[Point]]:
        """The limits as curves over ``freq`` for a plot: ``{"min": [(f, v)...], "max": [...]}``
        (a key is missing if there is no such limit anywhere)."""
        out: Dict[str, List[Point]] = {}
        for f in sorted(freq):
            low, high = self.bounds(f)
            if low is not None:
                out.setdefault("min", []).append((f, low))
            if high is not None:
                out.setdefault("max", []).append((f, high))
        return out


def parse_limits(spec: Optional[Mapping[str, Any]]) -> Limits:
    """Build ``Limits`` from the form in a measurement's parameters; ``None`` or ``{}`` means no
    limits. ``LimitError`` says what is wrong."""
    if not spec:
        return Limits()
    if not isinstance(spec, Mapping):
        raise LimitError('limits must be an object like {"max": 1.5}')
    unknown = sorted(set(spec) - {"min", "max", "bands"})
    if unknown:
        raise LimitError(f"unknown limit key(s) {unknown}: use min, max or bands")
    low = _line(spec["min"], "min") if "min" in spec else None
    high = _line(spec["max"], "max") if "max" in spec else None
    bands = []
    for n, raw in enumerate(spec.get("bands", []) or [], 1):
        where = f"band {n}"
        if not isinstance(raw, Mapping) or "from" not in raw or "to" not in raw:
            raise LimitError(f"{where} needs 'from' and 'to' (Hz)")
        start, stop = _number(raw["from"], where + " from"), _number(raw["to"], where + " to")
        if start >= stop:
            raise LimitError(f"{where}: 'from' must be below 'to'")
        if "min" not in raw and "max" not in raw:
            raise LimitError(f"{where} needs a 'min' or a 'max'")
        band_low = _number(raw["min"], where + " min") if "min" in raw else None
        band_high = _number(raw["max"], where + " max") if "max" in raw else None
        if band_low is not None and band_high is not None and band_low > band_high:
            raise LimitError(f"{where}: 'min' is above 'max'")
        bands.append(Band(start, stop, band_low, band_high))
    for name, line in (("min", low), ("max", high)):
        if isinstance(line, float) and name == "min" and isinstance(high, float) and line > high:
            raise LimitError("'min' is above 'max'")
    return Limits(low, high, bands)
