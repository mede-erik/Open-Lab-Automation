"""Cable characterization: parameters, calculations and whole runs on a simulated VNA."""

import copy
import time

import pytest

from ola import rf
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.runs import RunWriter, export_touchstone, read_run
from ola.sim_vna import SimVna

PARAMS = {
    "mode": "transmission",
    "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 401, "scale": "linear"},
    "cable": {"label": "RG58 #3", "length_m": 2.0},
    "frequencies_of_interest": [433e6, 868e6, 2.4e9],
    "confirm_setup": False,
}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(**changes):
    p = copy.deepcopy(PARAMS)
    for key, value in changes.items():
        if key == "sweep":
            p["sweep"].update(value)
        else:
            p[key] = value
    return p


def run(registry, p, vna=None, **runner_kw):
    vna = vna or SimVna(length_m=2.0)
    m = registry.create("cable", p)
    runner = Runner(m, {"vna": [vna]}, **runner_kw)
    runner.start()
    assert runner.join(20)
    return runner, vna


def events(runner):
    return runner.drain()


def traces(evs):
    return {e.data["name"]: e.data for e in evs if e.kind == "trace"}


# ---- the module ---------------------------------------------------------------------------------
def test_the_module_is_found_with_its_extension_and_role(registry):
    info = registry.get("cable")
    assert info.extension == ".cbl" and info.name == "Cable characterization"
    assert [(r.name, r.category, r.required) for r in info.roles] == [("vna", "network_analyzer", True)]
    assert registry.by_extension(".cbl").id == "cable"


# ---- parameters ---------------------------------------------------------------------------------
def problems(registry, p):
    return {x.path: x.message for x in registry.create("cable", p).check()}


def test_good_parameters_have_no_problems(registry):
    assert problems(registry, PARAMS) == {}
    assert registry.create("cable", PARAMS).validate() == []


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"mode": "both"}, "mode", "one of"),
        ({"sweep": {"start_hz": 0}}, "sweep.start_hz", "above 0"),
        ({"sweep": {"stop_hz": 5e5}}, "sweep.stop_hz", "above the start"),
        ({"sweep": {"points": 1}}, "sweep.points", "from 2"),
        ({"sweep": {"points": 2.5}}, "sweep.points", "whole number"),
        ({"sweep": {"scale": "decade"}}, "sweep.scale", "one of"),
        ({"sweep": {"if_bandwidth_hz": -1}}, "sweep.if_bandwidth_hz", "above 0"),
        ({"sweep": {"power_dbm": "high"}}, "sweep.power_dbm", "number"),
        ({"cable": {"length_m": 0}}, "cable.length_m", "above 0"),
        ({"cable": {"label": 5}}, "cable.label", "text"),
        ({"frequencies_of_interest": [5e9]}, "frequencies_of_interest", "outside the sweep"),
        ({"frequencies_of_interest": "433e6"}, "frequencies_of_interest", "list"),
        ({"limits": {"maximum": 1}}, "limits", "unknown limit key"),
        ({"averages": 0}, "averages", "from 1"),
        ({"confirm_setup": "yes"}, "confirm_setup", "true or false"),
        ({"mode": "reflection", "termination": "half"}, "termination", "one of"),
    ],
)
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = problems(registry, params(**changes))
    assert path in found and words in found[path]


def test_a_missing_sweep_is_reported(registry):
    p = params()
    del p["sweep"]
    assert "sweep" in problems(registry, p)
    assert registry.create("cable", p).validate()  # and the run would not start


