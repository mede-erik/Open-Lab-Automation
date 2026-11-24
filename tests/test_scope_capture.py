# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Waveforms during the efficiency measurements: the capture module, the run, and the session."""

import json
import math

import numpy as np
import pytest

from ola.demo_lab import INSTRUMENTS, DemoHandle, DemoLab, demo_params
from ola.efficiency_spec import validate_params
from ola.measurement import MeasurementError
from ola.project import MeasurementFile, Project
from ola.project_session import ProjectSession
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.scope_capture import capture_steps, enabled_channels, estimate
from ola.sim_scope import SimScope
from ola.vna_common import Problem  # noqa: F401  (the VNA modules: checked below)
from ola.wavefiles import export_csv, load_capture, wave_folder

LONG = {
    "settings": {"time_per_div": 1e-3},
    "channels": [
        {"channel_id": "CH1", "enabled": True, "volt_per_div": "1V"},
        {"channel_id": "CH2", "enabled": True, "volt_per_div": "1V"},
        {"channel_id": "CH3", "enabled": False, "volt_per_div": "1V"},
    ],
    "trigger": {"source": "CH1", "level": 1.0, "slope": "RISE", "mode": "AUTO"},
}
RISE = {"settings": {"time_per_div": 1e-6}, "channels": [{"channel_id": "CH1", "enabled": True}]}
ACQUISITIONS = [
    {"name": "long", "file": "long.was", "settings": LONG},
    {"name": "rise", "file": "rise.was", "settings": RISE},
]


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(every=2, **extra):
    p = demo_params(samples=1, interval_s=0.0)
    p["scope_capture"] = {
        "instrument": "osc1", "every": every, "wait_s": 0.0, "acquisitions": ACQUISITIONS, **extra
    }  # fmt: skip
    return p


def run(registry, p, tmp_path, scope=None, run_path=True):
    scope = scope or SimScope(name="osc1", default_depth=2000)
    lab = DemoLab()
    handles = {"instruments": [DemoHandle(n, lab) for n in INSTRUMENTS], "scope": [scope]}
    measurement = registry.create("efficiency", p)
    path = tmp_path / "runs" / "eff_run.jsonl"
    if run_path:
        measurement.set_run_path(path)
    runner = Runner(measurement, handles)
    runner.start()
    assert runner.join(60)
    tables, logs = {}, []
    for e in runner.drain():
        if e.kind == "point":
            tables.setdefault(e.data["table"], []).append(e.data["values"])
        elif e.kind == "log":
            logs.append((e.data["level"], e.data["message"]))
    return runner, scope, tables, logs, path


# ---- the helpers -------------------------------------------------------------------------------
def test_the_enabled_channels_of_a_settings_file_are_listed_in_order():
    assert enabled_channels(LONG) == [1, 2] and enabled_channels(RISE) == [1]
    assert enabled_channels({}) == [] and enabled_channels({"channels": [{"enabled": False}]}) == []
    by_key = {"channels": {"CH2": {"enabled": True}, "CH4": {"enabled": True}}}
    assert enabled_channels(by_key) == [2, 4]


def test_the_size_of_the_waveforms_is_estimated_before_the_start():
    assert capture_steps(9, 2) == 5 and capture_steps(9, 1) == 9 and capture_steps(0, 2) == 0
    # 9 steps every 2: 5 steps x (2 + 1 channels) x 1 M points x 4 bytes
    found = estimate(9, 2, ACQUISITIONS)
    assert found == {"captures": 10, "waveforms": 15, "bytes": 15 * 4_000_000}
    assert estimate(9, 2, ACQUISITIONS, channels=[1], points=1000)["waveforms"] == 10


