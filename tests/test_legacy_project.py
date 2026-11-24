# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Old projects: the efficiency files listed in ``eff_files`` become measurements."""

import json

from ola.efficiency_spec import validate_params
from ola.legacy_project import convert_params, is_old_efficiency
from ola.project import MeasurementFile, Project

OLD_EFF = {
    "type": "efficiency",
    "sweeps": [
        {"variable": "Vin", "config": {"mode": "list", "values": [9, 12]}},
        {"variable": "Iout", "config": {"mode": "range", "start": 0.1, "stop": 1, "points": 5}},
    ],
    "measured_variables": ["Iout", "Vin", "Vout"],
    "timing": {"delay_between_points": 0.5, "delay_between_loops": 2.0},
}


def project(tmp_path, eff=OLD_EFF, listed=("a.eff",)):
    (tmp_path / "t.inst").write_text(json.dumps({"instruments": [{"name": "PSU"}]}))
    if eff is not None:
        (tmp_path / "a.eff").write_text(json.dumps(eff))
    path = tmp_path / "Old.json"
    path.write_text(
        json.dumps({"project_name": "Old", "eff_files": list(listed), "inst_file": "t.inst"})
    )
    return path


def test_the_sweeps_are_reversed_and_the_timing_is_kept():
    params, notes = convert_params(OLD_EFF)
    assert [v["name"] for v in params["variables"]] == ["Iout", "Vin"]  # the outer one is last
    assert params["variables"][0]["sweep"] == {"start": 0.1, "stop": 1.0, "points": 5}
    assert params["variables"][1]["sweep"] == {"values": [9.0, 12.0]}
    assert params["timing"] == {"settle_s": 0.5, "cooldown_s": 2.0}
    assert any("Vout" in n for n in notes) and sum("instrument call" in n for n in notes) == 2
    # it says what is still missing instead of pretending to be a valid measurement
    assert validate_params(params, [], None)


def test_an_unreadable_sweep_is_dropped_with_a_note():
    params, notes = convert_params({"sweeps": [{"variable": "x", "config": {"mode": "list"}}]})
    assert params["variables"] == [] and any("dropped" in n for n in notes)


def test_the_files_of_an_old_project_become_measurements(tmp_path):
    path = project(tmp_path)
    original = (tmp_path / "a.eff").read_bytes()
    report = []
    assert Project.upgrade_legacy(path, report=report) is True
    assert [(r.file, r.converted) for r in report] == [("a.eff", True)]
    assert (tmp_path / "a.eff.bkp").read_bytes() == original  # the old file is kept
    content = MeasurementFile.load(tmp_path / "a.eff")
    assert content.type == "efficiency" and not is_old_efficiency(
        json.loads((tmp_path / "a.eff").read_text())
    )
    assert content.role_bindings == {"instruments": ["PSU"]}
    project_ = Project.load(path)
    assert [(m.id, m.type, m.name, m.file) for m in project_.measurements] == [
        ("m1", "efficiency", "a", "a.eff")
    ]
    assert project_.extra["eff_files"] == ["a.eff"]  # no key is lost


def test_a_missing_or_foreign_file_is_reported_and_left_alone(tmp_path):
    path = project(tmp_path, eff=None, listed=("gone.eff", "../x.eff"))
    report = []
    Project.upgrade_legacy(path, report=report)
    assert [r.converted for r in report] == [False, False] and all(r.notes for r in report)
    assert Project.load(path).measurements == []
    other = project(tmp_path, eff={"hello": 1})
    report = []
    Project.upgrade_legacy(other, report=report)
    assert not report[0].converted and json.loads((tmp_path / "a.eff").read_text()) == {"hello": 1}


def test_a_file_already_in_the_new_format_is_only_adopted(tmp_path):
    new = {"type": "efficiency", "params": {"variables": []}}
    path = project(tmp_path, eff=new)
    report = []
    Project.upgrade_legacy(path, report=report)
    assert report[0].converted and not (tmp_path / "a.eff.bkp").exists()
    assert json.loads((tmp_path / "a.eff").read_text()) == new
    assert [m.file for m in Project.load(path).measurements] == ["a.eff"]
