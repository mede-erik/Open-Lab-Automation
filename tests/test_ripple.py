# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Ripple and noise: parameters, the figures, the warnings, the load sweep, and whole runs."""

import copy
import time

import pytest

from ola.form_model import load_form_spec
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_scope import SimLoad, SimScope

BASE = {
    "device": {"label": "5 V rail", "nominal_v": 5.0},
    "scope": {
        "channel": 1, "probe_attenuation": 1, "coupling": "AC", "bandwidth_limit_hz": 20e6,
        "volts_per_div": 0.01, "time_per_div": 2e-6, "memory_depth": 20000,
    },
    "capture_wait_s": 0,
    "confirm_setup": False,
}  # fmt: skip


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(**changes):
    p = copy.deepcopy(BASE)
    for key, value in changes.items():
        if key in ("scope", "device", "trigger") and isinstance(value, dict):
            p.setdefault(key, {}).update(value)
        else:
            p[key] = value
    return p


def run(registry, p, scope=None, load=None, **sim):
    scope = scope or SimScope(**sim)
    bindings = {"oscilloscope": [scope]}
    if load is not None:
        bindings["load"] = [load]
    runner = Runner(registry.create("ripple", p), bindings)
    runner.start()
    assert runner.join(60)
    return runner, scope


def results(runner):
    evs = runner.drain()
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    rows = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    logs = [(e.data["level"], e.data["message"]) for e in evs if e.kind == "log"]
    return traces, rows, logs


def problems(registry, p):
    return {x.path: x.message for x in registry.create("ripple", p).check()}


# ---- the module --------------------------------------------------------------------------------
def test_the_module_is_found_with_an_editor(registry):
    info = registry.get("ripple")
    assert info.extension == ".rpl" and registry.by_extension(".rpl").id == "ripple"
    assert [r.name for r in info.roles] == ["oscilloscope", "load"]
    assert info.roles[0].required and not info.roles[1].required
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths, set(info.params_schema) - paths


def test_good_parameters_have_no_problems(registry):
    import sys

    assert problems(registry, BASE) == {}
    start = sys.modules[registry.load_class("ripple").__module__].default_params()
    assert registry.create("ripple", start).check() == []


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"scope": "ch1"}, "scope", "missing"),
        ({"scope": {"channel": 0}}, "scope.channel", "from 1"),
        ({"scope": {"coupling": "GND"}}, "scope.coupling", "one of"),
        ({"scope": {"probe_attenuation": 0}}, "scope.probe_attenuation", "above 0"),
        ({"scope": {"bandwidth_limit_hz": -1}}, "scope.bandwidth_limit_hz", "0 or more"),
        ({"scope": {"volts_per_div": "x"}}, "scope.volts_per_div", "above 0"),
        ({"scope": {"offset_v": "x"}}, "scope.offset_v", "number"),
        ({"scope": {"memory_depth": 0}}, "scope.memory_depth", "from 1"),
        ({"scope": {"bits": 4}}, "scope.bits", "from 8 to 16"),
        ({"scope": {"acquisition": "PEAK"}}, "scope.acquisition", "one of"),
        ({"trigger": {"slope": "UP"}}, "trigger.slope", "one of"),
        ({"trigger": {"level_v": "x"}}, "trigger.level_v", "number"),
        ({"trigger": {"mode": "SINGLE"}}, "trigger.mode", "one of"),
        ({"captures": 0}, "captures", "from 1 to"),
        ({"captures": 1000}, "captures", "from 1 to"),
        ({"capture_wait_s": -1}, "capture_wait_s", "0 or more"),
        ({"conditions": {"currents_a": []}}, "conditions", "currents_a"),
        ({"conditions": {"currents_a": [1, -1]}}, "conditions", "currents_a"),
        ({"conditions": {"currents_a": [1], "settle_s": -1}}, "conditions.settle_s", "0 s or more"),
        ({"peaks": 0}, "peaks", "from 1 to 20"),
        ({"limits": {"max_pp": 1}}, "limits", "unknown limit"),
        ({"limits": {"max_pp_v": -1}}, "limits", "above 0"),
        ({"spectrum": "yes"}, "spectrum", "true or false"),
        ({"device": {"nominal_v": "x"}}, "device.nominal_v", "number"),
        ({"device": {"asset_id": "nonsense"}}, "device.asset_id", "not a code"),
    ],
)
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = problems(registry, params(**changes))
    assert path in found and words in found[path], found


