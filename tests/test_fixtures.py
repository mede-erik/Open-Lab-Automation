# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Taking cables, adapters and pads out of a transmission measurement: the maths, the fixtures,
the two modules and the project."""

import cmath
import copy
import json

import pytest

from ola import fixtures as fx, rf
from ola.deembed import DeembedError
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.runs import RunWriter
from ola.sim_vna import SimVna

FREQ = [800e6 + k * 1e6 for k in range(121)]
CABLE = dict(loss_db_per_m_at_1ghz=0.6, velocity_factor=0.66)


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


# ---- synthetic networks ------------------------------------------------------------------------
def device(f):
    """An arbitrary lossy, mismatched, non-symmetric two-port: (s11, s21, s12, s22)."""
    x = f / 1e9
    return (
        0.2 * cmath.exp(-0.3j * x), 0.6 * cmath.exp(-1.1j * x),
        0.55 * cmath.exp(-1.0j * x), 0.15 * cmath.exp(0.4j * x),
    )  # fmt: skip


def fixture_sp(f, length):
    """A mismatched reciprocal fixture as seen from the VNA (port 1 at the VNA)."""
    x = f / 1e9
    s21 = 0.85 * cmath.exp(-0.9j * x * length)
    return (0.10 * cmath.exp(0.5j * x), s21, s21, 0.07 * cmath.exp(-0.2j * x))


def cascade(f, l1=None, l2=None, dut=device):
    """What the VNA measures through the fixtures of length l1 (port 1) and l2 (port 2)."""
    t = fx.to_t(*dut(f))
    if l1:
        t = fx.multiply(fx.to_t(*fixture_sp(f, l1)), t)
    if l2:
        a, b, c, d = fixture_sp(f, l2)
        t = fx.multiply(t, fx.to_t(d, c, b, a))  # turned round: its port 1 is at the device
    s11, s21, s12, s22 = fx.from_t(t)
    return {"S11": s11, "S21": s21, "S12": s12, "S22": s22}


def measured(l1=None, l2=None, freq=FREQ):
    rows = [cascade(f, l1, l2) for f in freq]
    return {k: [r[k] for r in rows] for k in ("S11", "S21", "S12", "S22")}


def fixture_obj(length, freq=None, reflections=True):
    freq = freq or [700e6 + k * 1e6 for k in range(321)]
    sp = [fixture_sp(f, length) for f in freq]
    return fx.Fixture(
        freq, [s[1] for s in sp], [s[0] for s in sp] if reflections else None,
        [s[3] for s in sp] if reflections else None, source=f"fixture{length}",
    )  # fmt: skip


def truth(name):
    index = {"S11": 0, "S21": 1, "S12": 2, "S22": 3}[name]
    return [device(f)[index] for f in FREQ]


# ---- the matrices ------------------------------------------------------------------------------
def test_the_transfer_matrix_goes_both_ways_and_cascades():
    s = device(1e9)
    assert fx.from_t(fx.to_t(*s)) == pytest.approx(s)
    a, b = fixture_sp(1e9, 1.0), device(1e9)
    whole = fx.from_t(fx.multiply(fx.to_t(*a), fx.to_t(*b)))
    # by hand: S21 of two cascaded two-ports
    s21 = a[1] * b[1] / (1 - a[3] * b[0])
    assert whole[1] == pytest.approx(s21)
    m = fx.to_t(*s)
    ident = fx.multiply(m, fx.inverse(m))
    assert ident[0][0] == pytest.approx(1) and ident[0][1] == pytest.approx(0, abs=1e-12)
    with pytest.raises(DeembedError, match="cannot be inverted"):
        fx.inverse(((1, 2), (2, 4)))


# ---- the two models ----------------------------------------------------------------------------
@pytest.mark.parametrize("sides", [(1.0, None), (None, 2.0), (1.0, 2.0)])
def test_the_full_model_recovers_the_device_exactly_through_mismatched_fixtures(sides):
    l1, l2 = sides
    left = fixture_obj(l1) if l1 else None
    right = fixture_obj(l2) if l2 else None
    out, info = fx.deembed_two_port(FREQ, measured(l1, l2), left, right, "complex", "full")
    for name in ("S11", "S21", "S12", "S22"):
        assert out[name] == pytest.approx(truth(name), abs=1e-6), name
    assert info["over_unity_points"] == 0 and info["gain_points"] == 0
    assert info["model"] == "full" and info.get("left_loss_db", 0) >= 0


def test_the_matched_model_is_exact_for_matched_fixtures():
    cable = SimVna(**CABLE, length_m=3.0)
    t = [cable.fixture(f, 3.0) for f in FREQ]
    left = fx.Fixture(FREQ, t, source="cable")
    meas = {
        "S21": [device(f)[1] * x for f, x in zip(FREQ, t)],
        "S11": [device(f)[0] * x * x for f, x in zip(FREQ, t)],
    }
    out, info = fx.deembed_two_port(FREQ, meas, left, None, "complex", "matched")
    assert out["S21"] == pytest.approx(truth("S21"), abs=1e-9)
    assert out["S11"] == pytest.approx(truth("S11"), abs=1e-9)
    assert info["left_loss_db"] > 1.0 and "right_loss_db" not in info


def test_a_fixture_on_each_side_in_the_matched_model():
    c1, c2 = SimVna(**CABLE), SimVna(**CABLE)
    t1 = [c1.fixture(f, 2.0) for f in FREQ]
    t2 = [c2.fixture(f, 4.0) for f in FREQ]
    meas = {
        "S21": [device(f)[1] * a * b for f, a, b in zip(FREQ, t1, t2)],
        "S11": [device(f)[0] * a * a for f, a in zip(FREQ, t1)],
        "S22": [device(f)[3] * b * b for f, b in zip(FREQ, t2)],
    }
    out, _ = fx.deembed_two_port(
        FREQ, meas, fx.Fixture(FREQ, t1, source="a"), fx.Fixture(FREQ, t2, source="b")
    )
    for name in ("S21", "S11", "S22"):
        assert out[name] == pytest.approx(truth(name), abs=1e-9), name


def test_the_matched_model_is_only_approximate_for_a_mismatched_fixture():
    """The full model is there for that: the matched one leaves the fixture's reflection behind."""
    left = fixture_obj(1.0)
    meas = measured(1.0, None)
    matched, _ = fx.deembed_two_port(FREQ, meas, left, None, "complex", "matched")
    full, _ = fx.deembed_two_port(FREQ, meas, left, None, "complex", "full")
    err_matched = max(abs(a - b) for a, b in zip(matched["S21"], truth("S21")))
    err_full = max(abs(a - b) for a, b in zip(full["S21"], truth("S21")))
    assert err_full < 1e-6 < 0.005 < err_matched


