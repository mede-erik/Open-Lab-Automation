# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Sweeps: the values an axis takes and the nested walk over several axes.

An axis is described by a dict, in one of three forms::

    {"values": [9, 12, 15]}                                   explicit list
    {"start": 0.1, "stop": 5, "points": 10}                   linear, number of points
    {"start": 0.1, "stop": 5, "points": 10, "scale": "log"}   logarithmic (start, stop > 0)
    {"start": 0.1, "stop": 5, "step": 0.1}                    linear, step (stop included)

``iter_points`` walks several axes nested: the **first** axis is the innermost (it changes first and
fastest), the last one the outermost (slowest). The second axis advances one step only when the
first has done its whole sweep, the third when the second has done its whole sweep, and so on.
"""

from __future__ import annotations

import itertools
import math
from typing import Any, Dict, Iterator, List, Mapping, Sequence, Tuple

MAX_AXIS_POINTS = 100_000
_FORMS = {"values", "start", "stop", "points", "step", "scale"}


class SweepError(ValueError):
    """The description of an axis is not valid (the message says why)."""


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SweepError(f"{what} must be a finite number, got {value!r}")
    return float(value)


def axis_values(spec: Mapping[str, Any]) -> List[float]:
    """The values of one axis. Raises ``SweepError`` with a readable message if it is invalid."""
    if not isinstance(spec, Mapping):
        raise SweepError("an axis is an object like {'start': 1, 'stop': 5, 'points': 5}")
    unknown = sorted(set(spec) - _FORMS - {"variable"})
    if unknown:
        raise SweepError(f"unknown field(s): {', '.join(unknown)}")
    if "values" in spec:
        if set(spec) - {"values", "variable"}:
            raise SweepError("with 'values' do not give start, stop, points, step or scale")
        values = spec["values"]
        if not isinstance(values, (list, tuple)) or not values:
            raise SweepError("'values' must be a non-empty list of numbers")
        if len(values) > MAX_AXIS_POINTS:
            raise SweepError(f"too many values (the limit is {MAX_AXIS_POINTS})")
        return [_number(v, f"values[{i}]") for i, v in enumerate(values)]
    if "start" not in spec or "stop" not in spec:
        raise SweepError("give 'values', or 'start' and 'stop' with 'points' or 'step'")
    start, stop = _number(spec["start"], "start"), _number(spec["stop"], "stop")
    has_points, has_step = "points" in spec, "step" in spec
    if has_points == has_step:
        raise SweepError("give either 'points' or 'step' (exactly one of them)")
    scale = spec.get("scale", "linear")
    if scale not in ("linear", "log"):
        raise SweepError("'scale' must be 'linear' or 'log'")
    if has_step:
        if scale == "log":
            raise SweepError("a logarithmic axis needs 'points', not 'step'")
        step = _number(spec["step"], "step")
        if step == 0 or (stop - start) * step < 0:
            raise SweepError("'step' must be non-zero and go from start towards stop")
        count = int(math.floor((stop - start) / step + 1e-9)) + 1
    else:
        points = spec["points"]
        if isinstance(points, bool) or not isinstance(points, int) or points < 1:
            raise SweepError("'points' must be an integer >= 1")
        count = points
    if count > MAX_AXIS_POINTS:
        raise SweepError(f"too many points ({count}; the limit is {MAX_AXIS_POINTS})")
    if count == 1:
        return [start]
    if scale == "log":
        if start <= 0 or stop <= 0:
            raise SweepError("a logarithmic axis needs start > 0 and stop > 0")
        ratio = (stop / start) ** (1.0 / (count - 1))
        return [start * ratio**i for i in range(count - 1)] + [stop]
    if has_step:
        return [start + i * float(spec["step"]) for i in range(count)]
    return [start + (stop - start) * i / (count - 1) for i in range(count - 1)] + [stop]


def total_points(axes: Sequence[Tuple[str, Sequence[float]]]) -> int:
    """Number of points of a nested sweep (1 when there are no axes: a single measurement)."""
    total = 1
    for _, values in axes:
        total *= len(values)
    return total


def iter_points(axes: Sequence[Tuple[str, Sequence[float]]]) -> Iterator[Dict[str, float]]:
    """Walk the axes nested, first axis innermost (fastest): yields ``{name: value}`` per point."""
    names = [name for name, _ in axes]
    # itertools.product varies its LAST input fastest, so feed it the axes in reverse
    for combo in itertools.product(*[values for _, values in reversed(axes)]):
        by_name = dict(zip(reversed(names), combo))
        yield {name: by_name[name] for name in names}  # keys in the order of the axes
