"""Tests of the project window with the simulated lab (no screen needed, see conftest.py)."""

import glob
import json
import os
import re
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from frontend.ui import ProjectWindow as project_module  # noqa: E402
from frontend.ui.ProjectWindow import JsonParamsDialog, ProjectWindow, demo_project  # noqa: E402
from ola.demo_lab import DemoHandle, DemoLab  # noqa: E402
from ola.project import Project  # noqa: E402
from ola.registry import default_registry  # noqa: E402

LANG_DIR = os.path.join(
    os.path.dirname(project_module.__file__), "..", "lang", "modules", "project"
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def pump(app, condition, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(autouse=True)
def no_real_dialogs(monkeypatch):
    """A message box that nobody answers would block the test for ever: fail instead."""

    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected message box: {args[1:3]}")

    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture
def window(app, tmp_path):
    lab = DemoLab()
    w = ProjectWindow(
        demo_project(str(tmp_path)),
        connect=lambda name: DemoHandle(name, lab),
        registry=default_registry(user_dir="/nonexistent"),
    )
    yield w
    for r in w.run_windows:
        r.runner.stop()
        r.runner.join(5)
        r._timer.stop()
        r.model.state = "finished"
        r.close()
    w._timer.stop()
    w.run_windows.clear()
    w.close()


def _catalogs():
    out = {}
    for path in sorted(glob.glob(os.path.join(LANG_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            out[os.path.basename(path)[:-5]] = json.load(f)
    return out


# ---- translations -----------------------------------------------------------------------------
def test_languages_have_the_same_keys_and_placeholders():
    catalogs = _catalogs()
    assert set(catalogs) >= {"en", "it", "fr", "es", "de"}
    for lang, data in catalogs.items():
        assert set(data) == set(catalogs["en"]), lang
        for key, text in data.items():
            assert set(re.findall(r"\{(\w+)\}", text)) == set(
                re.findall(r"\{(\w+)\}", catalogs["en"][key])
            ), (lang, key)


def test_every_key_used_by_the_window_exists():
    source = open(project_module.__file__, encoding="utf-8").read()
    used = set(re.findall(r'"(prj_[a-z_0-9]+)"', source))
    used |= {f"prj_state_{s}" for s in ("finished", "stopped", "failed", "interrupted")}
    assert sorted(used - set(_catalogs()["en"])) == []


# ---- the window -------------------------------------------------------------------------------
def test_lists_the_measurements_of_the_project(window):
    assert window.table.rowCount() == 1
    assert window.table.item(0, 0).text() == "Demo converter"
    assert window.table.item(0, 2).text().endswith(".eff")
    assert window.table.item(0, 3).text() == "OK"
    assert "Demo" in window.header.text()


def test_buttons_follow_the_selection_and_the_state_of_the_file(window):
    window.table.selectRow(0)
    assert window.buttons["prj_run"].isEnabled() and window.buttons["prj_edit"].isEnabled()
    window.session.path(window.session.project.measurements[0]).unlink()
    window._refresh()
    window.table.selectRow(0)
    assert "missing" in window.table.item(0, 3).text()
    assert not window.buttons["prj_run"].isEnabled()
    assert window.buttons["prj_remove"].isEnabled()  # a broken entry can still be removed


def test_start_measurement_opens_the_run_window_and_lists_the_run(app, window):
    window.table.selectRow(0)
    window.run_measurement()
    assert len(window.run_windows) == 1
    run = window.run_windows[0]
    assert pump(app, lambda: run.model.finished)
    assert run.model.state == "finished" and len(run.model.points) == 9
    window._refresh_runs()  # (also done by a timer every second)
    assert window.runs_table.rowCount() == 1
    assert window.runs_table.item(0, 2).text() == "9"
    assert window.export_btn.isEnabled() is False  # nothing selected yet
    window.runs_table.selectRow(0)
    assert window.export_btn.isEnabled()


def test_cannot_start_without_instruments_shows_why(window, monkeypatch):
    window.session.connect = None
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    window.table.selectRow(0)
    window.run_measurement()
    assert shown and "not connected" in shown[0]
    assert not window.run_windows


def test_opening_an_old_format_project_shows_the_reason(app, tmp_path, monkeypatch):
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"project_name": "Old", "eff_files": ["a.eff"]}))
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    w = ProjectWindow(registry=default_registry(user_dir="/nonexistent"))
    try:
        assert not w.open_path(str(old))
        assert shown and "not supported" in shown[0]
        assert w.session is None
    finally:
        w._timer.stop()
        w.close()


def test_without_a_project_nothing_can_be_done(app):
    w = ProjectWindow(registry=default_registry(user_dir="/nonexistent"))
    try:
        assert not w.buttons["prj_new"].isEnabled()
        assert not w.buttons["prj_run"].isEnabled()
        w.new_measurement()  # does nothing, no crash
    finally:
        w._timer.stop()
        w.close()


def test_project_file_stays_in_the_new_format(window):
    window.session.create("efficiency", "Second")
    window._refresh()
    assert window.table.rowCount() == 2
    assert Project.load(window.session.project.path).measurements[1].name == "Second"


# ---- the JSON editor of the types without an editor of their own -------------------------------
def test_json_editor_validates_and_saves(window, monkeypatch):
    ref = window.session.create("time_log", "Log")
    dialog = JsonParamsDialog(window.session, ref, window.tr_)
    dialog.edit.setPlainText("{ not json")
    assert "JSON" in dialog.message.text()
    dialog.edit.setPlainText("[1, 2]")
    assert "object" in dialog.message.text()
    good = {"interval_s": 1, "samples": 3, "reads": [{"instrument": "x", "call": "read_voltage"}]}
    dialog.edit.setPlainText(json.dumps(good))
    # the module judges the content: whatever it says is shown; saving asks if it sees problems
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    dialog.save()
    assert window.session.load(ref).params["samples"] == 3
    # text that is not JSON is never written
    before = window.session.load(ref).params
    dialog2 = JsonParamsDialog(window.session, ref, window.tr_)
    dialog2.edit.setPlainText("{ not json")
    dialog2.save()
    assert window.session.load(ref).params == before


# ---- inside the main window ---------------------------------------------------------------------
def test_the_window_can_be_a_tab_of_the_main_window(app, tmp_path):
    from PyQt6.QtWidgets import QTabWidget

    from frontend.ui.ProjectWindow import not_connected

    tabs = QTabWidget()
    panel = ProjectWindow(
        demo_project(str(tmp_path)),
        connect=not_connected,
        registry=default_registry(user_dir="/nonexistent"),
    )
    try:
        tabs.addTab(panel, panel.tr_.t("prj_tab"))
        tabs.show()
        assert tabs.tabText(0) == "Measurements"
        assert panel.table.rowCount() == 1
    finally:
        panel._timer.stop()
        tabs.close()


def test_not_connected_gives_a_readable_reason_and_sends_nothing(window, monkeypatch):
    from frontend.ui.ProjectWindow import not_connected

    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    window.session.connect = not_connected
    window.table.selectRow(0)
    window.run_measurement()
    assert shown and "cannot reach instrument" in shown[0] and "not available" in shown[0]
    assert not window.run_windows and not window.session.run_dir.exists()


def test_main_window_uses_the_project_tab():
    """main_window.py is not instantiated here (it opens a database); check the wiring."""
    path = os.path.join(os.path.dirname(project_module.__file__), "main_window.py")
    source = open(path, encoding="utf-8").read()
    assert "ProjectWindow(translator=self.translator, connect=not_connected)" in source
    assert "Funzionalità in arrivo" not in source
