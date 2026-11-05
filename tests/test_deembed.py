"""Taking a cable out of a reflection measurement: the maths, the cable data, the two modules."""

import cmath
import copy
import json

import pytest

from ola import deembed, rf
from ola.deembed import DeembedError
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.runs import RunWriter
from ola.sim_vna import SimVna

FREQ = [800e6 + k * 0.5e6 for k in range(301)]
CABLE = dict(length_m=5.0, loss_db_per_m_at_1ghz=0.6, velocity_factor=0.66)
ANTENNA = dict(antenna_f0_hz=868e6, antenna_r_ohm=55.0, antenna_q=12.0)


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def cable_t(freq, length=5.0, loss=0.6):
    """T(f) of a cable: its loss and the phase of its delay."""
    vna = SimVna(length_m=length, loss_db_per_m_at_1ghz=loss)
    return [vna.transmission(f) for f in freq]


def antenna_gamma(freq):
    return [SimVna(**ANTENNA).antenna_gamma(f) for f in freq]


def write_cable_s2p(path, freq=None, **kw):
    freq = freq or [700e6 + k * 0.5e6 for k in range(601)]
    vna = SimVna(**{**CABLE, **kw})
    rf.write_touchstone(
        path, freq, {"S11": [0] * len(freq), "S21": [vna.transmission(f) for f in freq]}
    )
    return freq


def cable_run(tmp_path, code="CBL-0001", stamp="20261103_100000", mode="transmission", **sim):
    params = {
        "mode": mode,
        "sweep": {"start_hz": 700e6, "stop_hz": 1.0e9, "points": 601},
        "cable": {"label": "feed", "asset_id": code, "length_m": 5.0},
        "confirm_setup": False,
    }
    if mode == "reflection":
        params["termination"] = sim.pop("far", "open")
    runner = Runner(
        default_registry(user_dir="/nonexistent").create("cable", params),
        {"vna": [SimVna(**{**CABLE, **sim, "termination": params.get("termination", "thru")})]},
    )
    path = tmp_path / "runs" / f"cable_{stamp}.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(30) and runner.state is RunState.FINISHED, runner.error
    return path


# ---- the maths ---------------------------------------------------------------------------------
def test_the_reflection_of_the_antenna_is_recovered_exactly():
    t2 = [t * t for t in cable_t(FREQ)]
    gamma = antenna_gamma(FREQ)
    measured = [g * c for g, c in zip(gamma, t2)]
    cable = deembed.CableData(FREQ, t2, True, "x")
    back, info = deembed.correct_reflection(FREQ, measured, cable)
    assert back == pytest.approx(gamma, abs=1e-9)
    assert info["over_unity_points"] == 0 and info["warnings"] == []
    assert info["mean_one_way_loss_db"] == pytest.approx(2.8, abs=0.3)  # 5 m of 0.6 dB/m @ 1 GHz
    # the cable made the antenna look better matched than it is
    assert max(rf.vswr(measured)) < max(rf.vswr(gamma)) - 1


def test_the_magnitude_mode_corrects_the_size_and_keeps_the_measured_phase():
    t2 = [t * t for t in cable_t(FREQ)]
    gamma = antenna_gamma(FREQ)
    measured = [g * c for g, c in zip(gamma, t2)]
    cable = deembed.CableData(FREQ, t2, True, "x")
    back, _ = deembed.correct_reflection(FREQ, measured, cable, "magnitude")
    assert [abs(v) for v in back] == pytest.approx([abs(g) for g in gamma], abs=1e-9)
    assert [cmath.phase(v) for v in back] == pytest.approx([cmath.phase(v) for v in measured])


