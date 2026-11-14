# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The resistive-efficiency measurement: parameters, the numbers, and whole runs on a simulated
converter with resistors on the relays of a multiplexer (or connected by hand)."""

import copy
import threading
import time

import pytest

from ola.measurement import MeasurementError
from ola.modules.resistive_efficiency.measurement import (
    default_params,
    figures,
    point_verdict,
)
from ola.registry import default_registry
from ola.resistors import parse_load
from ola.runner import FINAL_STATES, Runner, RunState
from ola.sim_bench import SimResistiveBench

OHMS = {"201": 10.0, "202": 22.0, "203": 47.0}

BASE = {
    "device": {"label": "5 V buck"},
    "vin_v": {"values": [9, 12, 15]},
    "loads": [
        {"name": "10R", "r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"},
        {
            "name": "22||47",
            "parallel": [
                {"r_ohm": 22, "tol_pct": 1, "power_w": 2, "channel": "202"},
                {"r_ohm": 47, "tol_pct": 5, "power_w": 2, "channel": "203"},
            ],
        },
    ],
    "switching": {"mode": "mux", "settle_s": 0, "supply_off": True},
    "vout_reading": {"call": "measure_dc_voltage", "args": {"channels": "103"}},
    "iin_reading": {"role": "supply", "call": "read_current"},
    "timing": {"settle_s": 0, "samples": 2, "interval_s": 0},
    "safety": {"max_vin_v": 20, "max_vout_v": 6, "max_iin_a": 5},
    "limits": {"min_efficiency_pct": 85},
    "confirm_setup": False,
}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(**changes):
    p = copy.deepcopy(BASE)
    for key, value in changes.items():
        if value is None:
            p.pop(key, None)
        elif isinstance(value, dict) and isinstance(p.get(key), dict):
            p[key].update(value)
        else:
            p[key] = value
    return p


def handles(bench, switch=True):
    found = {"supply": [bench.supply], "meter": [bench.meter]}
    if switch:
        found["switch"] = [bench.switch]
    return found


def run(registry, p, bench=None, switch=True):
    bench = bench or SimResistiveBench(channel_ohms=OHMS)
    runner = Runner(registry.create("resistive_efficiency", p), handles(bench, switch))
    runner.start()
    assert runner.join(60)
    tables = {"logs": [], "traces": {}}
    for e in runner.drain():
        if e.kind == "point":
            tables.setdefault(e.data["table"], []).append(e.data["values"])
        elif e.kind == "log":
            tables["logs"].append(e.data["message"])
        elif e.kind == "trace":
            tables["traces"][e.data["name"]] = e.data
    return runner, bench, tables


def problems(registry, p):
    return [(x.path, x.severity, x.message) for x in registry.create(
        "resistive_efficiency", p).check()]  # fmt: skip


# ---- the numbers ------------------------------------------------------------------------------
def test_the_efficiency_comes_with_the_range_of_the_tolerances():
    load = parse_load({"name": "10R", "r_ohm": 10, "tol_pct": 1})
    row = figures(12.0, 0.5, 5.0, load)  # Pin = 6 W
    assert row["pin_w"] == pytest.approx(6.0) and row["pout_w"] == pytest.approx(2.5)
    assert row["iout_a"] == pytest.approx(0.5)
    assert row["efficiency_pct"] == pytest.approx(2.5 / 6 * 100)
    assert row["pout_min_w"] == pytest.approx(25 / 10.1) and row["pout_max_w"] == pytest.approx(
        25 / 9.9
    )
    assert row["efficiency_min_pct"] < row["efficiency_pct"] < row["efficiency_max_pct"]
    assert row["efficiency_min_pct"] == pytest.approx(25 / 10.1 / 6 * 100)


def test_without_input_power_there_is_no_efficiency():
    row = figures(12.0, 0.0, 0.0, parse_load({"r_ohm": 10}))
    assert row["efficiency_pct"] is None and row["efficiency_min_pct"] is None
    assert point_verdict({**row, "vout_v": 0.0}, {"min_efficiency_pct": 80}) == [
        "no input power: the efficiency cannot be worked out"
    ]


def test_the_verdict_uses_the_lowest_efficiency():
    base = {"efficiency_min_pct": 84.0, "efficiency_pct": 86.0, "vout_v": 5.0}
    assert point_verdict(base, {"min_efficiency_pct": 85}) == [
        "efficiency 84 % (lowest) below 85 %"
    ]  # the nominal one would pass, the guaranteed one does not
    assert point_verdict(base, {"min_efficiency_pct": 80}) == []
    assert point_verdict(base, {"vout_min_v": 5.5}) == ["output 5 V below 5.5 V"]
    assert point_verdict(base, {"vout_max_v": 4.5}) == ["output 5 V above 4.5 V"]


# ---- the parameters ---------------------------------------------------------------------------
def test_the_starting_parameters_and_the_example_are_valid(registry):
    assert [p for p in problems(registry, default_params()) if p[1] == "error"] == []
    assert [p for p in problems(registry, BASE) if p[1] == "error"] == []
    info = registry.get("resistive_efficiency")
    assert info.extension == ".rfe"
    assert [(r.name, r.required) for r in info.roles] == [
        ("supply", True), ("meter", True), ("switch", False)]  # fmt: skip


@pytest.mark.parametrize(
    "changes,path,text",
    [
        ({"vin_v": None}, "vin_v", "missing"),
        ({"vin_v": {"values": [0, 12]}}, "vin_v", "above 0"),
        ({"vin_v": {"values": []}}, "vin_v", ""),
        ({"loads": None}, "loads", "give a list of loads"),
        ({"loads": [{"r_ohm": -1}]}, "loads[0].r_ohm", "above 0"),
        ({"vout_reading": None}, "vout_reading", "missing"),
        ({"iin_reading": None}, "iin_reading", "missing"),
        ({"iin_reading": {"role": "dmm"}}, "iin_reading.role", "must be one of"),
        ({"iin_reading": {"role": "supply", "scale": 0}}, "iin_reading.scale", "not be 0"),
        ({"vin_reading": {"call": 5}}, "vin_reading.call", "name of a call"),
        ({"switching": {"mode": "robot"}}, "switching.mode", "must be one of"),
        ({"switching": {"settle_s": -1}}, "switching.settle_s", "0 or more"),
        ({"switching": {"colour": 1}}, "switching.colour", "unknown field"),
        ({"safety": {"max_vin_v": 10}}, "safety.max_vin_v", "above the limit of 10 V"),
        ({"safety": {"max_vout_v": 20}}, "loads[0]", "dissipates"),
        ({"safety": {"max_iin_a": 0}}, "safety.max_iin_a", "above 0"),
        ({"timing": {"samples": 0}}, "timing.samples", "from 1 to 1000"),
        ({"timing": {"hurry": 1}}, "timing.hurry", "unknown field"),
        ({"limits": {"max_loss": 1}}, "limits", "unknown limit"),
        ({"limits": {"min_efficiency_pct": 0}}, "limits", "above 0"),
        ({"confirm_setup": "yes"}, "confirm_setup", "true or false"),
        ({"supply_channel": 0}, "supply_channel", "from 1"),
        ({"golden": {"tolerances": {"rows": {"match": []}}}}, "golden.name", ""),
    ],
)
def test_a_wrong_parameter_is_reported_at_its_field(registry, changes, path, text):
    found = problems(registry, params(**changes))
    assert any(p == path and text in m for p, _s, m in found), found


def test_with_relays_every_resistor_needs_one(registry):
    loads = copy.deepcopy(BASE["loads"])
    del loads[1]["parallel"][1]["channel"]
    found = problems(registry, params(loads=loads))
    assert [(p, s) for p, s, m in found if "needs a 'channel'" in m] == [("loads[1]", "error")]
    # by hand no relay is needed
    assert [p for p in problems(registry, params(loads=loads, switching={"mode": "manual"}))
            if p[1] == "error"] == []  # fmt: skip


def test_hot_switching_and_missing_ratings_check_are_warnings(registry):
    hot = problems(registry, params(switching={"supply_off": False}))
    assert [(p, s) for p, s, _m in hot if p == "switching.supply_off"] == [
        ("switching.supply_off", "warning")
    ]
    without = params()
    without["safety"] = {"max_vin_v": 20}
    no_cap = problems(registry, without)
    assert any(p == "safety.max_vout_v" and s == "warning" for p, s, _m in no_cap)
    assert not any(s == "warning" and p == "safety.max_vout_v"
                   for p, s, _m in problems(registry, BASE))  # fmt: skip


# ---- whole runs through the multiplexer --------------------------------------------------------
def test_every_load_is_connected_and_every_input_voltage_tried(registry):
    runner, bench, tables = run(registry, BASE)
    assert runner.state is RunState.FINISHED, runner.error
    rows = tables["points"]
    assert [(r["load"], r["vin_set_v"]) for r in rows] == [
        (load, vin) for load in ("10R", "22||47") for vin in (9, 12, 15)
    ]
    first = rows[0]
    assert first["r_nom_ohm"] == 10 and first["r_min_ohm"] == pytest.approx(9.9)
    assert first["vout_v"] == pytest.approx(5.0) and first["iout_a"] == pytest.approx(0.5)
    assert first["pout_w"] == pytest.approx(2.5) and first["n_samples"] == 2
    parallel = rows[3]
    assert parallel["r_nom_ohm"] == pytest.approx(1 / (1 / 22 + 1 / 47))
    assert parallel["r_min_ohm"] < parallel["r_nom_ohm"] < parallel["r_max_ohm"]
    assert [r["load"] for r in tables["summary"]] == ["10R", "22||47"]
    assert all(r["verdict"] == "PASS" for r in rows + tables["summary"])


def true_efficiency(row, r_error):
    """The efficiency the real resistors give: the nominal resistance off by ``r_error``."""
    return row["vout_v"] ** 2 / (row["r_nom_ohm"] * (1 + r_error)) / row["pin_w"] * 100


def test_the_real_efficiency_is_inside_the_range_of_the_tolerances(registry):
    """The simulated resistors are 1 % high: the range of the tolerances contains the truth."""
    bench = SimResistiveBench(channel_ohms=OHMS, r_error=0.01)
    _runner, _bench, tables = run(registry, params(limits=None), bench)
    for row in tables["points"]:
        truth = true_efficiency(row, 0.01)
        assert row["efficiency_min_pct"] - 1e-9 <= truth <= row["efficiency_max_pct"] + 1e-9
    # resistors 6 % off are outside the 1 % of the first load: the range does not hold them
    off = SimResistiveBench(channel_ohms=OHMS, r_error=0.06)
    _runner, _bench, tables = run(registry, params(limits=None), off)
    first = tables["points"][0]
    assert first["load"] == "10R"
    assert true_efficiency(first, 0.06) < first["efficiency_min_pct"]


def test_the_measured_efficiency_matches_the_simulated_converter(registry):
    bench = SimResistiveBench(channel_ohms=OHMS, quiescent_a=0.0)
    p = params(limits=None, loads=BASE["loads"][:1], vin_v={"values": [12]}, safety=None)
    seen = {}

    class Spy:
        def call(self, name, **args):
            value = bench.meter.call(name, **args)
            seen["eta"] = bench.efficiency()
            return value

    runner = Runner(
        registry.create("resistive_efficiency", p),
        {"supply": [bench.supply], "meter": [Spy()], "switch": [bench.switch]},
    )
    runner.start()
    assert runner.join(30) and runner.state is RunState.FINISHED, runner.error
    row = [e.data["values"] for e in runner.drain() if e.kind == "point"][0]
    assert row["efficiency_pct"] == pytest.approx(seen["eta"] * 100, rel=1e-6)


def test_the_supply_is_off_while_the_relays_change(registry):
    _runner, bench, _tables = run(registry, BASE)
    assert bench.events == [
        "close 201", "supply on",
        "supply off", "open 201", "close 202", "close 203", "supply on",
        "supply off", "open 202", "open 203",
    ]  # fmt: skip
    assert not bench.supply_on and bench.closed == []


def test_with_supply_off_false_the_supply_stays_on_while_the_relays_change(registry):
    _runner, bench, _tables = run(registry, params(switching={"supply_off": False}))
    assert bench.events == [
        "close 201", "supply on", "open 201", "close 202", "close 203",
        "supply off", "open 202", "open 203",
    ]  # fmt: skip


def test_the_ratings_are_checked_before_anything_is_switched_on(registry):
    p = params(safety={"max_vout_v": 20})
    runner = Runner(registry.create("resistive_efficiency", p), handles(SimResistiveBench(
        channel_ohms=OHMS)))  # fmt: skip
    with pytest.raises(MeasurementError, match="dissipates"):
        runner.start()


def test_a_resistor_above_its_rating_stops_the_run_and_switches_everything_off(registry):
    loads = copy.deepcopy(BASE["loads"])
    loads[0]["power_w"] = 1.0  # 5 V on 10 ohm is 2.5 W
    p = params(loads=loads)
    p["safety"] = {"max_vin_v": 20}  # no max_vout_v: only the readings can show it
    runner, bench, tables = run(registry, p)
    assert runner.state is RunState.FAILED
    assert "10R" in str(runner.error)
    assert "dissipates" in str(runner.error) and "stopped" in str(runner.error)
    assert not bench.supply_on and bench.closed == []  # supply off, relays open
    assert len(tables["points"]) == 1  # the row that showed it is kept


def test_a_too_large_input_current_stops_the_run(registry):
    runner, bench, _tables = run(registry, params(safety={"max_iin_a": 0.05, "max_vout_v": 6}))
    assert runner.state is RunState.FAILED and "input current" in str(runner.error)
    assert not bench.supply_on and bench.closed == []


def test_a_failing_efficiency_is_a_result_not_an_error(registry):
    runner, _bench, tables = run(registry, params(limits={"min_efficiency_pct": 99}))
    assert runner.state is RunState.FINISHED
    assert all(r["verdict"] == "FAIL" for r in tables["points"] + tables["summary"])
    assert any("(lowest) below 99 %" in m for m in tables["logs"])
    assert "efficiency check: FAIL" in tables["logs"]


def test_a_shunt_on_the_datalogger_gives_the_same_current(registry):
    shunt = {"call": "measure_dc_voltage", "args": {"channels": "102"}, "scale": 10}
    shunted = params(limits=None)
    shunted["iin_reading"] = shunt
    _r1, _b1, direct = run(registry, params(limits=None))
    _r2, _b2, via_shunt = run(registry, shunted)
    for a, b in zip(direct["points"], via_shunt["points"]):
        assert a["iin_a"] == pytest.approx(b["iin_a"], rel=1e-9)
        assert a["efficiency_pct"] == pytest.approx(b["efficiency_pct"], rel=1e-9)


def test_the_input_voltage_at_the_converter_is_used_when_it_is_read(registry):
    reading = {"call": "measure_dc_voltage", "args": {"channels": "101"}, "scale": 0.5}
    _r, _b, tables = run(registry, params(limits=None, vin_reading=reading))
    row = tables["points"][0]
    assert row["vin_set_v"] == 9 and row["vin_v"] == pytest.approx(4.5)  # half, by the scale
    assert row["pin_w"] == pytest.approx(row["vin_v"] * row["iin_a"])


def test_a_converter_that_does_not_start_gives_no_efficiency_and_fails(registry):
    bench = SimResistiveBench(channel_ohms=OHMS, dropout_v=10.0)  # 9 V is below its minimum
    runner, _bench, tables = run(registry, params(vin_v={"values": [9, 12]}), bench)
    assert runner.state is RunState.FINISHED
    low = [r for r in tables["points"] if r["vin_set_v"] == 9]
    assert all(r["efficiency_pct"] is None and r["verdict"] == "FAIL" for r in low)
    assert all(r["efficiency_pct"] for r in tables["points"] if r["vin_set_v"] == 12)
    assert [s["points"] for s in tables["summary"]] == [2, 2]
    assert all("efficiency_mean_pct" in s for s in tables["summary"])  # from the 12 V ones


def test_the_curves_are_drawn(registry):
    _runner, _bench, tables = run(registry, BASE)
    traces = tables["traces"]
    assert set(traces) == {"eff_vs_vin_10R", "eff_vs_vin_22_47"} | {
        f"eff_vs_r_{v}V" for v in (9, 12, 15)
    }
    by_vin = traces["eff_vs_vin_10R"]
    assert by_vin["x"] == [9.0, 12.0, 15.0] and by_vin["y"][0] > by_vin["y"][-1]
    assert not by_vin["meta"].get("hidden") and traces["eff_vs_r_9V"]["meta"]["hidden"]
    assert traces["eff_vs_r_9V"]["x"] == pytest.approx([10.0, 1 / (1 / 22 + 1 / 47)])


def test_the_multiplexer_is_needed_for_the_relays(registry):
    runner, _bench, _tables = run(registry, BASE, switch=False)
    assert runner.state is RunState.FAILED
    assert "multiplexer" in str(runner.error)


# ---- by hand ----------------------------------------------------------------------------------
def answer_questions(runner, bench, choice="continue", after=None):
    """What the operator does: connect the load that is asked for, then answer."""
    answered = []

    def work():
        while runner.state not in FINAL_STATES:
            for q in list(runner.pending_questions):
                if "load" in (q.get("data") or {}):
                    answered.append(q["data"]["load"])
                    if len(answered) == after:
                        runner.answer(q["id"], "abort")
                        continue
                    bench.manual_ohms = q["data"]["r_ohm"]
                runner.answer(q["id"], choice)
            time.sleep(0.005)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return answered, thread


def test_by_hand_the_program_asks_for_each_load_by_its_name(registry):
    bench = SimResistiveBench()
    p = params(switching={"mode": "manual"})
    runner = Runner(registry.create("resistive_efficiency", p), handles(bench, switch=False))
    answered, thread = answer_questions(runner, bench)
    runner.start()
    assert runner.join(60) and runner.state is RunState.FINISHED, runner.error
    thread.join(2)
    assert answered == ["10R", "22||47"]
    rows = [e.data["values"] for e in runner.drain() if e.kind == "point"
            and e.data["table"] == "points"]  # fmt: skip
    assert [r["load"] for r in rows] == ["10R"] * 3 + ["22||47"] * 3
    assert rows[3]["vout_v"] == pytest.approx(5.0)
    assert bench.events.count("supply off") == 2  # between the loads, and at the end
    assert bench.events[:4] == ["supply on", "supply off", "supply on", "supply off"]


def test_by_hand_refusing_a_load_stops_with_the_supply_off(registry):
    bench = SimResistiveBench()
    p = params(switching={"mode": "manual"})
    runner = Runner(registry.create("resistive_efficiency", p), handles(bench, switch=False))
    answered, thread = answer_questions(runner, bench, after=2)
    runner.start()
    assert runner.join(60)
    thread.join(2)
    assert runner.state is RunState.STOPPED and answered == ["10R", "22||47"]
    assert not bench.supply_on


def test_the_first_question_can_stop_a_run_before_anything_is_switched(registry):
    bench = SimResistiveBench(channel_ohms=OHMS)
    runner = Runner(registry.create("resistive_efficiency", params(confirm_setup=True)),
                    handles(bench))  # fmt: skip
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    assert "the relays connect them" in runner.pending_questions[0]["text"]
    runner.answer(runner.pending_questions[0]["id"], "abort")
    assert runner.join(10) and runner.state is RunState.STOPPED
    assert bench.log == []


# ---- the golden sample ------------------------------------------------------------------------
def test_the_rows_are_checked_against_a_golden_sample(registry, tmp_path):
    from ola.runs import RunWriter

    path = tmp_path / "resistive_efficiency_golden_20261110_100000.jsonl"
    bench = SimResistiveBench(channel_ohms=OHMS)
    runner = Runner(registry.create("resistive_efficiency", BASE), handles(bench))
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(30)
    spec = {"rows": {"match": ["load", "vin_set_v"], "columns": {"efficiency_pct": 1.0}}}
    with_golden = params(golden={"run": str(path), "tolerances": spec})
    assert [p for p in problems(registry, with_golden) if p[1] == "error"] == []
    same = run(registry, with_golden)[2]
    assert same["golden_result"][0]["golden_verdict"] == "PASS"
    worse = run(registry, with_golden, SimResistiveBench(channel_ohms=OHMS, eta_peak=0.85))[2]
    assert worse["golden_result"][0]["golden_verdict"] == "FAIL"
    assert worse["golden"][0]["check"] == "efficiency_pct (rows)"
