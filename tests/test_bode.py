# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Bode plot: parameters, the maths, and whole runs on a simulated generator, scope and circuit."""

import cmath
import copy
import math
import os
import time

import pytest

from ola.form_model import load_form_spec
from ola.modules.bode import measurement as bode
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_bode import SimBodeLab, delay, integrator_with_pole, second_order

BASE = {
    "sweep": {"start_hz": 100, "stop_hz": 1e6, "points": 21, "scale": "log"},
    "source": {"channel": 1, "amplitude_vpp": 0.1},
    "scope": {"input_channel": 1, "output_channel": 2, "coupling": "DC"},
    "settle_s": 0,
    "capture_wait_s": 0,
    "confirm_setup": False,
}


def lowpass(fc=1e3, gain=1.0):
    return lambda f: gain / (1 + 1j * f / fc)


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(**changes):
    p = copy.deepcopy(BASE)
    for key, value in changes.items():
        if value is None:
            p.pop(key, None)
        elif key in ("sweep", "source", "scope") and isinstance(value, dict):
            p[key].update(value)
        else:
            p[key] = value
    return p


def run(registry, p, lab=None, **lab_kw):
    lab = lab or SimBodeLab(**lab_kw)
    runner = Runner(
        registry.create("bode", p), {"generator": [lab.generator], "oscilloscope": [lab.scope]}
    )
    runner.start()
    assert runner.join(120)
    return runner, lab


def results(runner):
    evs = runner.drain()
    traces = {}
    growth = []
    for e in evs:
        if e.kind == "trace":
            traces[e.data["name"]] = e.data
            if e.data["name"] == "H":
                growth.append(len(e.data["x"]))
    rows = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    sweep = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "sweep"]
    logs = [(e.data["level"], e.data["message"]) for e in evs if e.kind == "log"]
    return traces, (rows[0] if rows else None), sweep, logs, growth


def problems(registry, p):
    return {x.path: (x.message, x.severity) for x in registry.create("bode", p).check()}


# ---- the module --------------------------------------------------------------------------------
def test_the_module_is_found_with_an_editor(registry):
    info = registry.get("bode")
    assert info.extension == ".bod" and registry.by_extension(".bod").id == "bode"
    assert [r.name for r in info.roles] == ["generator", "oscilloscope"]
    assert all(r.required for r in info.roles)
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths, set(info.params_schema) - paths


def test_good_parameters_have_no_problems(registry):
    import sys

    assert problems(registry, BASE) == {}
    start = sys.modules[registry.load_class("bode").__module__].default_params()
    found = registry.create("bode", start).check()
    assert [p for p in found if p.severity == "error"] == []


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"sweep": {"stop_hz": 50}}, "sweep.stop_hz", "above the start"),
        ({"sweep": {"points": 5000}}, "sweep.points", "at most"),
        ({"source": "g"}, "source", "missing"),
        ({"source": {"amplitude_vpp": 0}}, "source.amplitude_vpp", "above 0"),
        ({"source": {"channel": 0}}, "source.channel", "from 1"),
        ({"source": {"offset_v": "x"}}, "source.offset_v", "number"),
        ({"scope": "s"}, "scope", "missing"),
        ({"scope": {"output_channel": 1}}, "scope.output_channel", "another channel"),
        ({"scope": {"coupling": "GND"}}, "scope.coupling", "one of"),
        ({"scope": {"probe_attenuation": 0}}, "scope.probe_attenuation", "above 0"),
        ({"scope": {"cycles": 1}}, "scope.cycles", "from 2 to"),
        ({"scope": {"memory_depth": 0}}, "scope.memory_depth", "from 1 to"),
        ({"scope": {"input_volts_per_div": -1}}, "scope.input_volts_per_div", "above 0"),
        ({"settle_s": -1}, "settle_s", "0 or more"),
        ({"averages": 0}, "averages", "from 1 to 100"),
        ({"phase_offset_deg": "x"}, "phase_offset_deg", "degrees"),
        ({"loop": "yes"}, "loop", "true or false"),
        ({"limits": {"min_phase": 45}}, "limits", "unknown limit"),
        ({"limits": {"max_peaking_db": "x"}}, "limits", "must be a number"),
        ({"safety": {"max_amplitude_vpp": 0.05}}, "safety.max_amplitude_vpp", "above the limit"),
        ({"safety": {"max_amplitude_vpp": -1}}, "safety.max_amplitude_vpp", "above 0"),
        ({"safety": {"speed": 1}}, "safety", "max_amplitude_vpp"),
        ({"device": {"asset_id": "x"}}, "device.asset_id", "not a code"),
    ],
)
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = problems(registry, params(**changes))
    assert path in found and words in found[path][0] and found[path][1] == "error", found


