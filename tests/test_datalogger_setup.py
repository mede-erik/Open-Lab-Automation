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


def test_nplc_and_impedance_calls_only_when_supported():
    channels = [ch("a", 101, nplc=20, impedance="10M"), ch("b", 102)]
    names = [n for n, _ in datalogger_calls(channels, supports=lambda c: True)]
    assert "set_voltage_dc_nplc" in names or any("nplc" in n for n in names)
    assert any("impedance" in n for n in names)
    names_off = [n for n, _ in datalogger_calls(channels, supports=lambda c: False)]
    assert not any("nplc" in n or "impedance" in n for n in names_off)


def test_plain_channels_send_no_extra_calls():
    names = [n for n, _ in datalogger_calls([ch("a", 101)], supports=lambda c: True)]
    assert not any("nplc" in n or "impedance" in n for n in names)


def test_an_rtd_sends_its_nominal_resistance_only_when_the_model_has_the_call():
    channels = [ch("t", 101, "TEMP", probe_type="RTD", sensor_type="85", rtd_ohms=1000)]
    calls = datalogger_calls(channels, supports=lambda call: True)
    assert ("set_rtd_resistance", {"ohms": 1000.0, "channels": "101"}) in calls
    without = datalogger_calls(channels, supports=lambda call: call != "set_rtd_resistance")
    assert "set_rtd_resistance" not in [name for name, _ in without]


def test_scan_channels_lists_the_enabled_channels_once_in_channel_order():
    from ola.datalogger_setup import scan_channels

    entry = {
        "channels": [ch("vout", 103), ch("vin", 102, attenuation=10.0)],
        "slots": [{"channels": [ch("vout", 103), ch("off", 105, enabled=False)]}],
    }
    out = scan_channels(entry)
    assert [c["channel_id"] for c in out] == ["102", "103"]
    assert [c["name"] for c in out] == ["vin", "vout"]
    assert out[0]["attenuation"] == 10.0 and all("enabled" not in c for c in out)


def test_scan_channels_gives_different_names_to_different_channels():
    from ola.datalogger_setup import scan_channels

    out = scan_channels({"channels": [ch("v", 101), ch("v", 102), ch("", 103)]})
    names = [c["name"] for c in out]
    assert len(set(names)) == 3 and names[2] == "CH103"
