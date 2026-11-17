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
    """What the tab looks for in its parents: the open project."""

    def __init__(self, folder=None, data=None):
        super().__init__()
        self.current_project_dir = str(folder) if folder else None
        self.current_project_data = data


@pytest.fixture
def project(tmp_path):
    for name in ("osc1.was", "test_instruments.inst"):
        shutil.copy(EXAMPLE / name, tmp_path / name)
    return tmp_path, {"inst_file": "test_instruments.inst", "was_files": ["osc1.was"]}


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
    tab.setParent(window)
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
    tab = make_tab(app, folder, {**data, "was_files": []})
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


def test_settings_applied_are_confirmed(app, shown, project, monkeypatch):
    folder, data = project
    tab = make_tab(app, folder, data)
    executor = Executor()
    reachable(tab, monkeypatch, executor)
    tab._configure_oscilloscope_from_was()
    assert executor.calls
    assert shown == [("information", "OSC: the settings of osc1.was were applied.")]


def test_the_report_is_translated(app, shown, project):
    from frontend.core.Translator import Translator

    tab = make_tab(app)
    tab.translator = Translator(default_lang="it")
    tab._configure_oscilloscope_from_was()
    assert "progetto" in shown[0][1]
    assert json.dumps(shown)  # plain texts
