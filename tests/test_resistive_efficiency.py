# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The efficiency with a resistive load (``.rfe``): the efficiency measurement whose load is a
parameter made of resistors. Parameters, and whole runs on a simulated converter with resistors on
the relays of a multiplexer (or connected by hand)."""

import copy
import threading
import time

import pytest

from ola.efficiency_editor import EfficiencyEditor
from ola.efficiency_spec import parse_params, validate_params
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_bench import SimResistiveBench

OHMS = {"201": 10.0, "202": 22.0, "203": 47.0}
SHUNT = {"instrument": "meter", "call": "measure_dc_voltage", "args": {"channels": "103"}}
LOADS = [
    {"name": "10R", "r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"},
    {
        "name": "22||47",
        "parallel": [
            {"r_ohm": 22, "tol_pct": 1, "power_w": 2, "channel": "202"},
            {"r_ohm": 47, "tol_pct": 5, "power_w": 2, "channel": "203"},
        ],
    },
]
BASE = {
    "variables": [
        {
            "name": "vin",
            "set": {"instrument": "supply", "call": "set_voltage"},
            "sweep": {"values": [9, 12]},
            "reads": {"daq": {"instrument": "supply", "call": "read_voltage"}},
            "output": {
                "on": {"instrument": "supply", "call": "output_on"},
                "off": {"instrument": "supply", "call": "output_off"},
            },
        },
        {
            "name": "rload",
            "load": {
                "loads": LOADS,
                "switching": {"mode": "mux", "instrument": "switch", "settle_s": 0},
                "vout": "vout@daq",
                "max_vout_v": 6,
            },
        },
        {"name": "iin", "reads": {"daq": {"instrument": "supply", "call": "read_current"}}},
        {"name": "vout", "reads": {"daq": SHUNT}},
    ],
    "timing": {"settle_s": 0, "samples": 2, "interval_s": 0},
    "derived": {
        "pin": "vin * iin@daq",
        "pout": "vout@daq * vout@daq / rload",
        "efficiency": "100 * pout / pin",
        "efficiency_min": "100 * vout@daq * vout@daq / rload_max / pin",
    },
}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(**changes):
    p = copy.deepcopy(BASE)
    load = p["variables"][1]["load"]
    for key, value in changes.items():
        if key == "mode":
            load["switching"]["mode"] = value
        else:
            load[key] = value
    return p


def run(registry, p, bench=None):
    bench = bench or SimResistiveBench(channel_ohms=OHMS)
    handles = {"instruments": [bench.supply, bench.meter, bench.switch]}
    runner = Runner(registry.create("resistive_efficiency", p), handles)
    runner.start()
    assert runner.join(60)
    return runner, bench, rows(runner)


def rows(runner):
    out = {}
    for e in runner.drain():
        if e.kind == "point":
            out.setdefault(e.data["table"], []).append(e.data["values"])
    return out


def errors(p, allow=True):
    return [str(x) for x in validate_params(p, allow_load=allow) if x.severity == "error"]


# ---- the parameters ---------------------------------------------------------------------------
def test_the_module_is_the_efficiency_with_its_own_extension(registry):
    info = registry.get("resistive_efficiency")
    assert info.extension == ".rfe"
    assert [(r.name, r.multiple, r.required) for r in info.roles] == [
        ("instruments", True, True),
        ("scope", False, False),  # the oscilloscope of the waveforms: optional
    ]
    assert registry.create("resistive_efficiency", BASE).validate() == []


def test_the_template_and_the_example_are_valid_but_only_for_the_resistive_type(registry):
    template = EfficiencyEditor.template(["supply"], load=True)
    assert [e for e in errors(template) if "instrument is missing" not in e and "call" not in e]
    assert errors(BASE) == []
    plain = errors(BASE, allow=False)
    assert plain and "only in the efficiency with a resistive load" in plain[0]
    assert registry.create("efficiency", BASE).validate()  # an .eff file cannot have a load


def test_the_axis_is_the_nominal_resistance_of_each_load():
    spec = parse_params(BASE, allow_load=True)
    assert [name for name, _ in spec.axes] == ["vin", "rload"]
    assert spec.axes[1][1] == [10.0, pytest.approx(22 * 47 / 69)]
    assert spec.point_count() == 4


@pytest.mark.parametrize(
    "changes,text",
    [
        ({"loads": []}, "load"),
        (
            {"loads": [{"r_ohm": 10, "channel": "1"}, {"r_ohm": 10, "channel": "2"}]},
            "same resistance",
        ),
        ({"mode": "mux", "switching": None}, ""),
        ({"vout": "nothing@daq"}, "no reading"),
        ({"max_vout_v": 10}, "of its rating"),
        ({"loads": [{"kit": "", "ref": "R1"}]}, "names the kit"),
    ],
)
def test_the_load_is_checked_before_the_run(changes, text):
    p = params(**{k: v for k, v in changes.items() if v is not None})
    if changes.get("switching", 0) is None:
        del p["variables"][1]["load"]["switching"]["instrument"]
    found = errors(p)
    assert found and all(text in e for e in found[:1] if text), found


def test_the_multiplexer_needs_a_channel_for_every_resistor():
    loads = [{"r_ohm": 10, "channel": "201"}, {"r_ohm": 22}]
    found = errors(params(loads=loads))
    assert any("needs a channel" in e for e in found)
    assert errors(params(loads=loads, mode="manual")) == []


def test_the_extra_names_are_known_to_the_formulas():
    p = params()
    p["derived"]["x"] = "rload_nothing"
    assert any("unknown name 'rload_nothing'" in e for e in errors(p))


# ---- whole runs -------------------------------------------------------------------------------
def test_a_run_on_the_multiplexer_has_the_points_of_the_efficiency(registry):
    runner, bench, tables = run(registry, params())
    assert runner.state is RunState.FINISHED
    points = tables["points"]
    assert len(points) == 4 and len(tables["samples"]) == 8
    for row in points:
        assert row["rload"] in (10.0, pytest.approx(22 * 47 / 69))
        assert row["rload_min"] < row["rload"] < row["rload_max"]
        assert 0 < row["efficiency_min"] < row["efficiency"] < 100
    assert bench.events[-3:] == ["supply off", "open 202", "open 203"]  # off, then the relays


def test_the_converter_is_off_while_the_load_changes(registry):
    runner, bench, _ = run(registry, params())
    events = bench.events
    first_close = events.index("close 201")
    assert events.index("supply on") > first_close  # the relays close before the first power-on
    second = events.index("close 202")
    assert "supply off" in events[first_close:second]  # off before the load changes
    assert "open 201" in events[first_close:second]
    assert events[-1].startswith("open") and "supply off" in events[-3:]  # the end: off, then open


def test_by_hand_the_program_asks_for_each_load_with_a_drawing(registry):
    bench = SimResistiveBench(channel_ohms=OHMS)
    p = params(mode="manual")
    handles = {"instruments": [bench.supply, bench.meter, bench.switch]}
    runner = Runner(registry.create("resistive_efficiency", p), handles)
    asked = []

    def operator():
        deadline = time.time() + 30
        while time.time() < deadline and runner.state not in (RunState.FINISHED, RunState.FAILED):
            for q in list(runner.pending_questions):
                data = q["data"]
                asked.append((data["load"], data["r_ohm"], "svg" in data))
                bench.manual_ohms = data["r_ohm"]
                runner.answer(q["id"], "continue")
            time.sleep(0.01)

    thread = threading.Thread(target=operator)
    thread.start()
    runner.start()
    assert runner.join(60)
    thread.join()
    assert [a[0] for a in asked] == ["10R", "22||47"] and all(a[2] for a in asked)
    assert runner.state is RunState.FINISHED


def test_a_resistor_above_its_rating_stops_the_run_and_switches_off(registry):
    loads = [{"name": "tiny", "r_ohm": 10, "power_w": 0.5, "channel": "201"}]
    p = params(loads=loads, max_vout_v=None)
    del p["variables"][1]["load"]["max_vout_v"]
    runner, bench, _ = run(registry, p)
    assert runner.state is RunState.FAILED
    assert "dissipates" in str(runner.error) and "tiny" in str(runner.error)
    assert bench.events[-2:] == ["supply off", "open 201"]


def test_a_converter_with_two_outputs_has_a_load_for_each(registry):
    p = params(mode="manual")
    second = {
        "name": "rload2",
        "load": {
            "loads": [{"name": "4R7", "r_ohm": 4.7, "power_w": 20}],
            "switching": {"mode": "manual"},
            "vout": "vout@daq",
        },
    }
    p["variables"].insert(2, second)
    assert errors(p) == []
    bench = SimResistiveBench(channel_ohms=OHMS)
    handles = {"instruments": [bench.supply, bench.meter, bench.switch]}
    runner = Runner(registry.create("resistive_efficiency", p), handles)
    asked = []

    def operator():
        while runner.state not in (RunState.FINISHED, RunState.FAILED):
            for q in list(runner.pending_questions):
                asked.append((q["data"]["parameter"], q["data"]["load"]))
                bench.manual_ohms = q["data"]["r_ohm"]
                runner.answer(q["id"], "continue")
            time.sleep(0.005)

    thread = threading.Thread(target=operator)
    thread.start()
    runner.start()
    assert runner.join(60)
    thread.join()
    assert runner.state is RunState.FINISHED
    # the second load is asked once, at the start; the first changes with its own sweep
    assert asked == [("rload", "10R"), ("rload2", "4R7"), ("rload", "22||47")]
    points = rows(runner).get("points", [])
    assert not points or all("rload2" in row for row in points)


def open_params(mode):
    """The example with the open output as the first load (0 A), by hand or by relays."""
    p = params(mode=mode)
    p["variables"][1]["load"]["loads"].insert(0, {"name": "0 A", "open": True})
    return p


def test_the_open_output_is_a_point_of_the_sweep(registry):
    assert errors(open_params("mux")) == []
    runner, bench, tables = run(registry, open_params("mux"))
    assert runner.state is RunState.FINISHED
    points = tables["points"]
    assert len(points) == 6  # (open, 10R, 22||47) at two input voltages
    open_rows = [r for r in points if r["rload"] == float("inf")]
    assert len(open_rows) == 2 and all(r["pout"] == 0 for r in open_rows)
    assert all(r["rload_min"] == r["rload_max"] == float("inf") for r in open_rows)
    # no load: nothing closed for it, the relays that were closed before are open, supply off first
    events = bench.events
    assert events.index("supply on") < events.index("close 201")  # the open point comes first
    assert events[-3:] == ["supply off", "open 202", "open 203"]


def test_by_hand_the_open_output_is_asked_as_nothing_to_connect(registry):
    bench = SimResistiveBench(channel_ohms=OHMS)
    handles = {"instruments": [bench.supply, bench.meter, bench.switch]}
    runner = Runner(registry.create("resistive_efficiency", open_params("manual")), handles)
    asked = []

    def operator():
        while runner.state not in (RunState.FINISHED, RunState.FAILED):
            for q in list(runner.pending_questions):
                asked.append((q["data"]["load"], q["data"]["open"], q["data"]["r_ohm"], q["text"]))
                bench.manual_ohms = q["data"]["r_ohm"]  # None: nothing connected
                runner.answer(q["id"], "continue")
            time.sleep(0.005)

    thread = threading.Thread(target=operator)
    thread.start()
    runner.start()
    assert runner.join(60)
    thread.join()
    assert runner.state is RunState.FINISHED
    assert asked[0][:3] == ("0 A", True, None) and asked[0][3].startswith("Disconnect")
    assert [a[0] for a in asked] == ["0 A", "10R", "22||47"]


# ---- learning: a quick sweep, then the loads are planned again from the voltage found ----------
KIT_OHMS = (12, 10, 5, 2, 1, 12, 5)
KIT = [
    {"name": f"R{i}", "r_ohm": v, "power_w": 100, "channel": "", "kit": "PWR", "ref": f"R{i}"}
    for i, v in enumerate(KIT_OHMS)
]


def learning_params(**plan):
    """A converter that is not regulated (12 V from 24 V), loads from the kit, with learning."""
    p = params(mode="manual")
    p["variables"][0]["sweep"] = {"values": [24]}
    load = p["variables"][1]["load"]
    load["vout"] = "vout@daq"
    load.pop("max_vout_v", None)
    load["loads"] = [{"name": "placeholder", "r_ohm": 10, "power_w": 100}]
    load["plan"] = {
        "kit": "PWR", "kind": "unregulated", "ratio": 0.5, "vin_v": 24, "vin_param": "vin",
        "i_min": 0, "i_max": 6, "points": 7, "margin_pct": 100, "learn": True, "learn_points": 4,
        "resistors": KIT, **plan,
    }  # fmt: skip
    return p


def run_learning(registry, p, answer="continue", bench=None):
    bench = bench or SimResistiveBench(channel_ohms=OHMS, vout_v=12.0, pmax_w=30.0, dropout_v=6.0)
    handles = {"instruments": [bench.supply, bench.meter, bench.switch]}
    runner = Runner(registry.create("resistive_efficiency", p), handles)
    plans = []

    def operator():
        while runner.state not in (RunState.FINISHED, RunState.FAILED, RunState.STOPPED):
            for q in list(runner.pending_questions):
                data = q["data"] or {}
                if data.get("kind") == "plan":
                    plans.append(data["rows"])
                    runner.answer(q["id"], answer)
                else:
                    bench.manual_ohms = data.get("r_ohm")  # None: open
                    runner.answer(q["id"], "continue")
            time.sleep(0.005)

    thread = threading.Thread(target=operator)
    thread.start()
    runner.start()
    assert runner.join(60)
    thread.join()
    return runner, bench, rows(runner), plans


def test_learning_is_checked_before_the_run():
    assert errors(learning_params()) == []
    assert any("vin_param" in e for e in errors(learning_params(vin_param="rload")))
    assert any("vin_param" in e for e in errors(learning_params(vin_param="nothing")))
    for bad in ({"i_max": 0}, {"points": 1}, {"ratio": 0}, {"kit": ""}, {"margin_pct": 0}):
        assert errors(learning_params(**bad)), bad


def test_the_converter_is_learned_then_the_loads_are_planned_again(registry):
    runner, bench, tables, plans = run_learning(registry, learning_params())
    assert runner.state is RunState.FINISHED
    quick = tables["learning"]
    assert [r["rload"] for r in quick][0] == float("inf")  # 0 A: the open voltage first
    assert len(quick) == 2 * 4 and all(r["vin"] == 24 for r in quick)  # two rounds of 4, 0 A in
    # the converter gives less than 12 V when loaded (pmax 30 W): the curve was measured
    assert quick[0]["vout@daq"] == pytest.approx(12.0) and min(r["vout@daq"] for r in quick) < 11
    final = plans[0]
    assert len(final) == 7 and final[0]["combination"] == "open"
    assert final[0]["vout_v"] == pytest.approx(12.0)
    assert final[-1]["vout_v"] < final[1]["vout_v"]  # the voltage falls as the current rises
    for row in final[1:]:
        assert row["current_a"] == pytest.approx(row["vout_v"] / row["r_ohm"])
    assert max(error(r) for r in final[1:]) < 0.1  # the plan expects to be on target
    points = tables["points"]
    assert len(points) == 7 and points[0]["rload"] == float("inf")  # the plan is what was run
    real = [(r["vout@daq"] / r["rload"], t) for r, t in zip(points[1:], range(1, 7))]
    assert max(abs(i - t) for i, t in real) < 0.5  # and the converter really gave those currents
    assert [round(r["rload"], 6) for r in points[1:]] == [round(r["r_ohm"], 6) for r in final[1:]]
    assert tables["plan"] == final
    assert bench.events[-1].startswith("supply") or bench.events[-1] == "supply off"


def error(row):
    return abs(row["current_a"] - row["target_a"])


def test_a_second_round_reaches_the_currents_a_sagging_output_hides(registry):
    def worst(rounds):
        _r, _b, tables, _p = run_learning(registry, learning_params(learn_rounds=rounds))
        pts = tables["points"][1:]
        return max(abs(r["vout@daq"] / r["rload"] - t) for r, t in zip(pts, range(1, 7)))

    assert worst(2) < worst(1) - 0.2  # one quick sweep stops short of the top currents


def test_the_plan_can_be_refused(registry):
    runner, bench, tables, plans = run_learning(registry, learning_params(), answer="abort")
    assert runner.state is RunState.STOPPED
    assert "points" not in tables and plans
    assert bench.events[-1] == "supply off"  # stopped: the converter is switched off


def test_learning_needs_the_kit_to_be_resolved(registry):
    p = learning_params()
    del p["variables"][1]["load"]["plan"]["resistors"]
    runner, _bench, _tables, plans = run_learning(registry, p)
    assert runner.state is RunState.FAILED and "kit" in str(runner.error) and not plans