# ---- calculations -------------------------------------------------------------------------------
def test_a_transmission_run_reports_the_loss_the_cable_has(registry):
    vna = SimVna(length_m=2.0, loss_db_per_m_at_1ghz=0.6, dielectric_db_per_m_per_ghz=0.05)
    runner, _ = run(registry, PARAMS, vna)
    assert runner.state is RunState.FINISHED, runner.error
    evs = events(runner)
    t = traces(evs)
    assert {"S21", "loss_db", "loss_db_per_m", "group_delay_ns"} <= set(t)
    freq, loss = t["loss_db"]["x"], t["loss_db"]["y"]
    assert loss == [pytest.approx(vna.one_way_loss_db(f), abs=1e-9) for f in freq]
    assert t["loss_db"]["meta"]["ylabel"] == "Loss (dB)" and t["loss_db"]["meta"]["x_unit"] == "Hz"
    row = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"][0]
    assert row["cable"] == "RG58 #3" and row["length_m"] == 2.0
    assert row["loss_868MHz_db"] == pytest.approx(vna.one_way_loss_db(868e6), abs=0.01)
    assert row["loss_868MHz_db_per_m"] == pytest.approx(row["loss_868MHz_db"] / 2)
    assert row["velocity_factor"] == pytest.approx(0.66, abs=0.01)
    assert row["mean_delay_ns"] == pytest.approx(vna.delay_s() * 1e9, rel=0.01)
    assert "loss_433MHz_db" in row and "loss_2.4GHz_db" in row


def test_the_raw_traces_are_hidden_and_the_loss_is_not(registry):
    runner, _ = run(registry, PARAMS)
    t = traces(events(runner))
    assert t["S21"]["meta"]["hidden"] is True and t["group_delay_ns"]["meta"]["hidden"] is True
    assert "hidden" not in t["loss_db"]["meta"]


def test_the_sweep_table_has_a_row_per_frequency(registry):
    runner, _ = run(registry, PARAMS)
    rows = [
        e.data["values"] for e in events(runner) if e.kind == "point" and e.data["table"] == "sweep"
    ]
    assert len(rows) == 401 and rows[0]["frequency_hz"] == 1e6
    assert set(rows[0]) == {"frequency_hz", "loss_db", "loss_db_per_m", "group_delay_ns"}


def test_without_a_length_there_is_no_per_metre_and_no_velocity_factor(registry):
    runner, _ = run(registry, params(cable={"label": "x"}))
    evs = events(runner)
    assert "loss_db_per_m" not in traces(evs)
    row = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"][0]
    assert "velocity_factor" not in row and "loss_868MHz_db_per_m" not in row


def test_the_sweep_is_sent_to_the_vna(registry):
    p = params(sweep={"scale": "log", "if_bandwidth_hz": 300, "power_dbm": -20})
    _, vna = run(registry, p)
    name, args = vna.calls[0]
    assert name == "set_sweep"
    assert args == {
        "start_frequency": 1e6, "stop_frequency": 3e9, "points": 401, "sweep_type": "log",
        "if_bandwidth": 300, "power": -20,
    }  # fmt: skip
    assert [c[0] for c in vna.calls[1:]] == ["read_sparameter"]


def test_a_log_sweep_marks_the_axis_logarithmic(registry):
    runner, _ = run(registry, params(sweep={"scale": "log"}))
    assert traces(events(runner))["loss_db"]["meta"]["log_x"] is True


def test_reflection_mode_halves_the_round_trip(registry):
    vna = SimVna(length_m=2.0, termination="open")
    runner, _ = run(registry, params(mode="reflection", termination="open"), vna)
    assert runner.state is RunState.FINISHED, runner.error
    t = traces(events(runner))
    assert "S11" in t and "S21" not in t
    loss = t["loss_db"]["y"]
    assert loss == [pytest.approx(vna.one_way_loss_db(f), abs=1e-6) for f in t["loss_db"]["x"]]
    assert vna.calls[1][1] == {"parameter": "S11"}


def test_also_s11_gives_the_return_loss_of_the_cable(registry):
    runner, vna = run(registry, params(also_s11=True))
    evs = events(runner)
    row = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"][0]
    assert row["min_return_loss_db"] == pytest.approx(rf.db20(0.02) * -1, abs=0.01)
    assert row["max_vswr"] == pytest.approx(1.0417, abs=1e-3)
    assert "return_loss_db" in traces(evs)
    assert [c[1]["parameter"] for c in vna.calls[1:]] == ["S21", "S11"]