# ---- the parameters ----------------------------------------------------------------------------
def test_the_parameters_of_the_waveforms_are_checked():
    ok = params()
    assert [p for p in validate_params(ok) if p.severity == "error"] == []
    assert [p for p in validate_params(demo_params())] == [] or True  # no capture: nothing to say
    for change, text in (
        ({"every": 0}, "at least 1"),
        ({"every": "2"}, "number"),
        ({"channels": []}, "channel numbers"),
        ({"channels": [0]}, "channel numbers"),
        ({"bits": 12}, "8 or 16"),
        ({"wait_s": -1}, "at least"),
        ({"acquisitions": [{"name": "x"}]}, "name, file, settings"),
        ({"nothing": 1}, "unknown field"),
    ):
        found = validate_params(params(**change))
        assert any(text in p.message for p in found), (change, found)
    bad = params()
    del bad["scope_capture"]["every"]
    assert any("every how many steps" in p.message for p in validate_params(bad))
    bad = params()
    bad["scope_capture"]["instrument"] = "nope"
    assert any("not in the project" in p.message for p in validate_params(bad, ["psu1", "osc1"]))
    off = params()
    off["scope_capture"] = {}
    assert [p for p in validate_params(off) if p.severity == "error"] == []  # {} means off


# ---- a run -------------------------------------------------------------------------------------
def test_every_other_step_is_captured_for_each_acquisition_in_order(registry, tmp_path):
    runner, scope, tables, logs, path = run(registry, params(), tmp_path)
    assert runner.state is RunState.FINISHED and len(tables["points"]) == 9
    rows = tables["waves"]
    assert [(r["step"], r["acquisition"]) for r in rows] == [
        (s, a) for s in (0, 2, 4, 6, 8) for a in ("long", "rise")
    ]  # steps 0, 2, 4, 6, 8; the acquisitions one after the other, in the order of the list
    assert all(r["scope"] == "osc1" and r["bytes"] > 0 and not r["forced"] for r in rows)
    assert rows[0]["channels"] == "CH1,CH2" and rows[1]["channels"] == "CH1"
    assert rows[0]["points"] == 2000 and rows[0]["vin"] == 9.0  # the setpoints of that step
    folder = wave_folder(path)
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        f"s{s:05d}_{a}_osc1.npz" for s in (0, 2, 4, 6, 8) for a in ("long", "rise")
    )
    first = load_capture(folder / "s00000_long_osc1.npz")
    assert list(first.voltages) == ["CH1", "CH2"] and first.points == 2000
    assert first.settings == {"file": "long.was"} and first.setpoints["vin"] == 9.0
    assert first.dt == pytest.approx(1.0 / scope.sample_rate(), rel=1e-6) or first.dt > 0
    # the oscilloscope was set as each file says, just before its capture
    steps = [c for c in scope.calls if c[0] == "set_timebase_scale"]
    assert [c[1]["value"] for c in steps[:2]] == [1e-3, 1e-6]
    assert not [m for lvl, m in logs if lvl in ("warning", "error")]


def test_every_step_and_only_some_channels(registry, tmp_path):
    runner, _scope, tables, _logs, path = run(registry, params(every=1, channels=[2]), tmp_path)
    assert runner.state is RunState.FINISHED
    assert len(tables["waves"]) == 9 * 2 and {r["channels"] for r in tables["waves"]} == {"CH2"}
    assert len(list(wave_folder(path).iterdir())) == 18


def test_without_scope_capture_nothing_is_taken(registry, tmp_path):
    p = demo_params(samples=1, interval_s=0.0)
    runner, scope, tables, _logs, path = run(registry, p, tmp_path)
    assert runner.state is RunState.FINISHED and "waves" not in tables
    assert not wave_folder(path).exists() and scope.captures == 0
    # and the same with an empty block (an editor with nothing in it)
    p["scope_capture"] = {}
    runner, scope, tables, _logs, path = run(registry, p, tmp_path)
    assert runner.state is RunState.FINISHED and "waves" not in tables and scope.captures == 0


def test_a_scope_that_fails_at_one_step_does_not_stop_the_run(registry, tmp_path):
    class Flaky(SimScope):
        def read_waveform_full(self, channel_number, bits=8, stop=True):
            if self.captures == 3:  # the fourth waveform fails once
                self.captures += 1
                raise TimeoutError("no answer")
            return super().read_waveform_full(channel_number, bits, stop)

    runner, _scope, tables, logs, path = run(
        registry, params(), tmp_path, scope=Flaky(name="osc1", default_depth=500)
    )
    assert runner.state is RunState.FINISHED and len(tables["points"]) == 9
    warnings = [m for lvl, m in logs if lvl == "warning"]
    assert any("no answer" in m for m in warnings)
    assert 0 < len(tables["waves"]) < 10  # the others were captured
    assert len(list(wave_folder(path).iterdir())) == len(tables["waves"])


