# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The Project menu and the Measurements tab work on the same project.

"Add file" used to offer only the efficiency and the oscilloscope files, and a project made from
the menu could not be opened by the Measurements tab (first format). Now the menu creates and
opens projects of the current format, lists every measurement type, and the left list shows the
measurement files and opens their editors.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from ola.measurement import MeasurementError
from ola.project import Project
from ola.project_session import ProjectSession
from ola.registry import default_registry
from tests.conftest import REPO

EXAMPLE = Path(REPO) / "examples" / "test-dcdc-project"
LEGACY = {
    "project_id": "x",
    "project_name": "Old",
    "eff_files": ["a.eff"],
    "inst_file": "old.inst",
    "was_files": ["o.was"],
    "control_variables": ["V1"],
    "measure_variables": [],
}


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_first_format_project_is_upgraded_without_losing_a_key(tmp_path):
    path = write(tmp_path / "Old.json", LEGACY)
    assert Project.upgrade_legacy(path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format_version"] == 2 and data["measurements"] == []
    assert all(data[k] == v for k, v in LEGACY.items())
    project = Project.load(path)  # now readable
    assert project.name == "Old" and project.extra["eff_files"] == ["a.eff"]
    assert Project.upgrade_legacy(path) is False  # already current
    assert Project.upgrade_legacy(tmp_path / "missing.json") is False
    other = write(tmp_path / "other.json", {"hello": 1})
    assert Project.upgrade_legacy(other) is False  # not a project


def test_the_menu_keys_on_disk_win_when_the_project_is_saved(tmp_path):
    path = write(tmp_path / "Old.json", {**LEGACY, "format_version": 2, "measurements": []})
    project = Project.load(path)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    on_disk["calibrations"] = ["c1", "c2"]  # written by the calibration window meanwhile
    path.write_text(json.dumps(on_disk), encoding="utf-8")
    project.save()
    assert json.loads(path.read_text(encoding="utf-8"))["calibrations"] == ["c1", "c2"]


def test_the_was_files_of_an_early_project_become_scope_settings(tmp_path):
    path = write(tmp_path / "Old.json", {**LEGACY, "format_version": 2, "measurements": []})
    project = Project.load(path)
    assert project.scope_file_names() == ["o.was"] and project.active_scope_files() == ["o.was"]
    assert "was_files" not in project.extra
    project.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["scope_settings"] == [{"file": "o.was", "enabled": True}]
    assert "was_files" not in saved  # no longer written
    assert Project.load(path).scope_file_names() == ["o.was"]  # and read back


def make_session(tmp_path):
    project = Project.new("Lab", tmp_path)
    project.save()
    return ProjectSession(project, default_registry())


def test_every_measurement_type_can_be_added_and_an_existing_file_adopted(tmp_path):
    session = make_session(tmp_path)
    types = {t.id: t for t in session.module_types()}
    assert {"efficiency", "cable", "filter"} <= set(types)  # not only efficiency
    for type_id, info in types.items():
        ref = session.create(type_id, f"m {type_id}")
        assert ref.file.endswith(info.extension) and (tmp_path / ref.file).is_file()
    # a file made elsewhere is adopted: its type is read from the file
    shutil.copy(tmp_path / session.project.measurements[0].file, tmp_path / "copy.eff")
    ref = session.adopt("copy.eff")
    assert ref.name == "copy" and Project.load(session.project.path).get(ref.id).file == "copy.eff"
    with pytest.raises(MeasurementError):
        session.adopt("copy.eff")  # twice
    write(tmp_path / "junk.cbl", {"nothing": 1})
    with pytest.raises(MeasurementError):
        session.adopt("junk.cbl")
    write(tmp_path / "x.zzz", {"type": "not-a-type"})
    with pytest.raises(MeasurementError):
        session.adopt("x.zzz")


# ------------------------------------------------------------------------------ the windows
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
QtCore = pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("pytestqt")


@pytest.fixture
def home(monkeypatch, tmp_path):
    """Temporary settings and no blocking dialog (a message box is recorded, not shown)."""
    folder = tmp_path / "home"
    folder.mkdir()
    for var in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(folder))
    for fmt in (QtCore.QSettings.Format.NativeFormat, QtCore.QSettings.Format.IniFormat):
        QtCore.QSettings.setPath(fmt, QtCore.QSettings.Scope.UserScope, str(folder / "settings"))
    QtCore.QSettings("LabAutomation", "App").clear()
    boxes = []
    box = QtWidgets.QMessageBox
    for kind in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(
            box,
            kind,
            staticmethod(lambda *a, _k=kind, **k: boxes.append(_k) or box.StandardButton.Yes),
        )
    return boxes


