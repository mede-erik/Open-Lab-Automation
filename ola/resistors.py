# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A resistive load made of real resistors (no Qt): the equivalent resistance with its tolerance,
the power in every resistor, and the relays of a multiplexer that connect it.

A load is described in the measurement file as one resistor, or as resistors in **series** or in
**parallel**, nested as far as needed::

    {"name": "10R", "r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"}
    {"name": "22||47", "parallel": [
        {"r_ohm": 22, "tol_pct": 1, "power_w": 2, "channel": "202"},
        {"r_ohm": 47, "tol_pct": 5, "power_w": 2, "channel": "203"}]}
    {"name": "10+(22||47)", "series": [
        {"r_ohm": 10, "channel": "201"},
        {"parallel": [{"r_ohm": 22, "channel": "202"}, {"r_ohm": 47, "channel": "203"}]}]}

``tol_pct`` is the tolerance of the resistor in percent (0 if absent), ``power_w`` its rating
(none if absent: not checked) and ``channel`` the relay of a multiplexer that connects it (the
load is connected by closing the channels of all its resistors). ``parse_load`` checks the
description; ``Load.resistance()`` gives ``(nominal, lowest, highest)`` ohms: series add, and in
parallel the lowest value comes from every resistor at its lowest; ``Load.loading(v)`` gives the
power in each resistor for a voltage ``v`` across the whole load, as an **upper bound** that takes
the tolerances in the worst direction, with the fraction of the rating it is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Sequence, Tuple, Union

MAX_DEPTH = 6
MAX_RESISTORS = 64


class LoadError(ValueError):
    """The description of a load cannot be used; the message says where and why."""


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass
class Resistor:
    """One real resistor."""

    name: str
    r_ohm: float
    tol_pct: float = 0.0
    power_w: Optional[float] = None
    channel: str = ""

    @property
    def low(self) -> float:
        """The lowest value it can have, ohms."""
        return self.r_ohm * (1 - self.tol_pct / 100.0)

    @property
    def high(self) -> float:
        """The highest value it can have, ohms."""
        return self.r_ohm * (1 + self.tol_pct / 100.0)


@dataclass
class Group:
    """Resistors in ``series`` or in ``parallel`` (the children can be groups too)."""

    kind: str
    children: List[Union["Group", Resistor]] = field(default_factory=list)


Node = Union[Group, Resistor]


def _resistance(node: Node) -> Tuple[float, float, float]:
    if isinstance(node, Resistor):
        return node.r_ohm, node.low, node.high
    parts = [_resistance(child) for child in node.children]
    if node.kind == "series":
        return tuple(sum(p[i] for p in parts) for i in range(3))  # type: ignore[return-value]
    return tuple(1.0 / sum(1.0 / p[i] for p in parts) for i in range(3))  # type: ignore


def _resistors(node: Node) -> List[Resistor]:
    if isinstance(node, Resistor):
        return [node]
    return [r for child in node.children for r in _resistors(child)]


def _loading(node: Node, vmax: float, out: List[Tuple[Resistor, float]]) -> None:
    """The largest power in each resistor of ``node`` when at most ``vmax`` volts are across it."""
    if isinstance(node, Resistor):
        out.append((node, vmax * vmax / node.low))
    elif node.kind == "parallel":
        for child in node.children:
            _loading(child, vmax, out)
    else:  # series: the largest current, and each resistor at its highest value
        current = vmax / _resistance(node)[1]
        for child in node.children:
            _loading(child, current * _resistance(child)[2], out)


@dataclass
class Load:
    """A load: a name and the resistors it is made of."""

    name: str
    root: Node

    def resistance(self) -> Tuple[float, float, float]:
        """``(nominal, lowest, highest)`` ohms of the whole load."""
        return _resistance(self.root)

    def resistors(self) -> List[Resistor]:
        """All the resistors, in the order they are written."""
        return _resistors(self.root)

    def channels(self) -> List[str]:
        """The relays that connect the load (those of its resistors that have one)."""
        return [r.channel for r in self.resistors() if r.channel]

    def loading(self, volts: float) -> List[Tuple[Resistor, float, Optional[float]]]:
        """``[(resistor, power_w, fraction of the rating or None)]`` with ``volts`` across the load,
        an upper bound that takes the tolerances in the worst direction."""
        found: List[Tuple[Resistor, float]] = []
        _loading(self.root, abs(volts), found)
        return [(r, p, p / r.power_w if r.power_w else None) for r, p in found]

    def most_loaded(self, volts: float) -> Tuple[Optional[Resistor], float]:
        """The resistor that is closest to its rating (or None if none has a rating) and the
        fraction of its rating."""
        rated = [(r, f) for r, _p, f in self.loading(volts) if f is not None]
        return max(rated, key=lambda item: item[1]) if rated else (None, 0.0)


