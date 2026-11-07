# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Time domain from S11: the maths on synthetic reflections, and whole runs on a simulated VNA."""

import cmath
import copy
import math
import time

import pytest

from ola import tdr
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimVna

VF = 0.66
SCALE = tdr.C * VF / 2  # metres per second of delay


def grid(start=1e6, stop=1e9, n=501):
    return [start + (stop - start) * k / (n - 1) for k in range(n)]


def echo(freq, rho, distance_m, vf=VF):
    """What a reflection of coefficient ``rho`` at a distance gives at the frequencies."""
    tau = 2 * distance_m / (tdr.C * vf)
    return [rho * cmath.exp(-2j * math.pi * f * tau) for f in freq]


def add(*curves):
    return [sum(v) for v in zip(*curves)]


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


# ---- the helpers -------------------------------------------------------------------------------
def test_windows():
    assert tdr.window("rect", 5) == [1.0] * 5
    hann = tdr.window("hann", 9)
    assert hann[0] == pytest.approx(0) and hann[4] == pytest.approx(1)
    assert hann == pytest.approx(hann[::-1])  # symmetric (to the rounding)
    assert tdr.window("hamming", 9)[0] == pytest.approx(0.08)
    assert tdr.window("blackman", 9)[4] == pytest.approx(1.0) and tdr.window("hann", 1) == [1.0]
    with pytest.raises(tdr.TdrError, match="window must be one of"):
        tdr.window("kaiser", 5)


def test_the_sweep_must_be_linear_and_long_enough():
    assert tdr.step_of(grid(1e6, 5e6, 5)) == pytest.approx(1e6)
    with pytest.raises(tdr.TdrError, match="at least 4"):
        tdr.step_of([1, 2, 3])
    with pytest.raises(tdr.TdrError, match="linear"):
        tdr.step_of([1e6, 2e6, 4e6, 8e6, 16e6])
    with pytest.raises(tdr.TdrError, match="increase"):
        tdr.step_of([5, 4, 3, 2, 1])


def test_resolution_and_range():
    assert tdr.resolution_m(1e9, 0.66) == pytest.approx(0.099, abs=0.001)  # 10 cm for 1 GHz
    assert tdr.range_m(2e6, 0.66) == pytest.approx(49.5, abs=0.1)  # a step of 2 MHz: 50 m


# ---- a reflection is a peak at its distance ----------------------------------------------------
def test_one_reflection_gives_a_peak_of_its_size_at_its_distance():
    f = grid()
    t, env = tdr.impulse_response(f, echo(f, 0.4, 7.0))
    peak = max(range(len(env)), key=env.__getitem__)
    assert t[peak] * SCALE == pytest.approx(7.0, abs=0.02)
    assert env[peak] == pytest.approx(0.4, rel=0.03)
    assert max(v for i, v in enumerate(env) if abs(i - peak) > 40) < 0.02  # and nothing else


def test_the_faults_have_distance_size_sign_and_impedance():
    f = grid()
    s = add(echo(f, 0.4, 7.0), echo(f, -0.2, 12.0))
    found = tdr.find_faults(f, s, VF)
    a, b = found["faults"]
    assert a["distance_m"] == pytest.approx(7.0, abs=0.01) and a["reflection"] == pytest.approx(
        0.4, rel=0.01
    )
    assert a["kind"] == "higher impedance" and a["impedance_ohm"] == pytest.approx(
        50 * 1.4 / 0.6, rel=0.01
    )
    assert b["distance_m"] == pytest.approx(12.0, abs=0.01) and b["rho"].real == pytest.approx(
        -0.2, rel=0.01
    )
    assert b["kind"] == "lower impedance" and b["impedance_ohm"] == pytest.approx(
        50 * 0.8 / 1.2, rel=0.01
    )
    assert b["delay_s"] == pytest.approx(2 * 12 / (tdr.C * VF), rel=1e-3)
    assert found["resolution_m"] == pytest.approx(0.099, abs=0.002) and found["range_m"] > 49


def test_two_faults_closer_than_the_resolution_are_one_peak():
    f = grid()
    near = tdr.find_faults(f, add(echo(f, 0.3, 7.0), echo(f, 0.3, 7.04)), VF)["faults"]
    assert len(near) == 1  # 4 cm apart with a resolution of 10 cm
    apart = tdr.find_faults(f, add(echo(f, 0.3, 7.0), echo(f, 0.3, 7.40)), VF)["faults"]
    assert [round(x["distance_m"], 1) for x in apart] == [7.0, 7.4]


