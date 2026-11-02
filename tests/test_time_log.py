"""The built-in time_log module, through registry + runner + run storage."""

import time

import pytest

from ola.measurement import MeasurementError
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.runs import RunWriter, read_run
from tests.measurement_helpers import FakeHandle, run_to_end


@pytest.fixture
def registry(tmp_path):
    return default_registry(user_dir=tmp_path / "none")


def channels():
    return [
        {"name": "vout", "instrument": "dmm1", "call": "read_voltage"},
        {
            "name": "temp",
            "instrument": "daq",
            "call": "measure_temperature",
            "args": {"channels": "101"},
        },
    ]


def make(registry, **params):
    base = {"interval_s": 0.02, "samples": 5, "channels": channels()}
    base.update(params)
    return registry.create("time_log", base)


def handles():
    return {
        "instruments": [
            FakeHandle("dmm1", {"read_voltage": 5.01}),
            FakeHandle("daq", {"measure_temperature": lambda channels: 25.5}),
        ]
    }


def test_logs_the_requested_number_of_samples(registry):
    b = handles()
    r = run_to_end(Runner(make(registry), b))
    assert r.state is RunState.FINISHED
    points = [e.data for e in r.drain() if e.kind == "point"]
    assert len(points) == 5
    assert points[0]["values"]["vout"] == 5.01 and points[0]["values"]["temp"] == 25.5
    assert b["instruments"][1].calls[0] == ("measure_temperature", {"channels": "101"})
    assert len(b["instruments"][0].calls) == 5


def test_schedule_does_not_drift(registry):
    r = run_to_end(Runner(make(registry, interval_s=0.05, samples=6), handles()))
    t = [e.data["values"]["t_s"] for e in r.drain() if e.kind == "point"]
    # sample k must be near k * interval measured from the start, not accumulate delays
    for k, tk in enumerate(t):
        assert abs(tk - k * 0.05) < 0.04, (k, tk)


def test_slow_reads_shorten_the_wait_instead_of_shifting_the_log(registry):
    slow = FakeHandle("dmm1", {"read_voltage": lambda: time.sleep(0.03) or 1.0})
    daq = FakeHandle("daq", {"measure_temperature": lambda channels: 20.0})
    r = run_to_end(Runner(make(registry, interval_s=0.05, samples=5), {"instruments": [slow, daq]}))
    t = [e.data["values"]["t_s"] for e in r.drain() if e.kind == "point"]
    assert abs(t[4] - 0.2) < 0.05


def test_duration_limit(registry):
    m = registry.create("time_log", {"interval_s": 0.05, "duration_s": 0.2, "channels": channels()})
    r = run_to_end(Runner(m, handles()))
    n = len([e for e in r.drain() if e.kind == "point"])
    assert 4 <= n <= 5


@pytest.mark.parametrize(
    "params,message",
    [
        ({"interval_s": 0}, "interval_s"),
        ({"interval_s": "fast"}, "interval_s"),
        ({"samples": None}, "duration_s or samples"),
        ({"samples": 0}, "samples must be"),
        ({"samples": True}, "samples must be"),
        ({"duration_s": -1}, "duration_s"),
        ({"channels": []}, "non-empty list"),
        ({"channels": [{"name": "a"}]}, "needs 'name'"),
        ({"channels": channels() + channels()}, "duplicate channel name"),
        ({"channels": [{"name": "a", "instrument": "x", "call": "c", "args": 5}]}, "'args'"),
    ],
)
def test_parameter_validation(registry, params, message):
    p = {"interval_s": 1.0, "samples": 3, "channels": channels()}
    p.update(params)
    runner = Runner(registry.create("time_log", p), handles())
    with pytest.raises(MeasurementError, match=message):
        runner.start()
    assert all(h.calls == [] for h in handles()["instruments"])


def test_unbound_instrument_fails_before_any_read(registry):
    only_dmm = {"instruments": [FakeHandle("dmm1", {"read_voltage": 1.0})]}
    r = run_to_end(Runner(make(registry), only_dmm))
    assert r.state is RunState.FAILED and "'daq' is not bound" in r.error["message"]
    assert only_dmm["instruments"][0].calls == []


def test_a_failing_read_stops_the_log_and_keeps_the_data(registry, tmp_path):
    flaky = FakeHandle("dmm1", {"read_voltage": 1.0})
    calls = {"n": 0}

    def read():
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("timeout")
        return 1.0

    flaky.answers["read_voltage"] = read
    daq = FakeHandle("daq", {"measure_temperature": lambda channels: 20.0})
    runner = Runner(make(registry), {"instruments": [flaky, daq]}, collect=False)
    writer = RunWriter(tmp_path / "log.jsonl", RunWriter.header_for(runner))
    runner.add_listener(writer)
    run_to_end(runner)
    data = read_run(writer.path)
    assert runner.state is RunState.FAILED and len(data["points"]) == 2
    assert data["end"]["state"] == "failed" and data["end"]["error"]["message"] == "timeout"


def test_stop_ends_a_long_log_quickly(registry):
    m = registry.create("time_log", {"interval_s": 10, "duration_s": 3600, "channels": channels()})
    r = Runner(m, handles())
    r.start()
    time.sleep(0.1)
    t = time.perf_counter()
    r.stop()
    assert r.join(2) and time.perf_counter() - t < 0.5 and r.state is RunState.STOPPED