def test_the_cable_is_interpolated_on_the_frequencies_of_the_measurement():
    fine = [700e6 + k * 0.5e6 for k in range(601)]
    coarse = fine[::10]  # every 5 MHz: smooth enough to interpolate
    t2 = [t * t for t in cable_t(coarse)]
    cable = deembed.CableData(coarse, t2, True, "coarse")
    want = [t * t for t in cable_t(FREQ)]
    got = deembed.interpolate(cable.freq, cable.round_trip, FREQ)
    assert [abs(v) for v in got] == pytest.approx([abs(v) for v in want], rel=2e-3)
    assert [rf.db20(a / b) for a, b in zip(got, want)] == pytest.approx([0] * len(FREQ), abs=0.05)
    assert [abs(cmath.phase(a / b)) for a, b in zip(got, want)] == pytest.approx(
        [0] * len(FREQ), abs=0.03
    )
    only_size = deembed.interpolate(cable.freq, cable.round_trip, FREQ, keep_phase=False)
    assert all(abs(v.imag) < 1e-12 and v.real > 0 for v in only_size)


def test_the_cable_must_cover_the_sweep():
    cable = deembed.from_loss([850e6, 900e6], [1.0, 1.0], "short.s2p")
    with pytest.raises(DeembedError, match="does not cover the sweep"):
        deembed.correct_reflection(FREQ, [0.1] * len(FREQ), cable, "magnitude")
    just = deembed.from_loss([800e6 - 1e3, 950e6 + 1e3], [1.0, 1.0], "x")  # a hair short: fine
    deembed.correct_reflection(FREQ, [0.1] * len(FREQ), just, "magnitude")


def test_what_cannot_be_physical_is_limited_and_counted():
    cable = deembed.from_loss([700e6, 1e9], [3.0, 3.0], "x")  # 6 dB round trip: x2
    out, info = deembed.correct_reflection(FREQ, [0.7] * len(FREQ), cable, "magnitude")
    assert info["over_unity_points"] == len(FREQ)  # 0.7 x 2 = 1.4: more than total reflection
    assert max(abs(v) for v in out) < 1.0 and max(abs(v) for v in out) >= deembed.UNITY - 1e-9


def test_the_phase_cannot_be_corrected_with_the_loss_alone():
    cable = deembed.from_loss([700e6, 1e9], [1.0, 1.0], "loss.csv")
    with pytest.raises(DeembedError, match="only the loss"):
        deembed.correct_reflection(FREQ, [0.1] * len(FREQ), cable, "complex")
    with pytest.raises(DeembedError, match="mode must be one of"):
        deembed.correct_reflection(FREQ, [0.1] * len(FREQ), cable, "both")
    with pytest.raises(DeembedError, match="301 values|values"):
        deembed.correct_reflection(FREQ, [0.1], cable, "magnitude")


def test_a_cable_that_passes_nothing_is_refused():
    cable = deembed.CableData([700e6, 1e9], [0j, 0j], True, "dead")
    with pytest.raises(DeembedError, match="passes nothing"):
        deembed.correct_reflection(FREQ, [0.1] * len(FREQ), cable)


# ---- reading a cable ---------------------------------------------------------------------------
def test_the_ways_to_describe_a_cable():
    loss = deembed.from_loss([1e9, 2e9], [1.0, 2.0], "x")
    assert not loss.has_phase and loss.one_way_loss_db() == pytest.approx([1.0, 2.0])
    t = [0.5 * cmath.exp(-0.3j), 0.4 * cmath.exp(-0.6j)]
    assert deembed.from_transmission([1e9, 2e9], t, "x").round_trip == pytest.approx(
        [v * v for v in t]
    )
    s11 = [0.25 * cmath.exp(-0.6j), 0.16 * cmath.exp(-1.2j)]
    assert deembed.from_reflection([1e9, 2e9], s11, "open", "x").round_trip == pytest.approx(s11)
    assert deembed.from_reflection([1e9, 2e9], s11, "short", "x").round_trip == pytest.approx(
        [-v for v in s11]
    )
    with pytest.raises(DeembedError, match="'open' or 'short'"):
        deembed.from_reflection([1e9, 2e9], s11, "load", "x")
    with pytest.raises(DeembedError, match="increase"):
        deembed.from_loss([2e9, 1e9], [1, 1], "x")
    with pytest.raises(DeembedError, match="at least 2"):
        deembed.from_loss([1e9], [1], "x")
    with pytest.raises(DeembedError, match="3 losses|losses"):
        deembed.from_loss([1e9, 2e9], [1, 1, 1], "x")