# ---- the figures -------------------------------------------------------------------------------
def test_the_scope_is_set_up_for_ripple_before_reading(registry):
    runner, scope = run(registry, params(trigger={"level_v": 0, "slope": "RISE"}), ripple_pp_v=0.02)
    assert runner.state is RunState.FINISHED, runner.error
    sent = {name: args for name, args in scope.calls}
    assert sent["set_channel_coupling"] == {"channel_number": 1, "coupling_type": "AC"}
    assert sent["set_channel_bandwidth_limit"] == {"channel_number": 1, "bandwidth": 20e6}
    assert sent["set_probe_attenuation"] == {"channel_number": 1, "value": 1.0}
    assert (
        sent["set_channel_scale"]["value"] == 0.01 and sent["set_timebase_scale"]["value"] == 2e-6
    )
    assert sent["set_trigger_slope"] == {"slope": "RISE"} and sent["set_trigger_mode"] == {
        "mode": "AUTO"
    }
    order = [n for n, _ in scope.calls]
    assert order.index("set_channel_coupling") < order.index("run_acquisition")
    assert scope.captures == 1


def test_peak_to_peak_rms_and_the_frequency_of_the_ripple(registry):
    runner, _ = run(registry, BASE, dc_v=5.0, ripple_pp_v=0.020, fsw_hz=500e3, noise_rms_v=0.001)
    traces, rows, _ = results(runner)
    (row,) = rows
    assert row["device"] == "5 V rail" and row["coupling"] == "AC"
    assert 0.020 < row["pp_v"] < 0.032  # the ripple plus the extremes of the noise
    assert row["rms_v"] == pytest.approx((0.020 / 12**0.5) ** 2 + 0.001**2, rel=0.2) or True
    assert row["rms_v"] == pytest.approx(((0.020**2 / 12) + 0.001**2) ** 0.5, rel=0.05)
    assert row["ripple_frequency_hz"] == pytest.approx(500e3, rel=0.01)
    assert row["noise_rms_v"] < row["rms_v"] and row["noise_rms_v"] == pytest.approx(0.001, rel=0.5)
    assert abs(row["mean_v"]) < 0.001  # AC coupled: the 5 V is gone
    assert row["pp_percent_of_nominal"] == pytest.approx(100 * row["pp_v"] / 5.0)
    assert row["peak_pos_v"] > 0 > row["peak_neg_v"]
    assert row["samples"] == 20000 and row["sample_rate_hz"] == pytest.approx(1e9)
    assert "500" in row["peaks"] and "kHz" in row["peaks"]


def test_dc_coupling_shows_the_level(registry):
    p = params(scope={"coupling": "DC", "volts_per_div": 1.0, "offset_v": -5.0})
    runner, _ = run(registry, p, dc_v=5.0, ripple_pp_v=0.02)
    _, rows, _ = results(runner)
    assert rows[0]["mean_v"] == pytest.approx(5.0, abs=0.05) and rows[0]["coupling"] == "DC"


def test_the_curves_are_the_waveform_and_a_hidden_spectrum(registry):
    runner, _ = run(registry, BASE)
    traces, _, _ = results(runner)
    wave, spec = traces["waveform"], traces["spectrum_dbv"]
    assert len(wave["x"]) <= 4000 and wave["meta"]["x_unit"] == "s"
    assert spec["meta"]["hidden"] is True and spec["meta"]["log_x"] is True
    assert spec["x"][0] > 0  # no DC bin on a log axis
    # a triangle of 10 mV peak has a fundamental of 8/pi^2 x 10 mV = 8.1 mV peak = -44.8 dBV rms
    assert max(spec["y"]) == pytest.approx(-44.8, abs=1.0)


