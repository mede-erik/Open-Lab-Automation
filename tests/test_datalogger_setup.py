# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import os

import pytest

from ola.call_planner import plan_call
from ola.datalogger_setup import (
    DataloggerSetupError,
    channel_number,
    datalogger_calls,
    scan_order,
    signature,
)
from ola.library import Library

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)


def ch(name, number, meas="VOLT:DC", **extra):
    return {"name": name, "channel_id": str(number), "meas_type": meas, "enabled": True, **extra}


def test_channel_number_forms():
    assert channel_number({"channel_id": "103"}) == 103
    assert channel_number({"name": "CH3", "slot_number": 2}) == 203
    with pytest.raises(DataloggerSetupError):
        channel_number({"name": "battery"})


def test_groups_by_function_and_settings_then_scan_list():
    channels = [
        ch("a", 103),
        ch("b", 101),
        ch("c", 102, "VOLT:AC"),
        ch("d", 105, "DC_V", range=10),
        {**ch("off", 104), "enabled": False},
    ]
    assert datalogger_calls(channels) == [
        ("configure_dc_voltage", {"range": "AUTO", "resolution": "DEF", "channels": "101,103"}),
        ("configure_ac_voltage", {"range": "AUTO", "resolution": "DEF", "channels": "102"}),
        ("configure_dc_voltage", {"range": 10, "resolution": "DEF", "channels": "105"}),
        ("select_channels", {"channels": "101,102,103,105"}),
    ]
    assert [c["name"] for c in scan_order(channels)] == ["b", "c", "a", "d"]


def test_temperature_needs_probe_and_sensor():
    with pytest.raises(DataloggerSetupError):
        datalogger_calls([ch("t", 101, "TEMP")])
    calls = datalogger_calls([ch("t", 101, "TEMP", probe_type="TCouple", sensor_type="K")])
    assert calls[0] == (
        "configure_temperature",
        {"probe_type": "TCouple", "type": "K", "resolution": "DEF", "channels": "101"},
    )


def test_unknown_type_and_nothing_enabled():
    with pytest.raises(DataloggerSetupError):
        datalogger_calls([ch("x", 101, "WATT")])
    assert datalogger_calls([{**ch("x", 101), "enabled": False}]) == []


def test_signature_changes_with_the_configuration():
    assert signature([ch("a", 101)]) != signature([ch("a", 101), ch("b", 102)])
    assert signature([ch("a", 101)]) == signature([ch("a", 101)])


@pytest.mark.skipif(LIB is None, reason="library not available")
@pytest.mark.parametrize("model", ["DL_Keysight_34970A", "DL_Keysight_DAQ970A"])
def test_calls_are_known_to_the_datalogger_models(model):
    library = Library.load(LIB)
    resolved = library.resolve_model_id(model) or library.resolve_model_id(model.split("_")[-1])
    assert resolved, "datalogger model not found in the library"
    channels = [ch("a", 101), ch("b", 102, "VOLT:AC"), ch("c", 103, "RES", range=1000)]
    for name, args in datalogger_calls(channels):
        plan = plan_call(library, resolved, name, args)
        assert plan.steps, name