def test_two_things_are_warned_about_not_refused(registry):
    ac = problems(registry, params(sweep={"start_hz": 10}, scope={"coupling": "AC"}))
    assert ac["scope.coupling"][1] == "warning" and "phase lead" in ac["scope.coupling"][0]
    assert "scope.coupling" not in problems(registry, params(sweep={"start_hz": 10}))  # DC: fine
    margins = problems(registry, params(limits={"min_phase_margin_deg": 45}))
    assert margins["limits"][1] == "warning" and "'loop': true" in margins["limits"][0]
    assert "limits" not in problems(
        registry, params(limits={"min_phase_margin_deg": 45}, loop=True)
    )


# ---- the helpers -------------------------------------------------------------------------------
def test_snap_up_and_wrap():
    assert [bode.snap_up(v) for v in (0.0011, 0.002, 0.003, 0.05, 0.051, 1.0, 7.0)] == [
        0.002, 0.002, 0.005, 0.05, 0.1, 1.0, 10.0,
    ]  # fmt: skip
    assert bode.snap_up(0) == 1e-3
    assert [bode.wrap_deg(a) for a in (190, -190, 540, 0, 180, -180)] == [
        -170,
        170,
        180,
        0,
        180,
        -180,
    ]


def test_the_phase_is_made_continuous():
    wrapped = [-170.0, -176.0, 178.0, 171.0, 160.0, -179.0, 170.0]
    out = bode.unwrap_deg(wrapped)
    assert out == pytest.approx([-170, -176, -182, -189, -200, -179, -190])
    assert all(abs(b - a) < 180 for a, b in zip(out, out[1:]))
    assert bode.unwrap_deg([170, -170], start_deg=0) == [170, 190]
    assert bode.unwrap_deg([10], start_deg=-360)[0] == pytest.approx(
        -350
    )  # the branch near the start
    assert bode.unwrap_deg([]) == []


def test_crossings_are_interpolated_in_the_logarithm_of_the_frequency():
    freq = [10 ** (k / 4) for k in range(0, 21)]
    gain = [-20 * math.log10(f / 100) for f in freq]  # -20 dB/decade through 0 dB at 100 Hz
    found = bode.crossings_log(freq, gain, 0.0)
    assert found == [(pytest.approx(100.0, rel=1e-9), "falling")]
    assert bode.crossings_log(freq, gain, -20.0)[0][0] == pytest.approx(1000.0, rel=1e-9)
    assert bode.crossings_log(freq, gain, 1e9) == []


def test_the_figures_of_a_first_order_low_pass():
    freq = [10 ** (k / 10) for k in range(10, 71)]
    h = [1 / (1 + 1j * f / 1000) for f in freq]
    gain = [20 * math.log10(abs(v)) for v in h]
    phase = [math.degrees(cmath.phase(v)) for v in h]
    f = bode.figures(freq, gain, phase, loop=False)
    assert f["bandwidth_3db_hz"] == pytest.approx(1000, rel=0.01) and f["peaking_db"] == 0
    assert f["dc_gain_db"] == pytest.approx(0, abs=0.01) and "crossover_hz" not in f
    assert f["points"] == len(freq) and f["start_hz"] == 10 and f["stop_hz"] == pytest.approx(1e7)