def test_averaging_reduces_noise_and_reports_progress(registry):
    noisy = lambda: SimVna(length_m=2.0, noise_db=0.5, seed=7)  # noqa: E731
    one, v1 = run(registry, params(averages=1), noisy())
    many, v16 = run(registry, params(averages=16), noisy())
    clean = SimVna(length_m=2.0)

    def error(runner):
        t = traces(events(runner))["loss_db"]
        return sum(abs(y - clean.one_way_loss_db(x)) for x, y in zip(t["x"], t["y"])) / len(t["x"])

    assert error(many) < error(one) / 2
    assert len(v16.calls) == 1 + 16


# ---- limits and the verdict ---------------------------------------------------------------------
def verdict_row(runner):
    evs = events(runner)
    row = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"][0]
    return row, evs


def test_a_cable_within_the_limit_passes_and_draws_the_limit(registry):
    runner, _ = run(registry, params(limits={"max": 3.0}))
    row, evs = verdict_row(runner)
    assert row["verdict"] == "PASS" and row["margin_db"] > 0
    limits = traces(evs)["loss_db"]["meta"]["limits"]
    assert limits["view"] == "value" and len(limits["max"]) == 401 and "min" not in limits


def test_a_cable_over_the_limit_fails_but_the_run_still_finishes(registry):
    runner, _ = run(registry, params(limits={"bands": [{"from": 2e9, "to": 3e9, "max": 0.5}]}))
    assert runner.state is RunState.FINISHED  # a failed limit is a result, not an error
    row, evs = verdict_row(runner)
    assert row["verdict"] == "FAIL" and row["margin_db"] < 0
    logs = [e.data for e in evs if e.kind == "log" and "limit check" in e.data["message"]]
    assert logs and logs[0]["level"] == "warning" and "FAIL" in logs[0]["message"]


def test_without_limits_there_is_no_verdict(registry):
    runner, _ = run(registry, PARAMS)
    row, _ = verdict_row(runner)
    assert "verdict" not in row


# ---- the question before measuring --------------------------------------------------------------
def test_the_set_up_is_asked_before_anything_is_sent_to_the_vna(registry):
    p = params(confirm_setup=True)
    m = registry.create("cable", p)
    vna = SimVna(length_m=2.0)
    runner = Runner(m, {"vna": [vna]})
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    question = runner.pending_questions[0]
    assert question["data"]["kind"] == "calibration" and vna.calls == []  # nothing sent yet
    assert "calibrated" in question["text"] and "port 1 and port 2" in question["text"]
    assert question["choices"] == ["continue", "abort"] and question["default"] == "abort"
    runner.answer(question["id"], "continue")
    assert runner.join(20) and runner.state is RunState.FINISHED


def test_abort_at_the_question_stops_without_touching_the_vna(registry):
    runner, vna = run(registry, params(confirm_setup=True), unattended="abort")
    assert runner.state is RunState.STOPPED and vna.calls == []


def test_reflection_question_says_what_goes_on_the_far_end(registry):
    runner, _ = run(
        registry,
        params(mode="reflection", termination="short", confirm_setup=True),
        unattended="abort",
    )
    q = [e.data for e in events(runner) if e.kind == "question"][0]
    assert "short circuit" in q["text"] and "port 1" in q["text"]


# ---- what goes wrong ----------------------------------------------------------------------------
class Broken(SimVna):
    def __init__(self, answer, **kw):
        super().__init__(**kw)
        self.answer = answer

    def _read(self, parameter):
        return self.answer