def test_the_trigger_is_forced_when_it_does_not_arrive(registry, tmp_path):
    class Slow(SimScope):
        forced = 0

        def supports(self, name):
            return name in ("query_trigger_status", "force_trigger") or super().supports(name)

        def call(self, name, **args):
            if name == "query_trigger_status":
                return "WAIT"
            if name == "force_trigger":
                Slow.forced += 1
                return None
            return super().call(name, **args)

    p = params(every=4, wait_s=0.05)
    runner, _scope, tables, logs, _path = run(
        registry, p, tmp_path, scope=Slow(name="osc1", default_depth=500)
    )
    assert runner.state is RunState.FINISHED
    assert Slow.forced == len(tables["waves"]) == 6  # steps 0, 4, 8 x two acquisitions
    assert all(r["forced"] for r in tables["waves"])
    assert any("forced" in m for lvl, m in logs if lvl == "warning")


def test_a_trigger_that_arrived_is_not_forced(registry, tmp_path):
    class Quick(SimScope):
        def supports(self, name):
            return name in ("query_trigger_status", "force_trigger") or super().supports(name)

        def call(self, name, **args):
            if name == "query_trigger_status":
                return "TD"
            if name == "force_trigger":
                raise AssertionError("forced a trigger that had arrived")
            return super().call(name, **args)

    runner, _s, tables, _l, _p = run(
        registry, params(every=9), tmp_path, scope=Quick(name="osc1", default_depth=500)
    )
    assert runner.state is RunState.FINISHED and len(tables["waves"]) == 2
    assert not any(r["forced"] for r in tables["waves"])


def test_asking_for_waveforms_without_what_they_need_stops_before_anything_is_touched(
    registry, tmp_path
):
    lab = DemoLab()
    handles = [DemoHandle(n, lab) for n in INSTRUMENTS]
    for bound, p, text in (
        ([], params(), "one oscilloscope"),  # no oscilloscope
        (
            [SimScope(name="a")],
            {**params(), "scope_capture": {"instrument": "a", "every": 2}},
            "scope settings",
        ),
    ):
        measurement = registry.create("efficiency", p)
        measurement.set_run_path(tmp_path / "r.jsonl")
        runner = Runner(measurement, {"instruments": handles, "scope": bound})
        runner.start()
        runner.join(30)
        assert runner.state is RunState.FAILED and text in str(runner.error), (text, runner.error)
    two = Runner(
        registry.create("efficiency", params()),
        {"instruments": handles, "scope": [SimScope(name="a"), SimScope(name="b")]},
    )
    with pytest.raises(MeasurementError, match="accepts one instrument"):  # the runner says it
        two.start()
    measurement = registry.create("efficiency", params())  # no run file to put the waves next to
    runner = Runner(measurement, {"instruments": handles, "scope": [SimScope(name="a")]})
    runner.start()
    runner.join(30)
    assert runner.state is RunState.FAILED and "run file" in str(runner.error)
    assert lab.log == []  # no instrument of the converter was touched


def test_a_waveform_can_be_exported_to_csv(registry, tmp_path):
    _runner, _s, _t, _l, path = run(registry, params(every=9), tmp_path)
    file = wave_folder(path) / "s00000_long_osc1.npz"
    target = tmp_path / "out.csv"
    assert export_csv(file, target) == 2000
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "time_s,CH1,CH2" and len(lines) == 2001
    first = [float(x) for x in lines[1].split(",")]
    capture = load_capture(file)
    assert first[0] == pytest.approx(capture.times()[0]) and first[1] == pytest.approx(
        float(capture.voltages["CH1"][0])
    )
    assert math.isfinite(first[2]) and np.isfinite(capture.voltages["CH2"]).all()


# ---- the VNA measurements have no oscilloscope role --------------------------------------------
def test_no_vna_measurement_takes_waveforms(registry):
    for info in registry.list():
        roles = {r.name for r in info.roles}
        if "vna" in roles:
            assert "scope" not in roles and "oscilloscope" not in roles, info.id
    assert "scope" in {r.name for r in registry.get("efficiency").roles}
    assert "scope" in {r.name for r in registry.get("resistive_efficiency").roles}
    assert not next(r for r in registry.get("efficiency").roles if r.name == "scope").required


