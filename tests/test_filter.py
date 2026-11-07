# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Filter response: parameters, the edges, bandwidth and Q, and whole runs on a simulated filter."""

import copy
import time

import pytest

from ola.form_model import load_form_spec
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimVna

LOWPASS = {
    "filter": {"type": "lowpass", "label": "LPF 100 MHz"},
    "sweep": {"start_hz": 1e6, "stop_hz": 400e6, "points": 800, "scale": "linear"},
    "confirm_setup": False,
}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(base=LOWPASS, **changes):
    p = copy.deepcopy(base)
    for key, value in changes.items():
        if key in ("sweep", "filter") and isinstance(value, dict):
            p[key].update(value)
        else:
            p[key] = value
    return p


def run(registry, p, **sim):
    sim.setdefault("filter_type", p["filter"]["type"])
    sim.setdefault("filter_loss_db", 0.0)
    vna = SimVna(**sim)
    runner = Runner(registry.create("filter", p), {"vna": [vna]})
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
    return {x.path: x.message for x in registry.create("filter", p).check()}


def butterworth_edge(order, edge_db=3.0):
    """Where a normalised Butterworth response is ``edge_db`` down: 1 / (1 + x^2n) = 10^-edge/10."""
    return (10 ** (edge_db / 10) - 1) ** (1 / (2 * order))


# ---- the module --------------------------------------------------------------------------------
def test_the_module_is_found_with_an_editor(registry):
    info = registry.get("filter")
    assert info.extension == ".flt" and info.name == "Filter"
    assert registry.by_extension(".flt").id == "filter"
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths, set(info.params_schema) - paths


def test_good_parameters_have_no_problems(registry):
    assert problems(registry, LOWPASS) == {}


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"filter": {"type": "notch"}}, "filter.type", "one of"),
        ({"filter": {"label": 3}}, "filter.label", "text"),
        ({"filter": "lowpass"}, "filter", "missing"),
        ({"edge_db": 0}, "edge_db", "above 0"),
        ({"passband": {"from_hz": 5e6}}, "passband", "from_hz below to_hz"),
        ({"passband": {"from_hz": 9e6, "to_hz": 5e6}}, "passband", "from_hz below to_hz"),
        ({"passband": {"from_hz": 1e3, "to_hz": 5e6}}, "passband", "inside the sweep"),
        ({"sweep": {"stop_hz": 5e5}}, "sweep.stop_hz", "above the start"),
        ({"frequencies_of_interest": [1e9]}, "frequencies_of_interest", "outside the sweep"),
        ({"limits": {"max": "low"}}, "limits", "must be a number"),
        ({"also_s11": "yes"}, "also_s11", "true or false"),
    ],
)
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = problems(registry, params(**changes))
    assert path in found and words in found[path]


# ---- the four kinds of filter ------------------------------------------------------------------
def test_low_pass_cutoff_is_where_the_gain_is_3_db_down(registry):
    runner, _ = run(registry, LOWPASS, filter_f0_hz=100e6, filter_order=4)
    assert runner.state is RunState.FINISHED, runner.error
    _, row, _, _ = results(runner)
    assert row["cutoff_hz"] == pytest.approx(100e6 * butterworth_edge(4), rel=0.003)
    assert row["insertion_loss_db"] == pytest.approx(0, abs=0.01)
    assert row["type"] == "lowpass" and row["filter"] == "LPF 100 MHz"
    assert "f_low_hz" not in row and "q_factor" not in row


def test_the_edge_level_is_relative_to_the_peak_not_to_zero_db(registry):
    """A filter with 1.5 dB of insertion loss: -3 dB is measured from its own peak."""
    runner, _ = run(registry, LOWPASS, filter_f0_hz=100e6, filter_order=4, filter_loss_db=1.5)
    _, row, _, _ = results(runner)
    assert row["insertion_loss_db"] == pytest.approx(1.5, abs=0.01)
    assert row["cutoff_hz"] == pytest.approx(100e6 * butterworth_edge(4), rel=0.003)
    runner, _ = run(registry, params(edge_db=1), filter_f0_hz=100e6, filter_order=4)
    assert results(runner)[1]["cutoff_hz"] == pytest.approx(
        100e6 * butterworth_edge(4, 1), rel=0.005
    )


def test_high_pass_cutoff(registry):
    p = params(filter={"type": "highpass"}, sweep={"start_hz": 10e6, "stop_hz": 400e6})
    runner, _ = run(registry, p, filter_f0_hz=100e6, filter_order=4)
    _, row, _, _ = results(runner)
    assert row["cutoff_hz"] == pytest.approx(100e6 / butterworth_edge(4), rel=0.003)


def test_band_pass_edges_bandwidth_centre_and_q(registry):
    p = params(
        filter={"type": "bandpass"},
        sweep={"start_hz": 800e6, "stop_hz": 940e6, "points": 561},
    )
    runner, _ = run(registry, p, filter_f0_hz=868e6, filter_bw_hz=20e6, filter_order=3)
    _, row, _, _ = results(runner)
    assert row["f_low_hz"] < 868e6 < row["f_high_hz"]
    assert row["center_hz"] == pytest.approx(868e6, rel=0.001)
    assert row["bandwidth_hz"] == pytest.approx(20e6 * butterworth_edge(3), rel=0.02)
    assert row["q_factor"] == pytest.approx(row["center_hz"] / row["bandwidth_hz"])
    assert row["peak_at_hz"] == pytest.approx(868e6, abs=0.5e6)


