# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Line and load regulation: parameters, the figures, safety and whole runs on a simulated bench."""

import copy
import time

import pytest

from ola.form_model import load_form_spec
from ola.modules.regulation import measurement as reg
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_bench import SimBench

BASE = {
    "device": {"label": "5 V buck", "nominal_v": 5.0},
    "output_reading": {
        "call": "measure_dc_voltage",
        "args": {"range": "AUTO", "resolution": "DEF", "channels": "103"},
    },
    "line_test": {"vin_v": {"start": 9, "stop": 15, "points": 7}, "load_a": 1.0},
    "load_test": {"i_a": {"start": 0, "stop": 2, "points": 5}, "vin_v": 12},
    "timing": {"settle_s": 0, "samples": 2, "interval_s": 0},
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
        elif key in ("device", "timing", "output_reading") and isinstance(value, dict):
            p.setdefault(key, {}).update(value)
        else:
            p[key] = value
    return p


def run(registry, p, bench=None, bind_load=True, **sim):
    bench = bench or SimBench(**sim)
    bindings = {"supply": [bench.supply], "meter": [bench.meter]}
    if bind_load:
        bindings["load"] = [bench.load]
    runner = Runner(registry.create("regulation", p), bindings)
    runner.start()
    assert runner.join(60)
    return runner, bench


def results(runner):
    evs = runner.drain()
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    points = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    summary = {
        e.data["values"]["test"]: e.data["values"]
        for e in evs
        if e.kind == "point" and e.data["table"] == "summary"
    }
    logs = [(e.data["level"], e.data["message"]) for e in evs if e.kind == "log"]
    return traces, points, summary, logs


def problems(registry, p):
    return {x.path: x.message for x in registry.create("regulation", p).check()}


# ---- the module --------------------------------------------------------------------------------
def test_the_module_is_found_with_an_editor(registry):
    info = registry.get("regulation")
    assert info.extension == ".reg" and registry.by_extension(".reg").id == "regulation"
    assert [r.name for r in info.roles] == ["supply", "load", "meter"]
    assert [r.required for r in info.roles] == [True, False, True]
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths, set(info.params_schema) - paths


def test_good_parameters_have_no_problems(registry):
    import sys

    assert problems(registry, BASE) == {}
    start = sys.modules[registry.load_class("regulation").__module__].default_params()
    assert registry.create("regulation", start).check() == []


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"device": {"nominal_v": 0}}, "device.nominal_v", "above 0"),
        ({"device": {"label": 3}}, "device.label", "text"),
        ({"device": {"asset_id": "x"}}, "device.asset_id", "not a code"),
        ({"supply_channel": 0}, "supply_channel", "from 1"),
        ({"output_reading": None}, "output_reading", "missing"),
        ({"output_reading": {"call": ""}}, "output_reading.call", "name of a call"),
        ({"output_reading": {"args": "103"}}, "output_reading.args", "object"),
        ({"output_reading": {"scale": 0}}, "output_reading.scale", "not be 0"),
        ({"output_reading": {"scale": "x"}}, "output_reading.scale", "number"),
        ({"output_reading": {"colour": 1}}, "output_reading.colour", "unknown field"),
        ({"input_reading": {"role": "load"}}, "input_reading.role", "one of"),
        ({"line_test": None, "load_test": None}, "line_test", "a line_test, a load_test"),
        ({"line_test": {"load_a": 1}}, "line_test.vin_v", "missing"),
        ({"line_test": {"vin_v": {"start": 9}}}, "line_test.vin_v", "'stop'"),
        ({"line_test": {"vin_v": {"values": [-1, 5]}}}, "line_test.vin_v", "0 or more"),
        ({"line_test": {"vin_v": {"values": [9]}, "load_a": -1}}, "line_test.load_a", "0 or more"),
        ({"line_test": {"vin_v": {"values": [9]}, "speed": 1}}, "line_test.speed", "unknown"),
        ({"load_test": {"vin_v": 12}}, "load_test.i_a", "missing"),
        ({"load_test": {"i_a": {"values": [1]}}}, "load_test.vin_v", "number"),
        ({"load_test": {"i_a": {"values": [1]}, "vin_v": 12, "x": 1}}, "load_test.x", "unknown"),
        ({"timing": {"settle_s": -1}}, "timing.settle_s", "0 or more"),
        ({"timing": {"samples": 0}}, "timing.samples", "from 1 to"),
        ({"timing": {"speed": 1}}, "timing.speed", "unknown"),
        ({"safety": {"max_vin_v": 12}}, "safety.max_vin_v", "above the limit of 12 V"),
        ({"safety": {"max_load_a": 1}}, "safety.max_load_a", "above the limit of 1 A"),
        ({"safety": {"max_vin_v": -1}}, "safety.max_vin_v", "above 0"),
        ({"limits": {"max_load": 1}}, "limits", "unknown limit"),
        ({"limits": {"max_load_pct": 0}}, "limits", "above 0"),
        ({"confirm_setup": "yes"}, "confirm_setup", "true or false"),
    ],
)
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = problems(registry, params(**changes))
    assert path in found and words in found[path], found