def test_the_margins_of_a_loop():
    freq = [10 ** (k / 20) for k in range(40, 121)]  # 100 Hz to 1 MHz
    plant = integrator_with_pole(2e4, 2e5)
    h = [plant(f) for f in freq]
    gain = [20 * math.log10(abs(v)) for v in h]
    phase = bode.unwrap_deg([math.degrees(cmath.phase(v)) for v in h])
    f = bode.figures(freq, gain, phase, loop=True)
    assert f["crossover_hz"] == pytest.approx(2e4, rel=0.01)
    assert f["phase_margin_deg"] == pytest.approx(180 - 90 - math.degrees(math.atan(0.1)), abs=0.5)
    assert "phase_crossover_hz" not in f  # a first-order loop never reaches -180


def test_a_loop_with_a_delay_has_a_gain_margin():
    plant = integrator_with_pole(2e4, 1e7)
    lag = delay(8e-6)
    freq = [10 ** (k / 20) for k in range(40, 121)]
    h = [plant(f) * lag(f) for f in freq]
    gain = [20 * math.log10(abs(v)) for v in h]
    phase = bode.unwrap_deg([math.degrees(cmath.phase(v)) for v in h])
    f = bode.figures(freq, gain, phase, loop=True)
    # the phase is -90 - 360 f tau: -180 at 1 / (4 tau) = 31.25 kHz, where the gain is 20k/31.25k
    assert f["phase_crossover_hz"] == pytest.approx(1 / (4 * 8e-6), rel=0.01)
    assert f["gain_margin_db"] == pytest.approx(-20 * math.log10(2e4 / 31250), rel=0.02)
    assert f["phase_margin_deg"] == pytest.approx(180 - 90 - 360 * 2e4 * 8e-6, abs=1.0)


def test_the_verdict_names_what_failed_and_what_was_never_found():
    summary = {"phase_margin_deg": 40.0, "gain_margin_db": 12.0, "peaking_db": 4.0}
    verdict, reasons = bode.verdict(
        summary, {"min_phase_margin_deg": 45, "min_gain_margin_db": 6, "max_peaking_db": 3}
    )
    assert verdict == "FAIL" and len(reasons) == 2
    assert any("phase margin" in r and "below 45" in r for r in reasons)
    assert any("peaking" in r and "above 3" in r for r in reasons)
    assert bode.verdict(summary, {"min_gain_margin_db": 6}) == ("PASS", [])
    missing = bode.verdict({"peaking_db": 0.0}, {"min_bandwidth_hz": 1000})
    assert missing[0] == "FAIL" and "no bandwidth was found" in missing[1][0]
    assert bode.verdict({}, {}) == ("PASS", [])


# ---- whole runs --------------------------------------------------------------------------------
def test_a_first_order_low_pass_is_measured_at_every_frequency(registry):
    runner, lab = run(registry, BASE, plant=lowpass(1e3), noise_v=0.0002)
    assert runner.state is RunState.FINISHED, runner.error
    traces, row, sweep, logs, growth = results(runner)
    assert len(sweep) == 21 and growth == list(range(1, 22))  # the curve grows with every point
    for r in sweep:
        h = lowpass(1e3)(r["frequency_hz"])
        assert r["gain_db"] == pytest.approx(20 * math.log10(abs(h)), abs=0.5), r["frequency_hz"]
        if r["frequency_hz"] <= 1e5:  # above that the signal is under the noise: the phase is loose
            assert r["phase_deg"] == pytest.approx(math.degrees(cmath.phase(h)), abs=1.5)
    assert row["bandwidth_3db_hz"] == pytest.approx(1e3, rel=0.05) and row["peaking_db"] < 0.2
    assert row["dc_gain_db"] == pytest.approx(0, abs=0.1) and "phase_margin_deg" not in row
    assert traces["H"]["trace_kind"] == "complex" and traces["H"]["meta"]["log_x"] is True
    assert "hidden" not in traces["H"]["meta"] and traces["gain_db"]["meta"]["hidden"]
    assert not lab.generator_on


def test_a_resonance_shows_the_peaking(registry):
    p = params(sweep={"start_hz": 500, "stop_hz": 5e4, "points": 81})
    runner, _ = run(registry, p, plant=second_order(dc_gain=1.0, f0_hz=5e3, q=3.0), noise_v=0.0002)
    _, row, _, _, _ = results(runner)
    assert row["peaking_db"] == pytest.approx(20 * math.log10(3.0), abs=0.6)  # the peak is about Q
    assert row["peak_at_hz"] == pytest.approx(5e3, rel=0.1)