def listed(window):
    widget = window.project_files_list
    return [widget.item(i).text() for i in range(widget.count())]


@pytest.fixture
def window(qtbot, home):
    from frontend.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    yield window
    timer = getattr(getattr(window, "remote_tab", None), "measurement_timer", None)
    if timer is not None:
        timer.stop()


@pytest.mark.gui
def test_a_project_from_the_menu_opens_in_the_measurements_tab(window, home, monkeypatch, tmp_path):
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path))
    )
    monkeypatch.setattr(
        QtWidgets.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Bench", True))
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.No),
    )
    window.create_new_project()
    assert window.project_tab.session is not None  # the tab shows it
    assert window.project_tab.session.project.name == "Bench"
    assert json.loads((tmp_path / "Bench.json").read_text(encoding="utf-8"))["format_version"] == 2
    assert listed(window) == ["Bench.inst"]


@pytest.mark.gui
def test_add_file_offers_every_type_and_the_files_are_listed_and_edited(
    window, home, monkeypatch, tmp_path
):
    from frontend.ui import main_window as module

    project = tmp_path / "p"
    shutil.copytree(EXAMPLE, project)
    path = project / "Test DC-DC Converter.json"
    window._open_project_path(str(path))
    assert window.project_tab.session.project.name  # a project of the first format was upgraded
    seen = {}

    class Choice(module.AddFileDialog):
        def exec(self):
            seen["types"] = [self.type_combo.itemText(i) for i in range(self.type_combo.count())]
            index = self.type_combo.findData("cable")
            self.type_combo.setCurrentIndex(index)
            self.name_edit.setText("Lead A")
            return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(module, "AddFileDialog", Choice)
    window.add_project_file()
    assert any(".cbl" in t for t in seen["types"]) and any(".eff" in t for t in seen["types"])
    assert len(seen["types"]) >= 10 and len(window.project_tab.session.module_types()) >= 10
    cable_file = next(f for f in listed(window) if f.endswith(".cbl"))
    assert "test_instruments.inst" in listed(window) and "osc1.was" in listed(window)

    # saving the menu's data keeps the measurements the tab wrote
    window.project_tab.session.project.add_scope_file("osc2.was")  # added next to the first
    window.save_project_json()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "was_files" not in saved
    assert saved["scope_settings"] == [
        {"file": "osc1.was", "enabled": True},
        {"file": "osc2.was", "enabled": True},  # a new one is on: every file is an acquisition
    ]
    # (the example project already lists its efficiency measurement)
    assert [m["file"] for m in saved["measurements"]] == ["eff.eff", cable_file]
    # and the tab saving afterwards keeps the menu's data
    window.project_tab.session.rename("m2", "Lead B")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["scope_settings"]) == 2 and saved["measurements"][1]["name"] == "Lead B"

    # double click on a measurement file: the editor of the Measurements tab, not the old dialog
    opened = []
    monkeypatch.setattr(window.project_tab, "edit_measurement", lambda: opened.append(1))
    item = next(
        window.project_files_list.item(i)
        for i in range(window.project_files_list.count())
        if window.project_files_list.item(i).text() == cable_file
    )
    window.edit_project_file(item)
    assert opened == [1]
    # removing it goes through the tab too

    def remove():  # what the tab does after its question
        window.project_tab.session.remove("m2")
        window.project_tab._refresh()

    monkeypatch.setattr(window.project_tab, "remove_measurement", remove)
    window.delete_file(item)
    assert cable_file not in listed(window)
    remaining = json.loads(path.read_text(encoding="utf-8"))["measurements"]
    assert [m["file"] for m in remaining] == ["eff.eff"]  # the efficiency of the example is left


@pytest.mark.gui
def test_an_existing_measurement_file_can_be_added_from_disk(window, home, monkeypatch, tmp_path):
    project = tmp_path / "p"
    shutil.copytree(EXAMPLE, project)
    window._open_project_path(str(project / "Test DC-DC Converter.json"))
    session = window.project_tab.session
    source = tmp_path / "elsewhere"
    source.mkdir()
    other = ProjectSession(Project.new("Other", source), session.registry)
    ref = other.create("filter", "Band")
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(source / ref.file), "")),
    )
    window.add_existing_file()
    assert os.path.isfile(project / ref.file)
    assert ref.file in listed(window)
    assert [m.file for m in session.project.measurements] == ["eff.eff", ref.file]


