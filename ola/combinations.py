# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Combinations of resistors for a range of output current (no Qt).

The efficiency with a resistive load needs loads that give chosen output currents. With a kit of
resistors, ``plan_loads`` finds series / parallel networks (nested as far as needed, each physical
resistor used at most once per network) whose current at the output voltage is as near as possible
to equally spaced targets, without a resistor carrying more than a fraction of its rating, and
chooses among the nearly equivalent ones those that need the fewest resistors moved between one
point and the next.

The search goes **by the number of resistors used**: for every value (grouped in bands of relative
width ``eps``) it keeps a few ways to make it, with the set of resistors each uses, so that its
cost does not grow like ``3**n`` with the size of the kit (15 to 20 resistors take about a second).
The work is done by the Rust module ``ola_native`` when it is installed; this file has the same
steps in Python, with the same result (``OLA_COMBINATIONS=python`` forces it), a few times slower.

The 0 A point (no load) has no resistors: ``plan_loads`` leaves it out of the points and says so in
``open_circuit``, and ``loads_from_plan`` writes it as the first load, ``{"name": "0 A", "open":
true}`` (nothing connected, see ``ola.resistors``).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

Tree = Union[int, Tuple[str, Any, Any]]  # a resistor, or ("s" | "p", left, right)


class PlanError(ValueError):
    """The plan cannot be made; the message says why."""


@dataclass
class Point:
    """One planned point."""

    target_a: float  # the current that was asked for
    r_ohm: float  # resistance of the network
    current_a: float  # the current it gives at the output voltage
    deviation_pct: float  # from the target, in percent of the distance between two targets
    load_pct: float  # of its rating, for the most loaded resistor at the output voltage
    changes: int  # resistors moved from the previous point (the first point counts its own)
    tree: Tree = 0


@dataclass
class Plan:
    """The plan: its points in order, and whether a 0 A target was left out."""

    points: List[Point] = field(default_factory=list)
    open_circuit: bool = False

    @property
    def changes(self) -> int:
        """Resistors moved in all."""
        return sum(p.changes for p in self.points)


# ---- the search (the same steps as native/src/combos.rs) ---------------------------------------


@dataclass
class _Way:
    ohms: float
    mask: int
    q: float  # fraction of the rating per volt squared
    tree: Tree


def _band(value: float, lg: float) -> int:
    x = math.log(value) / lg
    return int(math.copysign(math.floor(abs(x) + 0.5), x))  # half away from zero, like Rust


def _ordered(level: Dict[int, List[_Way]]) -> List[_Way]:
    return [w for k in sorted(level) for w in level[k]]


def _insert(
    out: Dict[int, List[_Way]], key: int, ohms: float, mask: int, q: float, tree: Tree, keep: int
) -> None:
    """Keep a way if its band has room, or it is better (a lower load) than the worst kept."""
    slot = out.setdefault(key, [])
    for w in slot:
        if w.mask == mask:
            return
    if len(slot) < keep:
        slot.append(_Way(ohms, mask, q, tree))
        return
    worst = 0
    for i, w in enumerate(slot):
        if w.q > slot[worst].q:
            worst = i
    if q < slot[worst].q:
        slot[worst] = _Way(ohms, mask, q, tree)


