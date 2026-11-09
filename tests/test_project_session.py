# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

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


class ObservingHandle(DemoHandle):
    """A demo handle that remembers what it was asked and gave, like a real handle does."""

    def __init__(self, name, lab):
        super().__init__(name, lab)
        self.observed = {}

    def call(self, name, **args):
        result = super().call(name, **args)
        from ola.compat import observe

        observe(self.observed, name, args, result)
        return result


def test_the_end_of_a_run_file_keeps_what_the_instruments_were_asked_and_gave(tmp_path):
    registry = default_registry(user_dir="/nonexistent")
    lab = DemoLab()
    session = ProjectSession(
        Project.new("Demo", tmp_path),
        registry,
        connect=lambda name, cancel=None: ObservingHandle(name, lab),
        instruments=INSTRUMENTS,
    )
    ref = add_efficiency(session)
    runner, path = session.build_runner(ref)
    runner.start()
    runner.join(30)
    run = read_run(path)
    assert run["end"]["state"] == "finished"
    seen = run["end"].get("observed")
    assert seen, "the demo lab sets and reads voltages: something must have been observed"
    for rows in seen.values():
        for row in rows:
            assert all(v >= 0 for v in row["observed"].values())
    assert set(run["header"]["instruments"]) == set(run["header"]["bindings"])


def test_the_instruments_are_compared_with_the_ones_of_the_previous_run(tmp_path):
    registry = default_registry(user_dir="/nonexistent")
    lab = DemoLab()
    session = ProjectSession(
        Project.new("Demo", tmp_path),
        registry,
        connect=lambda name, cancel=None: ObservingHandle(name, lab),
        instruments=INSTRUMENTS,
    )
    ref = add_efficiency(session)
    big = {name: {"max_voltage": 200.0} for name in INSTRUMENTS}
    small = {name: {"max_voltage": 10.0} for name in INSTRUMENTS}
    assert (
        session.compatibility(ref, lambda name: big[name]) == []
    )  # no run yet: nothing to compare
    runner, path = session.build_runner(ref)
    runner.start()
    runner.join(30)
    # the header of that run keeps what the instruments could do; here the handles have no library
    # (they are demo handles), so write it as a real run would
    text = path.read_text(encoding="utf-8").splitlines()
    header = json.loads(text[0])
    header["instruments"] = {
        role: [{"name": n, "characteristics": big[n]} for n in names]
        for role, names in header["bindings"].items()
    }
    text[0] = json.dumps(header)
    path.write_text("\n".join(text) + "\n", encoding="utf-8")
    found = session.compatibility(ref, lambda name: small[name])
    assert found and all(f.characteristic == "max_voltage" and f.previous == 200.0 for f in found)
    assert session.compatibility(ref, lambda name: big[name]) == []
    # going on: the differences are written in the header of the next run
    runner, path = session.build_runner(ref, accepted_differences=found)
    runner.stop()
    runner.join(30)
    kept = read_run(path)["header"]["accepted_differences"]
    assert kept[0]["characteristic"] == "max_voltage" and kept[0]["previous"] == 200.0