def test_a_loop_gain_gives_the_crossover_and_the_phase_margin(registry):
    p = params(sweep={"start_hz": 100, "stop_hz": 1e6, "points": 41}, loop=True)
    runner, _ = run(registry, p, plant=integrator_with_pole(2e4, 2e5), noise_v=0.0001)
    assert runner.state is RunState.FINISHED, runner.error
    _, row, _, _, _ = results(runner)
    assert row["crossover_hz"] == pytest.approx(2e4, rel=0.03)
    assert row["phase_margin_deg"] == pytest.approx(84.3, abs=2.5)
    assert row["phase_at_crossover_deg"] == pytest.approx(-95.7, abs=2.5)


def test_a_loop_that_goes_through_minus_180_has_a_gain_margin(registry):
    p = params(sweep={"start_hz": 100, "stop_hz": 3e5, "points": 61}, loop=True)
    plant = integrator_with_pole(2e4, 1e7)
    lag = delay(8e-6)
    lab = SimBodeLab(plant=lambda f: plant(f) * lag(f), noise_v=0.0001)
    runner, _ = run(registry, p, lab=lab)
    _, row, sweep, _, _ = results(runner)
    assert row["phase_crossover_hz"] == pytest.approx(31250, rel=0.04)
    assert row["gain_margin_db"] == pytest.approx(-20 * math.log10(2e4 / 31250), abs=0.6)
    assert row["phase_margin_deg"] == pytest.approx(180 - 90 - 360 * 2e4 * 8e-6, abs=3.0)
    phases = [r["phase_deg"] for r in sweep]
    assert all(abs(b - a) < 120 for a, b in zip(phases, phases[1:]))  # continuous: no 360 jumps
    assert phases[-1] < -360  # it went round more than once


def test_the_scales_follow_an_output_that_changes_by_decades(registry):
    plant = second_order(dc_gain=100.0, f0_hz=2e3, q=0.7)  # 40 dB down to -40 dB over the sweep
    runner, lab = run(registry, params(sweep={"points": 31}), plant=plant, noise_v=0.0001)
    assert runner.state is RunState.FINISHED, runner.error
    _, row, sweep, logs, _ = results(runner)
    scales = [r["output_volts_per_div"] for r in sweep]
    assert scales[0] > scales[-1] * 20  # the vertical scale went down by decades
    assert len(set(scales)) > 5 and lab.captures < 31 * 2  # and the captures were not repeated much
    for r in sweep:
        h = plant(r["frequency_hz"])
        want = 20 * math.log10(abs(h))
        tolerance = 0.3 if want > -50 else 1.0  # far down the signal is near the noise
        assert r["gain_db"] == pytest.approx(want, abs=tolerance), r["frequency_hz"]
    assert not any("clips" in m for _, m in logs)


def test_a_lot_of_noise_is_averaged_out_by_the_fit(registry):
    p = params(sweep={"start_hz": 100, "stop_hz": 1e4, "points": 11})
    runner, _ = run(registry, p, plant=lowpass(1e3), noise_v=0.02)
    _, _, sweep, logs, _ = results(runner)  # 20 mV rms of noise against a 50 mV peak signal
    for r in sweep:
        h = lowpass(1e3)(r["frequency_hz"])
        assert r["gain_db"] == pytest.approx(20 * math.log10(abs(h)), abs=1.0), r["frequency_hz"]
    assert any("is not a sine" in m for _, m in logs)  # and it says so


def test_averages_capture_again_at_every_frequency(registry):
    runner, lab = run(registry, params(sweep={"points": 5}, averages=3), plant=lowpass(1e3))
    assert runner.state is RunState.FINISHED and lab.captures >= 15
    _, row, sweep, _, _ = results(runner)
    assert len(sweep) == 5 and row["points"] == 5