def _parse_node(raw: Any, path: str, depth: int, count: List[int], fallback: str) -> Node:
    if not isinstance(raw, Mapping):
        raise LoadError(f"{path}: must be an object (a resistor or a series / parallel group)")
    if depth > MAX_DEPTH:
        raise LoadError(f"{path}: groups nested too deep (at most {MAX_DEPTH})")
    groups = [k for k in ("series", "parallel") if k in raw]
    if len(groups) > 1 or (groups and "r_ohm" in raw):
        raise LoadError(f"{path}: a resistor (r_ohm) or one group (series or parallel), not both")
    if groups:
        kind = groups[0]
        unknown = sorted(set(raw) - {kind, "name"})
        if unknown:
            raise LoadError(f"{path}: unknown field(s) {unknown} in a {kind} group")
        items = raw[kind]
        if not isinstance(items, list) or len(items) < 2:
            raise LoadError(f"{path}.{kind}: give a list of at least two resistors")
        children = [
            _parse_node(item, f"{path}.{kind}[{i}]", depth + 1, count, f"{fallback}.{i + 1}")
            for i, item in enumerate(items)
        ]
        return Group(kind, children)
    unknown = sorted(set(raw) - {"name", "r_ohm", "tol_pct", "power_w", "channel"})
    if unknown:
        raise LoadError(f"{path}: unknown field(s) {unknown}: use r_ohm, tol_pct, power_w, channel")
    r = raw.get("r_ohm")
    if not _number(r) or r <= 0:
        raise LoadError(f"{path}.r_ohm: the resistance must be a number of ohms above 0")
    tol = raw.get("tol_pct", 0)
    if not _number(tol) or not 0 <= tol < 100:
        raise LoadError(f"{path}.tol_pct: the tolerance must be a percentage from 0 to below 100")
    power = raw.get("power_w")
    if power is not None and (not _number(power) or power <= 0):
        raise LoadError(f"{path}.power_w: the rating must be a number of watts above 0")
    channel = raw.get("channel", "")
    if not isinstance(channel, str):
        raise LoadError(f"{path}.channel: must be text (the relay of the multiplexer, '201')")
    count[0] += 1
    if count[0] > MAX_RESISTORS:
        raise LoadError(f"too many resistors in a load (at most {MAX_RESISTORS})")
    return Resistor(
        str(raw.get("name") or fallback), float(r), float(tol), power and float(power), channel
    )


def parse_load(raw: Any, path: str = "load", index: int = 0) -> Load:
    """The ``Load`` of a description (see the module docstring). ``LoadError`` says where and why;
    ``path`` is the path of the field in the file, for the message."""
    if not isinstance(raw, Mapping):
        raise LoadError(f"{path}: must be an object")
    name = raw.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        raise LoadError(f"{path}.name: must be text")
    name = (name or f"load{index + 1}").strip()
    root = _parse_node(raw, path, 0, [0], name)
    if isinstance(root, Resistor) and not raw.get("name"):
        root.name = name
    return Load(name, root)


def parse_loads(raw: Any, path: str = "loads") -> List[Load]:
    """The list of loads, with unique names. ``LoadError`` says where and why."""
    if not isinstance(raw, list) or not raw:
        raise LoadError(f'{path}: give a list of loads, like [{{"name": "10R", "r_ohm": 10}}]')
    loads = [parse_load(item, f"{path}[{i}]", i) for i, item in enumerate(raw)]
    seen = set()
    for i, load in enumerate(loads):
        if load.name in seen:
            raise LoadError(f"{path}[{i}].name: two loads are called {load.name!r}")
        seen.add(load.name)
    return loads


def channels_of(loads: Sequence[Load]) -> List[str]:
    """Every relay that any load uses, without repeats."""
    seen: List[str] = []
    for load in loads:
        for channel in load.channels():
            if channel not in seen:
                seen.append(channel)
    return seen


__all__ = [
    "Group", "Load", "LoadError", "Resistor", "channels_of", "parse_load", "parse_loads",
]  # fmt: skip
