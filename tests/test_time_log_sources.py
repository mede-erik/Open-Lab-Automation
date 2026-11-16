# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The time log with several sources, each at its own interval and in its own table, and the
earlier format still read as before."""

import time

import pytest

from ola.measurement import MeasurementError
from ola.registry import default_registry
from ola.runner import Runner, RunState
from tests.measurement_helpers import FakeHandle, run_to_end


@pytest.fixture
def registry(tmp_path):
    return default_registry(user_dir=tmp_path / "none")


def source(name, instrument, interval, readings, **extra):
    return {"name": name, "instrument": instrument, "interval_s": interval, "readings": readings,
            **extra}


def volts(name="vout"):
    return [{"name": name, "call": "read_voltage"}]


def params(**extra):
    base = {
        "sources": [
            source("dmm", "dmm1", 0.10, volts(), samples=3),
            source("daq", "daq", 0.05, [{"name": "temp", "call": "measure_temperature",
                                         "args": {"channels": "101"}}], samples=6),
        ]
    }
    base.update(extra)
    return base


def handles(dmm_read=None):
    return {
        "instruments": [
            FakeHandle("dmm1", {"read_voltage": dmm_read or 5.01}),
            FakeHandle("daq", {"measure_temperature": lambda channels: 25.5}),
        ]
    }


def points(runner):
    return [e.data for e in runner.drain() if e.kind == "point"]


def test_each_source_writes_its_own_table_at_its_own_interval(registry):
    runner = run_to_end(Runner(registry.create("time_log", params()), handles()))
    assert runner.state is RunState.FINISHED, runner.error
    rows = points(runner)
    by_table = {}
    for row in rows:
        by_table.setdefault(row["table"], []).append(row["values"])
    assert [r["vout"] for r in by_table["dmm"]] == [5.01, 5.01, 5.01]
    assert len(by_table["daq"]) == 6 and by_table["daq"][0]["temp"] == 25.5
    assert "points" not in by_table  # nothing in the main table: only the sources' tables
    # the dmm samples come at 0.1 s, the daq ones at 0.05 s
    t_dmm = [v["t_s"] for v in by_table["dmm"]]
    t_daq = [v["t_s"] for v in by_table["daq"]]
    assert abs(t_dmm[2] - 0.2) < 0.04 and abs(t_daq[5] - 0.25) < 0.04


def test_a_source_ends_after_its_samples_and_the_others_go_on(registry):
    runner = run_to_end(Runner(registry.create("time_log", params()), handles()))
    rows = points(runner)
    assert sum(1 for r in rows if r["table"] == "dmm") == 3
    assert sum(1 for r in rows if r["table"] == "daq") == 6


def test_a_common_duration_ends_sources_without_samples(registry):
    fast_reading = [{"name": "t", "call": "measure_temperature", "args": {"channels": "101"}}]
    p = {"duration_s": 0.2, "sources": [
        source("fast", "daq", 0.05, fast_reading),
        source("slow", "dmm1", 0.1, volts()),
    ]}
    runner = run_to_end(Runner(registry.create("time_log", p), handles()))
    rows = points(runner)
    fast = [r for r in rows if r["table"] == "fast"]
    slow = [r for r in rows if r["table"] == "slow"]
    assert 4 <= len(fast) <= 5 and 2 <= len(slow) <= 3
    assert max(r["values"]["t_s"] for r in rows) <= 0.25


def test_a_slow_source_skips_the_samples_it_missed_and_says_so(registry):
    slow = FakeHandle("dmm1", {"read_voltage": lambda: time.sleep(0.07) or 1.0})
    daq = FakeHandle("daq", {"measure_temperature": lambda channels: 20.0})
    p = {"sources": [source("dmm", "dmm1", 0.03, volts(), samples=3)]}
    runner = Runner(registry.create("time_log", p), {"instruments": [slow, daq]})
    run_to_end(runner)
    assert runner.state is RunState.FINISHED
    events = list(runner.drain())
    warnings = [e.data for e in events if e.kind == "log" and "skipped" in str(e.data)]
    assert warnings, [e.data for e in events if e.kind == "log"]
    t = [e.data["values"]["t_s"] for e in events if e.kind == "point"]
    assert t[1] - t[0] > 0.06  # the second sample is not taken at 0.03 s but after the read


def test_an_unbound_instrument_of_a_source_fails_before_any_read(registry):
    only_dmm = {"instruments": [FakeHandle("dmm1", {"read_voltage": 1.0})]}
    runner = run_to_end(Runner(registry.create("time_log", params()), only_dmm))
    assert runner.state is RunState.FAILED and "source 'daq'" in runner.error["message"]
    assert only_dmm["instruments"][0].calls == []


@pytest.mark.parametrize(
    "p,message",
    [
        ({"channels": [], "sources": []}, "not both"),
        ({}, "give 'sources'"),
        ({"sources": []}, "non-empty list"),
        ({"sources": [source("points", "dmm1", 1, volts())], "duration_s": 1},
         "reserved"),
        ({"sources": [source("a", "dmm1", 1, volts()), source("a", "dmm1", 1, volts())],
          "duration_s": 1}, "duplicate source name"),
        ({"sources": [source("a", "dmm1", 0, volts(), samples=2)]}, "interval_s"),
        ({"sources": [source("a", "dmm1", 1, volts())]}, "give samples"),
        ({"sources": [source("a", "dmm1", 1, volts(), samples=0)], "duration_s": 1},
         "samples must be"),
        ({"sources": [source("a", "dmm1", 1, [{"name": "t_s", "call": "read_voltage"}])],
          "duration_s": 1}, "not usable"),
        ({"sources": [source("a", "dmm1", 1, [])], "duration_s": 1}, "readings must be"),
        ({"sources": [source("a", "dmm1", 1, volts())], "samples": 3}, "belong to each source"),
        ({"sources": [source("a", "dmm1", 1, volts())], "duration_s": 0}, "duration_s must"),
    ],
)
def test_source_parameter_validation(registry, p, message):
    m = registry.create("time_log", p)
    problems = m.validate()
    assert any(message in problem for problem in problems), problems
    with pytest.raises(MeasurementError):
        Runner(m, handles()).start()


def test_the_earlier_format_still_writes_the_main_table(registry):
    old = {"interval_s": 0.02, "samples": 4, "channels": [
        {"name": "vout", "instrument": "dmm1", "call": "read_voltage"},
        {"name": "temp", "instrument": "daq", "call": "measure_temperature",
         "args": {"channels": "101"}},
    ]}
    runner = run_to_end(Runner(registry.create("time_log", old), handles()))
    rows = points(runner)
    assert len(rows) == 4 and all(r["table"] == "points" for r in rows)
    assert rows[0]["values"]["vout"] == 5.01 and rows[0]["values"]["temp"] == 25.5


def test_the_tables_reach_the_run_file(registry, tmp_path):
    from ola.runs import RunWriter, read_run

    runner = Runner(registry.create("time_log", params()), handles(), collect=False)
    writer = RunWriter(tmp_path / "log.jsonl", RunWriter.header_for(runner))
    runner.add_listener(writer)
    run_to_end(runner)
    data = read_run(writer.path)
    assert len(data["tables"]["dmm"]) == 3 and len(data["tables"]["daq"]) == 6
    assert data["points"] == []
