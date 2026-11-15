# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Renaming an instrument updates the measurements that name it (and only those)."""

import json

import pytest

from ola import project_rename as pr
from ola.project import Project


def make_project(tmp_path, name="P", inst="lab.inst", bindings=None):
    (tmp_path / inst).write_text(json.dumps({"instruments": []}), encoding="utf-8")
    project = Project.new(name, tmp_path, inst_file=inst)
    for i, binding in enumerate(bindings or []):
        file = f"m{i}.meas"
        raw = {
            "type": "x",
            "role_bindings": binding,
            "params": {"keep": i},
            "note": "unknown key",
        }
        (tmp_path / file).write_text(json.dumps(raw), encoding="utf-8")
        from ola.project import MeasurementRef

        project.measurements.append(MeasurementRef(f"m{i}", "x", f"meas {i}", file))
    project.save()
    return project


def test_every_role_that_names_the_instrument_is_found(tmp_path):
    make_project(
        tmp_path,
        bindings=[{"dmm": ["DMM1", "DMM2"], "psu": "PSU"}, {"dmm": "DMM2"}, {"psu": ["PSU"]}],
    )
    found = pr.find_references(tmp_path / "lab.inst", "DMM2")
    assert [(r.measurement_id, r.role) for r in found] == [("m0", "dmm"), ("m1", "dmm")]
    assert pr.find_references(tmp_path / "lab.inst", "nobody") == []


def test_rename_changes_only_the_bindings_and_keeps_everything_else(tmp_path):
    make_project(tmp_path, bindings=[{"dmm": ["DMM1", "DMM2"], "psu": "PSU"}, {"dmm": "DMM2"}])
    changed = pr.rename_references(tmp_path / "lab.inst", "DMM2", "METER")
    assert len(changed) == 2
    first = json.loads((tmp_path / "m0.meas").read_text(encoding="utf-8"))
    assert first["role_bindings"] == {"dmm": ["DMM1", "METER"], "psu": "PSU"}
    assert first["params"] == {"keep": 0} and first["note"] == "unknown key"
    second = json.loads((tmp_path / "m1.meas").read_text(encoding="utf-8"))
    assert second["role_bindings"] == {"dmm": "METER"}
    assert pr.find_references(tmp_path / "lab.inst", "DMM2") == []


def test_projects_that_use_another_instrument_file_are_left_alone(tmp_path):
    make_project(tmp_path, name="A", inst="lab.inst", bindings=[{"dmm": "DMM"}])
    other = tmp_path / "other"
    other.mkdir()
    make_project(other, name="B", inst="other.inst", bindings=[{"dmm": "DMM"}])
    assert [r.project for r in pr.find_references(tmp_path / "lab.inst", "DMM")] == ["A"]


def test_two_projects_sharing_one_instrument_file_are_both_updated(tmp_path):
    make_project(tmp_path, name="A", bindings=[{"dmm": "DMM"}])
    second = make_project(tmp_path, name="B", bindings=[])
    second.measurements.clear()
    (tmp_path / "b.meas").write_text(
        json.dumps({"type": "x", "role_bindings": {"dmm": "DMM"}}), encoding="utf-8"
    )
    from ola.project import MeasurementRef

    second.measurements.append(MeasurementRef("m1", "x", "b", "b.meas"))
    second.save()
    found = pr.find_references(tmp_path / "lab.inst", "DMM")
    assert sorted(r.project for r in found) == ["A", "B"]
    pr.rename_references(tmp_path / "lab.inst", "DMM", "NEW")
    assert pr.find_references(tmp_path / "lab.inst", "NEW") != []


def test_a_damaged_or_missing_measurement_file_does_not_stop_the_others(tmp_path):
    make_project(tmp_path, bindings=[{"dmm": "DMM"}, {"dmm": "DMM"}])
    (tmp_path / "m0.meas").write_text("{ broken", encoding="utf-8")
    assert [r.measurement_id for r in pr.find_references(tmp_path / "lab.inst", "DMM")] == ["m1"]
    (tmp_path / "m1.meas").unlink()
    assert pr.find_references(tmp_path / "lab.inst", "DMM") == []


def test_nothing_is_left_half_done_when_a_file_cannot_be_written(tmp_path, monkeypatch):
    make_project(tmp_path, bindings=[{"dmm": "DMM"}, {"dmm": "DMM"}])
    before = {f: (tmp_path / f).read_text(encoding="utf-8") for f in ("m0.meas", "m1.meas")}
    real = pr.atomic_write_json
    calls = []

    def flaky(path, data, *args, **kwargs):
        if str(path).endswith(".meas") and "NEW" in json.dumps(data):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("disk full")
        return real(path, data, *args, **kwargs)

    monkeypatch.setattr(pr, "atomic_write_json", flaky)
    with pytest.raises(pr.RenameError):
        pr.rename_references(tmp_path / "lab.inst", "DMM", "NEW")
    monkeypatch.setattr(pr, "atomic_write_json", real)
    after = {f: (tmp_path / f).read_text(encoding="utf-8") for f in before}
    assert json.loads(after["m0.meas"]) == json.loads(before["m0.meas"])
    assert json.loads(after["m1.meas"]) == json.loads(before["m1.meas"])


def test_an_empty_new_name_is_refused(tmp_path):
    make_project(tmp_path, bindings=[{"dmm": "DMM"}])
    with pytest.raises(pr.RenameError):
        pr.rename_references(tmp_path / "lab.inst", "DMM", "  ")
