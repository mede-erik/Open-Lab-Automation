# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Antenna impedance: parameters, resonances, impedance, matching components, whole runs."""

import copy
import math

import pytest

from ola.form_model import load_form_spec
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimVna

PARAMS = {
    "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 601, "scale": "linear"},
    "device": {"label": "868 MHz whip #2"},
    "frequencies_of_interest": [840e6, 868e6, 900e6],
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


def run(registry, p, **sim):
    vna = SimVna(termination="antenna", **sim)
    runner = Runner(registry.create("antenna", p), {"vna": [vna]})
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
    return {x.path: x.message for x in registry.create("antenna", p).check()}


# ---- the module ---------------------------------------------------------------------------------
def test_the_module_is_found_with_an_editor(registry):
    info = registry.get("antenna")
    assert info.extension == ".ant" and info.name == "Antenna impedance"
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths


def test_parameters(registry):
    assert problems(registry, PARAMS) == {}
    assert "z0" in problems(registry, params(z0=0))
    assert "vswr_max" in problems(registry, params(vswr_max=1))
    assert "device.label" in problems(registry, params(device={"label": 1}))
    assert "frequencies_of_interest" in problems(registry, params(frequencies_of_interest=[2e9]))
    assert "sweep.points" in problems(registry, params(sweep={"points": 1}))


# ---- matching components ------------------------------------------------------------------------
def test_the_component_that_cancels_a_reactance():
    from importlib import util

    spec = util.spec_from_file_location("ant", "ola/modules/antenna/measurement.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cancel = module.cancelling_component
    # +j50 ohm at 100 MHz needs a capacitor of 1 / (2 pi 100e6 50) = 31.8 pF
    assert cancel(50, 100e6) == "series capacitor 31.831 pF"
    # -j62.8 ohm at 100 MHz needs an inductor of 62.8 / (2 pi 100e6) = 100 nH
    assert cancel(-2 * math.pi * 100e6 * 100e-9, 100e6) == "series inductor 100 nH"
    assert cancel(0.001, 100e6) == "none needed"


# ---- a measurement ------------------------------------------------------------------------------
def test_the_series_resonance_is_found_where_the_reactance_crosses_zero(registry):
    runner, vna = run(registry, PARAMS)
    assert runner.state is RunState.FINISHED, runner.error
    traces, row, sweep, _ = results(runner)
    assert row["series_resonance_hz"] == pytest.approx(868e6, abs=0.3e6)
    assert row["series_resonance_r_ohm"] == pytest.approx(55, abs=0.5)
    assert row["series_resonance_count"] == 1 and "MHz" in row["resonances"]
    assert row["min_vswr"] == pytest.approx(1.105, abs=0.01) and row[
        "best_match_at_hz"
    ] == pytest.approx(868e6, abs=0.5e6)
    assert row["device"] == "868 MHz whip #2" and len(sweep) == 601
    assert set(sweep[0]) == {"frequency_hz", "r_ohm", "x_ohm", "vswr", "return_loss_db"}


def test_the_reactance_is_negative_below_the_resonance_and_positive_above(registry):
    runner, vna = run(registry, PARAMS)
    _, row, _, _ = results(runner)
    # a series RLC: below resonance it is capacitive (X < 0), above inductive (X > 0)
    assert row["x_840MHz_ohm"] < -5 and row["x_900MHz_ohm"] > 5
    assert abs(row["x_868MHz_ohm"]) < 2
    # and what is reported equals the model
    z = vna.antenna[1:]  # (R, Q)
    r, q = z
    expected_x = q * r * (840e6 / 868e6 - 868e6 / 840e6)
    assert row["x_840MHz_ohm"] == pytest.approx(expected_x, abs=0.3)
    assert row["z_abs_840MHz_ohm"] == pytest.approx(
        math.hypot(row["r_840MHz_ohm"], row["x_840MHz_ohm"])
    )


def test_the_cancelling_component_follows_the_sign_of_the_reactance(registry):
    runner, _ = run(registry, PARAMS)
    _, row, _, _ = results(runner)
    assert row["cancel_840MHz"].startswith("series inductor")  # X < 0 below resonance
    assert row["cancel_900MHz"].startswith("series capacitor")  # X > 0 above
    assert isinstance(row["cancel_868MHz"], str)  # at the resonance there is little to cancel


def test_a_wider_antenna_has_a_larger_fractional_bandwidth(registry):
    wide = results(run(registry, PARAMS, antenna_q=6)[0])[1]["fractional_bandwidth_pct"]
    narrow = results(run(registry, PARAMS, antenna_q=30)[0])[1]["fractional_bandwidth_pct"]
    assert wide > 2 * narrow > 0


def test_the_usable_band_matches_the_return_loss_measurement(registry):
    row = results(run(registry, PARAMS)[0])[1]
    lo, hi = row["widest_band_from_hz"], row["widest_band_to_hz"]
    assert lo < 868e6 < hi and row["fractional_bandwidth_pct"] == pytest.approx(
        100 * (hi - lo) / ((hi + lo) / 2)
    )


def test_a_device_that_never_resonates_reports_it(registry):
    runner, _ = run(registry, PARAMS, antenna_f0_hz=300e6)  # resonates far below the sweep
    _, row, _, evs = results(runner)
    assert row["series_resonance_count"] == 0 and "series_resonance_hz" not in row
    assert any("no series resonance" in e.data["message"] for e in evs if e.kind == "log")


def test_an_antiresonance_is_reported_apart(registry):
    class Parallel(SimVna):
        """A parallel resonance: the reactance goes from positive to negative through zero."""

        def antenna_gamma(self, f):
            f0 = 868e6
            y = complex(1 / 300, 0.02 * (f / f0 - f0 / f))  # a parallel RLC: admittance
            z = 1 / y
            return (z - 50) / (z + 50)

    vna = Parallel(termination="antenna")
    runner = Runner(registry.create("antenna", PARAMS), {"vna": [vna]})
    runner.start()
    assert runner.join(20)
    _, row, _, _ = results(runner)
    assert "anti_resonances" in row and row["series_resonance_count"] == 0


def test_the_traces_and_the_view(registry):
    runner, _ = run(registry, params(limits={"min": 10}))
    traces, row, _, _ = results(runner)
    assert (
        traces["S11"]["meta"]["default_view"] == "smith" and "hidden" not in traces["S11"]["meta"]
    )
    assert {"resistance_ohm", "reactance_ohm", "return_loss_db", "vswr"} <= set(traces)
    assert all(traces[n]["meta"]["hidden"] for n in ("resistance_ohm", "reactance_ohm", "vswr"))
    assert traces["return_loss_db"]["meta"]["limits"]["view"] == "value"
    assert (
        row["verdict"] == "FAIL"
    )  # the whole sweep, far from the resonance, is not 10 dB everywhere


def test_the_question_asks_to_connect_the_antenna_to_port_1(registry):
    runner = Runner(
        registry.create("antenna", params(confirm_setup=True)),
        {"vna": [SimVna(termination="antenna")]},
        unattended="abort",
    )
    runner.start()
    assert runner.join(10) and runner.state is RunState.STOPPED
    q = [e.data for e in runner.drain() if e.kind == "question"][0]
    assert "antenna to port 1" in q["text"]