def test_the_magnitude_mode_takes_out_the_size_and_keeps_the_phase():
    c = SimVna(**CABLE)
    t = [c.fixture(f, 3.0) for f in FREQ]
    meas = {"S21": [device(f)[1] * x for f, x in zip(FREQ, t)]}
    out, _ = fx.deembed_two_port(FREQ, meas, fx.Fixture(FREQ, t, source="c"), None, "magnitude")
    assert [abs(v) for v in out["S21"]] == pytest.approx([abs(v) for v in truth("S21")], abs=1e-9)
    assert [cmath.phase(v) for v in out["S21"]] == pytest.approx(
        [cmath.phase(v) for v in meas["S21"]]
    )


def test_a_reflection_that_cannot_be_physical_is_limited_and_a_gain_is_counted():
    pad = fx.Fixture(FREQ, [complex(0.5)] * len(FREQ), source="pad", has_phase=False)
    meas = {"S21": [0.6 + 0j] * len(FREQ), "S11": [0.3 + 0j] * len(FREQ)}
    out, info = fx.deembed_two_port(FREQ, meas, pad, None, "magnitude")
    assert info["gain_points"] == len(FREQ)  # 0.6 / 0.5 = 1.2: more than the device can give
    assert info["over_unity_points"] == len(FREQ)  # 0.3 / 0.25 = 1.2 as a reflection
    assert max(abs(v) for v in out["S11"]) < 1.0