def test_the_phase_offset_and_the_branch_of_the_first_point(registry):
    base = run(registry, params(sweep={"points": 9}), plant=lowpass(1e3), noise_v=0.0001)[0]
    shifted = run(
        registry,
        params(sweep={"points": 9}, phase_offset_deg=180),
        plant=lowpass(1e3),
        noise_v=0.0001,
    )[0]
    a, b = results(base)[2], results(shifted)[2]
    assert [y["phase_deg"] - x["phase_deg"] for x, y in zip(a, b)] == pytest.approx(
        [180] * 9, abs=3
    )
    low = run(
        registry,
        params(sweep={"points": 9}, phase_start_deg=-360),
        plant=lowpass(1e3),
        noise_v=0.0001,
    )[0]
    assert results(low)[2][0]["phase_deg"] == pytest.approx(-360, abs=10)  # near -360, not near 0


def test_the_pure_delay_phase_is_followed_over_many_turns(registry):
    tau = 5e-6
    p = params(sweep={"start_hz": 1e3, "stop_hz": 1e5, "points": 41})
    runner, _ = run(registry, p, plant=delay(tau), noise_v=0.0001, depth=100000)
    _, _, sweep, _, _ = results(runner)
    for r in sweep:
        want = -360 * r["frequency_hz"] * tau
        assert r["phase_deg"] == pytest.approx(want, abs=3), r["frequency_hz"]
    assert sweep[-1]["phase_deg"] < -150  # more than half a turn


# ---- the checks and the verdict ----------------------------------------------------------------
def test_limits_pass_or_fail_as_a_result(registry):
    p = params(sweep={"points": 41}, loop=True, limits={"min_phase_margin_deg": 45})
    runner, _ = run(registry, p, plant=integrator_with_pole(2e4, 2e5), noise_v=0.0001)
    assert runner.state is RunState.FINISHED and results(runner)[1]["verdict"] == "PASS"
    tight = {**p, "limits": {"min_phase_margin_deg": 89, "max_peaking_db": 0.0}}
    runner, _ = run(registry, tight, plant=integrator_with_pole(2e4, 2e5), noise_v=0.0001)
    _, row, _, logs, _ = results(runner)
    assert runner.state is RunState.FINISHED and row["verdict"] == "FAIL"
    assert any(lv == "warning" and "limit exceeded" in m and "phase margin" in m for lv, m in logs)


def test_a_loop_that_never_crosses_zero_is_said_so(registry):
    p = params(loop=True, limits={"min_phase_margin_deg": 45})
    runner, _ = run(registry, p, plant=lowpass(1e3, gain=0.5), noise_v=0.0001)  # always below 0 dB
    _, row, _, logs, _ = results(runner)
    assert row["verdict"] == "FAIL" and "crossover_hz" not in row
    assert any("never falls through 0 dB" in m for _, m in logs)


def test_too_few_samples_a_cycle_is_a_warning(registry):
    p = params(sweep={"start_hz": 1e5, "stop_hz": 1e6, "points": 4}, scope={"memory_depth": 30})
    runner, _ = run(registry, p, plant=lowpass(1e6), noise_v=0.0, depth=30)  # 6 samples a cycle
    _, _, _, logs, _ = results(runner)
    assert any("samples a cycle" in m and lv == "warning" for lv, m in logs)


# ---- safety ------------------------------------------------------------------------------------
def test_the_generator_is_off_until_the_circuit_is_set_up_and_off_again_at_the_end(registry):
    runner, lab = run(registry, params(sweep={"points": 4}), plant=lowpass(1e3))
    calls = [(w, c) for w, c, _ in lab.log if w == "generator"]
    assert calls[0] == ("generator", "set_output_state")
    assert lab.log[0][2] == {"channel_number": 1, "state": False}  # off first
    on = [i for i, (w, c, a) in enumerate(lab.log) if c == "set_output_state" and a["state"]]
    amplitude = [i for i, (w, c, a) in enumerate(lab.log) if c == "set_amplitude"]
    assert amplitude and on and amplitude[0] < on[0]  # the amplitude is set before it is on
    assert lab.log[-1] == ("generator", "set_output_state", {"channel_number": 1, "state": False})
    assert not lab.generator_on
    assert [a["value"] for w, c, a in lab.log if c == "set_amplitude"] == [0.1]


