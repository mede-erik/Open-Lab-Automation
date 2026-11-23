# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The combinations of resistors for a range of output current: the plan, the loads it gives, and
the Rust and Python versions making the same plan."""

import math
import time

import pytest

from ola import combinations
from ola.combinations import PlanError, loads_from_plan, plan_loads, targets_for, tree_to_load
from ola.resistors import parse_load, parse_loads

KIT = [
    {"name": f"R{i}", "r_ohm": v, "power_w": 100, "kit": "PWR", "ref": f"R{i}"}
    for i, v in enumerate((12, 10, 5, 2, 1, 12, 5))
]


@pytest.fixture(params=["python", "native"])
def backend(request, monkeypatch):
    """Every test with the Python search and, where it is installed, the Rust one."""
    if request.param == "python":
        monkeypatch.setenv("OLA_COMBINATIONS", "python")
    else:
        monkeypatch.delenv("OLA_COMBINATIONS", raising=False)
        if not combinations.native_available():
            pytest.skip("the native module with the planner is not installed")
    return request.param


def value(tree, kit=KIT):
    """Resistance of a tree, worked out again from the kit (not taken from the plan)."""
    if isinstance(tree, int):
        return kit[tree]["r_ohm"]
    a, b = value(tree[1], kit), value(tree[2], kit)
    return a + b if tree[0] == "s" else a * b / (a + b)


def test_the_targets_are_equally_spaced():
    assert targets_for(0, 10, 11) == [float(i) for i in range(11)]
    assert targets_for(2, 4, 3) == [2.0, 3.0, 4.0]
    assert targets_for(1, 5, 1) == [5]
    for args in ((5, 1, 3), (1, 1, 3), (-1, 5, 3), (0, 5, 0), (0, math.inf, 3)):
        with pytest.raises(PlanError):
            targets_for(*args)


def test_the_example_kit_gives_every_current_with_few_changes(backend):
    plan = plan_loads(KIT, 12, 0, 10, 11, margin=1.0)
    assert plan.open_circuit  # 0 A is not a load: it is left out and said
    assert [p.target_a for p in plan.points] == [float(i) for i in range(1, 11)]
    for p in plan.points:
        assert abs(p.current_a - p.target_a) < 0.05  # within 5 % of the step
        assert p.load_pct <= 100
        assert value(p.tree) == pytest.approx(p.r_ohm)  # the network is what it says
    assert plan.points[0].r_ohm == 12 and plan.points[-1].r_ohm == pytest.approx(1.2)
    assert plan.changes == 13  # one change is a resistor moved; fewer is better
    assert plan.points[0].changes == 1 and sum(p.changes for p in plan.points) == plan.changes


def test_each_resistor_is_used_once_per_network(backend):
    def leaves(tree):
        return [tree] if isinstance(tree, int) else leaves(tree[1]) + leaves(tree[2])

    for p in plan_loads(KIT, 12, 0, 10, 11, margin=1.0).points:
        used = leaves(p.tree)
        assert len(used) == len(set(used))


def test_the_margin_keeps_a_resistor_below_its_rating(backend):
    plan = plan_loads(KIT, 12, 0, 10, 11, margin=0.5)  # at most 50 W each
    assert all(p.load_pct <= 50 for p in plan.points)
    # the 1 ohm resistor alone would carry 144 W at 12 V: it never comes alone
    assert all(p.tree != 4 for p in plan.points)
    with pytest.raises(PlanError, match="rating"):
        plan_loads([{"r_ohm": 1, "power_w": 1}], 12, 0, 10, 3)


def test_bad_input_is_refused(backend):
    for args in (
        dict(resistors=[], vout_v=12, i_min=0, i_max=10, points=3),
        dict(resistors=KIT, vout_v=0, i_min=0, i_max=10, points=3),
        dict(resistors=KIT, vout_v=12, i_min=0, i_max=10, points=3, margin=0),
        dict(resistors=KIT, vout_v=12, i_min=5, i_max=1, points=3),
        dict(resistors=[{"r_ohm": -1, "power_w": 5}], vout_v=12, i_min=0, i_max=1, points=2),
    ):
        with pytest.raises(PlanError):
            plan_loads(**args)


def test_only_zero_amps_leaves_nothing_to_plan(backend):
    plan = plan_loads(KIT, 12, 0, 0.5, 1)
    assert [p.target_a for p in plan.points] == [0.5] and not plan.open_circuit


def test_rust_and_python_make_the_same_plan(monkeypatch):
    if not combinations.native_available():
        pytest.skip("the native module with the planner is not installed")
    sag = [12 - 0.3 * i for i in range(11)]
    cases = [
        (KIT, 12, 0, 10, 11, 1.0),
        (KIT, 12, 0, 10, 11, 1.0, sag),
        (KIT, 5, 0.5, 4, 6, 0.8),
        (
            [{"r_ohm": v, "power_w": 25} for v in (1, 2.2, 4.7, 10, 22, 47, 100, 3.3)],
            12,
            0,
            6,
            7,
            0.8,
        ),
    ]
    for args in cases:
        extra = {"vouts": args[6]} if len(args) > 6 else {}
        monkeypatch.delenv("OLA_COMBINATIONS", raising=False)
        native = plan_loads(*args[:5], margin=args[5], **extra)
        monkeypatch.setenv("OLA_COMBINATIONS", "python")
        python = plan_loads(*args[:5], margin=args[5], **extra)
        assert [p.tree for p in native.points] == [p.tree for p in python.points]
        assert [p.changes for p in native.points] == [p.changes for p in python.points]
        assert [p.r_ohm for p in native.points] == pytest.approx([p.r_ohm for p in python.points])


def test_every_point_can_have_its_own_voltage(backend):
    volts = [12, 11, 10, 9, 8]  # a converter whose output sags with the load, 0 A included
    plan = plan_loads(KIT, 12, 0, 4, 5, margin=1.0, vouts=volts)
    assert [p.target_a for p in plan.points] == [1.0, 2.0, 3.0, 4.0] and plan.open_circuit
    for p, v in zip(plan.points, volts[1:]):
        assert p.current_a == pytest.approx(v / p.r_ohm)  # the current at its own voltage
        assert abs(p.current_a - p.target_a) < 0.1
    flat = plan_loads(KIT, 12, 0, 4, 5, margin=1.0)
    assert plan.points[-1].r_ohm < flat.points[-1].r_ohm  # 4 A at 8 V needs less resistance
    for bad in ([12, 12], [12, 12, 12, 12, 0], [12, 12, 12, 12, math.nan]):
        with pytest.raises(PlanError):
            plan_loads(KIT, 12, 0, 4, 5, vouts=bad)


def test_the_rating_is_checked_at_the_voltage_of_each_point(backend):
    kit = [{"r_ohm": 4, "power_w": 10}, {"r_ohm": 8, "power_w": 10}]
    # at 6 V the 4 ohm resistor carries 9 W (fine); at 12 V 36 W (not allowed)
    assert plan_loads(kit, 6, 0, 3, 2, margin=1.0, vouts=[6, 6]).points
    with pytest.raises(PlanError, match="rating"):
        plan_loads(kit[:1], 12, 0, 3, 2, margin=1.0, vouts=[12, 12])


def test_a_kit_without_ratings_is_not_limited(backend):
    kit = [{"r_ohm": v} for v in (1, 2, 5)]
    assert plan_loads(kit, 12, 0, 8, 3).points


def test_the_loads_are_the_networks_written_as_the_measurement_file_wants(backend):
    plan = plan_loads(KIT, 12, 0, 10, 11, margin=1.0)
    loads = loads_from_plan(plan, KIT)
    assert len(loads) == 11 and loads[0] == {"name": "0 A", "open": True}  # no load: the first
    parsed = parse_loads(loads)
    assert parsed[0].resistance()[0] == math.inf
    for point, load in zip(plan.points, parsed[1:]):
        assert load.resistance()[0] == pytest.approx(point.r_ohm)
    assert loads[1]["ref"] == "R0" and loads[1]["kit"] == "PWR" and loads[1]["name"] == "1 A"
    assert loads[2]["name"] == "2 A" and ("series" in loads[2] or "parallel" in loads[2])
    assert len(loads_from_plan(plan_loads(KIT, 12, 1, 10, 10, margin=1.0), KIT)) == 10  # no 0 A


def test_a_series_inside_a_series_is_one_group():
    kit = [{"r_ohm": 1}, {"r_ohm": 2}, {"r_ohm": 3}]
    load = tree_to_load(("s", ("s", 0, 1), 2), kit)
    assert load == {"series": [{"r_ohm": 1}, {"r_ohm": 2}, {"r_ohm": 3}]}
    mixed = tree_to_load(("p", ("s", 0, 1), 2), kit)
    assert mixed == {"parallel": [{"series": [{"r_ohm": 1}, {"r_ohm": 2}]}, {"r_ohm": 3}]}
    assert parse_load(mixed).resistance()[0] == pytest.approx(3 * 3 / 6)


def test_a_big_kit_is_planned_in_a_reasonable_time(backend):
    values = (1, 1.5, 2.2, 3.3, 4.7, 6.8, 10, 15, 22, 33, 47, 68, 100, 150, 220)
    kit = [{"r_ohm": v, "power_w": 100} for v in values]
    kit = kit if backend == "native" else kit[:10]  # the Python search is about 15 times slower
    started = time.perf_counter()
    plan = plan_loads(kit, 12, 0, 10, 11)
    seconds = time.perf_counter() - started
    assert len(plan.points) == 10
    assert seconds < (15 if backend == "native" else 30), seconds