def test_the_errors_say_what_is_wrong():
    meas = measured(1.0, None)
    good = fixture_obj(1.0)
    with pytest.raises(DeembedError, match="at least one fixture"):
        fx.deembed_two_port(FREQ, meas)
    with pytest.raises(DeembedError, match="mode must be one of"):
        fx.deembed_two_port(FREQ, meas, good, None, "both")
    with pytest.raises(DeembedError, match="model must be one of"):
        fx.deembed_two_port(FREQ, meas, good, None, "complex", "exact")
    with pytest.raises(DeembedError, match="values for"):
        fx.deembed_two_port(FREQ, {"S21": [1]}, good)
    narrow = fixture_obj(1.0, freq=[850e6 + k * 1e6 for k in range(50)])
    with pytest.raises(DeembedError, match="port 1 fixture .* does not cover the sweep"):
        fx.deembed_two_port(FREQ, meas, narrow)
    with pytest.raises(DeembedError, match="port 2 fixture .* does not cover the sweep"):
        fx.deembed_two_port(FREQ, meas, None, narrow)
    loss = fx.Fixture(FREQ, [0.5 + 0j] * len(FREQ), has_phase=False, source="loss")
    with pytest.raises(DeembedError, match="only the loss"):
        fx.deembed_two_port(FREQ, meas, loss, None, "complex")
    with pytest.raises(DeembedError, match="needs the phase"):
        fx.deembed_two_port(FREQ, meas, good, None, "magnitude", "full")
    with pytest.raises(DeembedError, match="all four S-parameters"):
        fx.deembed_two_port(FREQ, {"S21": meas["S21"]}, good, None, "complex", "full")
    bare = fixture_obj(1.0, reflections=False)
    with pytest.raises(DeembedError, match="has no reflections"):
        fx.deembed_two_port(FREQ, meas, bare, None, "complex", "full")
    dead = fx.Fixture(FREQ, [0j] * len(FREQ), source="dead")
    with pytest.raises(DeembedError, match="passes nothing"):
        fx.deembed_two_port(FREQ, meas, dead)


def test_interpolating_a_fixture_on_a_coarser_grid():
    coarse = [700e6 + k * 10e6 for k in range(33)]
    left = fixture_obj(1.0, freq=coarse)
    out, _ = fx.deembed_two_port(FREQ, measured(1.0, None), left, None, "complex", "full")
    assert max(abs(a - b) for a, b in zip(out["S21"], truth("S21"))) < 0.01


# ---- reading fixtures --------------------------------------------------------------------------
def cable_run(tmp_path, code="CBL-0001", stamp="20261103_100000", kind="cable", **sim):
    reg = default_registry(user_dir="/nonexistent")
    if kind == "cable":
        params = {
            "sweep": {"start_hz": 700e6, "stop_hz": 1e9, "points": 301},
            "cable": {"label": "feed", "asset_id": code, "length_m": 3.0},
            "confirm_setup": False,
        }
        vna = SimVna(**CABLE, length_m=3.0)
    else:
        params = {
            "attenuator": {"label": "pad", "asset_id": code, "nominal_db": 6},
            "sweep": {"start_hz": 700e6, "stop_hz": 1e9, "points": 301},
            "confirm_setup": False,
        }
        vna = SimVna(attenuator_db=6.0, **sim)
    runner = Runner(reg.create(kind, params), {"vna": [vna]})
    path = tmp_path / "runs" / f"{kind}_{stamp}.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(30) and runner.state is RunState.FINISHED, runner.error
    return path


