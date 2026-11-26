# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A VNA that keeps its own calibration loses it when it is switched off: the program finds that
with a presence probe, reports it, and never blocks the measurement (issue 129)."""

import types

import pytest

from ola import identity as ident
from ola import vna_calibration_flow as flow
from ola import vna_controls as vc
from ola.demo_lab import INSTRUMENTS, DemoHandle, DemoLab
from ola.project import Project
from ola.project_session import ProjectSession
from ola.registry import default_registry
from ola.runs import read_run
from ola.vna_power_state import CALIBRATED, LOST, MISSING, PowerState
from tests.test_project_session import add_efficiency


class OwnCalibrationVna:
    """A fake VNA with its own calibration (no ``calibration_import``): it answers the identity
    query while it is on, and says nothing when it is off."""

    def __init__(self, name="VNA", serial="SN7"):
        self.name = name
        self.identity = ident.parse_idn(f"Siglent,SNA5000A,{serial},1.0")
        self.on = True
        self.calls = []

    def supports(self, call):
        return call != "calibration_import"

    def call(self, call, **kwargs):
        self.calls.append(call)
        if call == "identification_query":
            if not self.on:
                raise TimeoutError("no answer")
            return "Siglent,SNA5000A,SN7,1.0"
        return None


def calibrate(handle, state):
    session = flow.CalibrationSession(handle, "ONE_PORT", 1, None, None)
    session.start()
    for step in session.steps:
        session.measure(step)
    session.finish()
    state.mark_calibrated(handle)  # (the session does it on the state of the program)


def test_calibrated_then_off_then_on_again_stays_lost():
    state, vna = PowerState(), OwnCalibrationVna()
    assert state.status(vna) == MISSING  # the program has not seen it calibrated
    calibrate(vna, state)
    assert state.check(vna) is None and state.status(vna) == CALIBRATED  # answers: still valid
    vna.on = False
    warning = state.check(vna)  # no answer: cleared
    assert state.status(vna) == LOST and "switched off" in warning
    vna.on = True
    assert state.check(vna) is not None  # it answers again: still lost, the operator is told
    assert state.status(vna) == LOST
    calibrate(vna, state)  # a new calibration sets the state again
    assert state.check(vna) is None


def test_an_instrument_not_seen_calibrated_is_reported_as_missing():
    state = PowerState()
    text = state.check(OwnCalibrationVna())
    assert text and "not calibrated since the program started" in text


def test_the_state_belongs_to_the_apparatus():
    state = PowerState()
    a, b = OwnCalibrationVna("A", "SN1"), OwnCalibrationVna("B", "SN2")
    state.mark_calibrated(a)
    assert state.status(a) == CALIBRATED and state.status(b) == MISSING


def software_vna(serial="SN9"):
    handle = OwnCalibrationVna("LiteVNA", serial)
    handle.supports = lambda call: True  # it can import a calibration: the LiteVNA way
    handle.calibration = {"file": "x", "kind": "ONE_PORT"}
    handle.applied = []
    handle.set_calibration = handle.applied.append
    return handle


def test_a_software_calibration_is_forgotten_when_the_vna_was_off():
    handle, state = software_vna(), PowerState()
    state.mark_calibrated(handle)
    assert state.check(handle) is None and state.allows_restore(handle)
    handle.on = False
    text = state.check(handle)  # no answer: the calibration of the program is dropped
    assert "switched off" in text and not state.allows_restore(handle)
    assert "calibration_clear" in handle.calls and handle.applied == [None]
    handle.on = True
    assert state.check(handle) and not state.allows_restore(handle)  # answers again: still lost


def test_a_calibration_of_an_earlier_run_is_not_put_back():
    handle, state = software_vna(), PowerState()  # the program just started: nothing seen
    text = state.check(handle)
    assert "not calibrated in this session" in text
    assert not state.allows_restore(handle)


def test_the_saved_calibration_is_restored_only_in_the_session_that_made_it(
    monkeypatch, tmp_path
):
    from ola import vna_power_state as module

    fresh = PowerState()
    monkeypatch.setattr(module, "POWER_STATE", fresh)
    restored = []
    monkeypatch.setattr(
        flow, "auto_restore", lambda handle, path, sweep: restored.append(handle.name)
    )
    handle = software_vna()
    session = types.SimpleNamespace(
        project=types.SimpleNamespace(path=tmp_path / "p.json"), calibration_warnings=[]
    )
    ProjectSession._restore_calibrations(session, [handle], {"sweep": {"points": 11}})
    assert restored == [] and len(session.calibration_warnings) == 1  # a new start: forgotten
    fresh.mark_calibrated(handle)  # calibrated now, in this session
    session.calibration_warnings.clear()
    ProjectSession._restore_calibrations(session, [handle], {"sweep": {"points": 11}})
    assert restored == ["LiteVNA"] and session.calibration_warnings == []


def test_the_probe_never_raises():
    assert ident.probe_presence(OwnCalibrationVna()) is True
    off = OwnCalibrationVna()
    off.on = False
    assert ident.probe_presence(off) is False
    silent = OwnCalibrationVna()
    silent.call = lambda *a, **k: ""
    assert ident.probe_presence(silent) is False


def test_a_calibration_made_by_the_program_sets_the_state(monkeypatch):
    from ola import vna_power_state as module

    fresh = PowerState()
    monkeypatch.setattr(module, "POWER_STATE", fresh)
    vna = OwnCalibrationVna()
    session = flow.CalibrationSession(vna, "ONE_PORT", 1, None, None)
    session.start()
    for step in session.steps:
        session.measure(step)
    assert fresh.status(vna) == MISSING
    session.finish()
    assert fresh.status(vna) == CALIBRATED


def test_the_panel_asks_the_same_question(monkeypatch):
    from ola import vna_power_state as module

    monkeypatch.setattr(module, "POWER_STATE", PowerState())
    vna = OwnCalibrationVna()
    assert vc.power_warning(vna)  # never calibrated here
    module.POWER_STATE.mark_calibrated(vna)
    assert vc.power_warning(vna) is None


def test_a_run_before_the_calibration_is_reported_not_blocked(monkeypatch, tmp_path):
    from ola import vna_power_state as module

    monkeypatch.setattr(module, "POWER_STATE", PowerState())
    session = types.SimpleNamespace(
        project=types.SimpleNamespace(path=tmp_path / "p.json"), calibration_warnings=[]
    )
    vna = OwnCalibrationVna()
    ProjectSession._restore_calibrations(session, [vna], {"sweep": {"points": 11}})  # no raise
    assert [w["instrument"] for w in session.calibration_warnings] == ["VNA"]
    module.POWER_STATE.mark_calibrated(vna)
    session.calibration_warnings.clear()
    ProjectSession._restore_calibrations(session, [vna], {"sweep": {"points": 11}})
    assert session.calibration_warnings == []


def test_the_run_file_and_the_log_say_the_calibration_is_lost(tmp_path):
    lab = DemoLab()
    session = ProjectSession(
        Project.new("Demo", tmp_path),
        default_registry(user_dir="/nonexistent"),
        connect=lambda name, cancel=None: DemoHandle(name, lab),
        instruments=INSTRUMENTS,
    )
    ref = add_efficiency(session)
    original = session.bind

    def bind(*args, **kwargs):
        handles = original(*args, **kwargs)
        session.calibration_warnings = [{"instrument": "VNA", "text": "VNA lost its calibration"}]
        return handles

    session.bind = bind
    runner, path = session.build_runner(ref)
    runner.start()
    assert runner.join(30)  # not blocked
    logs = [e.data["message"] for e in runner.drain() if e.kind == "log"]
    assert "VNA lost its calibration" in logs
    run = read_run(path)
    assert run["end"]["state"] == "finished"
    assert run["header"]["calibration_lost"] == [
        {"instrument": "VNA", "text": "VNA lost its calibration"}
    ]


@pytest.mark.parametrize("lang", ["en", "it", "fr", "es", "de"])
def test_the_new_texts_exist_in_every_language(lang):
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "frontend" / "lang"
    main = json.loads((root / f"{lang}.json").read_text(encoding="utf-8"))
    path = root / "modules" / "project" / f"{lang}.json"
    project = json.loads(path.read_text(encoding="utf-8"))
    assert main["vna_calibration_lost"] and "{name}" in project["prj_calibration_lost"]
