# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The "configure the oscilloscope" button of the Remote control tab says what happened: the
settings applied, or why not (no project, an oscilloscope that is not there or does not answer,
settings the model refused). Before, every problem was only printed on the console."""

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from frontend.ui.RemoteControlTab import RemoteControlTab  # noqa: E402
from ola import call_planner  # noqa: E402
from ola.call_errors import CallNotSupportedError, StepFailedError  # noqa: E402
from tests.conftest import REPO  # noqa: E402

EXAMPLE = Path(REPO) / "examples" / "test-dcdc-project"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def shown(monkeypatch):
    seen = []
    for kind in ("warning", "information"):
        monkeypatch.setattr(
            QMessageBox, kind,
            staticmethod(lambda parent, title, text, k=kind: seen.append((k, text))),
        )  # fmt: skip
    return seen


class Window(QWidget):
    """The window that owns the tab: it tells the tab which project is open."""

    def __init__(self, folder=None, data=None):
        super().__init__()
        self.folder, self.data = folder, data

    def source(self):
        """What ``RemoteControlTab.project_source`` gives: the open project, or None."""
        if not self.folder:
            return None
        return {"dir": str(self.folder), **(self.data or {})}


@pytest.fixture
def project(tmp_path):
    for name in ("osc1.was", "test_instruments.inst"):
        shutil.copy(EXAMPLE / name, tmp_path / name)
    return tmp_path, {"inst_file": "test_instruments.inst", "scope_settings": ["osc1.was"]}


class Executor:
    def __init__(self, fail=None):
        self.name, self.fail, self.calls = "OSC", fail, []

    def run(self, plan):
        self.calls.append(plan)
        if self.fail is not None:
            raise self.fail


def make_tab(app, folder=None, data=None):
    window = Window(folder, data)
    tab = RemoteControlTab(LoadInstruments())
    tab.project_source = window.source
    tab._window = window  # kept alive with the tab
    return tab


def reachable(tab, monkeypatch, executor):
    """The library knows the model, VISA opens the address, the executor is ``executor``."""
    library = type("Library", (), {"resolve_model_id": lambda self, key: "M"})()
    monkeypatch.setattr(tab.instruments_manager, "get_library", lambda: library)
    monkeypatch.setattr(tab, "_ensure_visa_initialized", lambda: True)
    tab.rm = type("RM", (), {"open_resource": lambda self, address: object()})()
    monkeypatch.setattr(tab, "_get_instrument_executor", lambda *a, **k: executor)
    monkeypatch.setattr(call_planner, "plan_call", lambda library, model, name, args: name)


def test_without_a_project_it_says_so(app, shown):
    tab = make_tab(app)
    tab._configure_oscilloscope_from_was()
    assert shown and shown[0][0] == "warning" and "project" in shown[0][1]


def test_a_project_without_a_was_file_says_so(app, shown, project):
    folder, data = project
    tab = make_tab(app, folder, {**data, "scope_settings": []})
    tab._configure_oscilloscope_from_was()
    assert shown[0][0] == "warning" and ".was" in shown[0][1]


def test_an_oscilloscope_that_is_not_on_the_network_is_reported(app, shown, project, monkeypatch):
    folder, data = project
    tab = make_tab(app, folder, data)
    reachable(tab, monkeypatch, Executor())

    def refuse(self, address):
        raise OSError("VI_ERROR_RSRC_NFOUND")

    tab.rm = type("RM", (), {"open_resource": refuse})()
    tab._configure_oscilloscope_from_was()
    kind, text = shown[0]
    assert kind == "warning"
    assert "OSC" in text and "192.168.1.125" in text and "VI_ERROR_RSRC_NFOUND" in text


def test_an_oscilloscope_that_does_not_answer_stops_at_the_first_setting(
    app, shown, project, monkeypatch
):
    folder, data = project
    tab = make_tab(app, folder, data)
    executor = Executor(StepFailedError("set_timebase_scale", 0, TimeoutError("timeout")))
    reachable(tab, monkeypatch, executor)
    tab._configure_oscilloscope_from_was()
    assert len(executor.calls) == 1  # not one timeout for each setting
    assert shown[0][0] == "warning" and "does not answer" in shown[0][1]


def test_settings_the_model_refuses_are_listed(app, shown, project, monkeypatch):
    folder, data = project
    tab = make_tab(app, folder, data)
    executor = Executor(CallNotSupportedError("not on this model", call="set_trigger_slope"))
    reachable(tab, monkeypatch, executor)
    tab._configure_oscilloscope_from_was()
    kind, text = shown[0]
    assert kind == "warning" and "were not applied" in text and "not on this model" in text
    assert len(executor.calls) > 1  # the other settings were still tried


def test_when_everything_is_applied_no_window_appears(app, shown, project, monkeypatch):
    folder, data = project
    tab = make_tab(app, folder, data)
    executor = Executor()
    reachable(tab, monkeypatch, executor)
    tab._configure_oscilloscope_from_was()
    assert executor.calls and shown == []  # the result is seen on the oscilloscope


def test_the_report_is_translated(app, shown, project):
    from frontend.core.Translator import Translator

    tab = make_tab(app)
    tab.translator = Translator(default_lang="it")
    tab._configure_oscilloscope_from_was()
    assert "progetto" in shown[0][1]
    assert json.dumps(shown)  # plain texts


def test_each_problem_of_the_report_has_its_code(app, shown, project, monkeypatch):
    folder, data = project
    tab = make_tab(app, folder, data)
    reachable(tab, monkeypatch, Executor())

    def refuse(self, address):
        raise OSError("VI_ERROR_RSRC_NFOUND")

    tab.rm = type("RM", (), {"open_resource": refuse})()
    tab._configure_oscilloscope_from_was()
    assert shown[0][1].startswith("[VISA-001] OSC")
    tab2 = make_tab(app)
    tab2._configure_oscilloscope_from_was()
    assert shown[1][1].startswith("[PROJ-009]")


def test_a_failed_run_shows_its_code():
    from frontend.ui.RunWindow import failure_text

    assert failure_text({"message": "boom", "code": None}) == "[MEAS-006] boom"
    assert failure_text({"message": "[CALL-004] no answer", "code": "CALL-004"}) == (
        "[CALL-004] no answer"
    )
    assert failure_text({"message": "x", "code": "TRN-003"}) == "[TRN-003] x"


def test_with_several_files_on_the_user_chooses_which_one_is_applied(
    app, shown, project, monkeypatch
):
    folder, data = project
    shutil.copy(folder / "osc1.was", folder / "rise.was")
    tab = make_tab(app, folder, {**data, "scope_settings": ["osc1.was", "rise.was"]})
    reachable(tab, monkeypatch, Executor())
    offered = []
    applied = []
    monkeypatch.setattr(
        tab, "_choose_scope_file", lambda names: offered.append(names) or "rise.was"
    )
    monkeypatch.setattr(
        tab, "_apply_oscilloscope_settings", lambda was, name="", only=None: applied.append(name)
    )
    tab._configure_oscilloscope_from_was()
    assert offered == [["osc1.was", "rise.was"]] and applied == ["rise.was"]
    assert shown == []


def test_closing_the_menu_applies_nothing(app, shown, project, monkeypatch):
    folder, data = project
    tab = make_tab(app, folder, {**data, "scope_settings": ["osc1.was", "rise.was"]})
    applied = []
    monkeypatch.setattr(tab, "_choose_scope_file", lambda names: None)
    monkeypatch.setattr(
        tab, "_apply_oscilloscope_settings", lambda was, name="", only=None: applied.append(name)
    )
    tab._configure_oscilloscope_from_was()
    assert applied == [] and shown == []  # no report either: the user chose nothing


def test_with_one_file_on_there_is_no_menu(app, shown, project, monkeypatch):
    folder, data = project
    tab = make_tab(app, folder, data)
    reachable(tab, monkeypatch, Executor())
    monkeypatch.setattr(tab, "_choose_scope_file", lambda names: pytest.fail("asked"))
    tab._configure_oscilloscope_from_was()
    assert shown == []


def test_a_file_for_one_oscilloscope_is_applied_to_that_one_only(app, shown, project, monkeypatch):
    folder, data = project
    tab = make_tab(app, folder, {**data, "scope_settings": [{"file": "osc1.was", "scope": "OSC2"}]})
    seen = []
    monkeypatch.setattr(
        tab,
        "_get_project_oscilloscopes",
        lambda: [{"instance_name": "OSC1"}, {"instance_name": "OSC2"}],
    )
    monkeypatch.setattr(
        tab,
        "_configure_single_oscilloscope",
        lambda inst, was, name: seen.append(inst["instance_name"]),
    )
    tab._configure_oscilloscope_from_was()
    assert seen == ["OSC2"] and shown == []
    seen.clear()
    tab.project_source = lambda: {
        "dir": str(folder),
        "scope_settings": [{"file": "osc1.was", "scope": ""}],
    }
    tab._configure_oscilloscope_from_was()
    assert seen == ["OSC1", "OSC2"]  # a file that names none: every oscilloscope
    seen.clear()
    tab.project_source = lambda: {"dir": str(folder), "scope_settings": ["osc1.was"]}  # plain names
    tab._configure_oscilloscope_from_was()
    assert seen == ["OSC1", "OSC2"]