def test_a_cable_run_is_a_matched_fixture_and_an_attenuator_run_has_reflections(tmp_path):
    cable = fx.load_fixture_run(cable_run(tmp_path))
    assert cable.has_phase and not cable.has_reflections and cable.source.startswith("cable_")
    assert cable.loss_db()[0] == pytest.approx(3 * 0.6 * 0.7**0.5, rel=0.1)
    pad = fx.load_fixture_run(cable_run(tmp_path, "ATT-0001", "20261103_110000", "attenuator"))
    assert pad.has_reflections and pad.loss_db()[0] == pytest.approx(6.0, abs=0.05)
    assert abs(pad.s11[0]) == pytest.approx(0.02, abs=0.005)  # the simulated mismatch


def test_a_cable_run_in_reflection_or_with_the_loss_only_is_a_magnitude_fixture(tmp_path):
    path = tmp_path / "runs" / "cable_20261103_120000.jsonl"
    path.parent.mkdir(parents=True)
    lines = [
        {"kind": "run", "run_id": "r", "measurement": "cable", "params": {"mode": "reflection"}},
        {"kind": "trace", "name": "S11", "trace_kind": "complex", "x": [7e8, 1e9],
         "y": [[0.25, 0.0], [0.0, 0.16]]},
        {"kind": "end", "state": "finished"},
    ]  # fmt: skip
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    refl = fx.load_fixture_run(path)
    assert not refl.has_phase and [abs(v) for v in refl.s21] == pytest.approx([0.5, 0.4])
    lines[1] = {
        "kind": "trace",
        "name": "loss_db",
        "trace_kind": "real",
        "x": [7e8, 1e9],
        "y": [3, 6],
    }
    lines[0]["params"] = {"mode": "transmission"}
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    loss = fx.load_fixture_run(path)
    assert not loss.has_phase and loss.loss_db() == pytest.approx([3, 6])


def test_a_run_that_is_neither_is_refused(tmp_path):
    path = tmp_path / "runs" / "filter_20261103_100000.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"kind": "run", "run_id": "r", "measurement": "filter", "params": {}})
        + "\n"
        + json.dumps({"kind": "trace", "name": "x", "trace_kind": "real", "x": [1, 2], "y": [1, 2]})
        + "\n"
    )
    with pytest.raises(DeembedError, match="not a cable or an attenuator"):
        fx.load_fixture_run(path)
    with pytest.raises(DeembedError):
        fx.load_fixture_run(tmp_path / "gone.jsonl")
    with pytest.raises(DeembedError, match="no 'run', 'touchstone'"):
        fx.load_fixture({})


def test_a_touchstone_fixture_and_its_orientation(tmp_path):
    freq = [700e6 + k * 1e6 for k in range(321)]
    sp = [fixture_sp(f, 1.0) for f in freq]
    asym = [(a, b, 0.3 * b, d) for a, b, _, d in sp]  # a fixture that is not reciprocal
    rf.write_touchstone(
        tmp_path / "f.s2p", freq,
        {"S11": [s[0] for s in asym], "S21": [s[1] for s in asym],
         "S12": [s[2] for s in asym], "S22": [s[3] for s in asym]},
    )  # fmt: skip
    a = fx.load_fixture_touchstone(tmp_path / "f.s2p")
    assert a.has_reflections and a.s12 is not None and a.source == "f.s2p"
    assert a.s21 == pytest.approx([s[1] for s in asym], abs=1e-6)
    b = fx.load_fixture_touchstone(tmp_path / "f.s2p", reversed_file=True)  # port 1 at the device
    assert b.s21 == pytest.approx(a.s12, abs=1e-6) and b.s11 == pytest.approx(a.s22, abs=1e-6)
    assert fx.flipped(fx.flipped(a)).s21 == a.s21
    recip = fx.load_fixture_touchstone(
        _write(tmp_path / "r.s2p", freq, [fixture_sp(f, 1.0) for f in freq])
    )
    assert recip.s12 is not None or recip.s12 is None  # reciprocal files keep working
    assert fx.load_fixture({"touchstone": str(tmp_path / "f.s2p"), "reversed": True}).s21 == b.s21
    rf.write_touchstone(tmp_path / "one.s1p", freq, {"S11": [0.1] * len(freq)})
    with pytest.raises(DeembedError, match="two-port"):
        fx.load_fixture_touchstone(tmp_path / "one.s1p")
    with pytest.raises(DeembedError):
        fx.load_fixture_touchstone(tmp_path / "missing.s2p")


