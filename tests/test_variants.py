# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The variants of a run: the helpers, the check, the header, the comparison and the history."""

import pytest

from ola.assets import index_runs, read_header, runs_of
from ola.compare import load_run
from ola.duts import DutRegistry, dut_snapshots_for, index_dut_runs
from ola.efficiency_spec import validate_params
from ola.project import MeasurementFile, Project
from ola.project_session import ProjectSession
from ola.registry import default_registry
from ola.runs import RunWriter
from ola.sim_vna import SimVna
from ola.variants import format_lines, parse_lines, problem, variant_of, variant_text
from tests.efficiency_params import good

VARIANT = {"R100": "100 ohm", "fan": "on"}


# ---- the helpers -------------------------------------------------------------------------------
def test_a_variant_is_read_from_the_device_or_the_filter_of_a_file():
    assert variant_of({"device": {"variant": VARIANT}}) == VARIANT
    assert variant_of({"filter": {"type": "lowpass", "variant": {"C3": 10}}}) == {"C3": "10"}
    assert variant_of({"device": {"label": "x"}}) == {} and variant_of({}) == {}
    assert variant_of({"device": {"variant": {"": "x"}}}) == {}  # one that is not valid is ignored


def test_a_variant_is_shown_on_one_line_and_in_lines():
    assert variant_text(VARIANT) == "R100=100 ohm, fan=on" and variant_text({}) == ""
    assert format_lines(VARIANT) == "R100 = 100 ohm\nfan = on"
    assert parse_lines(format_lines(VARIANT)) == VARIANT
    assert parse_lines("  R100=100 ohm \n\n fan = on  ") == VARIANT


@pytest.mark.parametrize("text,line", [("R100", 1), ("= 5", 1), ("fan =", 1), ("a = 1\na = 2", 2)])
def test_a_bad_line_is_named_by_its_number(text, line):
    with pytest.raises(ValueError) as caught:
        parse_lines(text)
    assert str(caught.value) == str(line)


def test_what_is_a_valid_variant():
    assert problem(None) is None and problem({}) is None and problem(VARIANT) is None
    assert problem({"C3": 10, "gain": 2.5}) is None
    assert "list of name = value" in problem(["R100"])
    assert "name" in problem({" ": "x"})
    assert "must be text or a number" in problem({"fan": True})
    assert "must be text or a number" in problem({"fan": ["on"]})


# ---- the file ----------------------------------------------------------------------------------
def test_the_modules_check_the_variant():
    registry = default_registry(user_dir="/nonexistent")

    def problems(device):
        params = {"sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 11}, "device": device}
        return {p.path: p.message for p in registry.create("return_loss", params).check()}

    assert problems({"label": "x", "variant": VARIANT}) == {}
    assert "device.variant" in problems({"label": "x", "variant": "fan on"})
    assert "device.variant" in problems({"label": "x", "variant": {"fan": True}})


def test_the_efficiency_file_takes_a_dut_a_version_and_a_variant():
    params = good()
    params["device"] = {"name": "Pippo", "dut_id": "dut-1", "version": "rev A", "variant": VARIANT}
    assert validate_params(params) == []
    params["device"] = {"dut_id": "buck"}
    assert [p.path for p in validate_params(params)] == ["device.dut_id"]
    params["device"] = {"version": 3, "variant": {"": "x"}}
    assert [p.path for p in validate_params(params)] == ["device.version", "device.variant"]
    params["device"] = {"asset_id": "CBL-0001"}  # a component is not a device under test
    assert [p.path for p in validate_params(params)] == ["device"]


def test_the_card_of_an_efficiency_dut_is_saved_like_the_others(tmp_path):
    duts = DutRegistry(tmp_path / "duts.json")
    duts.create("converter", "Pippo", version="rev A")
    params = good()
    params["device"] = {"name": "Pippo", "dut_id": "DUT-0001", "version": "rev A"}
    assert list(dut_snapshots_for(params, duts)) == ["DUT-0001"]  # in the header of its runs


# ---- the header, the comparison, the history ---------------------------------------------------
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


def test_a_run_keeps_its_variant_and_the_comparison_shows_it(tmp_path):
    registry = default_registry(user_dir="/nonexistent")
    duts = DutRegistry(tmp_path / "duts.json")
    duts.create("antenna", "868 MHz whip", version="rev A")
    session = ProjectSession(
        Project.new("P", tmp_path / "proj"), registry,
        connect=lambda n, c=None: SimVna(termination="antenna"), instruments=["vna1"], duts=duts,
    )  # fmt: skip
    ref = session.create("return_loss", "RL")
    params = {
        "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 21},
        "device": {"label": "", "dut_id": "DUT-0001", "version": "rev A", "variant": VARIANT},
        "confirm_setup": False,
    }
    MeasurementFile(type="return_loss", role_bindings={"vna": ["vna1"]}, params=params).save(
        session.path(ref)
    )
    runner, path = session.build_runner(ref)
    runner.start()
    assert runner.join(20)
    assert read_header(path)["params"]["device"]["variant"] == VARIANT  # with its results
    run = load_run(path)
    assert run.variant == "R100=100 ohm, fan=on"
    assert "[R100=100 ohm, fan=on]" in run.label and run.label.startswith("DUT-0001 868 MHz whip")


def test_two_runs_of_a_dut_are_told_apart_in_its_history(tmp_path):
    runs = tmp_path / "runs"
    on = make_run(runs, "on", {"device": {"dut_id": "DUT-0001", "variant": {"fan": "on"}}},
                  stamp="20261103_100000")  # fmt: skip
    off = make_run(runs, "off", {"device": {"dut_id": "DUT-0001", "variant": {"fan": "off"}}},
                   stamp="20261104_100000")  # fmt: skip
    plain = make_run(runs, "plain", {"device": {"dut_id": "DUT-0001"}}, stamp="20261105_100000")
    duts = DutRegistry(tmp_path / "duts.json")
    dut = duts.create("antenna", "whip")
    found = runs_of(dut, index_dut_runs([runs]))
    assert [(r.path, r.variant) for r in found] == [(on, "fan=on"), (off, "fan=off"), (plain, "")]
    assert [r.variant for r in index_runs([runs]).get("DUT-0001", [])] == []  # not a component
