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


# ---- benchmarks/bench_hardware.py (safe selection of calls, simulated link) ----------------
def _load_hardware_script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "benchmarks" / "bench_hardware.py"
    spec = importlib.util.spec_from_file_location("bench_hardware", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def library():
    from pathlib import Path

    from ola.library import Library

    path = Path(__file__).resolve().parent.parent / "Instruments_LIB" / "instruments_lib.json"
    return Library.load(str(path))


def test_hardware_benchmark_runs_only_safe_queries(library):
    script = _load_hardware_script()
    ok, refused = script.safe_calls(
        library,
        "PSU_OWON_ODP3033",
        ["read_voltage", "set_voltage", "self_test", "output_on", "no_such_call", "error_query"],
    )
    assert ok == ["read_voltage", "error_query"]
    reasons = dict(refused)
    assert reasons["set_voltage"] == "not a query"
    assert "slow" in reasons["self_test"]
    assert reasons["output_on"] == "not a query"
    assert "does not define" in reasons["no_such_call"]


def test_hardware_benchmark_end_to_end_on_a_simulated_link(library, monkeypatch, capsys, tmp_path):
    script = _load_hardware_script()
    from ola import tester

    link = SimTransport(lambda cmd: "1.5" if cmd.endswith("?") else None)
    link.query = lambda cmd, timeout_ms=None: "ACME,PSU,1,1.0"  # the raw question
    monkeypatch.setattr(tester, "open_visa", lambda *a, **k: link)
    out = tmp_path / "r.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "bench_hardware.py",
            "--model",
            "PSU_OWON_ODP3033",
            "--address",
            "SIM",
            "--repeat",
            "5",
            "--calls",
            "read_voltage,set_voltage",
            "--arg",
            "channel_number=1",
            "--json",
            str(out),
        ],
    )
    script.main()
    text = capsys.readouterr().out
    assert "skipped set_voltage: not a query" in text
    assert "dut.read_voltage" in text and "Straight to the link" in text
    import json

    report = json.loads(out.read_text())
    call = next(r for r in report["rows"] if r["category"] == "call")
    assert call["n"] == 5  # the warm-up is not counted
    assert bench.current() is None
    assert link.log.count("MEAS:VOLT?") == 5 + 3  # measured + warm-up; set_voltage never sent
    assert not any(c.startswith("VOLT ") for c in link.log)


# ---- slowest calls and commands -----------------------------------------------------------------
def _report_with(rows, wall_s=None):
    return {"rows": rows, "summary": {"wall_s": wall_s} if wall_s else {}}


def _row(category, name, total_ms, n=10, **extra):
    return {
        "category": category,
        "name": name,
        "n": n,
        "total_ms": total_ms,
        "mean_ms": total_ms / n,
        "median_ms": total_ms / n,
        "p95_ms": total_ms / n,
        "min_ms": total_ms / n,
        "max_ms": total_ms / n,
        **extra,
    }


def test_hotspots_rank_calls_and_commands_by_total_time_and_leave_out_waits():
    report = _report_with(
        [
            _row("call", "a.fast", 5.0),
            _row("call", "a.slow", 50.0, share_pct=50.0),
            _row("step", "a: write X #", 30.0),
            _row("step", "a: query Y?", 80.0),
            _row("delay", "a: delay", 900.0),
            _row("wait", "sleep", 700.0),
        ]
    )
    slow = bench.hotspots(report, top=1)
    assert [r["name"] for r in slow["calls"]] == ["a.slow"] and slow["calls"][0]["share_pct"] == 50
    assert [r["name"] for r in slow["commands"]] == ["a: query Y?"]  # delays and waits are not here
    assert [r["name"] for r in bench.hotspots(report)["commands"]] == [
        "a: query Y?",
        "a: write X #",
    ]


def test_the_report_gives_each_row_its_share_of_the_measurement_time(tmp_path):
    def run(ctx):
        for i in range(3):
            ctx.sleep(0.01)
            ctx.emit_point({"i": i})

    runner = Runner(Scripted(run, params={}), {}, collect=False, bench=True)
    writer = RunWriter(tmp_path / "run.jsonl", RunWriter.header_for(runner))
    runner.add_listener(writer)
    run_to_end(runner)
    report = read_run(writer.path)["bench"]
    rows = {(r["category"], r["name"]): r for r in report["rows"]}
    assert 0 < rows[("wait", "sleep")]["share_pct"] <= 100
    assert rows[("phase", "run")]["share_pct"] > 90


def test_the_text_report_has_the_slowest_section_with_and_without_the_share():
    rows = [_row("call", "psu.read", 40.0, share_pct=40.0), _row("step", "psu: query A?", 30.0)]
    text = bench.format_report(_report_with(rows, wall_s=0.1))
    assert "Slowest calls" in text and "40.0%" in text and "Slowest commands" in text
    no_share = bench.format_report(_report_with([_row("call", "psu.read", 40.0)]))
    assert "Slowest calls" in no_share and "-" in no_share