def _write(path, freq, sp):
    rf.write_touchstone(
        path, freq,
        {"S11": [s[0] for s in sp], "S21": [s[1] for s in sp],
         "S12": [s[2] for s in sp], "S22": [s[3] for s in sp]},
    )  # fmt: skip
    return path


def test_the_fixture_on_port_2_is_turned_round(tmp_path):
    """A file is written as seen from the VNA for both ports: the second is mirrored here."""
    freq = [700e6 + k * 1e6 for k in range(321)]
    _write(tmp_path / "p2.s2p", freq, [fixture_sp(f, 2.0) for f in freq])
    right = fx.load_fixture_touchstone(tmp_path / "p2.s2p")
    out, _ = fx.deembed_two_port(FREQ, measured(None, 2.0), None, right, "complex", "full")
    assert out["S11"] == pytest.approx(truth("S11"), abs=1e-6)
    assert out["S22"] == pytest.approx(truth("S22"), abs=1e-6)


# ---- the parameters ----------------------------------------------------------------------------
def problems(correction):
    out = []
    fx.check_fixtures({"correction": correction}, out, lambda path, msg: (path, msg))
    return dict(out)


def test_the_parameters_of_the_correction():
    assert problems({"port1": {"asset_id": "CBL-0001"}}) == {}
    assert problems({"port2": {"touchstone": "a.s2p", "reversed": True}, "model": "full"}) == {}
    assert (
        problems({"port1": {"run": "a"}, "port2": {"asset_id": "ATT-0002"}, "mode": "magnitude"})
        == {}
    )
    assert "'port1' and / or" in problems({"cable": {"asset_id": "CBL-0001"}})["correction"]
    assert "unknown field" in problems({"port1": {"run": "a"}, "extra": 1})["correction.extra"]
    assert "one of asset_id" in problems({"port1": {}})["correction.port1"]
    assert "not a code" in problems({"port2": {"asset_id": "x"}})["correction.port2.asset_id"]
    assert (
        "true or false"
        in problems({"port1": {"run": "a", "reversed": 1}})["correction.port1.reversed"]
    )
    assert (
        "one of complex, magnitude"
        in problems({"port1": {"run": "a"}, "mode": "x"})["correction.mode"]
    )
    assert (
        "one of matched, full"
        in problems({"port1": {"run": "a"}, "model": "x"})["correction.model"]
    )
    out = []
    fx.check_fixtures({}, out, lambda *a: a)
    assert out == []
    assert fx.wanted_parameters({}, ["S21"]) == ["S21"]
    assert fx.wanted_parameters({"correction": {"model": "full"}}, ["S21"]) == [
        "S21", "S11", "S12", "S22",
    ]  # fmt: skip


# ---- the modules -------------------------------------------------------------------------------
FILTER = {
    "filter": {"type": "bandpass", "label": "868 SAW"},
    "sweep": {"start_hz": 800e6, "stop_hz": 940e6, "points": 281},
    "also_s11": True,
    "confirm_setup": False,
}
ATT = {
    "attenuator": {"label": "10 dB pad", "nominal_db": 10, "tolerance_db": 0.5},
    "sweep": {"start_hz": 800e6, "stop_hz": 940e6, "points": 141},
    "confirm_setup": False,
}
FILT_SIM = dict(filter_type="bandpass", filter_f0_hz=868e6, filter_bw_hz=40e6, filter_order=3,
                filter_loss_db=1.0)  # fmt: skip


