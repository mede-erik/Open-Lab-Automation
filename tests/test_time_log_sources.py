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
    entry = {"name": name, "instrument": instrument, "interval_s": interval, **extra}
    if readings is not None:
        entry["readings"] = readings
    return entry


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


# ----- a datalogger read as one scan -------------------------------------------------------------
SCAN_CHANNELS = [
    {"name": "vout", "channel_id": "103", "meas_type": "VOLT:DC"},
    {"name": "temp1", "channel_id": "101", "meas_type": "TEMP", "probe_type": "TCouple",
     "sensor_type": "K"},
]


def scan_source(samples=3, interval=0.02, **extra):
    entry = {"name": "daq", "instrument": "daq", "interval_s": interval, "scan": True,
             "channels": SCAN_CHANNELS, "samples": samples}
    entry.update(extra)
    return entry


def scan_source_without_readings(**extra):
    return scan_source(**extra)


def daq(scan_values=(20.5, 5.0)):
    return FakeHandle("daq", {"read_scan": lambda: list(scan_values)})


def test_a_datalogger_scan_is_configured_once_and_read_once_per_sample(registry):
    handle = daq()
    p = {"sources": [scan_source(samples=3)]}
    runner = run_to_end(Runner(registry.create("time_log", p), {"instruments": [handle]}))
    assert runner.state is RunState.FINISHED, runner.error
    names = [c[0] for c in handle.calls]
    assert names.count("read_scan") == 3
    assert names.count("select_channels") == 1  # the scan list: once, before the first sample
    assert names.index("select_channels") < names.index("read_scan")
    assert handle.calls[names.index("select_channels")][1] == {"channels": "101,103"}
    rows = [e.data["values"] for e in runner.drain() if e.kind == "point"]
    assert len(rows) == 3
    # the readings go to the channels in channel-number order: 101 (temp1) first, then 103 (vout)
    assert rows[0]["temp1"] == 20.5 and rows[0]["vout"] == 5.0


def test_the_scan_gives_fewer_readings_than_channels_stops_with_a_clear_message(registry):
    handle = FakeHandle("daq", {"read_scan": lambda: [20.5]})
    p = {"sources": [scan_source(samples=2)]}
    runner = run_to_end(Runner(registry.create("time_log", p), {"instruments": [handle]}))
    assert runner.state is RunState.FAILED
    assert "1 readings for 2 channels" in runner.error["message"]


def test_a_scan_has_channels_and_no_readings(registry):
    problems = registry.create(
        "time_log", {"sources": [scan_source_without_readings(channels=[])]}
    ).validate()
    assert any("channels must be a non-empty list" in p for p in problems), problems
    problems = registry.create(
        "time_log", {"sources": [scan_source(
            readings=[{"name": "x", "call": "read_voltage"}])]}
    ).validate()
    assert any("'channels', not 'readings'" in p for p in problems), problems
    plain = source("dmm", "dmm1", 1, volts(), channels=SCAN_CHANNELS, samples=2)
    assert any("is for a scan" in p for p in registry.create(
        "time_log", {"sources": [plain]}).validate())


def test_a_scan_channel_the_datalogger_cannot_configure_is_refused(registry):
    bad = [{"name": "x", "channel_id": "103", "meas_type": "NOPE"}]
    problems = registry.create(
        "time_log", {"sources": [scan_source_without_readings(channels=bad)]}
    ).validate()
    assert any("unknown measurement type" in p for p in problems), problems
    dup = [{"name": "a", "channel_id": "103", "meas_type": "VOLT:DC"},
           {"name": "a", "channel_id": "104", "meas_type": "VOLT:DC"}]
    problems = registry.create(
        "time_log", {"sources": [scan_source_without_readings(channels=dup)]}
    ).validate()
    assert any("channel name 'a' is not usable" in p for p in problems), problems


def test_a_scan_with_its_own_interval_next_to_a_multimeter(registry):
    p = {"sources": [
        scan_source(samples=4, interval=0.02),
        source("dmm", "dmm1", 0.05, volts(), samples=2),
    ]}
    handles = {"instruments": [daq(), FakeHandle("dmm1", {"read_voltage": 5.0})]}
    runner = run_to_end(Runner(registry.create("time_log", p), handles))
    assert runner.state is RunState.FINISHED, runner.error
    rows = points(runner)
    assert sum(1 for r in rows if r["table"] == "daq") == 4
    assert sum(1 for r in rows if r["table"] == "dmm") == 2
    daq_rows = [r["values"] for r in rows if r["table"] == "daq"]
    assert daq_rows[0]["temp1"] == 20.5 and daq_rows[0]["vout"] == 5.0


def test_a_channel_attenuation_divides_its_scan_value(registry):
    channels = [
        {"name": "vin", "channel_id": "102", "meas_type": "VOLT:DC", "attenuation": 10.0},
        {"name": "vout", "channel_id": "103", "meas_type": "VOLT:DC"},
    ]
    handle = daq(scan_values=(120.0, 5.0))
    p = {"sources": [scan_source(samples=1, channels=channels)]}
    runner = run_to_end(Runner(registry.create("time_log", p), {"instruments": [handle]}))
    assert runner.state is RunState.FINISHED, runner.error
    row = [e.data["values"] for e in runner.drain() if e.kind == "point"][0]
    assert row["vin"] == 12.0 and row["vout"] == 5.0


def test_a_channel_attenuation_must_be_positive(registry):
    channels = [{"name": "vin", "channel_id": "102", "meas_type": "VOLT:DC", "attenuation": 0}]
    problems = registry.create("time_log", {"sources": [scan_source(channels=channels)]}).validate()
    assert any("attenuation" in p for p in problems)