def test_a_window_keeps_the_sidelobes_of_a_strong_reflection_from_looking_like_faults():
    f = grid()
    s = echo(f, 1.0, 10.0)
    assert len(tdr.find_faults(f, s, VF, window_name="hann")["faults"]) == 1
    assert len(tdr.find_faults(f, s, VF, window_name="blackman")["faults"]) == 1
    rect = tdr.find_faults(f, s, VF, window_name="rect")["faults"]
    assert len(rect) > 1  # the -13 dB sidelobes of no window are above 0.05
    assert tdr.find_faults(f, s, VF, window_name="rect", min_reflection=0.5)["faults"][0][
        "reflection"
    ] == pytest.approx(1.0, rel=0.02)


def test_a_weak_reflection_next_to_a_strong_one_is_found_with_a_window():
    f = grid()
    s = add(echo(f, 0.9, 10.0), echo(f, 0.06, 13.0))
    found = tdr.find_faults(f, s, VF, min_reflection=0.04)["faults"]
    assert [round(x["distance_m"]) for x in found] == [10, 13]
    assert found[1]["reflection"] == pytest.approx(0.06, rel=0.1)


def test_the_distance_scales_with_the_velocity_factor():
    f = grid()
    s = echo(f, 0.4, 7.0, vf=VF)
    right = tdr.find_faults(f, s, VF)["faults"][0]["distance_m"]
    wrong = tdr.find_faults(f, s, 0.5)["faults"][0]["distance_m"]
    assert wrong == pytest.approx(right * 0.5 / VF, rel=1e-3)


def test_numpy_and_the_plain_transform_agree():
    f = grid(1e6, 1e9, 129)
    s = add(echo(f, 0.4, 7.0), echo(f, -0.2, 12.0))
    _, a = tdr.impulse_response(f, s, pad=4, use_numpy=True)
    _, b = tdr.impulse_response(f, s, pad=4, use_numpy=False)
    assert b == pytest.approx(a, abs=1e-9)


def test_the_search_can_be_limited_to_a_distance():
    f = grid()
    s = add(echo(f, 0.4, 7.0), echo(f, 0.3, 30.0))
    found = tdr.find_faults(f, s, VF, max_distance_m=20)
    assert [round(x["distance_m"]) for x in found["faults"]] == [7]
    assert found["delays"][-1] * SCALE < 21 and len(found["delays"]) == len(found["envelope"])


def test_errors_say_what_is_wrong():
    f = grid()
    with pytest.raises(tdr.TdrError, match="velocity factor"):
        tdr.find_faults(f, echo(f, 0.4, 7.0), 1.5)
    with pytest.raises(tdr.TdrError, match="values"):
        tdr.impulse_response(f, [0j] * 3)
    with pytest.raises(tdr.TdrError, match="padding"):
        tdr.impulse_response(f, echo(f, 0.4, 7.0), pad=0)
    assert tdr.find_faults(f, [0j] * len(f), VF)["faults"] == []


# ---- the step response and the impedance profile -----------------------------------------------
def harmonic(n=400, df=2.5e6):
    return [df * (k + 1) for k in range(n)]


def test_an_open_end_is_a_step_up_and_a_short_a_step_down():
    f = harmonic()
    for rho, sign in ((1.0, 1), (-1.0, -1)):
        t, step = tdr.step_response(f, echo(f, rho, 6.0))
        before = [s for tm, s in zip(t, step) if tm * SCALE < 5.5][50:]
        after = [s for tm, s in zip(t, step) if 6.6 < tm * SCALE < 20]
        assert max(abs(v) for v in before) < 0.03  # nothing before the end
        assert sum(after) / len(after) == pytest.approx(sign, abs=0.03)


def test_a_section_of_another_impedance_shows_in_the_profile():
    f = harmonic(n=600, df=2e6)
    rho = (75 - 50) / (75 + 50)  # 0.2: a 75 ohm section between 5 m and 9 m of 50 ohm line
    s = add(echo(f, rho, 5.0), echo(f, -rho * (1 - rho * rho) ** 0, 9.0))
    t, step = tdr.step_response(f, s)
    z = tdr.impedance_profile(step)
    d = [tm * SCALE for tm in t]
    middle = [v for x, v in zip(d, z) if 5.6 < x < 8.4]
    outside = [v for x, v in zip(d, z) if 10.0 < x < 20.0]
    assert sum(middle) / len(middle) == pytest.approx(75, abs=6)
    assert sum(outside) / len(outside) == pytest.approx(50, abs=5)


def test_the_step_response_needs_a_sweep_that_starts_at_its_step():
    f = grid(1.5e6, 1e9, 400)
    with pytest.raises(tdr.TdrError, match="multiple of its step"):
        tdr.step_response(f, echo(f, 1.0, 6.0))
    assert tdr.impedance_profile([0.0, 1.5, -1.5])[0] == 50
    assert tdr.impedance_profile([1.5])[0] == pytest.approx(50 * 1.999 / 0.001)  # kept finite


# ---- whole runs --------------------------------------------------------------------------------
PARAMS = {
    "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 501},
    "velocity_factor": 0.66,
    "confirm_setup": False,
}