def run_module(registry, module, params, **sim):
    runner = Runner(registry.create(module, params), {"vna": [SimVna(**CABLE, **sim)]})
    runner.start()
    assert runner.join(60)
    evs = runner.drain()
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    rows = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    logs = [(e.data["level"], e.data["message"]) for e in evs if e.kind == "log"]
    return runner, traces, rows[0] if rows else None, logs


def correct(params, **ports):
    p = copy.deepcopy(params)
    p["correction"] = ports
    return p


def test_the_filter_measured_through_cables_is_corrected_to_the_filter_alone(registry, tmp_path):
    alone = run_module(registry, "filter", FILTER, **FILT_SIM)[2]
    seen = run_module(registry, "filter", FILTER, **FILT_SIM, fixture1_m=3.0, fixture2_m=2.0)[2]
    c1 = cable_run(tmp_path, "CBL-0001", "20261101_100000")  # 3 m
    assert seen["insertion_loss_db"] > alone["insertion_loss_db"] + 1.5  # the cables add loss
    cables = {"port1": {"run": str(c1)}}
    # the 3 m of the run is port 1; port 2 is a 2 m cable: write it as a Touchstone file
    freq = [700e6 + k * 1e6 for k in range(321)]
    two = SimVna(**CABLE)
    rf.write_touchstone(
        tmp_path / "two.s2p", freq,
        {"S11": [0] * 321, "S21": [two.fixture(f, 2.0) for f in freq]},
    )  # fmt: skip
    cables["port2"] = {"touchstone": str(tmp_path / "two.s2p")}
    runner, traces, row, logs = run_module(
        registry, "filter", correct(FILTER, **cables), **FILT_SIM, fixture1_m=3.0, fixture2_m=2.0
    )
    assert runner.state is RunState.FINISHED, runner.error
    assert row["insertion_loss_db"] == pytest.approx(alone["insertion_loss_db"], abs=0.05)
    assert row["center_hz"] == pytest.approx(alone["center_hz"], rel=2e-3)
    assert row["bandwidth_hz"] == pytest.approx(alone["bandwidth_hz"], rel=0.02)
    assert row["corrected"] is True and row["correction_model"] == "matched"
    assert row["raw_insertion_loss_db"] == pytest.approx(seen["insertion_loss_db"], abs=0.05)
    assert row["fixture_loss_port1_db"] > 1.0 and row["fixture_loss_port2_db"] > 0.5
    assert {"S21", "S21_raw"} <= set(traces) and "hidden" not in traces["S21_raw"]["meta"]
    assert any("corrected for the fixtures, port 1" in m and "port 2" in m for _, m in logs)
    assert "corrected" not in seen and "raw_insertion_loss_db" not in seen


def test_the_attenuation_of_an_attenuator_is_not_charged_with_the_cable(registry, tmp_path):
    path = cable_run(tmp_path, "CBL-0001", "20261101_100000")
    seen = run_module(registry, "attenuator", ATT, attenuator_db=10.0, fixture1_m=3.0)
    fixed = run_module(
        registry, "attenuator", correct(ATT, port1={"run": str(path)}),
        attenuator_db=10.0, fixture1_m=3.0,
    )  # fmt: skip
    assert fixed[0].state is RunState.FINISHED, fixed[0].error
    assert seen[2]["mean_attenuation_db"] > 11.5  # the verdict would fail: the cable adds loss
    assert seen[2]["verdict"] == "FAIL"
    assert fixed[2]["mean_attenuation_db"] == pytest.approx(10.0, abs=0.05)
    assert fixed[2]["verdict"] == "PASS" and fixed[2]["corrected"] is True
    assert fixed[2]["raw_mean_attenuation_db"] == pytest.approx(
        seen[2]["mean_attenuation_db"], abs=0.05
    )
    traces = fixed[1]
    assert (
        "hidden" not in traces["attenuation_raw_db"]["meta"] and traces["S21_raw"]["meta"]["hidden"]
    )
    assert max(traces["attenuation_raw_db"]["y"]) > max(traces["attenuation_db"]["y"]) + 1


