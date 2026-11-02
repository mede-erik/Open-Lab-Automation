"""Incremental run storage."""

import csv
import json

from ola.registry import default_registry
from ola.runner import Runner
from ola.runs import RunWriter, export_points_csv, read_run
from tests.measurement_helpers import FakeHandle, Scripted, run_to_end


def make_run(tmp_path, run_fn, **kw):
    m = Scripted(run_fn, params={"p": 1})
    runner = Runner(m, {}, collect=False, run_id="r1")
    writer = RunWriter(tmp_path / "run.jsonl", RunWriter.header_for(runner, started_at=1.0))
    runner.add_listener(writer)
    return runner, writer


def test_roundtrip(tmp_path):
    def run(ctx):
        ctx.emit_point({"a": 1, "b": 2.5})
        ctx.emit_trace("ch1", [0, 1], [3.0, 4.0], kind="real", unit="V")
        ctx.emit_point({"a": 2, "c": "x"})
        ctx.log("note")

    runner, writer = make_run(tmp_path, run)
    run_to_end(runner)
    run = read_run(writer.path)
    assert run["header"]["run_id"] == "r1" and run["header"]["params"] == {"p": 1}
    assert [p["values"] for p in run["points"]] == [{"a": 1, "b": 2.5}, {"a": 2, "c": "x"}]
    assert run["traces"][0]["y"] == [3.0, 4.0] and run["traces"][0]["meta"] == {"unit": "V"}
    assert run["traces"][0]["kind"] == "trace" and run["traces"][0]["trace_kind"] == "real"
    assert run["logs"][0]["message"] == "note"
    assert run["end"]["state"] == "finished" and run["end"]["error"] is None
    lines = writer.path.read_text().splitlines()
    assert all(json.loads(line) for line in lines) and writer._f is None  # file closed


def test_failed_run_records_the_error(tmp_path):
    def run(ctx):
        ctx.emit_point({"a": 1})
        raise RuntimeError("instrument lost")

    runner, writer = make_run(tmp_path, run)
    run_to_end(runner)
    data = read_run(writer.path)
    assert data["end"]["state"] == "failed"
    assert data["end"]["error"]["message"] == "instrument lost"
    assert len(data["points"]) == 1  # what was measured before the failure is kept


def test_points_reach_the_disk_while_the_run_is_in_progress(tmp_path):
    import threading

    release, written = threading.Event(), threading.Event()

    def run(ctx):
        ctx.emit_point({"a": 1})
        written.set()
        release.wait(5)

    runner, writer = make_run(tmp_path, run)
    runner.start()
    assert written.wait(2)
    import time

    time.sleep(0.05)
    partial = read_run(writer.path)  # run still going: no "end" yet
    assert len(partial["points"]) == 1 and partial["end"] is None
    release.set()
    assert runner.join(2)
    assert read_run(writer.path)["end"]["state"] == "finished"


def test_truncated_file_is_still_readable(tmp_path):
    path = tmp_path / "crash.jsonl"
    path.write_text(
        '{"kind": "run", "run_id": "x"}\n'
        '{"kind": "point", "index": 0, "elapsed_s": 0.1, "values": {"a": 1}}\n'
        '{"kind": "point", "index": 1, "elaps'  # power cut in the middle of a line
    )
    run = read_run(path)
    assert run["header"]["run_id"] == "x" and len(run["points"]) == 1 and run["end"] is None


def test_export_csv(tmp_path):
    def run(ctx):
        ctx.emit_point({"a": 1, "b": 2})
        ctx.emit_point({"a": 3, "c": 4})

    runner, writer = make_run(tmp_path, run)
    run_to_end(runner)
    n = export_points_csv(writer.path, tmp_path / "out.csv")
    rows = list(csv.reader(open(tmp_path / "out.csv", newline="")))
    assert n == 2 and rows[0] == ["index", "elapsed_s", "a", "b", "c"]
    assert rows[1][2:] == ["1", "2", ""] and rows[2][2:] == ["3", "", "4"]


def test_header_uses_module_info_and_binding_names(tmp_path):
    reg = default_registry(user_dir=tmp_path / "none")
    m = reg.create(
        "time_log",
        {
            "interval_s": 1,
            "samples": 1,
            "channels": [{"name": "v", "instrument": "dmm1", "call": "read"}],
        },
    )
    runner = Runner(m, {"instruments": [FakeHandle("dmm1", {"read": 1.0})]})
    header = RunWriter.header_for(runner)
    assert header["measurement"] == "time_log" and header["module_version"] == "1.0.0"
    assert header["bindings"] == {"instruments": ["dmm1"]}
