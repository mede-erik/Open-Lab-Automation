# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The device under test in the measurements: the file, the header of a run, the history."""

import pytest

from ola.assets import AssetRegistry, read_header, runs_of
from ola.compare import load_run
from ola.duts import (
    DutRegistry,
    dut_ids_in,
    dut_snapshots_for,
    index_dut_runs,
    upgrade_params,
)
from ola.project import MeasurementFile, Project
from ola.project_session import ProjectSession
from ola.registry import default_registry
from ola.runs import RunWriter
from ola.sim_vna import SimVna
from tests.legacy_assets import add_legacy


@pytest.fixture
def archive(tmp_path):
    reg = DutRegistry(tmp_path / "duts.json")
    reg.create("antenna", "868 MHz whip", version="rev A")
    return reg


@pytest.fixture
def registry():
    return default_registry(user_dir="/nonexistent")


# ---- the file ----------------------------------------------------------------------------------
def test_a_file_names_its_dut_with_a_code_and_a_version():
    params = {"device": {"label": "x", "dut_id": "dut-1", "version": "rev A"}}
    assert dut_ids_in(params) == ["DUT-0001"]
    assert dut_ids_in({"filter": {"dut_id": "OLA:DUT-0002"}, "device": {}}) == ["DUT-0002"]
    assert dut_ids_in({"cable": {"asset_id": "CBL-0001"}, "device": {"label": "x"}}) == []


def test_a_file_made_before_the_archive_names_it_with_an_asset_id(tmp_path):
    params = {"device": {"asset_id": "ANT-0003"}, "filter": {"dut_id": "DUT-0007"}}
    assert dut_ids_in(params) == ["DUT-0007"]
    assert dut_ids_in(params, legacy=True) == ["ANT-0003", "DUT-0007"]  # the order of the groups


def test_the_file_is_checked_by_the_modules(registry):
    def problems(device):
        params = {"sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 11}, "device": device}
        return {p.path: p.message for p in registry.create("return_loss", params).check()}

    assert problems({"label": "x", "dut_id": "DUT-0001", "version": "rev A"}) == {}
    assert "device.dut_id" in problems({"label": "x", "dut_id": "whip"})
    assert "device.version" in problems({"label": "x", "dut_id": "DUT-0001", "version": 2})
    assert "device.asset_id" in problems({"label": "x", "asset_id": "DUT"})  # as before


def test_upgrading_a_file_gives_it_the_new_code_of_a_card_that_moved(tmp_path):
    components = AssetRegistry(tmp_path / "assets.json")
    add_legacy(components, "antenna", "old whip")  # ANT-0001
    duts = DutRegistry(tmp_path / "duts.json")
    duts.migrate_from(components)  # DUT-0001, with ANT-0001 as its old code
    params = {"device": {"label": "x", "asset_id": "ANT-0001"}, "cable": {"asset_id": "CBL-0001"}}
    assert upgrade_params(params, duts)
    assert params["device"] == {"label": "x", "dut_id": "DUT-0001"}
    assert params["cable"] == {"asset_id": "CBL-0001"}  # a component stays as it is
    assert not upgrade_params(params, duts)  # nothing more to do
    other = {"device": {"asset_id": "AMP-0001"}}  # an amplifier is not in the archive
    assert not upgrade_params(other, duts) and other == {"device": {"asset_id": "AMP-0001"}}
    assert not upgrade_params(params, None)


# ---- the card in the header of a run -----------------------------------------------------------
def test_the_snapshot_has_the_card_and_its_versions_and_finds_an_old_code(tmp_path, archive):
    components = AssetRegistry(tmp_path / "assets.json")
    add_legacy(components, "filter", "SAW")
    archive.migrate_from(components)  # FLT-0001 -> DUT-0002
    snap = dut_snapshots_for({"device": {"dut_id": "DUT-0001"}, "filter": {"asset_id": "FLT-0001"}},
                             archive)  # fmt: skip
    assert sorted(snap) == ["DUT-0001", "DUT-0002"]
    assert [v["label"] for v in snap["DUT-0001"]["versions"]] == ["rev A"]
    assert snap["DUT-0002"]["name"] == "SAW"
    assert dut_snapshots_for({"device": {"dut_id": "DUT-0099"}}, archive) == {}
    assert dut_snapshots_for({"device": {"dut_id": "DUT-0001"}}, None) == {}


def test_a_run_from_a_project_keeps_the_card_and_the_version_of_that_day(
    tmp_path, registry, archive
):
    project = Project.new("P", tmp_path / "proj")
    session = ProjectSession(
        project, registry, connect=lambda n, c=None: SimVna(termination="antenna"),
        instruments=["vna1"], duts=archive,
    )  # fmt: skip
    ref = session.create("return_loss", "RL")
    params = {
        "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 21},
        "device": {"label": "", "dut_id": "DUT-0001", "version": "rev A"},
        "confirm_setup": False,
    }
    MeasurementFile(type="return_loss", role_bindings={"vna": ["vna1"]}, params=params).save(
        session.path(ref)
    )
    runner, path = session.build_runner(ref)
    runner.start()
    assert runner.join(20)
    archive.update("DUT-0001", name="renamed later")  # the card changes after the run
    archive.add_version("DUT-0001", "rev B")
    header = read_header(path)
    assert header["duts"]["DUT-0001"]["name"] == "868 MHz whip"  # what it was that day
    assert [v["label"] for v in header["duts"]["DUT-0001"]["versions"]] == ["rev A"]
    assert header["params"]["device"]["version"] == "rev A"
    assert "assets" not in header  # nothing from the registry of components
    run = load_run(path)
    assert run.asset_id == "DUT-0001" and run.name == "868 MHz whip"  # the comparison names it


# ---- the history of a DUT ----------------------------------------------------------------------
def make_run(folder, name, params, cards=None, stamp="20261103_100000"):
    folder.mkdir(exist_ok=True)
    header = {"run_id": name, "measurement": "return_loss", "params": params}
    if cards:
        header["duts"] = cards
    path = folder / f"{name}_{stamp}.jsonl"
    writer = RunWriter(path, header)
    writer._write({"kind": "end", "state": "finished", "error": None})
    writer.close()
    return path


def test_the_runs_of_a_dut_are_found_by_its_code_its_uid_and_its_old_codes(tmp_path):
    components = AssetRegistry(tmp_path / "assets.json")
    antenna = add_legacy(components, "antenna", "whip")  # ANT-0001
    duts = DutRegistry(tmp_path / "duts.json")
    duts.migrate_from(components)
    dut = duts.get("DUT-0001")
    runs = tmp_path / "runs"
    old = make_run(runs, "old", {"device": {"asset_id": "ANT-0001"}}, stamp="20261101_100000")
    new = make_run(
        runs, "new", {"device": {"dut_id": "DUT-0001", "version": "rev A"}},
        cards={"DUT-0001": dut.snapshot()}, stamp="20261105_100000",
    )  # fmt: skip
    foreign = {"DUT-0002": {"uid": "someone else"}}
    other = make_run(runs, "other", {"device": {"dut_id": "DUT-0002"}}, foreign, "20261106_100000")
    make_run(runs, "nothing", {"device": {"label": "no code"}}, stamp="20261107_100000")
    index = index_dut_runs([runs, tmp_path / "missing"])
    assert [r.path for r in runs_of(dut, index)] == [old, new]  # the old code finds the old run
    assert [r.path for r in index["DUT-0002"]] == [other]
    assert antenna.uid == dut.uid