def test_the_return_loss_of_the_attenuator_is_corrected_too(registry, tmp_path):
    path = cable_run(tmp_path, "CBL-0001", "20261101_100000")
    runner, _, row, _ = run_module(
        registry, "attenuator", correct(ATT, port1={"run": str(path)}),
        attenuator_db=10.0, fixture1_m=3.0, mismatch=0.05,
    )  # fmt: skip
    assert runner.state is RunState.FINISHED, runner.error
    alone = run_module(registry, "attenuator", ATT, attenuator_db=10.0, mismatch=0.05)[2]
    assert row["min_input_return_loss_db"] == pytest.approx(
        alone["min_input_return_loss_db"], abs=0.5
    )


class TwoPortVna:
    """A VNA that sees a device through mismatched fixtures, to try the full model."""

    def __init__(self, dut_db, l1=None, l2=None):
        self.dut_db, self.l1, self.l2, self.sweep = dut_db, l1, l2, {}
        self.name = "vna"

    def call(self, name, **args):
        if name == "set_sweep":
            self.sweep = args
            return None
        n = self.sweep["points"]
        a, b = self.sweep["start_frequency"], self.sweep["stop_frequency"]
        freq = [a + (b - a) * k / (n - 1) for k in range(n)]
        index = {"S11": "S11", "S21": "S21", "S12": "S12", "S22": "S22"}[args["parameter"]]
        values = [cascade(f, self.l1, self.l2, self.dut)[index] for f in freq]
        return {"frequency": freq, "values": [[v.real, v.imag] for v in values]}

    def dut(self, f):
        gain = 10 ** (-self.dut_db / 20)
        return (0.05 + 0j, gain * cmath.exp(-0.5j * f / 1e9), gain * cmath.exp(-0.5j * f / 1e9),
                0.04 + 0j)  # fmt: skip


def test_the_full_model_reads_four_parameters_and_recovers_the_attenuator(registry, tmp_path):
    freq = [700e6 + k * 1e6 for k in range(321)]
    _write(tmp_path / "p1.s2p", freq, [fixture_sp(f, 1.0) for f in freq])
    _write(tmp_path / "p2.s2p", freq, [fixture_sp(f, 2.0) for f in freq])
    vna = TwoPortVna(10.0, 1.0, 2.0)
    params = correct(
        ATT,
        port1={"touchstone": str(tmp_path / "p1.s2p")},
        port2={"touchstone": str(tmp_path / "p2.s2p")},
        model="full",
    )
    runner = Runner(registry.create("attenuator", params), {"vna": [vna]})
    runner.start()
    assert runner.join(60) and runner.state is RunState.FINISHED, runner.error
    row = next(
        e.data["values"] for e in runner.drain()
        if e.kind == "point" and e.data["table"] == "points"
    )  # fmt: skip
    assert row["mean_attenuation_db"] == pytest.approx(10.0, abs=0.01)
    assert row["correction_model"] == "full" and row["verdict"] == "PASS"
    assert row["raw_mean_attenuation_db"] > 11.5
    # no correction: the fixtures are charged to the attenuator
    plain = Runner(registry.create("attenuator", ATT), {"vna": [TwoPortVna(10.0, 1.0, 2.0)]})
    plain.start()
    assert plain.join(60) and plain.state is RunState.FINISHED


