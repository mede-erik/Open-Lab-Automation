# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The settings of the oscilloscopes of a project (``Project.scope_settings``, the ``.was`` file):
the project object, the check of a file, the ``reset`` key, and the old ``was_files`` key."""

import json
import re
from pathlib import Path

import pytest

from ola.measurement import MeasurementError
from ola.project import Project
from ola.was_calls import check_was, oscilloscope_calls_from_was, reset_wanted
from tests.conftest import REPO


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def saved(project):
    return json.loads(project.path.read_text(encoding="utf-8"))


# ---- the project object ------------------------------------------------------------------------
def test_a_new_project_has_no_scope_settings_and_is_valid(tmp_path):
    project = Project.new("Lab", tmp_path)
    project.save()
    assert project.scope_settings == [] and project.active_scope_files() == []
    assert saved(project)["scope_settings"] == []
    assert Project.load(project.path).scope_settings == []


def test_every_file_is_an_acquisition_and_starts_on(tmp_path):
    project = Project.new("Lab", tmp_path)
    for name in ("long.was", "rise.was", "fall.was"):
        project.add_scope_file(name)
    project.add_scope_file("rise.was")  # twice: nothing changes
    assert project.scope_file_names() == ["long.was", "rise.was", "fall.was"]
    assert project.active_scope_files() == ["long.was", "rise.was", "fall.was"]  # all on
    project.save()
    assert saved(project)["scope_settings"] == [
        {"file": "long.was", "enabled": True},
        {"file": "rise.was", "enabled": True},
        {"file": "fall.was", "enabled": True},
    ]
    back = Project.load(project.path)
    assert back.scope_settings == project.scope_settings


def test_any_file_can_be_switched_off_not_only_the_last_ones(tmp_path):
    for name in ("long.was", "rise.was", "fall.was"):
        (tmp_path / name).write_text("{}")
    project = Project.new("Lab", tmp_path)
    for name in ("long.was", "rise.was", "fall.was"):
        project.add_scope_file(name)
    project.set_scope_enabled("long.was", False)  # the first one
    assert project.active_scope_files() == ["rise.was", "fall.was"]
    assert project.scope_file_names() == [
        "long.was",
        "rise.was",
        "fall.was",
    ]  # still in the project
    project.set_scope_enabled("rise.was", False)
    project.set_scope_enabled("fall.was", False)
    assert project.active_scope_files() == []  # none on: valid
    project.set_scope_enabled("long.was", True)
    assert project.active_scope_files() == ["long.was"]
    with pytest.raises(MeasurementError, match="not a scope settings file"):
        project.set_scope_enabled("other.was", True)
    project.remove_scope_file("rise.was")  # only the list changes
    assert project.scope_file_names() == ["long.was", "fall.was"]
    assert all((tmp_path / n).exists() for n in ("long.was", "rise.was", "fall.was"))


def test_the_order_is_the_order_of_the_acquisitions_and_can_be_changed(tmp_path):
    project = Project.new("Lab", tmp_path)
    for name in ("a.was", "b.was", "c.was"):
        project.add_scope_file(name)
    project.move_scope_file("c.was", -1)
    assert project.scope_file_names() == ["a.was", "c.was", "b.was"]
    project.move_scope_file("a.was", -1)  # already first: nothing
    project.move_scope_file("b.was", +1)  # already last: nothing
    assert project.scope_file_names() == ["a.was", "c.was", "b.was"]
    project.move_scope_file("b.was", -2)
    assert project.scope_file_names() == ["b.was", "a.was", "c.was"]
    project.set_scope_enabled("a.was", False)
    assert project.active_scope_files() == ["b.was", "c.was"]  # the order of the ones that are on
    project.save()
    assert Project.load(project.path).scope_settings == project.scope_settings
    with pytest.raises(MeasurementError):
        project.move_scope_file("x.was", 1)


def test_a_file_name_must_be_plain(tmp_path):
    project = Project.new("Lab", tmp_path)
    for bad in ("../x.was", "sub/x.was", ""):
        with pytest.raises(MeasurementError):
            project.add_scope_file(bad)


def test_a_single_name_and_a_list_of_names_are_read(tmp_path):
    base = {"format_version": 2, "project_id": "x", "project_name": "P", "measurements": []}
    one = Project.load(write(tmp_path / "one.json", {**base, "scope_settings": "a.was"}))
    assert one.scope_settings == [{"file": "a.was", "enabled": True}]
    names = Project.load(write(tmp_path / "n.json", {**base, "scope_settings": ["a.was", "b.was"]}))
    assert names.active_scope_files() == ["a.was", "b.was"]
    off = {"scope_settings": [{"file": "a.was", "enabled": False}, {"file": "b.was"}]}
    flags = Project.load(write(tmp_path / "f.json", {**base, **off}))
    assert flags.active_scope_files() == ["b.was"]  # a missing flag means on
    junk = Project.load(
        write(tmp_path / "j.json", {**base, "scope_settings": [3, "", "a.was", "a.was"]})
    )
    assert junk.scope_file_names() == ["a.was"]


def test_the_was_files_of_an_early_project_are_read_all_on_and_not_written(tmp_path):
    path = write(
        tmp_path / "p.json",
        {"format_version": 2, "project_id": "x", "project_name": "P",
         "was_files": ["a.was", "b.was"], "measurements": [], "calibrations": ["c"]},
    )  # fmt: skip
    before = path.read_bytes()
    project = Project.load(path)
    assert project.scope_settings == [
        {"file": "a.was", "enabled": True},
        {"file": "b.was", "enabled": True},  # nothing is lost, nothing is switched off
    ]
    assert path.read_bytes() == before  # opening wrote nothing
    project.save()
    data = saved(project)
    assert "was_files" not in data and data["calibrations"] == ["c"]
    assert data["scope_settings"] == project.scope_settings
    assert Project.load(path).scope_settings == project.scope_settings  # a second open: the same


def test_only_the_project_module_knows_the_old_key():
    """Issue #95: ``was_files`` is only in the code that reads the early projects."""
    found = []
    for folder in ("ola", "frontend"):
        for path in (Path(REPO) / folder).rglob("*.py"):
            if re.search(r"\bwas_files\b", path.read_text(encoding="utf-8", errors="ignore")):
                found.append(path.relative_to(REPO).as_posix())
    assert found == ["ola/project.py"]


