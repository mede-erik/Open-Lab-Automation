"""Attenuator: parameters, the numbers, the verdict, and whole runs on a simulated attenuator."""

import copy
import time

import pytest

from ola.form_model import load_form_spec
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimVna

BASE = {
    "attenuator": {"label": "10 dB SMA #3", "nominal_db": 10, "tolerance_db": 0.5},
    "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 301, "scale": "linear"},
    "confirm_setup": False,
}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(**changes):
    p = copy.deepcopy(BASE)
    for key, value in changes.items():
        if key in ("sweep", "attenuator") and isinstance(value, dict):
            p[key].update(value)
        else:
            p[key] = value
    return p


def run(registry, p, **sim):
    sim.setdefault("attenuator_db", 10.0)
    vna = SimVna(**sim)
    runner = Runner(registry.create("attenuator", p), {"vna": [vna]})
    runner.start()
    assert runner.join(20)
    return runner, vna


def results(runner):
    evs = runner.drain()
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    rows = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    sweep = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "sweep"]
    return traces, (rows[0] if rows else None), sweep, evs


def problems(registry, p):
    return {x.path: x.message for x in registry.create("attenuator", p).check()}


# ---- the module --------------------------------------------------------------------------------
def test_the_module_is_found_with_an_editor(registry):
    info = registry.get("attenuator")
    assert info.extension == ".att" and info.name == "Attenuator"
    assert registry.by_extension(".att").id == "attenuator"
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths, set(info.params_schema) - paths


def test_good_parameters_have_no_problems(registry):
    assert problems(registry, BASE) == {}


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"attenuator": "10 dB"}, "attenuator", "missing"),
        ({"attenuator": {"label": 3}}, "attenuator.label", "text"),
        ({"attenuator": {"nominal_db": -1}}, "attenuator.nominal_db", "0 or more"),
        ({"attenuator": {"tolerance_db": "x"}}, "attenuator.tolerance_db", "0 or more"),
        ({"attenuator": {"setting": 5}}, "attenuator.setting", "text"),
        ({"sweep": {"stop_hz": 5e5}}, "sweep.stop_hz", "above the start"),
        ({"frequencies_of_interest": [9e9]}, "frequencies_of_interest", "outside the sweep"),
        ({"limits": {"max": "low"}}, "limits", "must be a number"),
        ({"also_return_loss": "yes"}, "also_return_loss", "true or false"),
    ],
)
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = problems(registry, params(**changes))
    assert path in found and words in found[path]


def test_a_tolerance_without_a_nominal_value_is_an_error_unless_there_is_a_mask(registry):
    spec = {"label": "x", "tolerance_db": 1}
    bare = {**BASE, "attenuator": spec}
    assert "attenuator.nominal_db" in problems(registry, bare)
    assert "attenuator.nominal_db" not in problems(registry, {**bare, "limits": {"min": 5}})


# ---- the numbers -------------------------------------------------------------------------------
def test_a_flat_10_db_attenuator(registry):
    runner, vna = run(registry, BASE)
    assert runner.state is RunState.FINISHED, runner.error
    traces, row, sweep, _ = results(runner)
    assert row["mean_attenuation_db"] == pytest.approx(10.0, abs=0.01)
    assert row["flatness_db"] == pytest.approx(0, abs=0.01)
    assert row["slope_db_per_ghz"] == pytest.approx(0, abs=0.01)
    assert row["mean_deviation_db"] == pytest.approx(0, abs=0.01) and row["verdict"] == "PASS"
    assert row["attenuator"] == "10 dB SMA #3" and len(sweep) == 301
    assert traces["attenuation_db"]["y"][0] == pytest.approx(10.0, abs=0.01)  # positive dB
    assert traces["S21"]["meta"]["hidden"] and {"S11", "S22"} <= set(traces)
    assert [c[1]["parameter"] for c in vna.calls if c[0] == "read_sparameter"] == [
        "S21",
        "S11",
        "S22",
    ]


def test_the_slope_and_the_spread_of_a_real_attenuator(registry):
    runner, _ = run(registry, BASE, attenuator_db=10.0, attenuator_slope_db_per_ghz=0.2)
    _, row, _, _ = results(runner)
    assert row["slope_db_per_ghz"] == pytest.approx(0.2, rel=0.02)
    assert row["min_attenuation_db"] == pytest.approx(10.0, abs=0.01)
    assert row["max_attenuation_db"] == pytest.approx(10.6, abs=0.01)
    assert row["flatness_db"] == pytest.approx(0.6, abs=0.02)
    assert row["max_at_hz"] == pytest.approx(3e9) and row["min_at_hz"] == pytest.approx(1e6)
    assert row["worst_deviation_db"] == pytest.approx(0.6, abs=0.01)
    assert row["verdict"] == "FAIL" and row["margin_db"] < 0  # 10.6 is above 10.5