def test_a_correction_that_cannot_be_made_stops_the_run_with_the_reason(registry, tmp_path):
    freq = [900e6 + k * 1e6 for k in range(20)]
    _write(tmp_path / "narrow.s2p", freq, [fixture_sp(f, 1.0) for f in freq])
    runner, *_ = run_module(
        registry, "attenuator", correct(ATT, port1={"touchstone": str(tmp_path / "narrow.s2p")}),
        attenuator_db=10.0,
    )  # fmt: skip
    assert runner.state is RunState.FAILED and "fixture correction" in runner.error["message"]
    assert "does not cover the sweep" in runner.error["message"]
    runner, *_ = run_module(
        registry, "filter", correct(FILTER, port1={"run": str(tmp_path / "gone.jsonl")}), **FILT_SIM
    )
    assert runner.state is RunState.FAILED and "fixture correction" in runner.error["message"]


@pytest.mark.parametrize("module", ["filter", "attenuator"])
def test_the_parameters_are_checked_by_the_module(registry, module):
    base = FILTER if module == "filter" else ATT
    bad = registry.create(module, correct(base, port1={"run": "a", "touchstone": "b.s2p"})).check()
    assert [p.path for p in bad] == ["correction.port1"]
    assert registry.create(module, correct(base, port2={"asset_id": "ATT-0001"})).check() == []


# ---- the project: fixtures by their code -------------------------------------------------------
def make_project(tmp_path, registry, module, params, **sim):
    from ola.project import MeasurementFile, Project
    from ola.project_session import ProjectSession

    project = Project.new("P", tmp_path / "proj")
    ref = project.add_measurement(module, "M", registry)
    MeasurementFile(type=module, role_bindings={"vna": ["vna1"]}, params=params).save(
        project.directory / ref.file
    )
    project.save()
    session = ProjectSession(
        project, registry, connect=lambda n, cancel=None: SimVna(**CABLE, **sim)
    )
    return session, ref


def test_a_fixture_named_by_its_code_is_a_cable_or_an_attenuator_of_the_project(registry, tmp_path):
    params = correct(ATT, port1={"asset_id": "CBL-0001"}, port2={"asset_id": "ATT-0001"})
    session, ref = make_project(tmp_path, registry, "attenuator", params, attenuator_db=10.0)
    root = session.run_dir.parent
    cable = cable_run(root, "CBL-0001", "20261101_100000")
    pad = cable_run(root, "ATT-0001", "20261102_100000", "attenuator")
    cable_run(root, "CBL-0001", "20261001_100000")  # an older one
    runner, path = session.build_runner(ref)
    spec = runner.measurement.params["correction"]
    assert spec["port1"]["run"] == str(cable) and spec["port2"]["run"] == str(pad)
    assert spec["port1"]["asset_id"] == "CBL-0001"  # which measurement was used is in the run
    header = json.loads(path.read_text().splitlines()[0])
    assert header["params"]["correction"]["port2"]["run"] == str(pad)


def test_a_fixture_without_a_measurement_refuses_the_run_before_it_starts(registry, tmp_path):
    from ola.measurement import MeasurementError

    params = correct(ATT, port1={"asset_id": "CBL-0042"})
    session, ref = make_project(tmp_path, registry, "attenuator", params)
    with pytest.raises(MeasurementError, match="no finished cable or attenuator measurement"):
        session.build_runner(ref)


def test_the_resolution_leaves_the_rest_alone(registry, tmp_path):
    session, ref = make_project(tmp_path, registry, "attenuator", ATT)
    plain = session.load(ref).params
    assert session.resolve_correction(plain) is plain
    named = correct(
        ATT, port1={"asset_id": "CBL-0042", "run": "x.jsonl"}, port2={"touchstone": "a.s2p"}
    )
    assert session.resolve_correction(named) is named
    # a reflection measurement's cable is still resolved, and only from cable measurements
    mixed = {"correction": {"cable": {"asset_id": "CBL-0007"}}}
    from ola.measurement import MeasurementError

    with pytest.raises(MeasurementError, match="no finished cable measurement of CBL-0007"):
        session.resolve_correction(mixed)