@pytest.mark.parametrize(
    "answer,words",
    [
        (None, "no data"),
        ({"frequency": [1.0, 2.0], "values": [[1, 0]] * 3}, "values"),
        ({"frequency": [1.0], "values": ["x"]}, "not a list of complex"),
    ],
)
def test_bad_vna_data_fails_with_a_clear_message(registry, answer, words):
    runner, _ = run(registry, PARAMS, Broken(answer))
    assert runner.state is RunState.FAILED and words in runner.error["message"]


def test_a_plain_list_of_complex_numbers_is_accepted(registry):
    class Plain(SimVna):
        def _read(self, parameter):
            data = super()._read(parameter)
            return [complex(re, im) for re, im in data["values"]]

    runner, _ = run(registry, PARAMS, Plain(length_m=2.0))
    assert runner.state is RunState.FINISHED, runner.error
    assert traces(events(runner))["loss_db"]["x"][0] == 1e6  # frequencies are the sweep's


def test_stop_during_a_long_average_ends_quickly(registry):
    class Slow(SimVna):
        def _read(self, parameter):
            time.sleep(0.05)
            return super()._read(parameter)

    m = registry.create("cable", params(averages=500))
    runner = Runner(m, {"vna": [Slow(length_m=2.0)]})
    runner.start()
    time.sleep(0.2)
    runner.stop()
    assert runner.join(5) and runner.state is RunState.STOPPED


# ---- the files ----------------------------------------------------------------------------------
def test_a_run_file_exports_to_touchstone_and_keeps_the_cable_label(registry, tmp_path):
    vna = SimVna(length_m=2.0)
    m = registry.create("cable", params(also_s11=True))
    runner = Runner(m, {"vna": [vna]})
    path = tmp_path / "run.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(20)
    run_data = read_run(path)
    assert run_data["header"]["params"]["cable"]["label"] == "RG58 #3"
    out = tmp_path / "cable.s2p"
    assert export_touchstone(path, out) == 401
    freq, s, _ = rf.read_touchstone(out)
    assert rf.insertion_loss_db(s["S21"])[10] == pytest.approx(
        vna.one_way_loss_db(freq[10]), abs=1e-6
    )


# ---- a sweep that is too coarse for the cable ---------------------------------------------------
def test_a_coarse_sweep_warns_in_the_editor_before_measuring(registry):
    p = params(sweep={"points": 61})  # 50 MHz steps for a 2 m cable
    found = {x.path: x for x in registry.create("cable", p).check()}
    warning = found["sweep.points"]
    assert warning.severity == "warning" and "phase wraps" in warning.message
    assert "Use at least" in warning.message
    assert registry.create("cable", p).validate() == []  # it is only a warning: it can run


def test_a_coarse_sweep_loses_the_delay_but_keeps_the_loss(registry):
    runner, vna = run(registry, params(sweep={"points": 61}))
    assert runner.state is RunState.FINISHED
    evs = events(runner)
    row = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"][0]
    assert "velocity_factor" not in row  # not invented
    assert row["loss_868MHz_db"] == pytest.approx(vna.one_way_loss_db(868e6), abs=0.05)
    warnings = [e.data["message"] for e in evs if e.kind == "log" and e.data["level"] == "warning"]
    assert any("velocity factor could not be found" in w for w in warnings)


def test_a_log_sweep_is_judged_by_its_widest_step(registry):
    wide = problems(
        registry, params(sweep={"scale": "log", "start_hz": 1e6, "stop_hz": 3e9, "points": 61})
    )
    assert "sweep.points" in wide  # the steps at the top are 150 MHz
    dense = problems(registry, params(sweep={"scale": "log", "points": 1601}))
    assert "sweep.points" not in dense
    assert "sweep.points" not in problems(
        registry, params(cable={"label": "x"})
    )  # no length: no warning


def test_max_frequency_step(registry):
    import sys

    module = sys.modules[registry.load_class("cable").__module__]
    assert module.max_frequency_step(1.0) == pytest.approx(0.6 * 299_792_458 / 2, rel=1e-9)
    assert module.max_frequency_step(10.0) == pytest.approx(module.max_frequency_step(1.0) / 10)
