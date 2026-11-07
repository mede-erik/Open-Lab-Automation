# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Calls produced by a .was file and their translation per model (needs the real library)."""

import os

import pytest

from ola.call_errors import ValueNotHandledError
from ola.call_planner import plan_call
from ola.library import Library
from ola.was_calls import extract_channel_number, oscilloscope_calls_from_was, parse_voltage_value

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)

WAS = {
    "settings": {"time_per_div": 0.001},
    "channels": [{"channel_id": "CH1", "volt_per_div": "2V", "offset": 0, "coupling": "DC"}],
    "trigger": {"source": "CH1", "level": 1.5, "slope": "RISE", "mode": "NORM"},
}


def test_helpers():
    assert extract_channel_number("CH1") == 1 and extract_channel_number("C4") == 4
    assert extract_channel_number("3") == 3 and extract_channel_number(None) is None
    assert parse_voltage_value("2V") == 2.0 and parse_voltage_value("100mV") == 0.1
    assert parse_voltage_value("0.5") == 0.5 and parse_voltage_value("zzz") is None


def test_calls_from_was_order():
    names = [c for c, _ in oscilloscope_calls_from_was(WAS)]
    assert names == [
        "reset",
        "set_timebase_scale",
        "set_channel_scale",
        "set_channel_offset",
        "set_channel_coupling",
        "set_trigger_source",
        "set_trigger_level",
        "set_trigger_slope",
        "set_trigger_mode",
    ]
    assert "auto_setup" not in names  # the instrument keeps exactly the settings of the file


@pytest.mark.skipif(LIB is None, reason="library not available")
@pytest.mark.parametrize(
    "model,slope,mode",
    [
        ("OSC_Siglent_SDS824X_HD", ":TRIGger:EDGE:SLOPe RISing", ":TRIGger:MODE NORMal"),
        ("OSC_Rigol_DS1054Z", ":TRIGger:EDGe:SLOPe POSitive", ":TRIGger:SWEep NORMal"),
        ("OSC_Tek_MSO54", "TRIGger:A:EDGE:SLOpe RISe", "TRIGger:A:MODE NORMal"),
    ],
)
def test_same_was_every_brand(model, slope, mode):
    lib = Library.load(LIB)
    texts = {}
    for name, args in oscilloscope_calls_from_was(WAS):
        texts[name] = [s["text"] for s in plan_call(lib, model, name, args).steps]
    assert texts["set_trigger_slope"] == [slope]
    assert texts["set_trigger_mode"] == [mode]


@pytest.mark.skipif(LIB is None, reason="library not available")
def test_value_not_handled_per_model():
    lib = Library.load(LIB)
    with pytest.raises(ValueNotHandledError):
        plan_call(
            lib,
            "OSC_Tek_MSO54",
            "set_channel_coupling",
            {"channel_number": 1, "coupling_type": "GND"},
        )
    assert (
        plan_call(
            lib,
            "OSC_Siglent_SDS824X_HD",
            "set_channel_coupling",
            {"channel_number": 1, "coupling_type": "GND"},
        ).steps[0]["text"]
        == ":CHANnel1:COUPling GND"
    )


@pytest.mark.skipif(LIB is None, reason="library not available")
def test_tektronix_multi_command_calls():
    lib = Library.load(LIB)
    assert [s["text"] for s in plan_call(lib, "OSC_Tek_MSO54", "acquire_single").steps] == [
        "ACQuire:STOPAfter SEQuence",
        "ACQuire:STATE RUN",
    ]
    assert [
        s["text"]
        for s in plan_call(lib, "OSC_Tek_MSO54", "set_timebase_delay", {"value": 0.3}).steps
    ] == ["HORizontal:DELay:MODe ON", "HORizontal:DELay:TIMe 0.3"]
    assert [
        s["text"]
        for s in plan_call(
            lib, "OSC_Tek_MSO54", "set_waveform_format", {"format_type": "BYTE"}
        ).steps
    ] == ["DATa:ENCdg RIBinary", "DATa:WIDth 1"]


WAS_CHANNELS = {
    "settings": {"time_per_div": 1e-6},
    "channels": [
        {"channel_id": "CH1", "enabled": True, "volt_per_div": "10V", "probe_attenuation": 10.0},
        {"channel_id": "CH2", "enabled": True, "volt_per_div": "10V", "probe_attenuation": 10.0},
        {"channel_id": "CH3", "enabled": False, "volt_per_div": "1V", "probe_attenuation": 1.0},
    ],
}


def test_channels_are_turned_on_or_off_and_the_probe_is_set_before_the_scale():
    calls = oscilloscope_calls_from_was(WAS_CHANNELS)
    assert [name for name, _ in calls] == [
        "reset",
        "set_timebase_scale",
        "set_channel_state",
        "set_probe_attenuation",
        "set_channel_scale",
        "set_channel_state",
        "set_probe_attenuation",
        "set_channel_scale",
        "set_channel_state",  # CH3 is off: only switched off, its settings are not sent
    ]
    assert calls[2] == ("set_channel_state", {"channel_number": 1, "state": True})
    assert calls[3] == ("set_probe_attenuation", {"channel_number": 1, "value": 10.0})
    assert calls[-1] == ("set_channel_state", {"channel_number": 3, "state": False})


@pytest.mark.skipif(LIB is None, reason="library not available")
def test_channel_state_and_probe_on_the_sds():
    lib = Library.load(LIB)
    texts = [
        [s["text"] for s in plan_call(lib, "OSC_Siglent_SDS824X_HD", name, args).steps][0]
        for name, args in oscilloscope_calls_from_was(WAS_CHANNELS)
    ]
    assert ":CHANnel2:SWITch ON" in texts and ":CHANnel3:SWITch OFF" in texts
    assert ":CHANnel1:PROBe VALue,10" in texts
    assert texts.index(":CHANnel1:PROBe VALue,10") < texts.index(":CHANnel1:SCALe 10")