def test_the_generator_is_switched_off_also_when_the_run_fails(registry):
    class Breaks(SimBodeLab):
        def do(self, instrument, call, args):
            if call == "set_frequency" and args["value"] > 5e3:
                raise RuntimeError("the cable fell out")
            return super().do(instrument, call, args)

    lab = Breaks(plant=lowpass(1e3))
    runner, _ = run(registry, params(sweep={"points": 11}), lab=lab)
    assert runner.state is RunState.FAILED and "fell out" in runner.error["message"]
    assert not lab.generator_on


def test_a_larger_amplitude_than_the_limit_is_refused_before_anything_is_switched_on(registry):
    from ola.measurement import MeasurementError

    lab = SimBodeLab()
    p = params(source={"amplitude_vpp": 2.0}, safety={"max_amplitude_vpp": 1.0})
    runner = Runner(
        registry.create("bode", p), {"generator": [lab.generator], "oscilloscope": [lab.scope]}
    )
    with pytest.raises(MeasurementError, match="above the limit of 1 Vpp"):
        runner.start()
    assert lab.log == []


def test_the_connections_are_asked_before_anything_is_switched_on(registry):
    lab = SimBodeLab()
    runner = Runner(
        registry.create("bode", params(confirm_setup=True)),
        {"generator": [lab.generator], "oscilloscope": [lab.scope]},
    )
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    q = runner.pending_questions[0]
    assert "channel 1" in q["text"] and "channel 2" in q["text"] and "0.1 Vpp" in q["text"]
    assert lab.log == []
    runner.answer(q["id"], "abort")
    assert runner.join(10) and runner.state is RunState.STOPPED and lab.log == []


def test_both_channels_are_read_from_the_same_capture(registry):
    runner, lab = run(registry, params(sweep={"points": 3}), plant=lowpass(1e3))
    reads = [(c, a.get("channel_number")) for w, c, a in lab.log
             if c in ("run_acquisition", "read_waveform_full")]  # fmt: skip
    captures = []
    for name, channel in reads:
        if name == "run_acquisition":
            captures.append([])
        else:
            captures[-1].append(channel)
    assert captures and all(c == [1, 2] for c in captures)  # one run, then the two channels


def test_the_scope_is_set_up_for_the_circuit(registry):
    p = params(scope={"coupling": "AC", "probe_attenuation": 10, "bandwidth_limit_hz": 20e6,
                      "cycles": 8, "memory_depth": 100000, "input_volts_per_div": 0.02},
               sweep={"start_hz": 100, "points": 3})  # fmt: skip
    _, lab = run(registry, p, plant=lowpass(1e3))
    sent = {}
    for who, name, args in lab.log:
        sent.setdefault((name, args.get("channel_number")), args)
    assert sent[("set_channel_coupling", 1)]["coupling_type"] == "AC"
    assert sent[("set_probe_attenuation", 2)]["value"] == 10.0
    assert sent[("set_channel_bandwidth_limit", 1)]["bandwidth"] == 20e6
    assert sent[("set_acquisition_depth", None)]["depth"] == 100000
    assert sent[("set_channel_scale", 1)]["value"] == 0.02  # where the scale starts
    tb = [a["value"] for w, c, a in lab.log if c == "set_timebase_scale"]
    assert tb[0] == pytest.approx(8 / 100 / 10)  # 8 cycles of 100 Hz over the 10 divisions


# ---- the real library --------------------------------------------------------------------------
def test_the_scope_calls_exist_for_the_oscilloscopes_of_the_library(registry):
    from ola.call_planner import plan_call
    from ola.library import Library

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "Instruments_LIB", "instruments_lib.json")
    if not os.path.isfile(path):
        pytest.skip("library not available")
    lib = Library.load(path)
    p = params(
        scope={"coupling": "AC", "bandwidth_limit_hz": 20e6, "memory_depth": 100000},
        sweep={"points": 3},
    )
    _, lab = run(registry, p, plant=lowpass(1e3))
    sent = {}
    for who, name, args in lab.log:
        if who == "oscilloscope" and name != "read_waveform_full":
            sent.setdefault(name, args)
    for model in ("OSC_Siglent_SDS824X_HD", "OSC_Rigol_DS1054Z", "OSC_Tek_MSO54"):
        for name, args in sent.items():
            assert plan_call(lib, model, name, args).steps or name == "run_acquisition", (
                model,
                name,
            )