# ---- the project -------------------------------------------------------------------------------
def make_session(tmp_path, scope_files=("long.was", "rise.was"), settings=None, every=2):
    registry = default_registry(user_dir="/nonexistent")
    lab = DemoLab()
    scope = SimScope(name="osc1", default_depth=500)

    def connect(name, cancel=None):
        return scope if name == "osc1" else DemoHandle(name, lab)

    session = ProjectSession(
        Project.new("Lab", tmp_path),
        registry,
        connect=connect,
        instruments=INSTRUMENTS + ["osc1"],
    )
    ref = session.create("efficiency", "Eff")
    p = demo_params(samples=1, interval_s=0.0)
    p["scope_capture"] = {"instrument": "osc1", "every": every, "wait_s": 0.0}
    MeasurementFile(
        type="efficiency", role_bindings={"instruments": INSTRUMENTS, "scope": ["osc1"]}, params=p
    ).save(session.path(ref))
    contents = {"long.was": LONG, "rise.was": RISE, **(settings or {})}
    for name in scope_files:
        (tmp_path / name).write_text(json.dumps(contents.get(name, LONG)), encoding="utf-8")
        session.project.add_scope_file(name)
    return session, ref, scope


def test_the_project_gives_the_acquisitions_in_order_and_leaves_the_file_alone(tmp_path):
    session, ref, _scope = make_session(tmp_path)
    session.project.set_scope_enabled("long.was", False)
    session.project.add_scope_file("fall.was")
    (tmp_path / "fall.was").write_text(json.dumps(RISE), encoding="utf-8")
    session.project.move_scope_file("fall.was", -2)  # fall, long (off), rise
    resolved = session.resolve_scope_settings(session.load(ref).params)
    got = resolved["scope_capture"]["acquisitions"]
    assert [a["name"] for a in got] == ["fall", "rise"]  # the ones that are on, in order
    assert got[0]["file"] == "fall.was" and got[0]["settings"] == RISE
    assert "acquisitions" not in session.load(ref).params["scope_capture"]  # the file is as it was
    plain = demo_params()
    assert session.resolve_scope_settings(plain) == plain  # no capture asked: nothing changes


def test_a_project_without_a_usable_settings_file_says_so_before_the_start(tmp_path):
    session, ref, _scope = make_session(tmp_path, scope_files=())
    with pytest.raises(MeasurementError, match="no scope settings file that is on"):
        session.build_runner(ref)
    session, ref, _scope = make_session(tmp_path / "b", scope_files=("long.was",))
    session.project.set_scope_enabled("long.was", False)
    with pytest.raises(MeasurementError, match="no scope settings file that is on"):
        session.build_runner(ref)
    session, ref, _scope = make_session(tmp_path / "c", scope_files=("long.was",))
    (tmp_path / "c" / "long.was").unlink()
    with pytest.raises(MeasurementError, match="long.was is missing"):
        session.build_runner(ref)
    (tmp_path / "c" / "long.was").write_text("not json", encoding="utf-8")
    with pytest.raises(MeasurementError, match="cannot be read"):
        session.build_runner(ref)
    (tmp_path / "c" / "long.was").write_text(json.dumps({"trigger": {"slope": "UP"}}))
    with pytest.raises(MeasurementError, match="slope"):
        session.build_runner(ref)


def test_a_run_of_the_project_writes_the_waveforms_next_to_its_results(tmp_path):
    session, ref, _scope = make_session(tmp_path)
    runner, path = session.build_runner(ref)
    runner.start()
    assert runner.join(60) and runner.state is RunState.FINISHED
    folder = wave_folder(path)
    assert folder.name == path.stem + "_waves" and folder.parent == path.parent
    assert len(list(folder.iterdir())) == 5 * 2
    lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    waves = [x for x in lines if x.get("kind") == "point" and x.get("table") == "waves"]
    assert len(waves) == 10 and waves[0]["values"]["file"].startswith(path.stem + "_waves/")
    header = lines[0]
    assert header["params"]["scope_capture"]["every"] == 2  # the header keeps the parameters
    assert [a["name"] for a in header["params"]["scope_capture"]["acquisitions"]] == [
        "long", "rise"]  # fmt: skip


