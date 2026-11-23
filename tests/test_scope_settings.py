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
    assert project.scope_settings is None and project.scope_file_names() == []
    assert saved(project)["scope_settings"] is None and "scope_files" not in saved(project)
    assert Project.load(project.path).scope_settings is None
    assert project.scope_path() is None


def test_the_first_file_is_the_active_one_and_the_next_ones_wait_disabled(tmp_path):
    project = Project.new("Lab", tmp_path)
    project.add_scope_file("a.was")
    project.add_scope_file("b.was")
    project.add_scope_file("a.was")  # twice: nothing changes
    assert project.scope_settings == "a.was" and project.scope_path() == tmp_path / "a.was"
    assert project.scope_files == [
        {"file": "a.was", "enabled": True},
        {"file": "b.was", "enabled": False},
    ]
    project.save()
    assert saved(project)["scope_files"] == project.scope_files
    back = Project.load(project.path)
    assert back.scope_settings == "a.was" and back.scope_files == project.scope_files


def test_the_active_file_can_be_changed_and_nothing_is_deleted(tmp_path):
    for name in ("a.was", "b.was"):
        (tmp_path / name).write_text("{}")
    project = Project.new("Lab", tmp_path)
    project.add_scope_file("a.was")
    project.add_scope_file("b.was")
    project.set_active_scope("b.was")
    assert project.scope_settings == "b.was"
    assert [e["enabled"] for e in project.scope_files] == [False, True]  # exactly one is active
    with pytest.raises(MeasurementError, match="not a scope settings file"):
        project.set_active_scope("c.was")
    project.remove_scope_file("b.was")  # the active one leaves: there is none until one is chosen
    assert project.scope_settings is None and project.scope_file_names() == ["a.was"]
    assert (tmp_path / "a.was").exists() and (tmp_path / "b.was").exists()  # only the list changed


def test_a_file_name_must_be_plain(tmp_path):
    project = Project.new("Lab", tmp_path)
    for bad in ("../x.was", "sub/x.was", ""):
        with pytest.raises(MeasurementError):
            project.add_scope_file(bad)


def test_the_was_files_of_an_early_project_are_read_and_not_written(tmp_path):
    path = write(
        tmp_path / "p.json",
        {"format_version": 2, "project_id": "x", "project_name": "P",
         "was_files": ["a.was", "b.was"], "measurements": [], "calibrations": ["c"]},
    )  # fmt: skip
    before = path.read_bytes()
    project = Project.load(path)
    assert project.scope_settings == "a.was"  # the first one stays the one that is applied
    assert project.scope_files == [
        {"file": "a.was", "enabled": True},
        {"file": "b.was", "enabled": False},  # not lost: kept, disabled
    ]
    assert path.read_bytes() == before  # opening wrote nothing
    project.save()
    data = saved(project)
    assert "was_files" not in data and data["scope_settings"] == "a.was"
    assert data["calibrations"] == ["c"] and len(data["scope_files"]) == 2
    assert Project.load(path).scope_files == project.scope_files  # a second open changes nothing


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
        assert "was_files" not in raw and raw["scope_settings"].endswith(".was")
        project = Project.load(Path(REPO) / example)
        assert project.scope_settings == raw["scope_settings"]
        assert project.scope_path().is_file()


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