# ---- the figures -------------------------------------------------------------------------------
def test_fit_line():
    assert reg.fit_line([0, 1, 2], [1, 3, 5]) == pytest.approx((2.0, 1.0))
    assert reg.fit_line([3, 3, 3], [1, 2, 3])[0] == 0.0  # equal x: no slope


def test_line_figures():
    f = reg.line_figures([9, 12, 15], [4.99, 5.0, 5.01], 5.0)
    assert f["span_mv"] == pytest.approx(20) and f["line_regulation_pct"] == pytest.approx(0.4)
    assert f["line_regulation_mv_per_v"] == pytest.approx(10 / 3)
    assert f["reference_v"] == 5.0 and f["vin_min_v"] == 9 and f["vout_max_v"] == 5.01
    assert reg.line_figures([9, 15], [4.0, 6.0], None)["reference_v"] == pytest.approx(5.0)  # mean


def test_load_figures_do_not_depend_on_the_order():
    f = reg.load_figures([2.0, 0.0, 1.0], [4.92, 5.0, 4.96], None)
    assert f["v_low_load_v"] == 5.0 and f["v_high_load_v"] == 4.92 and f["reference_v"] == 4.92
    assert f["load_regulation_pct"] == pytest.approx(0.08 / 4.92 * 100)
    assert f["output_resistance_mohm"] == pytest.approx(40.0)
    assert reg.load_figures([0, 2], [5.0, 4.92], 5.0)["load_regulation_pct"] == pytest.approx(1.6)


def test_a_line_test_measures_the_line_regulation_of_the_converter(registry):
    runner, _ = run(registry, params(load_test=None), line_mv_per_v=2.0, output_mohm=0)
    assert runner.state is RunState.FINISHED, runner.error
    traces, points, summary, _ = results(runner)
    line = summary["line"]
    assert line["line_regulation_mv_per_v"] == pytest.approx(2.0, rel=0.02)
    assert line["line_regulation_pct"] == pytest.approx(0.24, rel=0.05)  # 12 mV over 5 V nominal
    assert line["points"] == 7 and line["load_a"] == 1.0 and "load" not in summary
    assert [p["test"] for p in points] == ["line"] * 7
    assert points[0]["vin_set_v"] == 9 and points[-1]["vin_set_v"] == 15
    assert traces["vout_vs_vin"]["meta"]["x_unit"] == "V" and "vout_vs_load" not in traces
    assert len(traces["vout_vs_vin"]["x"]) == 7


def test_a_load_test_measures_the_load_regulation_and_the_output_resistance(registry):
    runner, _ = run(registry, params(line_test=None), output_mohm=40.0, line_mv_per_v=0)
    assert runner.state is RunState.FINISHED, runner.error
    traces, points, summary, _ = results(runner)
    load = summary["load"]
    assert load["output_resistance_mohm"] == pytest.approx(40.0, rel=0.03)
    assert load["load_regulation_pct"] == pytest.approx(1.6, rel=0.03)  # 80 mV over 5 V
    assert load["v_low_load_v"] == pytest.approx(5.0, abs=1e-6)
    assert load["vin_v"] == 12 and load["i_min_a"] == 0 and load["i_max_a"] == 2
    assert [p["load_a"] for p in points] == [0, 0.5, 1, 1.5, 2]
    assert traces["vout_vs_load"]["meta"]["x_unit"] == "A" and "vout_vs_vin" not in traces


def test_both_tests_in_one_run_and_the_points_are_in_order(registry):
    runner, _ = run(registry, BASE)
    _, points, summary, _ = results(runner)
    assert [p["test"] for p in points] == ["line"] * 7 + ["load"] * 5
    assert set(summary) == {"line", "load"} and summary["load"]["device"] == "5 V buck"


def test_without_the_nominal_voltage_the_reference_is_the_mean_or_the_full_load_output(registry):
    p = params(device={"nominal_v": None})
    del p["device"]["nominal_v"]
    runner, _ = run(registry, p)
    _, _, summary, _ = results(runner)
    assert summary["line"]["reference_v"] == pytest.approx(4.96, abs=0.02)
    assert summary["load"]["reference_v"] == pytest.approx(summary["load"]["v_high_load_v"])


