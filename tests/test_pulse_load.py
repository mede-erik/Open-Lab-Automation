# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The pulse on an electronic load as a measurement: parameters, the power checks (no Qt), and a
run with a simulated load: the calls, the readings, and the load switched off at the end."""

import time

import pytest

from ola.efficiency_spec import Problem
from ola.pulse_load import (
    REQUIRED_CALLS,
    check_params,
    default_params,
    duty_percent,
    power_of,
    pulse_profile,
)
from ola.pulse_power import corrected_parameter
from ola.registry import default_registry
from ola.runner import Runner, RunState
from tests.measurement_helpers import FakeHandle, run_to_end


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


class Load(FakeHandle):
    """A simulated electronic load; ``limits`` are what the library gives for its model."""

    is_manual = True  # handle_characteristics reads ``limits`` of such a handle

    def __init__(self, limits=None, answers=None, fail_on=None, missing=()):
        super().__init__("load", {"read_voltage": 12.0, "read_current": 1.0, **(answers or {})},
                         fail_on)  # fmt: skip
        self.limits = limits or {}
        self.missing = set(missing)

    def supports(self, name):
        return name not in self.missing


def params(**extra):
    base = {"duration_s": 0.3, "read_interval_s": 0.1, "voltage_v": 12.0}
    return {**default_params(), **base, **extra}


def names(load):
    return [c[0] for c in load.calls]


def problems(p):
    return {x.path for x in check_params(p) if x.severity == "error"}


# ---- the parameters -----------------------------------------------------------------------------
def test_a_new_file_is_valid(registry):
    assert check_params(default_params()) == []
    assert registry.create("pulse_load", default_params()).validate() == []
    assert registry.get("pulse_load").extension == ".pls"


@pytest.mark.parametrize(
    "change,path",
    [
        ({"amplitude_a": -1}, "amplitude_a"),
        ({"base_level_a": "x"}, "base_level_a"),
        ({"width_us": 0}, "width_us"),
        ({"width_us": 2000}, "width_us"),  # 2000 us does not fit in 1 kHz
        ({"frequency_hz": 0}, "frequency_hz"),
        ({"rise_time_us": 0}, "rise_time_us"),
        ({"voltage_v": -5}, "voltage_v"),
        ({"duration_s": 0}, "duration_s"),
        ({"read_interval_s": 0.001}, "read_interval_s"),
    ],
)
def test_each_wrong_parameter_is_at_its_field(change, path):
    assert path in problems({**default_params(), **change})


def test_a_current_above_the_load_is_a_problem():
    out = check_params({**default_params(), "amplitude_a": 8}, max_current=5)
    assert [p.path for p in out] == ["amplitude_a"] and isinstance(out[0], Problem)


def test_the_duty_cycle_and_the_shape():
    assert duty_percent(100, 1000) == pytest.approx(10.0)
    times, currents = pulse_profile(2.0, 0.5, 100, 1000, 10, 10)
    assert times[0] == 0 and currents[0] == pytest.approx(0.5)
    assert max(currents) == pytest.approx(2.0) and min(currents) == pytest.approx(0.5)
    assert times[-1] == pytest.approx(0.002)  # two periods of 1 kHz, in seconds


def test_the_power_of_a_pulse():
    assert power_of({**default_params(), "amplitude_a": 2.0}, 10.0, 15.0).exceeded == ["peak"]
    assert power_of({**default_params(), "amplitude_a": 2.0}, 10.0, 25.0).exceeded == []


@pytest.mark.parametrize("last,param", [("amplitude", "amplitude"), ("voltage", "amplitude"),
                                        ("width", "width"), ("base_level", "base_level"),
                                        ("frequency", "frequency")])  # fmt: skip
def test_the_parameter_changed_last_is_the_one_corrected(last, param):
    name, value = corrected_parameter(last, 5.0, 1.0, 400.0, 1000.0, 20.0, 50.0)
    assert name == param and value > 0


# ---- a run --------------------------------------------------------------------------------------
def test_a_run_makes_the_pulse_reads_the_load_and_switches_it_off(registry):
    load = Load({"max_power": 100.0, "max_current": 5.0})
    runner = run_to_end(Runner(registry.create("pulse_load", params()), {"load": [load]}))
    assert runner.state is RunState.FINISHED, runner.error
    called = names(load)
    start = called.index("set_dynamic_level_high")
    assert called[start:start + 5] == [
        "set_dynamic_level_high", "set_dynamic_level_low", "set_dynamic_timing",
        "enable_dynamic_mode", "load_on",
    ]  # fmt: skip
    assert called[-2:] == ["disable_dynamic_mode", "load_off"]
    assert ("set_dynamic_timing", {"frequency": 1000.0, "duty": pytest.approx(10.0)}) in load.calls
    events = runner.drain()
    rows = [e.data["values"] for e in events if e.kind == "point"]
    assert len(rows) >= 2 and rows[0]["voltage_v"] == 12.0 and rows[0]["current_a"] == 1.0
    assert rows[0]["power_w"] == pytest.approx(12.0)
    traces = [e.data for e in events if e.kind == "trace"]
    assert [t["name"] for t in traces] == ["profile"]  # the shape, drawn in the run window


def test_a_pulse_above_the_power_limit_is_refused_before_anything_is_switched_on(registry):
    load = Load({"max_power": 100.0})
    p = params(amplitude_a=5.0, voltage_v=30.0)  # 150 W
    runner = run_to_end(Runner(registry.create("pulse_load", p), {"load": [load]}))
    assert runner.state is RunState.FAILED
    assert "150" in runner.error["message"] and "100" in runner.error["message"]
    assert not {"set_dynamic_level_high", "enable_dynamic_mode", "load_on", "load_off",
                "disable_dynamic_mode"} & set(names(load))  # fmt: skip


def test_the_voltage_read_from_the_load_counts_too(registry):
    load = Load({"max_power": 100.0}, answers={"read_voltage": 40.0})
    p = params(amplitude_a=5.0, voltage_v=0.0)  # 200 W at the voltage of the load
    runner = run_to_end(Runner(registry.create("pulse_load", p), {"load": [load]}))
    assert runner.state is RunState.FAILED and "load_on" not in names(load)


def test_a_power_limit_with_no_known_voltage_is_refused(registry):
    load = Load({"max_power": 100.0}, answers={"read_voltage": 0.0})
    runner = run_to_end(Runner(registry.create("pulse_load", params(voltage_v=0.0)),
                               {"load": [load]}))  # fmt: skip
    assert runner.state is RunState.FAILED and "voltage" in runner.error["message"]
    assert "load_on" not in names(load)


def test_a_current_above_the_maximum_of_the_load_is_refused(registry):
    load = Load({"max_power": 1000.0, "max_current": 3.0})
    runner = run_to_end(Runner(registry.create("pulse_load", params(amplitude_a=4.0)),
                               {"load": [load]}))  # fmt: skip
    assert runner.state is RunState.FAILED and "amplitude_a" in runner.error["message"]
    assert "load_on" not in names(load)


def test_a_load_without_the_dynamic_calls_is_refused(registry):
    load = Load(missing=("set_dynamic_timing", "enable_dynamic_mode"))
    runner = run_to_end(Runner(registry.create("pulse_load", params()), {"load": [load]}))
    assert runner.state is RunState.FAILED
    assert "set_dynamic_timing" in runner.error["message"] and "load_on" not in names(load)
    assert set(REQUIRED_CALLS) >= {"set_dynamic_timing", "enable_dynamic_mode"}


def test_the_load_is_switched_off_after_an_error(registry):
    load = Load({"max_power": 1000.0}, fail_on="read_current")
    runner = run_to_end(Runner(registry.create("pulse_load", params()), {"load": [load]}))
    assert runner.state is RunState.FAILED
    assert names(load)[-2:] == ["disable_dynamic_mode", "load_off"]


def test_the_load_is_switched_off_after_a_stop(registry):
    load = Load({"max_power": 1000.0})
    p = {k: v for k, v in params().items() if k != "duration_s"}  # until Stop
    runner = Runner(registry.create("pulse_load", p), {"load": [load]})
    runner.start()
    deadline = time.time() + 5
    while "load_on" not in names(load) and time.time() < deadline:
        time.sleep(0.01)
    runner.stop()
    assert runner.join(5)
    assert runner.state is RunState.STOPPED
    assert names(load)[-2:] == ["disable_dynamic_mode", "load_off"]


def test_a_failing_switch_off_does_not_stop_the_other(registry):
    load = Load({"max_power": 1000.0}, fail_on="disable_dynamic_mode")
    runner = run_to_end(Runner(registry.create("pulse_load", params()), {"load": [load]}))
    assert names(load)[-1] == "load_off"  # the load input is still switched off
    assert any(e.kind == "log" and "disable_dynamic_mode" in e.data["message"]
               for e in runner.drain())  # fmt: skip