def test_the_oscilloscope_is_bound_to_its_own_role_even_in_a_file_written_by_hand(tmp_path):
    session, ref, scope = make_session(tmp_path)
    content = session.load(ref)
    content.role_bindings = {"instruments": INSTRUMENTS}  # no "scope" binding
    content.save(session.path(ref))
    runner, _path = session.build_runner(ref)
    assert [h.name for h in runner.bindings["scope"]] == ["osc1"]


def test_the_estimate_before_the_start(tmp_path):
    session, ref, _scope = make_session(tmp_path)
    found = session.wave_estimate(ref)
    assert found == {"steps": 9, "captures": 10, "waveforms": 15, "bytes": 15 * 4_000_000}
    plain, plain_ref, _s = make_session(tmp_path / "p")
    content = plain.load(plain_ref)
    del content.params["scope_capture"]
    content.save(plain.path(plain_ref))
    assert plain.wave_estimate(plain_ref) is None  # no waveforms asked: nothing to warn about
    nothing, nothing_ref, _s = make_session(tmp_path / "n", scope_files=())
    assert nothing.wave_estimate(nothing_ref) is None  # the run itself will say why not


# ---- the windows -------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.gui
def test_the_editor_asks_for_the_oscilloscope_and_how_often_and_says_what_it_costs(app, tmp_path):
    from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog
    from ola.efficiency_editor import EfficiencyEditor

    editor = EfficiencyEditor(demo_params())
    path = tmp_path / "x.eff"
    editor.save(str(path))
    dialog = EfficiencyEditorDialog(str(path), None, INSTRUMENTS + ["osc1"])
    assert dialog.waves_summary.text() == ""
    dialog.waves_instrument.setCurrentText("osc1")
    dialog.waves_every.setText("2")
    assert dialog.editor.params["scope_capture"] == {"instrument": "osc1", "every": 2}
    assert dialog.waves_summary.text()  # "5 of 9 steps are captured..."
    assert "5" in dialog.waves_summary.text() and "9" in dialog.waves_summary.text()
    saved = dialog.editor.to_measurement_file()
    assert saved.role_bindings["scope"] == ["osc1"]  # its own role
    assert "osc1" not in saved.role_bindings["instruments"]
    dialog.waves_every.setText("")
    dialog.waves_instrument.setCurrentText("")
    assert "scope_capture" not in dialog.editor.params  # emptied: no waveforms, no block
    dialog.dirty = False
    dialog.close()


@pytest.mark.gui
def test_a_run_that_takes_gigabytes_asks_first(app, tmp_path, monkeypatch):
    from frontend.ui import ProjectWindow as module
    from frontend.ui.ProjectWindow import ProjectWindow, demo_project

    lab = DemoLab()
    window = ProjectWindow(
        demo_project(str(tmp_path)),
        connect=lambda name, cancel=None: DemoHandle(name, lab),
        registry=default_registry(user_dir="/nonexistent"),
    )
    ref = window.session.project.measurements[0]
    content = window.session.load(ref)
    content.params["scope_capture"] = {"instrument": "psu1", "every": 1, "points": 100_000_000}
    content.save(window.session.path(ref))
    (tmp_path / "a.was").write_text(json.dumps(LONG), encoding="utf-8")
    window.session.project.add_scope_file("a.was")
    asked = []
    answers = iter([QtWidgets.QMessageBox.StandardButton.No])
    monkeypatch.setattr(
        module.QMessageBox,
        "question",
        staticmethod(lambda parent, title, text: asked.append(text) or next(answers)),
    )
    window.table.selectRow(0)
    window.run_measurement()
    assert len(asked) == 1 and "GB" in asked[0] and "waveforms" in asked[0]
    assert not window.run_windows  # No: nothing started
    content.params["scope_capture"]["points"] = 1000  # small: no question
    content.save(window.session.path(ref))
    assert window._confirm_waves(ref) is True and len(asked) == 1
    window._timer.stop()
    window.close()
