"""Tests of the project logic behind the project window (no screen)."""

import json

import pytest

from ola.demo_lab import INSTRUMENTS, DemoHandle, DemoLab, demo_params
from ola.measurement import MeasurementError
from ola.project import MeasurementFile, Project
from ola.project_session import ProjectSession, instrument_names
from ola.registry import default_registry
from ola.runner import RunState
from ola.runs import read_run


def make(tmp_path, with_connect=True):
    registry = default_registry(user_dir="/nonexistent")
    project = Project.new("Demo", tmp_path)
    lab = DemoLab()
    connect = (lambda name, cancel=None: DemoHandle(name, lab)) if with_connect else None
    session = ProjectSession(project, registry, connect=connect, instruments=INSTRUMENTS)
    return session, lab


def add_efficiency(session, name="Efficiency"):
    ref = session.create("efficiency", name)
    MeasurementFile(
        type="efficiency",
        role_bindings={"instruments": list(INSTRUMENTS)},
        params=demo_params(interval_s=0.01),
    ).save(session.path(ref))
    return ref


def test_instrument_names_from_an_inst_file(tmp_path):
    f = tmp_path / "x.inst"
    f.write_text(
        json.dumps({"instruments": [{"instance_name": "HC"}, {"x": 1}, {"instance_name": "VIN"}]})
    )
    assert instrument_names(f) == ["HC", "VIN"]
    assert instrument_names(tmp_path / "missing.inst") == []
    f.write_text("not json")
    assert instrument_names(f) == []


def test_create_rename_remove_are_saved(tmp_path):
    session, _ = make(tmp_path)
    ref = session.create("efficiency", "Converter A")
    assert ref.file.endswith(".eff") and session.path(ref).is_file()
    again = Project.load(session.project.path)  # saved to disk
    assert [m.name for m in again.measurements] == ["Converter A"]
    session.rename(ref.id, "Converter B")
    assert Project.load(session.project.path).measurements[0].name == "Converter B"
    session.remove(ref.id, delete_file=False)
    assert session.path(ref).is_file() and not Project.load(session.project.path).measurements
    with pytest.raises(MeasurementError):
        session.create("efficiency", "  ")


def test_a_new_efficiency_starts_from_the_template_with_the_instruments(tmp_path):
    session, _ = make(tmp_path)
    ref = session.create("efficiency", "New")
    params = session.load(ref).params
    assert params["variables"]


def test_rows_report_a_missing_file_and_an_unknown_type(tmp_path):
    session, _ = make(tmp_path)
    ref = session.create("efficiency", "A")
    session.path(ref).unlink()
    session.project.measurements.append(type(ref)("m9", "nonexistent", "Ghost", "g.xyz"))
    rows = {r.ref.id: r for r in session.rows()}
    assert "missing" in rows[ref.id].problem
    assert rows["m9"].info is None and "unknown" in rows["m9"].problem


def test_build_runner_runs_and_writes_the_run_file(tmp_path):
    session, _ = make(tmp_path)
    ref = add_efficiency(session)
    runner, path = session.build_runner(ref)
    assert path.parent == tmp_path / "runs"
    runner.start()
    assert runner.join(20) and runner.state is RunState.FINISHED
    run = read_run(path)
    assert len(run["points"]) == 9 and run["end"]["state"] == "finished"
    assert run["header"]["measurement_id"] == ref.id and run["header"]["project"] == "Demo"
    assert session.runs(ref) == [path]
    info = session.describe_run(path)
    assert info["state"] == "finished" and info["points"] == 9


def test_runs_of_a_measurement_with_a_similar_name_are_not_mixed(tmp_path):
    session, _ = make(tmp_path)
    a = add_efficiency(session, "eff")
    b = add_efficiency(session, "eff 2")
    session.run_dir.mkdir()
    (session.run_dir / "eff_20260101_101010.jsonl").write_text("")
    (session.run_dir / "eff_2_20260101_101010.jsonl").write_text("")
    assert [p.name for p in session.runs(a)] == ["eff_20260101_101010.jsonl"]
    assert [p.name for p in session.runs(b)] == ["eff_2_20260101_101010.jsonl"]


def test_without_a_way_to_connect_the_reason_is_readable(tmp_path):
    session, _ = make(tmp_path, with_connect=False)
    ref = add_efficiency(session)
    with pytest.raises(MeasurementError, match="not connected"):
        session.build_runner(ref)
    assert not session.run_dir.exists()  # nothing was created


def test_an_instrument_that_cannot_be_reached_names_it(tmp_path):
    session, _ = make(tmp_path)

    def connect(name, cancel=None):
        raise OSError("timeout")

    session.connect = connect
    ref = add_efficiency(session)
    with pytest.raises(
        MeasurementError, match="psu1.*timeout|daq1.*timeout|load1.*timeout|psu2.*timeout"
    ):
        session.build_runner(ref)


def test_an_instrument_not_in_the_project_is_refused(tmp_path):
    session, _ = make(tmp_path)
    ref = add_efficiency(session)
    session._instruments = ["psu1"]  # the project only has psu1
    with pytest.raises(MeasurementError, match="not in the project"):
        session.build_runner(ref)


def test_a_file_of_another_type_is_refused(tmp_path):
    session, _ = make(tmp_path)
    ref = add_efficiency(session)
    MeasurementFile(type="time_log", params={}).save(session.path(ref))
    with pytest.raises(MeasurementError, match="time_log"):
        session.build_runner(ref)


def test_choosing_the_instrument_file(tmp_path):
    session, _ = make(tmp_path)
    session._instruments = None
    (tmp_path / "x.inst").write_text(json.dumps({"instruments": [{"instance_name": "HC"}]}))
    session.set_instrument_file("x.inst")
    assert session.instruments == ["HC"]
    with pytest.raises(MeasurementError):
        session.set_instrument_file("../evil.inst")
    with pytest.raises(MeasurementError):
        session.set_instrument_file("nothere.inst")
