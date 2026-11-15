# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the shared archive (docs/proposals/shared-archive.md, section 6) needs from the files
already: atomic writes, a stable project id, who/where in every run, unique run file names,
a uid for every card of the registry, and no absolute path inside a project."""

import json
import os
from pathlib import Path

import pytest

from ola import vna_calibration_flow as flow
from ola.assets import AssetRegistry, RunRef, history, index_runs, runs_of
from ola.call_errors import InvalidArgumentError
from ola.fileio import atomic_write_json, atomic_write_text
from ola.project import Project
from ola.provenance import ENV_AUTHOR, provenance
from ola.runs import RunWriter
from tests.test_project_session import add_efficiency, make

# ---- atomic writes ----------------------------------------------------------------------------


def test_an_atomic_write_replaces_the_file_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "a.json"
    atomic_write_text(target, "old\n")
    atomic_write_json(target, {"é": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"é": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]


def test_a_failed_atomic_write_keeps_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "a.json"
    target.write_text("old", encoding="utf-8")

    def boom(*_):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["a.json"]  # the temporary file is gone


# ---- project id -------------------------------------------------------------------------------


def test_a_project_keeps_its_id_when_saved_loaded_and_renamed(tmp_path):
    project = Project.new("Pippo", tmp_path)
    project.save()
    again = Project.load(project.path)
    assert again.project_id == project.project_id and len(project.project_id) == 32
    again.name = "Pluto"
    again.save()
    assert Project.load(again.path).project_id == project.project_id


def test_a_project_without_an_id_is_given_one_that_stays(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(
        json.dumps({"format_version": 2, "project_name": "Old", "measurements": []}),
        encoding="utf-8",
    )
    first = Project.load(path)
    assert Project.load(path).project_id == first.project_id  # it was written, not made up again
    assert json.loads(path.read_text(encoding="utf-8"))["project_id"] == first.project_id


# ---- who and where ----------------------------------------------------------------------------


def test_provenance_uses_the_declared_author(monkeypatch):
    monkeypatch.setenv(ENV_AUTHOR, "Erik")
    data = provenance()
    assert data["author"] == "Erik"
    assert data["host"] and data["software_version"]  # never empty: "unknown" at worst


def test_a_run_says_who_made_it_and_its_file_name_has_the_run_id(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_AUTHOR, "Erik")
    session, _ = make(tmp_path)
    ref = add_efficiency(session)
    runner, path = session.build_runner(ref)
    assert path.stem.endswith("_" + runner.run_id)
    header = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert header["author"] == "Erik" and header["host"] and header["software_version"]
    assert header["run_id"] == runner.run_id


def test_two_runs_started_in_the_same_second_have_different_files(tmp_path):
    session, _ = make(tmp_path)
    ref = add_efficiency(session)
    (_, first), (_, second) = session.build_runner(ref), session.build_runner(ref)
    assert first != second
    assert {first, second} <= set(session.runs(ref))


# ---- registry uid -----------------------------------------------------------------------------


def test_every_card_has_a_uid_that_is_saved_and_in_the_snapshot(tmp_path):
    registry = AssetRegistry(tmp_path / "assets.json")
    card = registry.create("cable", "RG316")
    other = registry.create("cable", "RG58")
    assert card.uid and card.uid != other.uid
    assert AssetRegistry(tmp_path / "assets.json").get(card.id).uid == card.uid
    assert card.snapshot()["uid"] == card.uid and card.snapshot()["former_codes"] == []


def test_cards_made_before_the_uid_get_one_that_stays(tmp_path):
    path = tmp_path / "assets.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "counters": {"CBL": 1},
                "assets": [{"id": "CBL-0001", "kind": "cable", "name": "old", "keep": 1}],
            }
        ),
        encoding="utf-8",
    )
    first = AssetRegistry(path).get("CBL-0001").uid
    assert AssetRegistry(path).get("CBL-0001").uid == first
    assert json.loads(path.read_text(encoding="utf-8"))["assets"][0]["keep"] == 1


def _run(folder: Path, name: str, code: str, card: dict | None):
    folder.mkdir(exist_ok=True)
    header = {
        "run_id": name,
        "measurement": "cable",
        "params": {"cable": {"asset_id": code}},
    }
    if card is not None:
        header["assets"] = {code: card}
    path = folder / f"{name}_20261103_100000_{name}.jsonl"
    with RunWriter(path, header):
        pass
    return path


def test_the_history_follows_the_uid_when_the_code_changes(tmp_path):
    registry = AssetRegistry(tmp_path / "assets.json")
    card = registry.create("cable", "RG316")
    runs = tmp_path / "runs"
    before = _run(runs, "a", card.id, card.snapshot())  # made when it was CBL-0001
    old_code = card.id
    card.id, card.former_codes = "CBL-0020", [old_code]  # renumbered when joining an archive
    after = _run(runs, "b", card.id, card.snapshot())
    index = index_runs([runs])
    assert [r.path for r in runs_of(card, index)] == [before, after]
    assert [r.path for r in history("CBL-0020", [runs], registry)] == [before, after]
    assert [r.path for r in history("CBL-0020", [runs])] == [after]  # by the code alone


def test_two_different_objects_with_the_same_code_are_not_mixed(tmp_path):
    mine = AssetRegistry(tmp_path / "mine.json").create("cable", "mine")
    theirs = AssetRegistry(tmp_path / "theirs.json").create("cable", "theirs")
    assert mine.id == theirs.id and mine.uid != theirs.uid
    runs = tmp_path / "runs"
    run_mine = _run(runs, "a", mine.id, mine.snapshot())
    run_theirs = _run(runs, "b", theirs.id, theirs.snapshot())
    index = index_runs([runs])
    assert [r.path for r in runs_of(mine, index)] == [run_mine]
    assert [r.path for r in runs_of(theirs, index)] == [run_theirs]


def test_a_run_made_before_the_uid_is_found_by_the_code_and_former_codes(tmp_path):
    card = AssetRegistry(tmp_path / "assets.json").create("cable", "RG316")
    runs = tmp_path / "runs"
    old = _run(runs, "a", "CBL-0001", {"name": "RG316"})  # a card without uid
    card.id, card.former_codes = "CBL-0020", ["CBL-0001"]
    assert [r.path for r in runs_of(card, index_runs([runs]))] == [old]


def test_runref_keeps_working_without_uids():
    ref = RunRef(Path("x.jsonl"), "2026-11-03 10:00", "cable", "finished")
    assert ref.uids == {}


# ---- nothing absolute inside a project --------------------------------------------------------


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _absolute(text: str) -> bool:
    return text.startswith("/") or (len(text) > 2 and text[1] == ":" and text[2] in "\\/")


def test_a_project_with_measurements_and_a_calibration_names_no_absolute_path(tmp_path):
    session, _ = make(tmp_path)
    add_efficiency(session)
    session.project.save()
    record = flow.CalibrationRecord("v", "m", "ONE_PORT", 1, None, {}, ["OPEN@1"])
    path = flow.save_record(record, tmp_path / "calibrations")
    flow.attach_to_project(session.project.path, path, record)
    for file in [session.project.path, *tmp_path.glob("*.eff"), *tmp_path.glob("*.json")]:
        data = json.loads(file.read_text(encoding="utf-8"))
        # file names of the project and of its measurements, not the values of a measurement
        names = [data["inst_file"]] if data.get("inst_file") else []
        names += [m["file"] for m in data.get("measurements", [])]
        names += [c["file"] for c in data.get("calibrations", [])]
        assert not [n for n in names if _absolute(n) or ".." in Path(n).parts], file


def test_a_calibration_outside_the_project_is_refused(tmp_path):
    project = tmp_path / "p" / "p.json"
    project.parent.mkdir()
    project.write_text(json.dumps({"format_version": 2, "project_name": "p"}))
    record = flow.CalibrationRecord("v", "m", "ONE_PORT", 1, None, {}, ["OPEN@1"])
    elsewhere = flow.save_record(record, tmp_path / "elsewhere")
    with pytest.raises(InvalidArgumentError):
        flow.attach_to_project(project, elsewhere, record)
    assert "calibrations" not in json.loads(project.read_text())
