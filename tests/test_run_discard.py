# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A run that failed is not kept; a run can be deleted on purpose."""

import json

import numpy as np
import pytest

from ola.runner import Runner
from ola.runs import RunWriter, delete_run
from ola.wavefiles import Capture, save_capture, wave_folder
from tests.measurement_helpers import Scripted, run_to_end


def run_with(tmp_path, run_fn, discard):
    runner = Runner(Scripted(run_fn, params={"p": 1}), {}, collect=False, run_id="r1")
    writer = RunWriter(
        tmp_path / "run.jsonl", RunWriter.header_for(runner, started_at=1.0), discard_failed=discard
    )
    runner.add_listener(writer)
    # a capture of the run, to see that the folder of the waveforms goes with it
    save_capture(
        wave_folder(writer.path),
        Capture(0, "long", "osc1", {"CH1": np.zeros(10, dtype=np.float32)}, 1e-6, 0.0),
    )
    run_to_end(runner)
    return writer


def finish(ctx):
    ctx.emit_point({"a": 1})


def fail(ctx):
    ctx.emit_point({"a": 1})
    raise RuntimeError("instrument lost")


def test_a_failed_run_is_deleted_with_its_waveforms(tmp_path):
    writer = run_with(tmp_path, fail, discard=True)
    assert writer.discarded is True
    assert not writer.path.exists() and not wave_folder(writer.path).exists()
    assert list(tmp_path.iterdir()) == []  # nothing is left in the folder


def test_a_run_that_finished_is_always_kept(tmp_path):
    writer = run_with(tmp_path, finish, discard=True)
    assert writer.discarded is False and writer.path.is_file() and wave_folder(writer.path).is_dir()
    assert json.loads(writer.path.read_text().splitlines()[-1])["state"] == "finished"


def test_a_failed_run_is_kept_when_asked(tmp_path):
    writer = run_with(tmp_path, fail, discard=False)  # the default of the writer
    assert writer.discarded is False and writer.path.is_file()
    assert json.loads(writer.path.read_text().splitlines()[-1])["state"] == "failed"


def test_a_stopped_run_is_kept(tmp_path):
    import threading

    started = threading.Event()

    def wait(ctx):
        ctx.emit_point({"a": 1})
        started.set()
        ctx.sleep(30)

    runner = Runner(Scripted(wait, params={"p": 1}), {}, collect=False, run_id="r1")
    writer = RunWriter(
        tmp_path / "run.jsonl", RunWriter.header_for(runner, started_at=1.0), discard_failed=True
    )
    runner.add_listener(writer)
    runner.start()
    assert started.wait(2)
    runner.stop()
    assert runner.join(5) and runner.state.value == "stopped"
    assert writer.discarded is False and writer.path.is_file()  # it has data: never discarded


def test_a_run_is_deleted_on_purpose_with_its_waveforms(tmp_path):
    writer = run_with(tmp_path, finish, discard=False)
    removed = delete_run(writer.path)
    assert len(removed) == 2 and not writer.path.exists() and not wave_folder(writer.path).exists()
    assert delete_run(writer.path) == []  # already gone: not an error


def test_only_a_run_file_can_be_deleted(tmp_path):
    other = tmp_path / "notes.jsonl"
    other.write_text(json.dumps({"kind": "point"}) + "\n")
    with pytest.raises(ValueError):
        delete_run(other)
    assert other.exists()
    text = tmp_path / "project.json"
    text.write_text("{}")
    with pytest.raises(ValueError):
        delete_run(text)
    assert text.exists()
    garbage = tmp_path / "x.jsonl"
    garbage.write_text("not json\n")
    with pytest.raises(ValueError):
        delete_run(garbage)
    assert garbage.exists()


def test_the_session_discards_a_failed_run_unless_the_settings_keep_it(tmp_path):
    from ola.demo_lab import DemoHandle, DemoLab
    from ola.project import MeasurementFile, Project
    from ola.project_session import ProjectSession
    from ola.registry import default_registry
    from tests.test_variants import good

    lab = DemoLab()
    session = ProjectSession(
        Project.new("Lab", tmp_path),
        default_registry(user_dir="/nonexistent"),
        connect=lambda name, cancel=None: DemoHandle(name, lab),
        instruments=["a"],
    )
    ref = session.create("efficiency", "Eff")
    MeasurementFile(type="efficiency", role_bindings={"instruments": ["a"]}, params=good()).save(
        session.path(ref)
    )
    runner, path = session.build_runner(ref)  # the default: a failed run is not kept
    runner.start()
    runner.join(30)
    assert runner.state.value == "failed"  # (the demo instrument "a" cannot do what good() asks)
    assert not path.exists()
    kept, kept_path = session.build_runner(ref, keep_failed=True)
    kept.start()
    kept.join(30)
    assert kept.state.value == "failed" and kept_path.is_file()
    assert session.runs(ref) == [
        kept_path
    ]  # only the kept one is in the history of the measurement
