# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Benchmark mode: ola.bench, its hooks in the instrument layer and the runner."""

import threading
import time

import pytest

from ola import bench
from ola.instrument import Instrument
from ola.runner import Runner, RunState
from ola.runs import RunWriter, read_run
from ola.sim import SimTransport
from tests.measurement_helpers import Scripted, run_to_end


@pytest.fixture(autouse=True)
def clean():
    bench.disable()
    yield
    bench.disable()


def plan(*steps, call="c"):
    return {"call": call, "access": "scpi", "steps": list(steps)}


def test_off_by_default_and_records_nothing():
    assert bench.current() is None and bench.stamp() == 0
    with bench.span("x", "y"):
        pass
    with bench.call_frame("a", "b") as frame:
        with frame.part("plan"):
            pass
    inst = Instrument("i", SimTransport(lambda c: "1.0"))
    inst.run(plan({"op": "query", "text": "A?", "returns": "float"}))
    assert bench.current() is None


def test_numbers_are_normalised_so_values_share_a_row():
    assert bench.normalize("VOLT 5") == bench.normalize("VOLT 12.5") == "VOLT #"
    assert bench.normalize("INST:NSEL 1") == "INST:NSEL #"
    assert len(bench.normalize("X" * 200)) == 60


def test_steps_and_calls_are_measured_with_the_answer_wait_separate():
    b = bench.enable(fresh=True)

    def slow(cmd):
        return "2.0"

    inst = Instrument("psu", SimTransport(slow))
    with bench.call_frame("psu", "read_voltage"):
        inst.run(
            plan(
                {"op": "write", "text": "INST:NSEL 1"},
                {"op": "delay", "ms": 20},
                {"op": "query", "text": "MEAS:VOLT?", "returns": "float"},
            )
        )
    rows = {(r["category"], r["name"]): r for r in b.report()["rows"]}
    assert rows[("step", "psu: write INST:NSEL #")]["n"] == 1
    assert rows[("delay", "psu: delay")]["mean_ms"] >= 19
    assert ("tx", "psu: query MEAS:VOLT?") in rows and ("rx", "psu: query MEAS:VOLT?") in rows
    call = rows[("call", "psu.read_voltage")]
    parts = call["parts_ms"]
    assert parts["delay"] >= 19 and parts["io"] > 0
    assert call["total_ms"] >= parts["delay"] + parts["io"] - 0.01
    assert parts["overhead"] >= 0


def test_a_failed_step_is_still_timed():
    b = bench.enable(fresh=True)
    inst = Instrument("psu", SimTransport(lambda c: None, timeout_ms=10))
    with pytest.raises(Exception):
        inst.run(plan({"op": "query", "text": "A?", "returns": "float", "timeout_ms": 10}))
    assert any(r["category"] == "step" for r in b.report()["rows"])


def test_waiting_for_the_lock_is_a_part_of_the_call():
    b = bench.enable(fresh=True)
    gate = threading.Event()
    inst = Instrument("psu", SimTransport(lambda c: "1"))

    def hold():
        with inst._lock:
            gate.set()
            time.sleep(0.05)

    t = threading.Thread(target=hold)
    t.start()
    gate.wait()
    with bench.call_frame("psu", "c"):
        inst.run(plan({"op": "query", "text": "A?", "returns": "float"}))
    t.join()
    row = next(r for r in b.report()["rows"] if r["category"] == "call")
    assert row["parts_ms"]["lock"] >= 30


def test_driver_calls_are_timed():
    b = bench.enable(fresh=True)

    class Driver:
        def call(self, function, args):
            time.sleep(0.01)
            return 1

    inst = Instrument("ad", driver=Driver())
    inst.run({"call": "c", "access": "driver", "driver": {"function": "scope_read", "args": {}}})
    rows = {(r["category"], r["name"]): r for r in b.report()["rows"]}
    assert rows[("step", "ad: driver scope_read")]["mean_ms"] >= 9


def test_a_run_publishes_a_report_with_the_time_summary_and_writes_it(tmp_path):
    def run(ctx):
        for i in range(5):
            ctx.sleep(0.02)
            ctx.emit_point({"i": i})

    m = Scripted(run, params={})
    runner = Runner(m, {}, collect=False, run_id="r1", bench=True)
    writer = RunWriter(tmp_path / "run.jsonl", RunWriter.header_for(runner))
    runner.add_listener(writer)
    run_to_end(runner)
    report = read_run(writer.path)["bench"]
    assert report["run_id"] == "r1" and report["version"] == bench.REPORT_VERSION
    summary = report["summary"]
    assert summary["wait_s"] >= 0.09 and summary["wall_s"] >= summary["wait_s"]
    assert (
        abs(sum(summary[k] for k in ("wait_s", "calls_s", "emit_s", "other_s")) - summary["wall_s"])
        < 0.01
    )
    names = {(r["category"], r["name"]) for r in report["rows"]}
    assert ("phase", "run") in names and ("emit", "point") in names
    assert ("listener", "RunWriter") in names and ("wait", "sleep") in names
    assert bench.current() is None  # the run switched it off again
    assert "Measurement thread" in bench.format_report(report)


def test_without_the_benchmark_a_run_has_no_bench_line(tmp_path):
    m = Scripted(lambda ctx: ctx.emit_point({"a": 1}), params={})
    runner = Runner(m, {}, collect=False, bench=False)
    writer = RunWriter(tmp_path / "run.jsonl", RunWriter.header_for(runner))
    runner.add_listener(writer)
    run_to_end(runner)
    assert read_run(writer.path)["bench"] is None and runner.state is RunState.FINISHED


def test_the_environment_variable_turns_it_on(monkeypatch):
    monkeypatch.delenv("OLA_BENCH", raising=False)
    assert not bench.env_enabled()
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv("OLA_BENCH", value)
        assert bench.env_enabled()
    monkeypatch.setenv("OLA_BENCH", "0")
    assert not bench.env_enabled()
    monkeypatch.setenv("OLA_BENCH", "1")
    assert Runner(Scripted(lambda ctx: None), {})._bench is True


def test_a_failure_of_the_report_does_not_fail_the_run(monkeypatch):
    monkeypatch.setattr(bench.Bench, "report", lambda self, run_thread=None: 1 / 0)
    runner = Runner(Scripted(lambda ctx: ctx.emit_point({"a": 1})), {}, bench=True)
    run_to_end(runner)
    assert runner.state is RunState.FINISHED


def test_compare_reports_shows_the_change():
    def rep(median):
        return {"rows": [{"category": "call", "name": "psu.x", "median_ms": median}]}

    text = bench.compare_reports(rep(2.0), rep(1.0))
    assert "-50.0%" in text
    assert "new" in bench.compare_reports({"rows": []}, rep(1.0))


def test_the_overhead_of_the_hooks_is_small():
    """A disabled hook costs well under a microsecond-scale: a million of them in a second."""
    t = time.perf_counter()
    for _ in range(100_000):
        with bench.span("a", "b"):
            pass
    assert time.perf_counter() - t < 1.0