def test_the_readings_are_averaged_and_their_spread_is_reported(registry):
    runner, _ = run(registry, params(timing={"samples": 8}), noise_mv=2.0)
    _, points, _, _ = results(runner)
    assert all(p["samples"] == 8 and p["vout_spread_mv"] > 0 for p in points)
    runner, _ = run(registry, params(timing={"samples": 1}))
    assert all(p["vout_spread_mv"] == 0 for p in results(runner)[1])


def test_the_reading_is_scaled_for_a_divider(registry):
    p = params(line_test=None, output_reading={"scale": 2.0, "offset": 0.1})
    runner, _ = run(registry, p, output_mohm=0)
    _, points, _, _ = results(runner)
    assert points[0]["vout_v"] == pytest.approx(5.0 * 2.0 + 0.1, abs=0.01)


# ---- the input at the converter ----------------------------------------------------------------
def test_reading_the_input_at_the_converter_shows_the_drop_in_the_cables(registry):
    p = params(
        input_reading={"args": {"range": "AUTO", "resolution": "DEF", "channels": "101"}},
        load_test=None,
    )
    runner, bench = run(registry, p, cable_mohm=500.0)
    _, points, summary, _ = results(runner)
    assert all(pt["vin_v"] < pt["vin_set_v"] for pt in points)
    assert points[-1]["vin_drop_v"] == pytest.approx(points[-1]["vin_set_v"] - points[-1]["vin_v"])
    assert summary["line"]["max_vin_drop_v"] > 0.1
    # the slope is against the measured input, the true regulation of the converter
    assert summary["line"]["line_regulation_mv_per_v"] == pytest.approx(2.0, rel=0.02)
    assert any(
        c[:2] == ("meter", "measure_dc_voltage") and c[2]["channels"] == "101" for c in bench.log
    )


def test_without_an_input_reading_the_setpoint_is_the_input(registry):
    runner, _ = run(registry, params(load_test=None))
    _, points, summary, _ = results(runner)
    assert all(pt["vin_v"] == pt["vin_set_v"] and "vin_drop_v" not in pt for pt in points)
    assert "max_vin_drop_v" not in summary["line"]


def test_the_input_can_be_read_from_the_supply_itself(registry):
    p = params(input_reading={"role": "supply"}, load_test=None)
    runner, bench = run(registry, p)
    _, points, _, _ = results(runner)
    assert all(pt["vin_v"] == pytest.approx(pt["vin_set_v"]) for pt in points)
    assert any(c[:2] == ("supply", "read_voltage") for c in bench.log)


# ---- the verdict -------------------------------------------------------------------------------
def test_a_regulation_beyond_the_limit_is_a_result_not_an_error(registry):
    p = params(limits={"max_line_pct": 1.0, "max_load_pct": 1.0})
    runner, _ = run(registry, p)  # the load regulation is 1.6 %
    assert runner.state is RunState.FINISHED
    _, _, summary, logs = results(runner)
    assert summary["line"]["verdict"] == "PASS" and summary["load"]["verdict"] == "FAIL"
    assert any(lv == "warning" and "load test" in m and "1.6" in m for lv, m in logs)


def test_the_output_window_is_checked(registry):
    p = params(limits={"vout_min_v": 4.95, "vout_max_v": 5.05})
    runner, _ = run(registry, p)
    _, _, summary, logs = results(runner)
    assert summary["line"]["verdict"] == "PASS" and summary["load"]["verdict"] == "FAIL"
    assert any("below 4.95 V" in m for _, m in logs)
    runner, _ = run(registry, params(limits={"vout_max_v": 4.9}))
    assert results(runner)[2]["line"]["verdict"] == "FAIL"


def test_without_limits_there_is_no_verdict(registry):
    _, _, summary, _ = results(run(registry, BASE)[0])
    assert "verdict" not in summary["line"] and "verdict" not in summary["load"]


# ---- safety ------------------------------------------------------------------------------------
def test_the_load_is_at_zero_before_the_supply_is_on_and_everything_ends_off(registry):
    runner, bench = run(registry, BASE)
    order = [
        (i, c) for i, c, _ in bench.log if c in ("output_on", "output_off", "load_on", "load_off")
    ]
    assert order == [
        ("supply", "output_on"),
        ("load", "load_on"),
        ("load", "load_off"),
        ("supply", "output_off"),
    ]
    first_load = next(a for i, c, a in bench.log if (i, c) == ("load", "set_current_level"))
    assert first_load == {"value": 0.0}  # 0 A before anything is on
    levels = [a["value"] for i, c, a in bench.log if (i, c) == ("load", "set_current_level")]
    assert levels[-1] == 0.0  # and 0 A again before it is switched off
    assert not bench.supply_on and not bench.load_on
    assert bench.log[0][:2] == ("load", "set_mode") and bench.log[0][2] == {"mode": "CC"}


