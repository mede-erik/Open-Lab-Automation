# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A run made before, read back as if it were happening again (ola.run_replay)."""

import json

import pytest

from ola.run_replay import ReplayError, ReplayRunner
from ola.run_view import RunModel
from ola.runner import Runner
from ola.runs import RunWriter, end_state
from tests.measurement_helpers import Scripted, run_to_end


def make_run(tmp_path, run_fn, name="run.jsonl"):
    runner = Runner(Scripted(run_fn, params={"p": 1}), {}, collect=False, run_id="r1")
    path = tmp_path / name
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner, started_at=1.0)))
    run_to_end(runner)
    return path


def measure(ctx):
    ctx.emit_point({"a": 1, "b": 2.5})
    ctx.emit_trace("ch1", [0, 1], [3.0, 4.0], kind="real", unit="V")
    ctx.emit_point({"a": 2, "b": 3.5})
    ctx.log("note")


def test_a_run_is_shown_as_it_was(tmp_path):
    path = make_run(tmp_path, measure)
    replay = ReplayRunner(path)
    assert replay.run_id == "r1" and replay.header["params"] == {"p": 1} and replay.ended
    model = RunModel()
    for event in replay.drain():
        model.apply(event)
    assert model.state == "finished" and model.finished
    assert [p["a"] for p in model.points] == [1, 2] and model.columns == ["a", "b"]
    assert model.traces["ch1"]["y"] == [3.0, 4.0] and model.traces["ch1"]["meta"] == {"unit": "V"}
    assert any("note" in message for _t, _lvl, message in model.logs)
    assert replay.drain() == []  # the events come once
    assert replay.pending_questions == [] and replay.join() is True
    replay.start(), replay.stop(), replay.pause(), replay.resume(), replay.answer("x", "y")


def test_a_failed_run_shows_its_error_once(tmp_path):
    def fail(ctx):
        ctx.emit_point({"a": 1})
        raise RuntimeError("instrument lost")

    runner = Runner(Scripted(fail, params={}), {}, collect=False, run_id="r2")
    path = tmp_path / "failed.jsonl"
    runner.add_listener(
        RunWriter(path, RunWriter.header_for(runner, started_at=1.0), discard_failed=False)
    )
    run_to_end(runner)
    model = RunModel()
    for event in ReplayRunner(path).drain():
        model.apply(event)
    assert model.state == "failed" and model.error["message"] == "instrument lost"
    assert [m for _t, lvl, m in model.logs if lvl == "error"].count("instrument lost") == 1


def test_a_run_without_an_end_is_shown_as_stopped_and_says_so(tmp_path):
    path = make_run(tmp_path, measure)
    lines = path.read_text().splitlines()
    cut = tmp_path / "cut.jsonl"
    cut.write_text("\n".join(lines[:-1]) + "\n" + lines[-1][:5])  # no end, a truncated last line
    assert end_state(cut) == "interrupted"
    replay = ReplayRunner(cut)
    assert not replay.ended
    model = RunModel()
    for event in replay.drain():
        model.apply(event)
    assert model.state == "stopped" and len(model.points) == 2
    assert any("interrupted" in m for _t, _lvl, m in model.logs)


def test_the_questions_of_the_run_are_not_asked_again(tmp_path):
    path = make_run(tmp_path, measure)
    lines = path.read_text().splitlines()
    ask = {"kind": "question", "id": "q1", "text": "ok?", "choices": ["yes"], "t": 2.0}
    lines.insert(2, json.dumps(ask))
    path.write_text("\n".join(lines) + "\n")
    replay = ReplayRunner(path)
    model = RunModel()
    for event in replay.drain():
        model.apply(event)
    assert model.pending == {} and replay.pending_questions == []


def test_what_is_not_a_run_file_is_refused(tmp_path):
    other = tmp_path / "notes.jsonl"
    other.write_text(json.dumps({"kind": "point"}) + "\n")
    with pytest.raises(ReplayError):
        ReplayRunner(other)
    with pytest.raises(ReplayError):
        ReplayRunner(tmp_path / "missing.jsonl")
    garbage = tmp_path / "g.jsonl"
    garbage.write_text("not json\n")
    with pytest.raises(ReplayError):
        ReplayRunner(garbage)
