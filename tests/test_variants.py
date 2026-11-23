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


# ---- the question asked when a run starts ------------------------------------------------------
def write_run(folder, name, dut_id, variant, mtime):
    """A run file with only its header, as far as the question of a variant reads it."""
    import json
    import os

    folder.mkdir(exist_ok=True)
    path = folder / name
    group = {"dut_id": dut_id, **({"variant": variant} if variant else {})}
    path.write_text(json.dumps({"kind": "run", "params": {"device": group}}) + "\n")
    os.utime(path, (mtime, mtime))


def test_the_earlier_variants_of_a_dut_come_newest_first(tmp_path):
    from ola.variants import previous_variants, variant_names

    runs = tmp_path / "runs"
    write_run(runs, "a.jsonl", "DUT-0001", {"R100": "100 ohm", "fan": "on"}, 1000)
    write_run(runs, "b.jsonl", "DUT-0001", {"R100": "47 ohm"}, 2000)
    write_run(runs, "c.jsonl", "DUT-0001", None, 3000)  # a run without a variant counts too
    write_run(runs, "d.jsonl", "DUT-0002", {"other": "x"}, 4000)  # another DUT
    (runs / "e.jsonl").write_text("not a run\n")
    (runs / "f.jsonl").write_text("")
    found = previous_variants(runs, "DUT-0001")
    assert found == [{}, {"R100": "47 ohm"}, {"R100": "100 ohm", "fan": "on"}]
    assert variant_names(found) == ["R100", "fan"]  # the most used first
    assert previous_variants(tmp_path / "nothing", "DUT-0001") == []


def test_the_parameters_of_a_run_get_the_variant_and_the_file_does_not(tmp_path):
    from ola.variants import dut_group, with_variant

    params = {"device": {"dut_id": "DUT-0001", "variant": {"old": "1"}}, "timing": {}}
    changed = with_variant(params, {"R100": " 100 ohm ", " ": "x", "fan": "on"})
    assert changed["device"]["variant"] == {"R100": "100 ohm", "fan": "on"}
    assert params["device"]["variant"] == {"old": "1"}  # untouched
    assert "variant" not in with_variant(params, {})["device"]
    flt = {"filter": {"dut_id": "DUT-0003"}}
    assert dut_group(flt) == "filter" and with_variant(flt, {"C3": "10"})["filter"]["variant"]
    with pytest.raises(ValueError, match="DUT"):
        with_variant({"device": {"label": "x"}}, {"a": "b"})


def make_session(tmp_path, dut=True, kind="efficiency"):
    registry = default_registry(user_dir="/nonexistent")
    session = ProjectSession(Project.new("Lab", tmp_path), registry, instruments=["a"])
    ref = session.create(kind, "Eff")
    params = good()
    if dut:
        params["device"] = {"dut_id": "DUT-0001", "version": "rev A", "variant": {"fan": "on"}}
    MeasurementFile(type=kind, role_bindings={"instruments": ["a"]}, params=params).save(
        session.path(ref)
    )
    return session, ref


def test_a_measurement_with_a_dut_asks_for_its_variant(tmp_path):
    session, ref = make_session(tmp_path)
    assert session.variant_question(ref)["last"] == {"fan": "on"}  # no run yet: the file's
    write_run(session.run_dir, "a.jsonl", "DUT-0001", {"R100": "47 ohm"}, 1000)
    question = session.variant_question(ref)
    assert question["dut_id"] == "DUT-0001" and question["version"] == "rev A"
    assert question["last"] == {"R100": "47 ohm"}  # the last run, not the file
    assert question["current"] == {"fan": "on"} and question["names"] == ["R100", "fan"]


def test_no_question_without_a_dut_or_for_a_type_that_does_not_ask(tmp_path):
    session, ref = make_session(tmp_path, dut=False)
    assert session.variant_question(ref) is None
    session, ref = make_session(tmp_path / "x", kind="resistive_efficiency")
    assert session.variant_question(ref) is not None  # the other efficiency asks too
    session.registry.get("efficiency")
    from ola.variants import ASK_FOR_VARIANT

    assert set(ASK_FOR_VARIANT) == {"efficiency", "resistive_efficiency", "regulation", "ripple"}


def test_the_variant_of_a_run_is_in_its_header_and_not_in_the_file(tmp_path):
    from ola.demo_lab import DemoHandle, DemoLab

    lab = DemoLab()
    registry = default_registry(user_dir="/nonexistent")
    session = ProjectSession(
        Project.new("Lab", tmp_path),
        registry,
        connect=lambda name, cancel=None: DemoHandle(name, lab),
        instruments=["a"],
    )
    ref = session.create("efficiency", "Eff")
    params = good()
    params["device"] = {"dut_id": "DUT-0001", "variant": {"fan": "on"}}
    MeasurementFile(type="efficiency", role_bindings={"instruments": ["a"]}, params=params).save(
        session.path(ref)
    )
    runner, path = session.build_runner(ref, variant={"R100": "100 ohm"})
    runner.start()
    runner.join(30)
    header = path.read_text(encoding="utf-8").splitlines()[0]
    import json

    assert json.loads(header)["params"]["device"]["variant"] == {"R100": "100 ohm"}
    assert session.load(ref).params["device"]["variant"] == {"fan": "on"}  # the file is as it was
    assert read_header(path) is not None
