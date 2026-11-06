"""Return loss / VSWR: parameters, calculations and whole runs on a simulated antenna."""

import copy
import math
import time

import pytest

from ola import rf
from ola.form_model import load_form_spec
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimVna

PARAMS = {
    "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 301, "scale": "linear"},
    "device": {"label": "868 MHz antenna #2"},
    "z0": 50,
    "vswr_max": 2.0,
    "frequencies_of_interest": [868e6, 900e6],
    "confirm_setup": False,
}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def antenna(**kw):
    return SimVna(termination="antenna", **kw)


def params(**changes):
    p = copy.deepcopy(PARAMS)
    for key, value in changes.items():
        if key == "sweep":
            p["sweep"].update(value)
        else:
            p[key] = value
    return p


def run(registry, p, vna=None, **runner_kw):
    vna = vna or antenna()
    runner = Runner(registry.create("return_loss", p), {"vna": [vna]}, **runner_kw)
    runner.start()
    assert runner.join(20)
    return runner, vna


def results(runner):
    evs = runner.drain()
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    row = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    sweep = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "sweep"]
    return traces, (row[0] if row else None), sweep, evs


def problems(registry, p):
    return {x.path: x.message for x in registry.create("return_loss", p).check()}


# ---- the module ---------------------------------------------------------------------------------
def test_the_module_is_found(registry):
    info = registry.get("return_loss")
    assert info.extension == ".rtl" and info.name == "Return loss / VSWR"
    assert [(r.name, r.category, r.required) for r in info.roles] == [("vna", "network_analyzer", True)]
    assert registry.by_extension(".rtl").id == "return_loss"
    assert load_form_spec(info) is not None  # it has an editor


def test_every_parameter_of_the_module_has_a_field_in_the_form(registry):
    info = registry.get("return_loss")
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths, set(info.params_schema) - paths


# ---- parameters ---------------------------------------------------------------------------------
def test_good_parameters_have_no_problems(registry):
    assert problems(registry, PARAMS) == {}


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"sweep": {"stop_hz": 700e6}}, "sweep.stop_hz", "above the start"),
        ({"sweep": {"points": 1}}, "sweep.points", "from 2"),
        ({"z0": 0}, "z0", "above 0"),
        ({"z0": "fifty"}, "z0", "above 0"),
        ({"vswr_max": 1}, "vswr_max", "above 1"),
        ({"device": {"label": 3}}, "device.label", "text"),
        ({"device": "antenna"}, "device", "object"),
        ({"frequencies_of_interest": [2e9]}, "frequencies_of_interest", "outside the sweep"),
        ({"limits": {"minimum": 10}}, "limits", "unknown limit key"),
        ({"averages": 0}, "averages", "from 1"),
        ({"confirm_setup": 1}, "confirm_setup", "true or false"),
    ],
)
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = problems(registry, params(**changes))
    assert path in found and words in found[path]


# ---- calculations -------------------------------------------------------------------------------
def test_the_best_match_is_at_the_resonance_of_the_antenna(registry):
    runner, vna = run(registry, PARAMS)
    assert runner.state is RunState.FINISHED, runner.error
    traces, row, sweep, _ = results(runner)
    assert row["device"] == "868 MHz antenna #2"
    assert row["best_at_hz"] == pytest.approx(868e6, abs=0.6e6)
    gamma = abs((55 - 50) / (55 + 50))  # at resonance the antenna is 55 ohm
    assert row["best_return_loss_db"] == pytest.approx(-20 * math.log10(gamma), abs=0.3)
    assert row["min_vswr"] == pytest.approx(1.105, abs=0.01)
    assert row["z_real_ohm"] == pytest.approx(55, abs=1) and abs(row["z_imag_ohm"]) < 3
    assert row["worst_return_loss_db"] < row["best_return_loss_db"]
    assert {"S11", "return_loss_db", "vswr"} <= set(traces) and "S21" not in traces
    assert len(sweep) == 301 and set(sweep[0]) == {
        "frequency_hz", "return_loss_db", "vswr", "z_real_ohm", "z_imag_ohm"
    }  # fmt: skip


def test_the_usable_band_is_where_the_vswr_is_under_the_limit(registry):
    runner, vna = run(registry, PARAMS)
    _, row, _, _ = results(runner)
    assert row["usable_band_count"] == 1
    lo, hi = row["widest_band_from_hz"], row["widest_band_to_hz"]
    assert lo < 868e6 < hi and row["widest_band_hz"] == pytest.approx(hi - lo)
    # the edges of the band are where the VSWR is 2 (found between points)
    for edge in (lo, hi):
        assert rf.vswr([abs(vna.antenna_gamma(edge))])[0] == pytest.approx(2.0, abs=0.05)
    assert "to" in row["usable_bands"] and "MHz" in row["usable_bands"]