def test_a_cable_measured_with_too_few_points_is_flagged():
    coarse = [800e6 + k * 20e6 for k in range(8)]  # 20 MHz steps on a 5 m cable: 360 degrees
    data = deembed.from_transmission(coarse, cable_t(coarse), "coarse")
    assert any("too few points" in w for w in data.warnings)
    fine = deembed.from_transmission(FREQ, cable_t(FREQ), "fine")
    assert fine.warnings == []


def test_a_touchstone_file_with_two_ports_or_one(tmp_path):
    freq = write_cable_s2p(tmp_path / "feed.s2p")
    two = deembed.load_cable_touchstone(tmp_path / "feed.s2p")
    assert two.has_phase and two.source == "feed.s2p" and two.freq == pytest.approx(freq)
    t = cable_t(freq)
    assert two.round_trip == pytest.approx([v * v for v in t], abs=1e-6)
    open_end = SimVna(**CABLE, termination="open")
    rf.write_touchstone(
        tmp_path / "open.s1p", freq, {"S11": [open_end.reflection(f) for f in freq]}
    )
    one = deembed.load_cable_touchstone(tmp_path / "open.s1p", "open")
    assert one.round_trip == pytest.approx(two.round_trip, abs=1e-6)  # S11 of an open is T^2
    shorted = deembed.load_cable_touchstone(tmp_path / "open.s1p", "short")
    assert shorted.round_trip == pytest.approx([-v for v in two.round_trip], abs=1e-6)
    with pytest.raises(DeembedError):
        deembed.load_cable_touchstone(tmp_path / "missing.s2p")
    (tmp_path / "bad.s2p").write_text("# GHZ S RI R 50\n1 2 3\n")
    with pytest.raises(DeembedError):
        deembed.load_cable_touchstone(tmp_path / "bad.s2p")