def _search(ohms: Sequence[float], watts: Sequence[float], eps: float, keep: int) -> List[_Way]:
    n = len(ohms)
    lg = math.log1p(eps)
    levels: List[Dict[int, List[_Way]]] = [{} for _ in range(n + 1)]
    for i in range(n):
        _insert(levels[1], _band(ohms[i], lg), ohms[i], 1 << i, 1.0 / (ohms[i] * watts[i]), i, keep)
    for length in range(2, n + 1):
        out: Dict[int, List[_Way]] = {}
        for i in range(1, length // 2 + 1):
            left, right = _ordered(levels[i]), _ordered(levels[length - i])
            for x in left:
                for y in right:
                    if x.mask & y.mask:
                        continue
                    mask = x.mask | y.mask
                    total = x.ohms + y.ohms
                    fx, fy = x.ohms / total, y.ohms / total
                    q = max(x.q * (fx * fx), y.q * (fy * fy))
                    _insert(out, _band(total, lg), total, mask, q, ("s", x.tree, y.tree), keep)
                    both = x.ohms * y.ohms / total
                    _insert(
                        out, _band(both, lg), both, mask, max(x.q, y.q), ("p", x.tree, y.tree), keep
                    )
        levels[length] = out
    return [w for level in levels[1:] for w in _ordered(level)]


def _plan_python(
    ohms, watts, targets, vout, step, eps, ways, candidates, w_dev, w_change, margin, vouts=None
) -> List[Tuple[float, float, float, float, int, str]]:
    volts = list(vouts) if vouts else [vout] * len(targets)
    found = _search(ohms, watts, eps, ways)
    layers: List[List[_Way]] = []
    for t, v in zip(targets, volts):
        near = [w for w in found if w.q * v * v <= margin]
        if not near:
            raise PlanError(
                f"no combination of the kit keeps every resistor within its rating at {v:g} V"
            )
        near.sort(key=lambda w: abs(v / w.ohms - t))  # stable, like Rust's
        layers.append(near[:candidates])
    cost: List[List[Tuple[float, int]]] = []
    for li, layer in enumerate(layers):
        row = []
        for w in layer:
            dev = abs(volts[li] / w.ohms - targets[li]) / step
            if li == 0:
                row.append((w_dev * dev + w_change * bin(w.mask).count("1"), 0))
                continue
            best = (float("inf"), 0)
            for pi, prev in enumerate(layers[li - 1]):
                moved = bin(prev.mask ^ w.mask).count("1")
                c = cost[li - 1][pi][0] + w_dev * dev + w_change * moved
                if c < best[0]:
                    best = (c, pi)
            row.append(best)
        cost.append(row)
    at = 0
    for i, c in enumerate(cost[-1]):
        if c[0] < cost[-1][at][0]:
            at = i
    chosen = [0] * len(layers)
    for li in range(len(layers) - 1, -1, -1):
        chosen[li] = at
        at = cost[li][at][1]
    points, before = [], 0
    for li, layer in enumerate(layers):
        w = layer[chosen[li]]
        points.append(
            (
                targets[li],
                w.ohms,
                volts[li] / w.ohms,
                w.q * volts[li] * volts[li],
                bin(before ^ w.mask).count("1"),
                json.dumps(_listed(w.tree), separators=(",", ":")),
            )
        )
        before = w.mask
    return points


def _listed(tree: Tree) -> Any:
    return tree if isinstance(tree, int) else [tree[0], _listed(tree[1]), _listed(tree[2])]


# ---- the plan ----------------------------------------------------------------------------------


def native_available() -> bool:
    """True if the planner of the Rust module is used."""
    if os.environ.get("OLA_COMBINATIONS", "").lower() == "python":
        return False
    try:
        import ola_native

        return hasattr(ola_native, "plan_combinations")
    except ImportError:
        return False


def targets_for(i_min: float, i_max: float, points: int) -> List[float]:
    """The ``points`` currents equally spaced from ``i_min`` to ``i_max`` (both included); one point
    is ``i_max``."""
    if points < 1:
        raise PlanError("give at least one point")
    if not (math.isfinite(i_min) and math.isfinite(i_max)) or i_min < 0 or i_max <= i_min:
        raise PlanError("the largest current must be above the smallest, and neither below 0")
    if points == 1:
        return [i_max]
    return [i_min + (i_max - i_min) * k / (points - 1) for k in range(points)]


def plan_loads(
    resistors: Sequence[Mapping[str, Any]],
    vout_v: float,
    i_min: float,
    i_max: float,
    points: int,
    margin: float = 0.8,
    eps: float = 0.01,
    ways: int = 3,
    candidates: int = 6,
    w_dev: float = 10.0,
    w_change: float = 1.0,
    vouts: Optional[Sequence[float]] = None,
) -> Plan:
    """The networks that give ``points`` currents from ``i_min`` to ``i_max`` at ``vout_v``.

    ``resistors`` are the kit (``r_ohm`` and ``power_w``; a resistor without a rating is not
    limited). ``margin`` is the largest fraction of its rating a resistor may carry, ``eps`` the
    width of a band of values (0.01 = 1 %). ``vouts`` gives the output voltage at each of the
    ``points`` currents (a converter that is not regulated, once its curve is known); without it
    ``vout_v`` is used for all. ``PlanError`` if nothing can be planned."""
    if not resistors:
        raise PlanError("the kit has no resistors")
    if not (math.isfinite(vout_v) and vout_v > 0):
        raise PlanError("the output voltage must be above 0")
    if not 0 < margin <= 1:
        raise PlanError("the margin must be above 0 and at most 1 (100 % of the rating)")
    wanted = targets_for(i_min, i_max, points)
    if vouts is not None and (
        len(vouts) != len(wanted) or not all(math.isfinite(v) and v > 0 for v in vouts)
    ):
        raise PlanError("give one output voltage above 0 for every point")
    drop = bool(wanted) and wanted[0] == 0
    wanted = wanted[1:] if drop else wanted
    volts = list(vouts)[1:] if (vouts is not None and drop) else (list(vouts) if vouts else None)
    step = (i_max - i_min) / (points - 1) if points > 1 else i_max
    ohms = [float(r["r_ohm"]) for r in resistors]
    watts = [float(r["power_w"]) if r.get("power_w") else math.inf for r in resistors]
    args = (ohms, watts, wanted, float(vout_v), step, eps, ways, candidates, w_dev, w_change)
    args += (margin, volts)
    if not wanted:
        raw: List[Tuple[float, float, float, float, int, str]] = []
    elif native_available():
        import ola_native

        try:
            raw = ola_native.plan_combinations(*args)
        except ValueError as exc:
            raise PlanError(str(exc)) from exc
    else:
        if len(ohms) > 64:
            raise PlanError("the kit needs from 1 to 64 resistors")
        if any(o <= 0 for o in ohms) or any(w <= 0 for w in watts):
            raise PlanError("every resistor needs a resistance and a rating above 0")
        raw = _plan_python(*args)
    result = Plan(open_circuit=drop)
    for target, r, current, load, changes, tree in raw:
        result.points.append(
            Point(target, r, current, (current - target) / step * 100, load * 100, changes,
                  _tuple(json.loads(tree)))
        )  # fmt: skip
    return result


def _tuple(tree: Any) -> Tree:
    return tree if isinstance(tree, int) else (tree[0], _tuple(tree[1]), _tuple(tree[2]))


def tree_to_load(tree: Tree, resistors: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The network as a load of the measurement file: ``{"series": [...]}`` or
    ``{"parallel": [...]}``, nested, a series inside a series (or a parallel inside a parallel)
    merged. A resistor is the entry of ``resistors`` that it came from (a ``{"kit", "ref"}``
    reference stays a reference)."""
    if isinstance(tree, int):
        return dict(resistors[tree])
    kind = "series" if tree[0] == "s" else "parallel"
    items: List[Dict[str, Any]] = []
    for side in (tree[1], tree[2]):
        node = tree_to_load(side, resistors)
        items.extend(node[kind] if kind in node and len(node) == 1 else [node])
    return {kind: items}


def tree_text(tree: Tree, names: Sequence[str], top: bool = True) -> str:
    """The network in one line: ``R1 || (R2 + R3)``."""
    if isinstance(tree, int):
        return str(names[tree])
    text = f"{tree_text(tree[1], names, False)} {'+' if tree[0] == 's' else '||'} " \
           f"{tree_text(tree[2], names, False)}"  # fmt: skip
    return text if top else f"({text})"


def loads_from_plan(plan: Plan, resistors: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The loads of the plan, named by their target (``"3 A"``), ready for ``loads``; the open
    output of a 0 A target comes first."""
    out: List[Dict[str, Any]] = [{"name": "0 A", "open": True}] if plan.open_circuit else []
    for p in plan.points:
        load = tree_to_load(p.tree, resistors)
        out.append({"name": f"{p.target_a:g} A", **{k: v for k, v in load.items() if k != "name"}})
    return out