def test_a_narrower_antenna_has_a_narrower_band(registry):
    wide = results(run(registry, PARAMS, antenna(antenna_q=6))[0])[1]["widest_band_hz"]
    narrow = results(run(registry, PARAMS, antenna(antenna_q=30))[0])[1]["widest_band_hz"]
    assert narrow < wide / 2


def test_values_at_the_frequencies_of_interest(registry):
    runner, vna = run(registry, PARAMS)
    _, row, _, _ = results(runner)
    g = abs(vna.antenna_gamma(900e6))
    assert row["return_loss_900MHz_db"] == pytest.approx(rf.return_loss_db([g])[0], abs=0.1)
    assert row["vswr_900MHz"] == pytest.approx(rf.vswr([g])[0], rel=0.02)
    assert row["return_loss_868MHz_db"] > row["return_loss_900MHz_db"]


def test_a_device_that_is_never_matched_reports_no_band_and_says_so(registry):
    runner, _ = run(registry, PARAMS, antenna(antenna_r_ohm=500, antenna_q=0.1))
    _, row, _, evs = results(runner)
    assert row["usable_band_count"] == 0 and "widest_band_hz" not in row
    assert any(
        e.kind == "log" and "above 2" in e.data["message"] and e.data["level"] == "warning"
        for e in evs
    )


def test_an_open_circuit_gives_a_capped_vswr_not_infinity(registry):
    class Open(SimVna):
        def _read(self, parameter):
            data = super()._read(parameter)
            return {"frequency": data["frequency"], "values": [[1.0, 0.0]] * len(data["values"])}

    runner, _ = run(registry, PARAMS, Open())
    traces, row, _, _ = results(runner)
    assert max(traces["vswr"]["y"]) == 100.0 and row["max_vswr"] == 100.0
    assert row["best_return_loss_db"] == pytest.approx(0, abs=1e-6)


def test_the_traces_start_as_the_module_asks(registry):
    runner, _ = run(registry, params(limits={"min": 10}))
    traces, _, _, _ = results(runner)
    assert traces["S11"]["meta"]["hidden"] is True and traces["vswr"]["meta"]["hidden"] is True
    assert "hidden" not in traces["return_loss_db"]["meta"]
    assert traces["return_loss_db"]["meta"]["ylabel"] == "Return loss (dB)"


# ---- limits -------------------------------------------------------------------------------------
def test_a_minimum_return_loss_in_the_band_passes_or_fails(registry):
    ok = results(
        run(registry, params(limits={"bands": [{"from": 860e6, "to": 876e6, "min": 10}]}))[0]
    )
    assert ok[1]["verdict"] == "PASS" and ok[1]["margin_db"] > 0
    limits = ok[0]["return_loss_db"]["meta"]["limits"]
    assert limits["view"] == "value" and "min" in limits and "max" not in limits
    bad_runner, _ = run(
        registry, params(limits={"min": 10})
    )  # the whole sweep, far from the resonance
    assert bad_runner.state is RunState.FINISHED  # a failed limit is a result
    _, row, _, evs = results(bad_runner)
    assert row["verdict"] == "FAIL" and row["margin_db"] < 0
    assert any(
        "FAIL" in e.data["message"] and e.data["level"] == "warning" for e in evs if e.kind == "log"
    )


def test_without_limits_there_is_no_verdict(registry):
    assert "verdict" not in results(run(registry, PARAMS)[0])[1]


# ---- the question and the sweep -----------------------------------------------------------------
def test_the_set_up_is_asked_first_and_nothing_is_sent_before_the_answer(registry):
    runner = Runner(
        registry.create("return_loss", params(confirm_setup=True)), {"vna": [antenna()]}
    )
    vna = runner.bindings["vna"][0]
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    q = runner.pending_questions[0]
    assert q["data"]["kind"] == "calibration" and vna.calls == []
    assert "port 1" in q["text"] and "calibrated" in q["text"]
    runner.answer(q["id"], "abort")
    assert runner.join(10) and runner.state is RunState.STOPPED and vna.calls == []


def test_the_sweep_goes_to_the_vna_and_s11_is_read(registry):
    _, vna = run(registry, params(sweep={"scale": "log", "if_bandwidth_hz": 300, "power_dbm": -20}))
    assert vna.calls[0] == (
        "set_sweep",
        {"start_frequency": 800e6, "stop_frequency": 950e6, "points": 301, "sweep_type": "log",
         "if_bandwidth": 300, "power": -20},
    )  # fmt: skip
    assert [c for c in vna.calls[1:]] == [("read_sparameter", {"parameter": "S11"})]


def test_averaging_reads_the_sweep_several_times(registry):
    _, vna = run(registry, params(averages=4))
    assert [c[0] for c in vna.calls] == ["set_sweep"] + ["read_sparameter"] * 4