def test_everything_is_switched_off_also_when_the_run_fails(registry):
    class Breaks(SimBench):
        def do(self, instrument, call, args):
            if instrument == "meter" and len(self.log) > 20:
                raise RuntimeError("the cable fell out")
            return super().do(instrument, call, args)

    bench = Breaks()
    runner, _ = run(registry, BASE, bench=bench)
    assert runner.state is RunState.FAILED and "fell out" in runner.error["message"]
    assert not bench.supply_on and not bench.load_on and bench.current_a == 0.0


def test_a_point_above_the_safety_limit_is_refused_before_anything_is_switched_on(registry):
    from ola.measurement import MeasurementError

    bench = SimBench()
    with pytest.raises(MeasurementError, match="above the limit of 12 V"):
        run(registry, params(safety={"max_vin_v": 12}), bench=bench)
    assert bench.log == []


def test_a_test_that_needs_a_load_without_one_is_refused_before_anything_is_switched_on(registry):
    runner, bench = run(registry, params(line_test=None), bind_load=False)
    assert runner.state is RunState.FAILED and "electronic load" in runner.error["message"]
    assert bench.log == []


def test_a_line_test_without_load_current_needs_no_load(registry):
    p = params(load_test=None, line_test={"vin_v": {"values": [9, 12, 15]}})
    runner, bench = run(registry, p, bind_load=False)
    assert runner.state is RunState.FINISHED, runner.error
    assert not any(i == "load" for i, _, _ in bench.log)
    assert [a["value"] for i, c, a in bench.log if c == "set_voltage"][:3] == [9, 9, 12]


def test_the_output_channel_of_the_supply_is_passed(registry):
    _, bench = run(registry, params(supply_channel=2, load_test=None))
    sets = [a for i, c, a in bench.log if c == "set_voltage"]
    assert sets and all(a["channel_number"] == 2 for a in sets)


def test_the_question_is_asked_before_anything_is_switched_on(registry):
    bench = SimBench()
    runner = Runner(
        registry.create("regulation", params(confirm_setup=True)),
        {"supply": [bench.supply], "load": [bench.load], "meter": [bench.meter]},
    )
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    q = runner.pending_questions[0]
    assert "electronic load" in q["text"] and "0 A first" in q["text"] and bench.log == []
    runner.answer(q["id"], "abort")
    assert runner.join(10) and runner.state is RunState.STOPPED and bench.log == []


def test_a_reading_that_is_not_a_number_is_an_error_that_says_so(registry):
    class Text(SimBench):
        def do(self, instrument, call, args):
            return "OVER" if instrument == "meter" else super().do(instrument, call, args)

    runner, bench = run(registry, params(load_test=None), bench=Text())
    assert runner.state is RunState.FAILED and "did not return a number" in str(runner.error)
    assert not bench.supply_on


def test_the_traces_grow_with_every_point(registry):
    runner, _ = run(registry, params(load_test=None))
    evs = [e for e in runner.drain() if e.kind == "trace" and e.data["name"] == "vout_vs_vin"]
    assert [len(e.data["x"]) for e in evs] == list(range(1, 8))


# ---- the real library --------------------------------------------------------------------------
def test_the_calls_exist_for_the_supplies_loads_and_data_loggers_of_the_library(registry):
    """The logical calls the module sends must be translated for real models."""
    import os

    from ola.call_planner import plan_call
    from ola.library import Library

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "Instruments_LIB", "instruments_lib.json")
    if not os.path.isfile(path):
        pytest.skip("library not available")
    lib = Library.load(path)
    runner, bench = run(registry, params(supply_channel=1))
    assert runner.state is RunState.FINISHED, runner.error
    seen = {}
    for who, name, args in bench.log:
        seen.setdefault((who, name), args)
    models = {
        "supply": ["PSU_Keysight_E36311A", "PSU_OWON_ODP3033"],
        "load": ["EL_Chroma_6330A", "EL_Keysight_EL4913A", "EL_Siglent_SDL1030X_E"],
        "meter": ["DL_Keysight_34972A", "DL_Keysight_DAQ970A"],
    }
    for (who, name), args in seen.items():
        for model in models[who]:
            assert plan_call(lib, model, name, args).steps, (model, name)
    # a multimeter has no channels and wants numbers, not keywords
    meter = {"range": 10, "resolution": 0.001}
    assert plan_call(lib, "MTR_Agilent_34401A", "measure_dc_voltage", meter).steps
    with pytest.raises(Exception, match="needs argument 'range'"):  # the call says what is missing
        plan_call(lib, "DL_Keysight_34972A", "measure_dc_voltage", {"channels": "103"})