def params(**changes):
    p = copy.deepcopy(PARAMS)
    for key, value in changes.items():
        if key == "sweep" and isinstance(value, dict):
            p["sweep"].update(value)
        elif value is None:
            p.pop(key, None)
        else:
            p[key] = value
    return p


def run(registry, p, **sim):
    sim = {"velocity_factor": 0.66, **sim}
    runner = Runner(registry.create("tdr", p), {"vna": [SimVna(**sim)]})
    runner.start()
    assert runner.join(60)
    evs = runner.drain()
    tables = {}
    for e in evs:
        if e.kind == "point":
            tables.setdefault(e.data["table"], []).append(e.data["values"])
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    logs = [(e.data["level"], e.data["message"]) for e in evs if e.kind == "log"]
    return runner, tables, traces, logs


def test_the_module_is_found_with_an_editor(registry):
    from ola.form_model import load_form_spec

    info = registry.get("tdr")
    assert info.extension == ".tdr" and registry.by_extension(".tdr").id == "tdr"
    assert [(r.name, r.category) for r in info.roles] == [("vna", "network_analyzer")]
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths, set(info.params_schema) - paths


def test_a_damaged_spot_and_the_open_end_are_found_at_their_distances(registry):
    runner, tables, traces, logs = run(
        registry, params(), length_m=5.0, termination="open", fault_at_m=2.0, fault_gamma=0.3
    )
    assert runner.state is RunState.FINISHED, runner.error
    a, b = tables["faults"]
    assert a["distance_m"] == pytest.approx(2.0, abs=0.02) and b["distance_m"] == pytest.approx(
        5.0, abs=0.02
    )
    assert (
        a["kind"] == "higher impedance" and 0.2 < a["reflection"] < 0.3
    )  # 0.3 less the cable loss
    assert b["reflection"] > a["reflection"] and b["number"] == 2
    row = tables["points"][0]
    assert row["reflection_count"] == 2 and row["first_reflection_m"] == pytest.approx(
        2.0, abs=0.02
    )
    assert row["last_reflection_m"] == pytest.approx(5.0, abs=0.02)
    assert row["resolution_m"] == pytest.approx(0.099, abs=0.002) and row["range_m"] > 49
    assert traces["impulse"]["meta"]["x_unit"] == "m" and traces["S11"]["meta"]["hidden"]
    peak = max(traces["impulse"]["y"])
    assert traces["impulse"]["x"][traces["impulse"]["y"].index(peak)] == pytest.approx(
        5.0, abs=0.02
    )
    assert any("2 reflection(s)" in m for _, m in logs)


def test_a_short_is_a_reflection_of_lower_impedance(registry):
    _, tables, _, _ = run(registry, params(), length_m=5.0, termination="short")
    end = tables["faults"][-1]
    assert end["kind"] == "lower impedance" and end["impedance_ohm"] < 20  # 12: the loss weakens it
    assert end["distance_m"] == pytest.approx(5.0, abs=0.02)


def test_the_velocity_factor_that_fits_a_cable_of_known_length(registry):
    p = params(velocity_factor=0.5, expected_length_m=5.0)  # the wrong one
    _, tables, _, _ = run(registry, p, length_m=5.0, termination="open")
    row = tables["points"][0]
    assert row["last_reflection_m"] == pytest.approx(5.0 * 0.5 / 0.66, abs=0.05)
    assert row["velocity_factor_estimate"] == pytest.approx(0.66, abs=0.005)
    assert row["length_error_m"] == pytest.approx(row["last_reflection_m"] - 5.0)
    _, right, _, _ = run(registry, params(expected_length_m=5.0), length_m=5.0, termination="open")
    assert right["points"][0]["length_error_m"] == pytest.approx(0, abs=0.03)


def test_the_verdict_counts_only_what_is_before_the_end(registry):
    sim = dict(length_m=5.0, termination="open", fault_at_m=2.0, fault_gamma=0.3)
    _, bad, _, logs = run(registry, params(limits={"max_fault_reflection": 0.1}), **sim)
    assert bad["points"][0]["verdict"] == "FAIL"
    assert any(lv == "warning" and "before the end" in m and "2 m" in m for lv, m in logs)
    _, ok, _, _ = run(registry, params(limits={"max_fault_reflection": 0.5}), **sim)
    assert ok["points"][0]["verdict"] == "PASS"  # the end (0.6) is not a fault
    _, clean, _, _ = run(
        registry, params(limits={"max_fault_reflection": 0.1}), length_m=5.0, termination="open"
    )
    assert clean["points"][0]["verdict"] == "PASS"  # only the end
    _, none, _, _ = run(registry, params(), **sim)
    assert "verdict" not in none["points"][0]