def test_the_scope_files_can_be_switched_off_and_moved_from_the_file_list(window, home, tmp_path):
    folder = tmp_path / "p"
    shutil.copytree(EXAMPLE, folder)
    window._open_project_path(str(folder / "Test DC-DC Converter.json"))
    project = window.project_tab.session.project
    project.add_scope_file("rise.was")
    project.add_scope_file("fall.was")
    window.change_scope_file("osc1.was", "toggle")  # the first one off
    assert project.active_scope_files() == ["rise.was", "fall.was"]
    window.change_scope_file("fall.was", "up")
    assert project.scope_file_names() == ["osc1.was", "fall.was", "rise.was"]
    on_disk = json.loads(project.path.read_text(encoding="utf-8"))
    assert [e["file"] for e in on_disk["scope_settings"]] == ["osc1.was", "fall.was", "rise.was"]
    assert on_disk["scope_settings"][0]["enabled"] is False  # saved at once
    names = {window.project_files_list.item(i).text(): window.project_files_list.item(i)
             for i in range(window.project_files_list.count())}  # fmt: skip
    assert names["osc1.was"].font().italic() and not names["fall.was"].font().italic()

    def on(source):
        return [e["file"] for e in source["scope_settings"]]

    assert on(window.open_project_source()) == [
        "fall.was",
        "rise.was",
    ]  # what the remote control sees
    window.change_scope_file("osc1.was", "toggle")
    assert on(window.open_project_source()) == ["osc1.was", "fall.was", "rise.was"]


def test_a_scope_file_can_be_set_for_one_oscilloscope_from_the_file_list(window, home, tmp_path):
    folder = tmp_path / "p"
    shutil.copytree(EXAMPLE, folder)
    window._open_project_path(str(folder / "Test DC-DC Converter.json"))
    project = window.project_tab.session.project
    window.set_scope_target("osc1.was", "OSC2")
    assert project.scope_target("osc1.was") == "OSC2"
    on_disk = json.loads(project.path.read_text(encoding="utf-8"))
    assert on_disk["scope_settings"][0]["scope"] == "OSC2"  # saved at once
    assert window.open_project_source()["scope_settings"] == [{"file": "osc1.was", "scope": "OSC2"}]
    names = {
        window.project_files_list.item(i).text(): window.project_files_list.item(i)
        for i in range(window.project_files_list.count())
    }
    assert "OSC2" in names["osc1.was"].toolTip()
    window.set_scope_target("osc1.was", "")
    assert window.open_project_source()["scope_settings"] == [{"file": "osc1.was", "scope": ""}]
    window.set_scope_target("missing.was", "OSC1")  # not in the project: nothing happens


# ---- the backup copy when an old project is opened (issue #106) ----------------------------
def test_the_backup_is_a_byte_identical_copy_and_never_overwritten(tmp_path):
    path = write(tmp_path / "Old.json", LEGACY)
    original = path.read_bytes()
    assert Project.needs_upgrade(path) is True
    assert Project.upgrade_legacy(path) is True
    backup = tmp_path / "Old.json.bkp"
    assert backup.read_bytes() == original and path.read_bytes() != original
    assert Project.needs_upgrade(path) is False
    # a second old file with the same name: the first backup stays, the new one is numbered
    write(path, LEGACY)
    assert Project.backup_path(path) == tmp_path / "Old.json.bkp.1"
    Project.upgrade_legacy(path)
    assert backup.read_bytes() == original
    assert (tmp_path / "Old.json.bkp.1").read_bytes() == original


def test_no_backup_for_a_current_project_or_when_not_asked(tmp_path):
    path = write(tmp_path / "New.json", {**LEGACY, "format_version": 2, "measurements": []})
    assert Project.upgrade_legacy(path) is False
    assert not list(tmp_path.glob("*.bkp*"))
    old = write(tmp_path / "Old.json", LEGACY)
    assert Project.upgrade_legacy(old, backup=False) is True
    assert not list(tmp_path.glob("*.bkp*"))