def test_a_cable_run_in_transmission_in_reflection_or_with_the_loss_only(tmp_path):
    t = [v * v for v in cable_t([700e6 + k * 0.5e6 for k in range(601)])]
    trans = deembed.load_cable_run(cable_run(tmp_path, stamp="20261103_100000"))
    assert trans.has_phase and trans.round_trip == pytest.approx(t, abs=1e-6)
    refl = deembed.load_cable_run(
        cable_run(tmp_path, stamp="20261103_110000", mode="reflection", far="open")
    )
    assert refl.round_trip == pytest.approx(t, abs=0.03)  # an open: S11 is T^2 (a small mismatch)
    short = deembed.load_cable_run(
        cable_run(tmp_path, stamp="20261103_120000", mode="reflection", far="short")
    )
    assert short.round_trip == pytest.approx(t, abs=0.03)  # and -S11 of a short
    # a run that kept only the loss curve
    path = tmp_path / "runs" / "cable_20261103_130000.jsonl"
    header = {
        "kind": "run",
        "run_id": "r",
        "measurement": "cable",
        "params": {"mode": "transmission"},
    }
    lines = [
        header,
        {"kind": "trace", "name": "loss_db", "trace_kind": "real", "x": [700e6, 1e9], "y": [2, 3]},
        {"kind": "end", "state": "finished"},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    only = deembed.load_cable_run(path)
    assert not only.has_phase and only.one_way_loss_db() == pytest.approx([2, 3])
    assert deembed.load_cable({"run": str(path)}).source == path.name


def test_a_run_that_is_not_a_cable_is_refused(tmp_path):
    path = tmp_path / "runs" / "other_20261103_100000.jsonl"
    path.parent.mkdir(parents=True)
    lines = [
        {"kind": "run", "run_id": "r", "measurement": "filter", "params": {}},
        {"kind": "trace", "name": "S21", "trace_kind": "real", "x": [1, 2], "y": [1, 2]},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    with pytest.raises(DeembedError, match="not a cable measurement"):
        deembed.load_cable_run(path)
    with pytest.raises(DeembedError, match="not a run file|cannot read"):
        deembed.load_cable_run(tmp_path / "nothing.jsonl")
    with pytest.raises(DeembedError, match="no 'run', 'touchstone'"):
        deembed.load_cable({})


def test_the_newest_finished_measurement_of_a_cable_is_found(tmp_path):
    old = cable_run(tmp_path, "CBL-0007", "20261101_100000")
    new = cable_run(tmp_path, "CBL-0007", "20261103_100000")
    cable_run(tmp_path, "CBL-0008", "20261104_100000")  # another cable, newer
    interrupted = tmp_path / "runs" / "cable_20261105_100000.jsonl"
    interrupted.write_text(new.read_text().rsplit('{"kind": "end"', 1)[0])  # no end: interrupted
    folders = [tmp_path / "runs", tmp_path / "nowhere"]
    assert deembed.latest_cable_run("CBL-0007", folders) == new
    assert deembed.latest_cable_run("cbl-7", folders) == new  # any way of writing the code
    assert deembed.latest_cable_run("CBL-0099", folders) is None
    assert old != new


# ---- the parameters ----------------------------------------------------------------------------
def problems(correction):
    out = []
    deembed.check_correction({"correction": correction}, out, lambda path, msg: (path, msg))
    return dict(out)


def test_the_cable_is_named_in_exactly_one_way():
    assert problems({"cable": {"asset_id": "CBL-0001"}}) == {}
    assert problems({"cable": {"run": "a.jsonl", "mode": "magnitude"}}) == {}
    assert problems({"cable": {"touchstone": "a.s1p", "termination": "short"}}) == {}
    assert "one of asset_id" in problems({"cable": {}})["correction.cable"]
    both = problems({"cable": {"run": "a", "touchstone": "b.s2p"}})
    assert "one of asset_id" in both["correction.cable"]
    # the code may accompany the run it was resolved to
    assert problems({"cable": {"run": "a.jsonl", "asset_id": "CBL-0001"}}) == {}
    assert "not a code" in problems({"cable": {"asset_id": "feed"}})["correction.cable.asset_id"]
    assert (
        "must be a .s1p or .s2p"
        in problems({"cable": {"touchstone": "a.csv"}})["correction.cable.touchstone"]
    )
    assert "path of a file" in problems({"cable": {"run": 3}})["correction.cable.run"]
    assert (
        "one of open, short"
        in problems({"cable": {"run": "a", "termination": "x"}})["correction.cable.termination"]
    )
    assert (
        "one of complex, magnitude"
        in problems({"cable": {"run": "a", "mode": "x"}})["correction.cable.mode"]
    )
    assert (
        "unknown field" in problems({"cable": {"run": "a", "speed": 1}})["correction.cable.speed"]
    )
    assert "with a 'cable'" in problems("cable")["correction"]
    out = []
    deembed.check_correction({}, out, lambda *a: a)
    assert out == []  # no correction: nothing to say


# ---- the measurements --------------------------------------------------------------------------
RL = {
    "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 301},
    "device": {"label": "868 MHz whip"},
    "vswr_max": 2.0,
    "confirm_setup": False,
}


def run_module(registry, module, params, **sim):
    runner = Runner(registry.create(module, params), {"vna": [SimVna(**sim)]})
    runner.start()
    assert runner.join(60)
    evs = runner.drain()
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    rows = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    sweep = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "sweep"]
    logs = [(e.data["level"], e.data["message"]) for e in evs if e.kind == "log"]
    return runner, traces, rows[0] if rows else None, sweep, logs


def with_cable(params, **cable):
    p = copy.deepcopy(params)
    p["correction"] = {"cable": cable}
    return p


def test_the_return_loss_through_a_cable_is_corrected_to_the_antenna_alone(registry, tmp_path):
    write_cable_s2p(tmp_path / "feed.s2p")
    truth = run_module(registry, "return_loss", RL, termination="antenna", **ANTENNA)
    seen = run_module(
        registry, "return_loss", RL, termination="antenna_via_cable", **CABLE, **ANTENNA
    )
    fixed = run_module(
        registry,
        "return_loss",
        with_cable(RL, touchstone=str(tmp_path / "feed.s2p")),
        termination="antenna_via_cable",
        **CABLE,
        **ANTENNA,
    )
    assert fixed[0].state is RunState.FINISHED, fixed[0].error
    t_row, s_row, f_row = truth[2], seen[2], fixed[2]
    assert s_row["max_vswr"] < t_row["max_vswr"] - 1  # through the cable it looks too good
    assert f_row["max_vswr"] == pytest.approx(t_row["max_vswr"], rel=0.02)  # corrected: the truth
    assert f_row["min_vswr"] == pytest.approx(t_row["min_vswr"], rel=0.02)
    assert f_row["corrected"] is True and f_row["correction_mode"] == "complex"
    assert f_row["correction_source"] == "feed.s2p"
    assert f_row["raw_max_vswr"] == pytest.approx(s_row["max_vswr"], rel=0.01)
    assert f_row["raw_min_vswr"] == pytest.approx(s_row["min_vswr"], rel=0.01)
    assert f_row["cable_loss_one_way_db"] == pytest.approx(2.8, abs=0.4)
    # the usable band is the one of the antenna, not the one the cable flatters
    assert f_row["widest_band_hz"] == pytest.approx(t_row["widest_band_hz"], rel=0.05)
    assert s_row["widest_band_hz"] > t_row["widest_band_hz"] * 1.2
    assert "corrected" not in s_row and "raw_max_vswr" not in s_row  # no correction: no extras


def test_the_corrected_and_the_raw_curves_are_both_kept(registry, tmp_path):
    write_cable_s2p(tmp_path / "feed.s2p")
    p = with_cable(RL, touchstone=str(tmp_path / "feed.s2p"))
    _, traces, _, sweep, logs = run_module(
        registry, "return_loss", p, termination="antenna_via_cable", **CABLE, **ANTENNA
    )
    assert {"vswr", "vswr_raw", "return_loss_db", "return_loss_raw_db", "S11", "S11_raw"} <= set(
        traces
    )
    # the two return losses are drawn together; the VSWR curves and the S11 are there to pick
    assert "hidden" not in traces["return_loss_raw_db"]["meta"]
    assert "hidden" not in traces["return_loss_db"]["meta"]
    assert traces["vswr_raw"]["meta"]["hidden"] and traces["S11_raw"]["meta"]["hidden"]
    assert max(traces["return_loss_raw_db"]["y"]) > max(traces["return_loss_db"]["y"])
    assert max(traces["vswr_raw"]["y"]) < max(traces["vswr"]["y"])
    assert {"vswr_raw", "return_loss_raw_db"} <= set(sweep[0])
    assert any("corrected for the cable feed.s2p (complex" in m for _, m in logs)
    # without a correction there is nothing extra
    _, plain, _, plain_sweep, _ = run_module(
        registry, "return_loss", RL, termination="antenna", **ANTENNA
    )
    assert "vswr_raw" not in plain and "vswr_raw" not in plain_sweep[0]


def test_the_loss_alone_corrects_the_vswr(registry, tmp_path):
    """A cable known only by its loss: the magnitude mode, enough for the VSWR."""
    path = cable_run(tmp_path)
    truth = run_module(registry, "return_loss", RL, termination="antenna", **ANTENNA)[2]
    p = with_cable(RL, run=str(path), mode="magnitude")
    runner, _, row, _, logs = run_module(
        registry, "return_loss", p, termination="antenna_via_cable", **CABLE, **ANTENNA
    )
    assert runner.state is RunState.FINISHED, runner.error
    assert row["correction_mode"] == "magnitude"
    assert row["max_vswr"] == pytest.approx(truth["max_vswr"], rel=0.02)


def test_a_cable_that_does_not_fit_is_reported(registry, tmp_path):
    write_cable_s2p(tmp_path / "long.s2p", length_m=12.0, loss_db_per_m_at_1ghz=0.9)
    p = with_cable(RL, touchstone=str(tmp_path / "long.s2p"))  # the wrong cable: too much loss
    runner, _, row, _, logs = run_module(
        registry, "return_loss", p, termination="antenna_via_cable", **CABLE, **ANTENNA
    )
    assert runner.state is RunState.FINISHED
    assert any(lv == "warning" and "exceed 1" in m for lv, m in logs)


def test_a_cable_that_does_not_cover_the_sweep_stops_the_run(registry, tmp_path):
    write_cable_s2p(tmp_path / "narrow.s2p", freq=[850e6 + k * 1e6 for k in range(51)])
    runner, *_ = run_module(
        registry,
        "return_loss",
        with_cable(RL, touchstone=str(tmp_path / "narrow.s2p")),
        termination="antenna_via_cable",
        **CABLE,
        **ANTENNA,
    )
    assert runner.state is RunState.FAILED and "cable correction" in runner.error["message"]
    assert "does not cover the sweep" in runner.error["message"]


def test_a_file_that_is_not_there_stops_the_run_with_the_reason(registry, tmp_path):
    runner, *_ = run_module(
        registry, "return_loss", with_cable(RL, touchstone=str(tmp_path / "gone.s2p")), **ANTENNA
    )
    assert runner.state is RunState.FAILED and "cable correction" in runner.error["message"]


ANT = {
    "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 301},
    "device": {"label": "868 MHz whip"},
    "confirm_setup": False,
}


def test_the_antenna_impedance_through_a_cable_is_corrected_too(registry, tmp_path):
    write_cable_s2p(tmp_path / "feed.s2p")
    truth = run_module(registry, "antenna", ANT, termination="antenna", **ANTENNA)
    fixed = run_module(
        registry,
        "antenna",
        with_cable(ANT, touchstone=str(tmp_path / "feed.s2p")),
        termination="antenna_via_cable",
        **CABLE,
        **ANTENNA,
    )
    assert fixed[0].state is RunState.FINISHED, fixed[0].error
    t_row, f_row = truth[2], fixed[2]
    assert f_row["series_resonance_hz"] == pytest.approx(t_row["series_resonance_hz"], rel=1e-3)
    assert f_row["z_real_ohm"] == pytest.approx(t_row["z_real_ohm"], rel=0.03)
    assert f_row["min_vswr"] == pytest.approx(t_row["min_vswr"], rel=0.02)
    assert f_row["corrected"] and f_row["raw_min_vswr"] < f_row["min_vswr"] * 1.5
    traces = fixed[1]
    assert traces["S11"]["meta"]["default_view"] == "smith" and "S11_raw" in traces
    assert traces["vswr_raw"]["meta"]["hidden"]


def test_the_antenna_impedance_is_refused_with_a_cable_known_by_its_loss_only(registry, tmp_path):
    path = tmp_path / "runs" / "cable_20261103_130000.jsonl"
    path.parent.mkdir(parents=True)
    lines = [
        {"kind": "run", "run_id": "r", "measurement": "cable", "params": {"mode": "transmission"}},
        {"kind": "trace", "name": "loss_db", "trace_kind": "real", "x": [700e6, 1e9], "y": [2, 3]},
        {"kind": "end", "state": "finished"},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    runner, *_ = run_module(registry, "antenna", with_cable(ANT, run=str(path)), **ANTENNA)
    assert runner.state is RunState.FAILED
    assert "needs the phase of the cable" in runner.error["message"]
    runner, *_ = run_module(
        registry, "return_loss", with_cable(RL, run=str(path)), **ANTENNA
    )  # the return loss can use it, in the magnitude mode it picks by itself
    assert runner.state is RunState.FINISHED, runner.error


@pytest.mark.parametrize("module", ["return_loss", "antenna"])
def test_the_parameters_of_the_correction_are_checked_by_the_module(registry, module):
    base = RL if module == "return_loss" else ANT
    bad = registry.create(module, with_cable(base, run="a.jsonl", touchstone="b.s2p")).check()
    assert [p.path for p in bad] == ["correction.cable"]
    good = registry.create(module, with_cable(base, asset_id="CBL-0001")).check()
    assert good == []


# ---- the project: a cable by its code ----------------------------------------------------------
def make_project(tmp_path, registry, params, module="return_loss", name="Whip"):
    from ola.project import MeasurementFile, Project
    from ola.project_session import ProjectSession

    project = Project.new("P", tmp_path / "proj")
    ref = project.add_measurement(module, name, registry)
    MeasurementFile(type=module, role_bindings={"vna": ["vna1"]}, params=params).save(
        project.directory / ref.file
    )
    project.save()
    session = ProjectSession(
        project,
        registry,
        connect=lambda n, cancel=None: SimVna(termination="antenna_via_cable", **CABLE, **ANTENNA),
    )
    return session, ref


def test_a_cable_named_by_its_code_is_the_newest_measurement_in_the_project(registry, tmp_path):
    session, ref = make_project(tmp_path, registry, with_cable(RL, asset_id="CBL-0001"))
    cable_run(session.run_dir.parent, "CBL-0001", "20261101_090000")  # older
    newest = cable_run(session.run_dir.parent, "CBL-0001", "20261103_100000")
    runner, path = session.build_runner(ref)
    spec = runner.measurement.params["correction"]["cable"]
    assert spec["run"] == str(newest) and spec["asset_id"] == "CBL-0001"  # which one was used
    runner.start()
    assert runner.join(60) and runner.state is RunState.FINISHED, runner.error
    header = json.loads(path.read_text().splitlines()[0])
    assert header["params"]["correction"]["cable"]["run"] == str(newest)  # saved with the run
    row = next(
        json.loads(x)["values"]
        for x in path.read_text().splitlines()
        if '"kind": "point"' in x and '"table": "points"' in x
    )
    assert row["corrected"] and row["correction_source"] == "CBL-0001"


def test_without_a_measurement_of_that_cable_the_run_is_refused_before_it_starts(
    registry, tmp_path
):
    from ola.measurement import MeasurementError

    session, ref = make_project(tmp_path, registry, with_cable(RL, asset_id="CBL-0042"))
    cable_run(session.run_dir.parent, "CBL-0001", "20261101_090000")
    with pytest.raises(MeasurementError, match="no finished cable measurement of CBL-0042"):
        session.build_runner(ref)


def test_a_named_file_is_left_alone_and_a_run_without_correction_is_unchanged(registry, tmp_path):
    session, ref = make_project(tmp_path, registry, RL)
    plain = session.load(ref).params
    assert session.resolve_correction(plain) is plain
    named = with_cable(RL, asset_id="CBL-0042", run="somewhere.jsonl")
    assert session.resolve_correction(named) is named
    assert session.resolve_correction(with_cable(RL, touchstone="a.s2p")) is not None
    other = tmp_path / "other"
    cable_run(other, "CBL-0042", "20261103_100000")
    session.extra_run_dirs.append(other / "runs")  # a cable measured in another project
    found = session.resolve_correction(with_cable(RL, asset_id="cbl-42"))
    assert found["correction"]["cable"]["run"].endswith("cable_20261103_100000.jsonl")
    assert "run" not in named["correction"]["cable"] or named["correction"]["cable"]["run"]