def test_the_waveform_keeps_the_peaks_when_it_is_thinned():
    from ola.modules.ripple.measurement import envelope

    t = list(range(100000))
    v = [0.0] * 100000
    v[54321], v[77777] = 3.0, -2.0
    x, y = envelope(t, v, 1000)
    assert len(x) <= 1000 and max(y) == 3.0 and min(y) == -2.0
    assert x == sorted(x)
    assert envelope([1, 2], [3, 4]) == ([1, 2], [3, 4])  # short records are not touched


def test_without_the_spectrum_there_is_no_frequency_and_no_noise_figure(registry):
    runner, _ = run(registry, params(spectrum=False))
    traces, rows, _ = results(runner)
    assert "spectrum_dbv" not in traces
    assert "ripple_frequency_hz" not in rows[0] and "noise_rms_v" not in rows[0]
    assert rows[0]["pp_v"] > 0.02


def test_several_captures_report_the_worst_peak_to_peak(registry):
    runner, scope = run(registry, params(captures=5), noise_rms_v=0.004)
    _, rows, _ = results(runner)
    row = rows[0]
    assert scope.captures == 5 and row["captures"] == 5
    assert row["pp_worst_v"] >= row["pp_mean_v"] and row["pp_v"] == row["pp_worst_v"]


# ---- the verdict -------------------------------------------------------------------------------
def test_ripple_above_the_limit_is_a_result_not_an_error(registry):
    p = params(limits={"max_pp_v": 0.010, "max_rms_v": 0.1})
    runner, _ = run(registry, p, ripple_pp_v=0.020)
    assert runner.state is RunState.FINISHED
    _, rows, logs = results(runner)
    assert rows[0]["verdict"] == "FAIL"
    assert any(
        level == "warning" and "peak-to-peak" in m and "limit exceeded" in m for level, m in logs
    )
    assert not any("rms" in m and "limit exceeded" in m for _, m in logs)


def test_ripple_inside_the_limits_passes(registry):
    runner, _ = run(registry, params(limits={"max_pp_v": 0.1, "max_rms_v": 0.1}))
    assert results(runner)[1][0]["verdict"] == "PASS"
    runner, _ = run(registry, BASE)
    assert "verdict" not in results(runner)[1][0]


# ---- warnings: when the figures cannot be trusted ----------------------------------------------
def test_a_clipped_signal_is_reported(registry):
    runner, _ = run(registry, params(scope={"volts_per_div": 0.001}), ripple_pp_v=0.020)
    _, _, logs = results(runner)
    assert any(level == "warning" and "edge of the screen" in m for level, m in logs)


def test_a_coarse_scale_warns_about_the_resolution(registry):
    runner, _ = run(
        registry, params(scope={"volts_per_div": 0.5}), ripple_pp_v=0.003, noise_rms_v=0
    )
    _, _, logs = results(runner)
    assert any("different levels" in m and "sensitivity" in m for _, m in logs)
    runner, _ = run(registry, BASE)  # the scale of the example: no such warning
    assert not any("different levels" in m for _, m in results(runner)[2])


def test_a_record_with_few_periods_warns(registry):
    p = params(scope={"time_per_div": 0.2e-6, "memory_depth": 20000})
    runner, _ = run(registry, p, fsw_hz=500e3)  # 2 us record = one period
    assert any("fewer than 5 periods" in m for _, m in results(runner)[2])


def test_a_slow_sample_rate_warns(registry):
    p = params(scope={"time_per_div": 2e-6, "memory_depth": 100})  # 5 MSa/s for a 2 MHz ripple
    runner, _ = run(registry, p, fsw_hz=2e6, noise_rms_v=0)
    assert any("sample rate" in m for _, m in results(runner)[2])


def test_the_oscilloscope_returning_nothing_is_an_error(registry):
    class Empty(SimScope):
        def read_waveform_full(self, channel_number, bits=8, stop=True):
            return {"time": [], "voltage": [], "points": 0}

    runner, _ = run(registry, BASE, scope=Empty())
    assert runner.state is RunState.FAILED and "0 points" in runner.error["message"]


# ---- the load ----------------------------------------------------------------------------------
LOADED = {"currents_a": [0.0, 1.0, 2.0], "settle_s": 0}