def test_a_matched_line_has_no_reflection_and_says_so(registry):
    _, tables, _, logs = run(registry, params(), length_m=5.0, termination="thru", mismatch=0.01)
    assert tables.get("faults", []) == [] and tables["points"][0]["reflection_count"] == 0
    assert any(lv == "warning" and "no reflection above 0.05" in m for lv, m in logs)
    _, found, _, _ = run(
        registry, params(min_reflection=0.005), length_m=5.0, termination="thru", mismatch=0.02
    )
    assert found["faults"]  # a lower threshold finds the connector mismatch


def test_the_same_result_with_the_library_calls(registry):
    sim = dict(length_m=5.0, termination="open", fault_at_m=2.0, fault_gamma=0.3)
    simple = run(registry, params(), **sim)[1]
    library = run(registry, params(), library_calls=True, **sim)[1]
    assert [f["distance_m"] for f in library["faults"]] == pytest.approx(
        [f["distance_m"] for f in simple["faults"]]
    )


def test_the_step_response_and_the_impedance_profile(registry):
    p = params(sweep={"start_hz": 2e6, "stop_hz": 1e9, "points": 500}, step_response=True)
    runner, tables, traces, _ = run(registry, p, length_m=5.0, termination="open")
    assert runner.state is RunState.FINISHED, runner.error
    assert {"step", "impedance_ohm"} <= set(traces) and traces["step"]["meta"]["hidden"]
    assert len(traces["step"]["x"]) == len(traces["impulse"]["x"])
    d, step = traces["step"]["x"], traces["step"]["y"]
    beyond = [s for x, s in zip(d, step) if 5.4 < x < 12]
    assert sum(beyond) / len(beyond) > 0.4  # an open end: the step is up


def test_a_window_the_range_and_the_points_are_used(registry):
    p = params(window="rect", pad=2, max_distance_m=10, min_reflection=0.3)
    _, tables, traces, _ = run(registry, p, length_m=5.0, termination="open")
    assert [round(f["distance_m"]) for f in tables["faults"]] == [5]
    assert max(traces["impulse"]["x"]) < 11


def test_averaging_reads_the_sweep_again(registry):
    runner = Runner(
        registry.create("tdr", params(averages=3)),
        {"vna": [vna := SimVna(length_m=5.0, termination="open")]},
    )
    runner.start()
    assert runner.join(60) and runner.state is RunState.FINISHED
    assert len([c for c in vna.calls if c[0] == "read_sparameter"]) == 3


def test_the_question_is_asked_before_anything_is_sent(registry):
    vna = SimVna()
    runner = Runner(registry.create("tdr", params(confirm_setup=True)), {"vna": [vna]})
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    q = runner.pending_questions[0]
    assert "far end open" in q["text"] and "calibrated" in q["text"] and vna.calls == []
    runner.answer(q["id"], "abort")
    assert runner.join(10) and runner.state is RunState.STOPPED and vna.calls == []


def test_a_log_sweep_that_cannot_be_transformed_is_refused_by_the_check(registry):
    found = {
        x.path: x.message for x in registry.create("tdr", params(sweep={"scale": "log"})).check()
    }
    assert "linear sweep" in found["sweep.scale"]


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"sweep": {"points": 8}}, "sweep.points", "at least 16"),
        ({"velocity_factor": 0}, "velocity_factor", "above 0"),
        ({"velocity_factor": 1.2}, "velocity_factor", "at most 1"),
        ({"min_reflection": 0}, "min_reflection", "above 0"),
        ({"z0": -1}, "z0", "above 0"),
        ({"max_distance_m": 0}, "max_distance_m", "above 0"),
        ({"expected_length_m": "x"}, "expected_length_m", "above 0"),
        ({"window": "kaiser"}, "window", "one of"),
        ({"pad": 100}, "pad", "from 1 to 64"),
        ({"averages": 0}, "averages", "from 1 to 1000"),
        ({"step_response": "yes"}, "step_response", "true or false"),
        ({"limits": {"max_fault": 1}}, "limits", "unknown limit"),
        ({"limits": {"max_fault_reflection": 2}}, "limits", "between 0 and 1"),
        ({"device": {"asset_id": "x"}}, "device.asset_id", "not a code"),
        ({"step_response": True}, "sweep.start_hz", "multiple of its step"),
    ],
)
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = {x.path: x.message for x in registry.create("tdr", params(**changes)).check()}
    assert path in found and words in found[path], found


def test_a_step_response_sweep_that_starts_at_its_step_is_fine(registry):
    p = params(sweep={"start_hz": 2e6, "stop_hz": 1e9, "points": 500}, step_response=True)
    assert registry.create("tdr", p).check() == []
    import sys

    start = sys.modules[registry.load_class("tdr").__module__].default_params()
    assert [x for x in registry.create("tdr", start).check() if x.severity == "error"] == []