@pytest.mark.gui
def test_opening_an_old_project_asks_first(window, monkeypatch, tmp_path):
    from ola.measurement import MeasurementError

    path = write(tmp_path / "Old.json", LEGACY)
    original = path.read_bytes()
    asked = []
    monkeypatch.setattr(window, "confirm_project_upgrade", lambda p: asked.append(p) or False)
    with pytest.raises(MeasurementError):
        window._open_project_path(str(path))
    assert asked and path.read_bytes() == original and not list(tmp_path.glob("*.bkp*"))

    monkeypatch.setattr(window, "confirm_project_upgrade", lambda p: asked.append(p) or True)
    monkeypatch.setattr(window, "show_upgrade_report", lambda report: None)
    window._open_project_path(str(path))
    assert (tmp_path / "Old.json.bkp").read_bytes() == original
    assert json.loads(path.read_text(encoding="utf-8"))["format_version"] == 2

    asked.clear()
    window._open_project_path(str(path))  # opened again: nothing to ask
    assert asked == []


# ------------------------------------------------------- the runs under a measurement file
def write_run(session, ref, stamp, points=3, finish=True):
    """A real run file of the measurement, as the program writes it."""
    from ola.runner import Runner
    from ola.runs import RunWriter
    from tests.measurement_helpers import Scripted, run_to_end

    def measure(ctx):
        for n in range(points):
            ctx.emit_point({"a": n, "b": n * 2.0})

    runner = Runner(Scripted(measure, params={"p": 1}), {}, collect=False, run_id=f"id{stamp[-4:]}")
    path = (
        session.run_dir / f"{__import__('pathlib').Path(ref.file).stem}_{stamp}_aaaaaaaaaaaa.jsonl"
    )
    writer = RunWriter(path, RunWriter.header_for(runner, started_at=1.0))
    runner.add_listener(writer)
    if finish:
        run_to_end(runner)
    else:
        runner.start()
        runner.join(5)
        writer.close()
        lines = path.read_text().splitlines()
        path.write_text("\n".join(lines[:-1]) + "\n")  # no end line: it was interrupted
    return path


def open_example(window, tmp_path):
    project = tmp_path / "p"
    shutil.copytree(EXAMPLE, project)
    window._open_project_path(str(project / "Test DC-DC Converter.json"))
    session = window.project_tab.session
    return session, session.project.measurements[0]


def rows(window):
    from frontend.ui.ProjectFilesList import RUN_ROLE

    return [
        (window.project_files_list.item(i).text(), window.project_files_list.item(i).data(RUN_ROLE))
        for i in range(window.project_files_list.count())
    ]


def click_arrow(window, name):
    from frontend.ui.ProjectFilesList import arrow_rect

    widget = window.project_files_list
    item = next(widget.item(i) for i in range(widget.count()) if widget.item(i).text() == name)
    point = arrow_rect(widget.visualItemRect(item)).center()
    QtTest = pytest.importorskip("PyQt6.QtTest")
    QtTest.QTest.mouseClick(widget.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=point)


@pytest.mark.gui
def test_a_measurement_with_runs_has_an_arrow_that_opens_its_runs(window, home, tmp_path):
    from frontend.ui.ProjectFilesList import RUNS_ROLE

    window.show()
    session, ref = open_example(window, tmp_path)
    item = window.project_files_list.item(1)
    assert item.text() == ref.file and item.data(RUNS_ROLE) is None  # no run: no arrow
    first = write_run(session, ref, "20261125_100000")
    second = write_run(session, ref, "20261125_110000", finish=False)
    window.refresh_project_files()
    item = next(
        window.project_files_list.item(i)
        for i in range(window.project_files_list.count())
        if window.project_files_list.item(i).text() == ref.file
    )
    assert item.data(RUNS_ROLE) is False and "2 run" in item.toolTip()
    assert [r for _n, r in rows(window) if r] == []  # closed: only the files
    click_arrow(window, ref.file)  # open
    runs = [(n.strip(), r) for n, r in rows(window) if r]
    assert [n for n, _r in runs] == [second.name, first.name]  # newest first
    assert [r for _n, r in runs] == [str(second), str(first)]
    names = [n for n, _r in rows(window)]
    assert names.index(ref.file) + 1 == names.index("      " + second.name)  # right under it
    from frontend.ui.ProjectFilesList import RUN_ROLE

    by_path = {
        window.project_files_list.item(i).data(RUN_ROLE): window.project_files_list.item(i)
        for i in range(window.project_files_list.count())
    }
    assert by_path[str(second)].font().italic()  # it did not finish: in italics
    assert not by_path[str(first)].font().italic()
    assert "double click" in by_path[str(first)].toolTip()
    click_arrow(window, ref.file)  # close
    assert [r for _n, r in rows(window) if r] == []