def test_out_of_tolerance_is_a_result_not_an_error(registry):
    runner, _ = run(registry, BASE, attenuator_db=11.5)
    assert runner.state is RunState.FINISHED
    _, row, _, evs = results(runner)
    assert row["verdict"] == "FAIL" and row["worst_deviation_db"] == pytest.approx(1.5, abs=0.01)
    assert any(e.kind == "log" and "limit check" in e.data["message"] for e in evs)


def test_without_a_nominal_value_there_is_no_verdict(registry):
    p = params(attenuator={"label": "x"})
    del p["attenuator"]["nominal_db"], p["attenuator"]["tolerance_db"]
    _, row, _, _ = results(run(registry, p)[0])
    assert "verdict" not in row and "mean_deviation_db" not in row
    assert row["mean_attenuation_db"] == pytest.approx(10.0, abs=0.01)


def test_a_mask_replaces_the_tolerance(registry):
    p = params(limits={"bands": [{"from": 0, "to": 3e9, "min": 9, "max": 11}]})
    p["attenuator"]["tolerance_db"] = 0.01  # would fail, but the mask decides
    runner, _ = run(registry, p, attenuator_db=10.4)
    traces, row, _, _ = results(runner)
    assert row["verdict"] == "PASS"
    assert traces["attenuation_db"]["meta"]["limits"]["min"][0][1] == 9


def test_the_tolerance_band_is_drawn_on_the_curve(registry):
    traces, _, _, _ = results(run(registry, BASE)[0])
    limits = traces["attenuation_db"]["meta"]["limits"]
    assert limits["min"][0][1] == pytest.approx(9.5) and limits["max"][0][1] == pytest.approx(10.5)


def test_the_attenuation_at_chosen_frequencies_and_the_return_loss(registry):
    p = params(frequencies_of_interest=[433e6, 2.4e9])
    _, row, sweep, _ = results(
        run(registry, p, attenuator_db=10, attenuator_slope_db_per_ghz=0.1)[0]
    )
    assert row["attenuation_433MHz_db"] == pytest.approx(10.043, abs=0.01)
    assert row["attenuation_2.4GHz_db"] == pytest.approx(10.24, abs=0.01)
    assert row["min_input_return_loss_db"] == pytest.approx(34, abs=0.2)  # 20 log(1/0.02)
    assert row["min_output_return_loss_db"] == pytest.approx(34, abs=0.2)
    assert {"input_return_loss_db", "output_return_loss_db"} <= set(sweep[0])


def test_without_the_return_loss_only_s21_is_read(registry):
    runner, vna = run(registry, params(also_return_loss=False))
    traces, row, sweep, _ = results(runner)
    assert [c[1]["parameter"] for c in vna.calls if c[0] == "read_sparameter"] == ["S21"]
    assert "S11" not in traces and "min_input_return_loss_db" not in row
    assert "input_return_loss_db" not in sweep[0]


def test_the_setting_of_a_step_attenuator_is_written_in_the_result(registry):
    p = params(attenuator={"setting": "step 3 (20 dB)"})
    _, row, _, _ = results(run(registry, p)[0])
    assert row["setting"] == "step 3 (20 dB)"


def test_the_attenuator_is_connected_between_the_ports_after_the_question(registry):
    runner = Runner(registry.create("attenuator", params(confirm_setup=True)), {"vna": [SimVna()]})
    vna = runner.bindings["vna"][0]
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    q = runner.pending_questions[0]
    assert "between port 1 and port 2" in q["text"] and vna.calls == []
    runner.answer(q["id"], "abort")
    assert runner.join(10) and runner.state is RunState.STOPPED and vna.calls == []


def test_averaging_reads_every_parameter_each_time(registry):
    _, vna = run(registry, params(averages=3))
    assert len([c for c in vna.calls if c[0] == "read_sparameter"]) == 9


# ---- a card in the registry --------------------------------------------------------------------
def test_the_attenuator_card_and_its_label_line(tmp_path):
    from ola.assets import AssetRegistry
    from ola.labels import PRESETS, build_drawing, field_text, specs_text

    cards = AssetRegistry(tmp_path / "a.json")
    att = cards.create(
        "attenuator", "10 dB SMA #3",
        attributes={"nominal_db": 10, "max_frequency": 6e9, "max_power_w": 2, "tolerance_db": 0.5},
    )  # fmt: skip
    assert att.id == "ATT-0001"
    assert specs_text(att) == "10 dB, 6 GHz, 2 W" == field_text("specs", att)
    amp = cards.create("amplifier", "LNA", attributes={"nominal_gain_db": 20})
    assert specs_text(amp) == "20 dB gain"
    assert specs_text(cards.create("cable", "RG316")) == ""
    texts = [getattr(i, "text", "") for i in build_drawing(PRESETS["50x25"], att).items]
    assert "10 dB, 6 GHz, 2 W" in texts
