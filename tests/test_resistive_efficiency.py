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
    assert [(r.name, r.multiple) for r in info.roles] == [("instruments", True)]
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