@pytest.mark.gui
def test_double_click_on_a_run_opens_it_in_the_run_window(window, home, tmp_path):
    session, ref = open_example(window, tmp_path)
    path = write_run(session, ref, "20261125_100000", points=4)
    window.refresh_project_files()
    window.toggle_runs(window.project_files_list.item(1))
    run_item = next(
        window.project_files_list.item(i)
        for i in range(window.project_files_list.count())
        if window.project_files_list.item(i).text().strip() == path.name
    )
    before = len(window.project_tab.run_windows)
    window.edit_project_file(run_item)  # what a double click does
    assert len(window.project_tab.run_windows) == before + 1
    shown = window.project_tab.run_windows[-1]
    assert shown.model.state == "finished" and len(shown.model.points) == 4
    assert shown.table.rowCount() == 4 and not shown.start_btn.isEnabled()
    shown._timer.stop()
    shown.close()


@pytest.mark.gui
def test_a_run_is_deleted_from_the_disk_after_asking(window, home, monkeypatch, tmp_path):
    from ola.wavefiles import wave_folder

    session, ref = open_example(window, tmp_path)
    path = write_run(session, ref, "20261125_100000")
    folder = wave_folder(path)
    folder.mkdir()
    (folder / "x.npz").write_bytes(b"x")
    window.refresh_project_files()
    window.toggle_runs(window.project_files_list.item(1))
    item = next(
        window.project_files_list.item(i)
        for i in range(window.project_files_list.count())
        if window.project_files_list.item(i).text().strip() == path.name
    )
    box = QtWidgets.QMessageBox
    asked = []

    def answer(yes):
        def question(parent, title, text, *a, **k):
            asked.append(text)
            return box.StandardButton.Yes if yes else box.StandardButton.No

        monkeypatch.setattr(box, "question", staticmethod(question))

    answer(False)
    window.delete_file(item)  # declined
    assert path.is_file() and folder.is_dir() and path.name in asked[0]
    assert "deleted for good" in asked[0]
    answer(True)
    window.delete_file(item)
    assert not path.exists() and not folder.exists()  # the file and its waveforms are gone
    assert [r for _n, r in rows(window) if r] == []
    # no run left: the arrow is gone as well
    from frontend.ui.ProjectFilesList import RUNS_ROLE

    assert window.project_files_list.item(1).data(RUNS_ROLE) is None


@pytest.mark.gui
def test_the_runs_follow_new_and_deleted_files(window, home, tmp_path):
    session, ref = open_example(window, tmp_path)
    window.refresh_project_files()
    window.toggle_runs(window.project_files_list.item(1))  # nothing to show yet: stays closed
    window._expanded_runs.add(ref.file)
    path = write_run(session, ref, "20261125_100000")
    window._check_runs()  # (the timer does it every two seconds)
    assert [n.strip() for n, r in rows(window) if r] == [path.name]
    window._check_runs()  # nothing changed: nothing redrawn
    other = write_run(session, ref, "20261125_120000")
    path.unlink()
    window._check_runs()
    assert [n.strip() for n, r in rows(window) if r] == [other.name]


@pytest.mark.gui
def test_a_file_that_is_not_a_run_cannot_be_opened(window, home, monkeypatch, tmp_path):
    session, ref = open_example(window, tmp_path)
    junk = tmp_path / "junk.jsonl"
    junk.write_text("not json\n")
    shown = []
    from frontend.ui import ProjectWindow as module

    monkeypatch.setattr(
        module, "show_problem", lambda *a, **k: shown.append(k.get("code")), raising=True
    )
    assert window.project_tab.open_run(junk) is False and shown == ["MEAS-007"]


@pytest.mark.gui
def test_the_context_menu_of_a_run_and_of_a_measurement(window, home, monkeypatch, tmp_path):
    session, ref = open_example(window, tmp_path)
    path = write_run(session, ref, "20261125_100000")
    window.refresh_project_files()
    labels = []

    def fake_exec(self, *a, **k):
        labels.append([x.text() for x in self.actions()])
        return None

    monkeypatch.setattr(QtWidgets.QMenu, "exec", fake_exec)
    widget = window.project_files_list
    item = widget.item(1)
    window.show_file_context_menu(widget.visualItemRect(item).center())
    assert "Show the runs" in labels[-1]
    window.toggle_runs(item)
    window.show_file_context_menu(widget.visualItemRect(widget.item(1)).center())
    assert "Hide the runs" in labels[-1]
    run_item = widget.item(2)
    assert run_item.text().strip() == path.name
    window.show_file_context_menu(widget.visualItemRect(run_item).center())
    assert (
        labels[-1][0] == "Open this run" and "Delete this run... (also from the disk)" in labels[-1]
    )
