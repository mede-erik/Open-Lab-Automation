# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""One de-embedding for every VNA measurement: the reflection measurements use the fixtures of
``ola.fixtures`` too (``deembed_one_port``), with the same numbers as the cable correction of
before, and the ``full`` model for a fixture with its own reflections. The amplifier and the cable
take fixtures out as the filter and the attenuator do."""

import cmath

import pytest

from ola import deembed, fixtures as fx, rf
from ola.efficiency_spec import Problem
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.runs import RunWriter
from ola.sim_vna import SimAmplifier, SimVna

FREQ = [800e6 + k * 1e6 for k in range(121)]
GRID = [700e6 + k * 1e6 for k in range(321)]
CABLE = dict(loss_db_per_m_at_1ghz=0.6, velocity_factor=0.66)


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def dut(f):
    """The reflection of an arbitrary device."""
    return 0.4 * cmath.exp(-1.3j * f / 1e9)


def pad(f):
    """A mismatched reciprocal two-port, as seen from the VNA: (s11, s21, s12, s22)."""
    x = f / 1e9
    s21 = 0.7 * cmath.exp(-0.8j * x)
    return 0.12 * cmath.exp(0.5j * x), s21, s21, 0.09 * cmath.exp(-0.3j * x)


def pad_fixture():
    sp = [pad(f) for f in GRID]
    return fx.Fixture(GRID, [s[1] for s in sp], [s[0] for s in sp], [s[3] for s in sp])


def through_pad(f):
    """What the VNA sees: the device behind the pad."""
    e00, s21, s12, e11 = pad(f)
    g = dut(f)
    return e00 + s21 * s12 * g / (1 - e11 * g)


def test_a_cable_gives_the_same_numbers_as_the_correction_of_before():
    s11 = [0.3 * cmath.exp(-2j * f / 1e9) for f in FREQ]
    t = [0.9 * cmath.exp(-3j * f / 1e9) for f in GRID]
    cables = (
        deembed.from_transmission(GRID, t, "t"),
        deembed.from_reflection(GRID, [v * v for v in t], "open", "r"),
        deembed.from_loss(GRID, [0.9] * len(GRID), "l"),
    )
    for cable in cables:
        mode = "complex" if cable.has_phase else "magnitude"
        before, old = deembed.correct_reflection(FREQ, s11, cable, mode)
        now, info = fx.deembed_one_port(FREQ, s11, fx.fixture_from_cable(cable), mode)
        assert now == pytest.approx(before, abs=1e-12), cable.source
        assert info["mean_one_way_loss_db"] == pytest.approx(old["mean_one_way_loss_db"])
        assert info["over_unity_points"] == old["over_unity_points"]


def test_the_full_model_takes_out_the_reflections_of_the_fixture():
    measured = [through_pad(f) for f in FREQ]
    full, info = fx.deembed_one_port(FREQ, measured, pad_fixture(), "complex", "full")
    assert full == pytest.approx([dut(f) for f in FREQ], abs=1e-9)
    assert info["model"] == "full" and info["mean_one_way_loss_db"] == pytest.approx(3.1, abs=0.1)
    matched, _ = fx.deembed_one_port(FREQ, measured, pad_fixture(), "complex", "matched")
    assert max(abs(a - dut(f)) for a, f in zip(matched, FREQ)) > 0.05  # only approximate


def test_what_the_one_port_correction_needs():
    measured = [through_pad(f) for f in FREQ]
    no_phase = fx.fixture_from_cable(deembed.from_loss(GRID, [3.0] * len(GRID), "loss"))
    with pytest.raises(deembed.DeembedError, match="magnitude"):
        fx.deembed_one_port(FREQ, measured, no_phase, "complex")
    with pytest.raises(deembed.DeembedError, match="no reflections"):
        cable = fx.fixture_from_cable(deembed.from_transmission(GRID, [0.9] * len(GRID), "c"))
        fx.deembed_one_port(FREQ, measured, cable, "complex", "full")
    short = fx.Fixture([900e6, 950e6], [0.9, 0.9])
    with pytest.raises(deembed.DeembedError, match="does not cover"):
        fx.deembed_one_port(FREQ, measured, short)


def check(correction):
    out = []
    deembed.check_correction({"correction": correction}, out, Problem)
    return {p.path: p.message for p in out}


def test_the_correction_of_a_reflection_measurement_names_port1_or_cable():
    assert check({"port1": {"touchstone": "pad.s2p"}, "model": "full"}) == {}
    assert check({"cable": {"run": "a.jsonl"}, "mode": "magnitude"}) == {}  # as written before
    assert "not both" in check({"port1": {"run": "a"}, "cable": {"run": "b"}})["correction"]
    assert "one port" in check({"port1": {"run": "a"}, "port2": {"run": "b"}})["correction.port2"]
    assert "matched" in check({"port1": {"run": "a"}, "model": "exact"})["correction.model"]


def test_a_return_loss_behind_a_pad_with_the_full_model(registry, tmp_path):
    """A .s2p of a pad with its reflections, taken out of a return loss with the full model."""
    sp = [pad(f) for f in GRID]
    path = tmp_path / "pad.s2p"
    names = ("S11", "S21", "S12", "S22")
    rf.write_touchstone(path, GRID, {n: [s[i] for s in sp] for i, n in enumerate(names)})
    loaded = fx.load_one_port_fixture({"touchstone": str(path)})
    assert loaded.has_reflections
    params = {
        "sweep": {"start_hz": 800e6, "stop_hz": 920e6, "points": 121},
        "correction": {"port1": {"touchstone": str(path)}, "model": "full"},
        "confirm_setup": False,
    }
    measurement = registry.create("return_loss", params)
    assert measurement.validate() == []
    runner = Runner(measurement, {"vna": [SimVna(termination="load")]})
    runner.start()
    assert runner.join(30)
    logs = [e.data["message"] for e in runner.drain() if e.kind == "log"]
    assert runner.state is RunState.FINISHED, runner.error
    assert any("corrected for the fixture pad.s2p (full, complex" in m for m in logs), logs


def cable_run(tmp_path, length=3.0):
    """A finished cable measurement of a cable of ``length`` metres, in transmission."""
    reg = default_registry(user_dir="/nonexistent")
    params = {
        "sweep": {"start_hz": 1e6, "stop_hz": 1.2e9, "points": 1201},
        "cable": {"label": "feed", "length_m": length},
        "confirm_setup": False,
    }
    runner = Runner(reg.create("cable", params), {"vna": [SimVna(**CABLE, length_m=length)]})
    path = tmp_path / f"cable_{length:g}m.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(60) and runner.state is RunState.FINISHED, runner.error
    return path


def summary(registry, module, params, vna):
    runner = Runner(registry.create(module, params), {"vna": [vna]})
    runner.start()
    assert runner.join(60)
    events = runner.drain()
    assert runner.state is RunState.FINISHED, runner.error
    rows = [e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "points"]
    logs = [e.data["message"] for e in events if e.kind == "log"]
    traces = {e.data["name"] for e in events if e.kind == "trace"}
    return rows[-1], logs, traces


def test_the_amplifier_is_measured_alone_through_a_cable(registry, tmp_path):
    feed = cable_run(tmp_path)
    params = {
        "sweep": {"start_hz": 700e6, "stop_hz": 1050e6, "points": 351, "power_dbm": -30},
        "frequencies_of_interest": [868e6],
        "confirm_setup": False,
    }
    alone, _, _ = summary(registry, "amplifier", params, SimAmplifier())
    seen, _, _ = summary(registry, "amplifier", params, SimAmplifier(**CABLE, fixture1_m=3.0))
    assert seen["gain_868MHz_db"] < alone["gain_868MHz_db"] - 1.0  # the cable is charged
    corrected, logs, traces = summary(
        registry,
        "amplifier",
        dict(params, correction={"port1": {"run": str(feed)}}),
        SimAmplifier(**CABLE, fixture1_m=3.0),
    )
    assert corrected["gain_868MHz_db"] == pytest.approx(alone["gain_868MHz_db"], abs=0.05)
    assert "S21_raw" in traces and any("corrected for the fixtures" in m for m in logs)


def test_the_compression_takes_the_fixtures_out_as_losses(registry, tmp_path):
    feed = cable_run(tmp_path)
    comp = {"frequency_hz": 868e6, "start_dbm": -40, "stop_dbm": 0, "step_db": 1}
    params = {
        "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 31, "power_dbm": -40},
        "compression": comp,
        "confirm_setup": False,
    }
    alone, _, _ = summary(registry, "amplifier", params, SimAmplifier())
    corrected, logs, _ = summary(
        registry,
        "amplifier",
        dict(params, correction={"port1": {"run": str(feed)}}),
        SimAmplifier(**CABLE, fixture1_m=3.0),
    )
    loss = fx.losses_at({"correction": {"port1": {"run": str(feed)}}}, 868e6)["left"]
    assert loss > 1.0 and any("taken out as losses" in m for m in logs)
    gain_alone, gain_now = alone["small_signal_gain_db"], corrected["small_signal_gain_db"]
    assert gain_now == pytest.approx(gain_alone, abs=0.1)
    # the cable lowers the power that reaches the amplifier: the same compression happens at a
    # VNA power higher by the loss, and is reported at the amplifier input
    assert corrected["p1db_input_dbm"] == pytest.approx(alone["p1db_input_dbm"], abs=0.6)


def test_a_cable_is_measured_without_the_adapter_in_front_of_it(registry, tmp_path):
    adapter = cable_run(tmp_path, length=1.0)  # a 1 m piece between port 1 and the cable
    params = {
        "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 1001},
        "cable": {"label": "under test", "length_m": 2.0},
        "frequencies_of_interest": [500e6],
        "confirm_setup": False,
    }
    alone, _, _ = summary(registry, "cable", params, SimVna(**CABLE, length_m=2.0))
    corrected, logs, _ = summary(
        registry,
        "cable",
        dict(params, correction={"port1": {"run": str(adapter)}}),
        SimVna(**CABLE, length_m=3.0),  # the 2 m under test behind 1 m of the same cable
    )
    assert corrected["loss_500MHz_db"] == pytest.approx(alone["loss_500MHz_db"], abs=0.02)
    assert any("corrected for the fixtures" in m for m in logs)