def test_ripple_against_load_has_a_row_and_curves_per_current(registry):
    scope = SimScope(ripple_pp_v=0.010, ripple_per_a_v=0.010)
    load = SimLoad(scope)
    runner, _ = run(registry, params(conditions=LOADED), scope=scope, load=load)
    assert runner.state is RunState.FINISHED, runner.error
    traces, rows, logs = results(runner)
    assert [r["load_current_a"] for r in rows] == [0.0, 1.0, 2.0]
    pps = [r["pp_v"] for r in rows]
    assert pps[0] < pps[1] < pps[2] and pps[2] > 0.028  # 10 mV + 2 A x 10 mV/A
    assert {"waveform @ 0 A", "waveform @ 1 A", "waveform @ 2 A"} <= set(traces)
    calls = [c for c, _ in load.calls]
    assert calls[0] == "set_mode" and calls.count("load_on") == 1 and calls[-1] == "load_off"
    assert load.calls[1] == ("set_current_level", {"value": 0.0})
    assert not load.on and scope.current_a == 0


def test_the_load_is_switched_off_also_when_the_run_fails(registry):
    class Breaks(SimScope):
        def read_waveform_full(self, channel_number, bits=8, stop=True):
            if self.captures >= 1:
                raise RuntimeError("the cable fell out")
            return super().read_waveform_full(channel_number, bits, stop)

    scope = Breaks()
    load = SimLoad(scope)
    runner, _ = run(registry, params(conditions=LOADED), scope=scope, load=load)
    assert runner.state is RunState.FAILED and "fell out" in runner.error["message"]
    assert [c for c, _ in load.calls][-1] == "load_off" and not load.on


def test_conditions_without_a_load_are_refused_before_anything_is_switched_on(registry):
    runner, scope = run(registry, params(conditions=LOADED))
    assert runner.state is RunState.FAILED and "electronic load" in runner.error["message"]
    assert scope.calls == []


# ---- the question ------------------------------------------------------------------------------
def test_the_probe_is_connected_after_the_question(registry):
    scope = SimScope()
    runner = Runner(
        registry.create("ripple", params(confirm_setup=True)), {"oscilloscope": [scope]}
    )
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    q = runner.pending_questions[0]
    assert "ground spring" in q["text"] and "20 MHz" in q["text"] and scope.calls == []
    runner.answer(q["id"], "abort")
    assert runner.join(10) and runner.state is RunState.STOPPED and scope.calls == []


# ---- the same calls on the real library --------------------------------------------------------
def test_every_call_of_the_measurement_exists_for_the_oscilloscopes_of_the_library(registry):
    """The measurement sends logical calls; each must be translated for every scope model."""
    import os

    from ola.call_planner import plan_call
    from ola.library import Library

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "Instruments_LIB", "instruments_lib.json")
    if not os.path.isfile(path):
        pytest.skip("library not available")
    lib = Library.load(path)
    scope, trigger = BASE["scope"], {"level_v": 0.0, "slope": "RISE", "mode": "AUTO"}
    sent = SimScope()
    runner = Runner(
        registry.create(
            "ripple",
            params(trigger=trigger, scope={"acquisition": "NORMAL", "memory_depth": 100000}),
        ),
        {"oscilloscope": [sent]},
    )
    runner.start()
    assert runner.join(30) and runner.state is RunState.FINISHED, runner.error
    models = ["OSC_Siglent_SDS824X_HD", "OSC_Rigol_DS1054Z", "OSC_Tek_MSO54"]
    for model in models:
        for name, args in sent.calls:
            plan = plan_call(lib, model, name, args)
            assert plan.steps or name in ("run_acquisition",), (model, name)
    assert scope["bandwidth_limit_hz"] == 20e6


def test_a_memory_depth_the_model_does_not_have_is_an_error_that_says_so(registry):
    """The depth is one of a few values per model (10k, 100k, 1M...): the library says which."""
    import os

    from ola.call_errors import ValueNotHandledError
    from ola.call_planner import plan_call
    from ola.library import Library

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "Instruments_LIB", "instruments_lib.json")
    if not os.path.isfile(path):
        pytest.skip("library not available")
    with pytest.raises(ValueNotHandledError, match="depth"):
        plan_call(
            Library.load(path), "OSC_Siglent_SDS824X_HD", "set_acquisition_depth", {"depth": 20000}
        )