def test_band_stop_notch_depth_edges_and_q(registry):
    p = params(
        filter={"type": "bandstop"},
        sweep={"start_hz": 800e6, "stop_hz": 940e6, "points": 560},  # no point exactly on 868 MHz
    )
    runner, _ = run(registry, p, filter_f0_hz=868e6, filter_bw_hz=20e6, filter_order=3)
    _, row, _, _ = results(runner)
    assert row["notch_at_hz"] == pytest.approx(868e6, abs=0.5e6) and row["notch_depth_db"] > 40
    assert row["f_low_hz"] < 868e6 < row["f_high_hz"]
    assert row["bandwidth_hz"] > 10e6 and row["q_factor"] == pytest.approx(
        868e6 / row["bandwidth_hz"], rel=0.01
    )


def test_the_gain_at_the_frequencies_of_interest(registry):
    p = params(frequencies_of_interest=[50e6, 200e6])
    runner, _ = run(registry, p, filter_f0_hz=100e6, filter_order=4)
    _, row, _, _ = results(runner)
    assert row["gain_50MHz_db"] == pytest.approx(-0.017, abs=0.01)
    assert row["gain_200MHz_db"] == pytest.approx(-24.1, abs=0.3)  # 10 log(1 + 2^8)


def test_ripple_in_the_passband_and_the_reference_level(registry):
    p = params(passband={"from_hz": 1e6, "to_hz": 50e6})
    runner, _ = run(registry, p, filter_f0_hz=100e6, filter_order=4)
    _, row, _, _ = results(runner)
    assert 0 <= row["passband_ripple_db"] < 0.05  # Butterworth is flat there
    assert "passband_ripple_db" not in results(run(registry, LOWPASS, filter_f0_hz=100e6)[0])[1]


def test_the_return_loss_with_s11(registry):
    p = params(also_s11=True, passband={"from_hz": 1e6, "to_hz": 50e6})
    runner, vna = run(registry, p, filter_f0_hz=100e6)
    traces, row, _, _ = results(runner)
    assert row["min_return_loss_db"] == pytest.approx(33.98, abs=0.5)  # the simulated 0.02 mismatch
    assert traces["S11"]["meta"]["hidden"] is True
    assert [c[1]["parameter"] for c in vna.calls[1:]] == ["S21", "S11"]


# ---- when an edge is not in the sweep ----------------------------------------------------------
def test_an_edge_outside_the_sweep_is_left_out_and_said(registry):
    p = params(sweep={"start_hz": 1e6, "stop_hz": 50e6})  # the gain never falls 3 dB
    runner, _ = run(registry, p, filter_f0_hz=100e6)
    assert runner.state is RunState.FINISHED
    _, row, _, evs = results(runner)
    assert "cutoff_hz" not in row
    warnings = [e.data["message"] for e in evs if e.kind == "log" and e.data["level"] == "warning"]
    assert any("could not find the cut-off" in w and "widen the sweep" in w for w in warnings)


def test_a_band_pass_with_one_edge_outside_reports_the_other(registry):
    p = params(
        filter={"type": "bandpass"}, sweep={"start_hz": 860e6, "stop_hz": 940e6, "points": 401}
    )
    runner, _ = run(registry, p, filter_f0_hz=868e6, filter_bw_hz=20e6, filter_order=3)
    _, row, _, _ = results(runner)
    assert "f_high_hz" in row and "f_low_hz" not in row and "q_factor" not in row


# ---- traces, tables and the mask ---------------------------------------------------------------
def test_s21_is_the_visible_curve_and_the_rest_start_hidden(registry):
    runner, _ = run(registry, params(also_s11=True), filter_f0_hz=100e6)
    traces, _, sweep, _ = results(runner)
    assert traces["S21"]["trace_kind"] == "complex" and "hidden" not in traces["S21"]["meta"]
    assert traces["group_delay_ns"]["meta"]["hidden"] is True
    assert len(sweep) == 800 and set(sweep[0]) == {"frequency_hz", "gain_db", "phase_deg"}
    assert sweep[0]["gain_db"] == pytest.approx(0, abs=0.01)


def test_a_mask_passes_or_fails_and_is_drawn_on_the_magnitude_view(registry):
    mask = {
        "bands": [{"from": 1e6, "to": 50e6, "min": -1}, {"from": 250e6, "to": 400e6, "max": -30}]
    }
    runner, _ = run(registry, params(limits=mask), filter_f0_hz=100e6, filter_order=4)
    traces, row, _, _ = results(runner)
    assert row["verdict"] == "PASS" and row["margin_db"] > 0
    meta = traces["S21"]["meta"]["limits"]
    assert meta["view"] == "magnitude_db" and "min" in meta and "max" in meta
    tight = {"bands": [{"from": 1e6, "to": 120e6, "min": -1}]}  # the cut-off is inside this band
    runner, _ = run(registry, params(limits=tight), filter_f0_hz=100e6, filter_order=4)
    assert runner.state is RunState.FINISHED  # a failed mask is a result
    _, row, _, evs = results(runner)
    assert row["verdict"] == "FAIL" and row["margin_db"] < 0
    assert any(
        "FAIL" in e.data["message"] for e in evs if e.kind == "log" and e.data["level"] == "warning"
    )


def test_without_a_mask_there_is_no_verdict(registry):
    assert "verdict" not in results(run(registry, LOWPASS, filter_f0_hz=100e6)[0])[1]


# ---- the question and the sweep ----------------------------------------------------------------
def test_the_filter_is_connected_between_the_ports_after_the_question(registry):
    runner = Runner(registry.create("filter", params(confirm_setup=True)), {"vna": [SimVna()]})
    vna = runner.bindings["vna"][0]
    runner.start()
    deadline = time.time() + 5
    while not runner.pending_questions and time.time() < deadline:
        time.sleep(0.01)
    q = runner.pending_questions[0]
    assert "between port 1 and port 2" in q["text"] and vna.calls == []
    runner.answer(q["id"], "abort")
    assert runner.join(10) and runner.state is RunState.STOPPED and vna.calls == []
