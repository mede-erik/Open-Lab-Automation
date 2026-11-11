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
    on_disk["was_files"] = ["o.was", "p.was"]  # written by the main window meanwhile
    path.write_text(json.dumps(on_disk), encoding="utf-8")
    project.save()
    assert json.loads(path.read_text(encoding="utf-8"))["was_files"] == ["o.was", "p.was"]


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
    window.current_project_data["control_variables"] = ["VX"]
    window.save_project_json()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["control_variables"] == ["VX"]
    assert [m["file"] for m in saved["measurements"]] == [cable_file]
    # and the tab saving afterwards keeps the menu's data
    window.project_tab.session.rename("m1", "Lead B")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["control_variables"] == ["VX"] and saved["measurements"][0]["name"] == "Lead B"

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
        window.project_tab.session.remove("m1")
        window.project_tab._refresh()

    monkeypatch.setattr(window.project_tab, "remove_measurement", remove)
    window.delete_file(item)
    assert cable_file not in listed(window)
    assert json.loads(path.read_text(encoding="utf-8"))["measurements"] == []


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
    assert [m.file for m in session.project.measurements] == [ref.file]
