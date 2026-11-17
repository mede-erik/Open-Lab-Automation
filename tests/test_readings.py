# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The readings an instrument has inside (``ola.readings``) and how the time log reaches them,
for a supply, an electronic load and a multimeter alike."""

import pytest

from ola.measurement import MeasurementError
from ola.readings import call_arguments, readable_calls
from ola.registry import default_registry
from ola.runner import Runner, RunState
from tests.conftest import LIBRARY_PATH
from tests.measurement_helpers import FakeHandle, run_to_end

needs_library = pytest.mark.skipif(
    LIBRARY_PATH is None, reason="instrument library not available"
)


def library():
    from ola.library import Library

    return Library.load(LIBRARY_PATH)


@needs_library
def test_a_supply_a_load_and_a_meter_list_their_own_readings():
    lib = library()
    supply = {r.name: r for r in readable_calls(lib, "PSU_OWON_ODP3033")}
    assert {"read_voltage", "read_current", "read_power"} <= set(supply)
    assert supply["read_voltage"].unit == "V" and supply["read_voltage"].channel
    load = {r.name: r for r in readable_calls(lib, "EL_Keysight_EL4913A")}
    assert {r.name for r in load.values()} == {"read_voltage", "read_current", "read_power"}
    assert load["read_power"].unit == "W" and not load["read_power"].channel
    meter = {r.name for r in readable_calls(lib, "MTR_Agilent_34401A")}
    assert "measure_dc_voltage" in meter and "read_measurement" in meter


@needs_library
def test_status_and_calibration_queries_are_not_readings():
    lib = library()
    for model in ("MTR_Agilent_34401A", "PSU_Keysight_E36312A", "EL_Chroma_6330A"):
        names = {r.name for r in readable_calls(lib, model)}
        assert not any(n.startswith(("query_", "calibration", "self_test")) for n in names)


@needs_library
def test_what_a_datalogger_reading_needs_is_listed():
    needs = {r.name: r.needs for r in readable_calls(library(), "DL_Agilent_34970A")}
    assert "channels" in needs["measure_dc_voltage"]


@needs_library
def test_the_arguments_of_a_call_and_an_unknown_model():
    lib = library()
    assert "channel_number" in call_arguments(lib, "PSU_Keysight_E36312A", "read_voltage")
    assert call_arguments(lib, "EL_Keysight_EL4913A", "read_voltage") == {}
    assert readable_calls(lib, "nope") == []


@needs_library
def test_every_reading_listed_is_planned_by_the_library():
    from ola.call_planner import plan_call

    lib = library()
    models = ("PSU_Keysight_E36312A", "PSU_OWON_ODP3033", "EL_Keysight_EL4913A",
              "EL_Siglent_SDL1030X_E", "EL_Chroma_6330A", "MTR_Agilent_34401A")
    for model in models:
        for r in readable_calls(lib, model):
            if r.needs:
                continue
            plan_call(lib, model, r.name, {"channel_number": 1} if r.channel else {})


# ----- the time log reaches the readings -----------------------------------------

@pytest.fixture
def registry(tmp_path):
    return default_registry(user_dir=tmp_path / "none")


class Instrument(FakeHandle):
    """A handle that says which arguments its calls take, like the real one."""

    def __init__(self, name, answers, takes_channel, selectable=False):
        super().__init__(name, answers)
        self._takes_channel, self._selectable = takes_channel, selectable

    def call_arguments(self, name):
        return {"channel_number": False} if self._takes_channel else {}

    def supports(self, name):
        return name == "select_channel" and self._selectable


def run(registry, handle, readings):
    p = {"duration_s": 0.03, "sources": [
        {"name": "x", "instrument": handle.name, "interval_s": 0.01, "readings": readings}]}
    runner = run_to_end(Runner(registry.create("time_log", p), {"instruments": [handle]}))
    return runner


def test_a_supply_gets_the_channel_as_an_argument(registry):
    supply = Instrument("psu", {"read_voltage": 12.0, "read_current": 0.5}, takes_channel=True)
    runner = run(registry, supply, [{"name": "v", "call": "read_voltage", "channel": 2},
                                    {"name": "i", "call": "read_current", "channel": 2}])
    assert runner.state is RunState.FINISHED, runner.error
    assert supply.calls[0] == ("read_voltage", {"channel_number": 2})
    assert all(c[0] != "select_channel" for c in supply.calls)


def test_a_multichannel_load_has_its_channel_selected_first(registry):
    load = Instrument("load", {"read_voltage": 5.0, "select_channel": None}, takes_channel=False,
                      selectable=True)
    runner = run(registry, load, [{"name": "v", "call": "read_voltage", "channel": 2}])
    assert runner.state is RunState.FINISHED, runner.error
    assert load.calls[0] == ("select_channel", {"channel_number": 2})
    assert load.calls[1] == ("read_voltage", {})


def test_a_load_with_one_input_is_read_without_arguments(registry):
    load = Instrument("load", {"read_voltage": 5.0, "read_power": 20.0}, takes_channel=False)
    runner = run(registry, load, [{"name": "v", "call": "read_voltage"},
                                  {"name": "p", "call": "read_power"}])
    assert runner.state is RunState.FINISHED, runner.error
    assert load.calls[0] == ("read_voltage", {}) and load.calls[1] == ("read_power", {})


def test_an_instrument_without_channels_refuses_a_channel(registry):
    meter = Instrument("dmm", {"read_measurement": 1.0}, takes_channel=False)
    runner = run(registry, meter, [{"name": "v", "call": "read_measurement", "channel": 1}])
    assert runner.state is RunState.FAILED
    assert "has no channels" in runner.error["message"] and meter.calls == []


def test_the_channel_of_a_reading_is_checked(registry):
    for bad in (0, -1, "1", True):
        p = {"duration_s": 1, "sources": [{"name": "x", "instrument": "a", "interval_s": 1,
             "readings": [{"name": "v", "call": "read_voltage", "channel": bad}]}]}
        problems = registry.create("time_log", p).validate()
        assert any("channel must be an integer" in q for q in problems), (bad, problems)
    with pytest.raises(MeasurementError):
        Runner(registry.create("time_log", {"duration_s": 1, "sources": [
            {"name": "x", "instrument": "a", "interval_s": 1,
             "readings": [{"name": "v", "call": "read_voltage", "channel": 0}]}]}), {}).start()