def test_the_examples_name_their_scope_settings():
    for example in (
        "examples/Test_scpi/Test_Scpi.json",
        "examples/test-dcdc-project/Test DC-DC Converter.json",
    ):
        raw = json.loads((Path(REPO) / example).read_text(encoding="utf-8"))
        assert "was_files" not in raw and raw["scope_settings"]
        project = Project.load(Path(REPO) / example)
        assert project.scope_settings == raw["scope_settings"]
        assert all(project.scope_path(name).is_file() for name in project.scope_file_names())


# ---- the file ----------------------------------------------------------------------------------
def test_reset_is_the_default_and_can_be_left_out():
    base = {"settings": {"time_per_div": 1e-3}}
    assert reset_wanted(base) and reset_wanted({**base, "reset": True})
    assert not reset_wanted({**base, "reset": False})
    assert oscilloscope_calls_from_was(base)[0] == ("reset", {})  # as it always was
    off = oscilloscope_calls_from_was({**base, "reset": False})
    assert off == [("set_timebase_scale", {"value": 1e-3})]  # no reset call, the rest the same
    assert (
        oscilloscope_calls_from_was({**base, "reset": False})
        == oscilloscope_calls_from_was(base)[1:]
    )


def test_a_good_file_has_no_problem_and_a_bad_one_says_what():
    good = {
        "settings": {"time_per_div": 1e-3},
        "channels": [{"channel_id": "CH1", "enabled": True, "volt_per_div": "1V",
                      "probe_attenuation": 10.0}],
        "trigger": {"source": "CH1", "slope": "RISE", "level": 1.5, "mode": "AUTO"},
    }  # fmt: skip
    assert check_was(good) == [] and check_was({}) == []
    bad = {
        "reset": "no", "settings": {"time_per_div": 0},
        "channels": [{"channel_id": "CH1"}, {"channel_id": "CH1"}, {"channel_id": "x"}],
        "trigger": {"source": "foo", "slope": "UP", "level": "high", "mode": "weird"},
    }  # fmt: skip
    problems = " | ".join(check_was(bad))
    for word in ("reset", "time base", "set twice", "no channel number", "source", "slope",
                 "level", "mode"):  # fmt: skip
        assert word in problems, word
    assert check_was([1]) == ["the settings must be an object"]


# ---- the windows -------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.gui
def test_the_was_editor_has_a_reset_box_that_writes_only_what_is_not_the_default(app, tmp_path):
    from frontend.core.Translator import Translator
    from frontend.ui.WasFileDialog import WasFileDialog

    path = tmp_path / "o.was"
    path.write_text(json.dumps({"settings": {"time_per_div": 1e-3}}), encoding="utf-8")
    dialog = WasFileDialog(str(path), Translator("en"), None)
    assert dialog.reset_check.isChecked() and "reset" not in dialog.data  # an old file: reset
    dialog.reset_check.setChecked(False)
    assert dialog.data["reset"] is False
    dialog.save_changes()
    assert json.loads(path.read_text(encoding="utf-8"))["reset"] is False
    again = WasFileDialog(str(path), Translator("en"), None)
    assert not again.reset_check.isChecked()  # read back
    again.reset_check.setChecked(True)
    assert "reset" not in again.data  # the default is not written: the file is as an old one
    again.close()
    dialog.close()
