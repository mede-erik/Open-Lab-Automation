# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""InstrumentHandle: planner + executor + interpretation behind handle.call()."""

import pytest

from ola.call_errors import CallNotSupportedError, InvalidArgumentError
from ola.instrument import Instrument
from ola.instrument_handle import InstrumentHandle
from ola.library import Library
from ola.sim import SimTransport

SCHEMA = {
    "schema_version": 1,
    "category": "power_supplies_series",
    "types": {"bool": {"kind": "bool"}},
    "calls": {
        "set_voltage": {
            "requirement": "mandatory",
            "kind": "set",
            "args": {
                "channel_number": {"type": "int", "min": 1, "required": False},
                "value": {"type": "float"},
            },
        },
        "read_voltage": {
            "requirement": "mandatory",
            "kind": "query",
            "args": {"channel_number": {"type": "int", "min": 1, "required": False}},
            "result": {"type": "float"},
        },
        "output_state_query": {
            "requirement": "mandatory",
            "kind": "query",
            "result": {"type": "bool"},
        },
    },
}

SERIES = {
    "series_id": "S",
    "common_scpi_commands": {
        "set_voltage": {
            "set": {
                "steps": [
                    {"op": "write", "text": "INST:NSEL {channel_number}"},
                    {"op": "write", "text": "VOLT {value}"},
                ]
            },
            "query": {
                "steps": [
                    {"op": "write", "text": "INST:NSEL {channel_number}"},
                    {"op": "query", "text": "VOLT?", "returns": "float"},
                ]
            },
            "parameters": {"channel_number": {"type": "int"}, "value": {"type": "float"}},
        },
        "read_voltage": {
            "query": {
                "steps": [
                    {"op": "write", "text": "INST:NSEL {channel_number}"},
                    {"op": "query", "text": "MEAS:VOLT?", "returns": "float"},
                ],
                "return_type": "float",
            },
            "parameters": {"channel_number": {"type": "int"}},
        },
        "output_state_query": {
            "query": {
                "syntax": "OUTP?",
                "return_type": "string",
                "bool": {"true": ["1", "ON"], "false": ["0", "OFF"]},
            }
        },
    },
    "models": [{"id": "PSU1"}],
}


def make(responder=None):
    library = Library({"power_supplies_series": [SERIES]}, {"power_supplies_series": SCHEMA})
    sim = SimTransport(responder)
    return InstrumentHandle("psu", library, "PSU1", Instrument("psu", sim)), sim


def test_call_set_sends_all_steps():
    handle, sim = make()
    assert handle.call("set_voltage", channel_number=2, value=5) is None
    assert sim.log == ["INST:NSEL 2", "VOLT 5"]
    assert handle.name == "psu"


def test_call_query_returns_logical_value():
    handle, sim = make(lambda cmd: "3.25" if cmd == "MEAS:VOLT?" else None)
    assert handle.call("read_voltage", channel_number=1) == 3.25
    assert sim.log == ["INST:NSEL 1", "MEAS:VOLT?"]


def test_bool_result():
    handle, _ = make(lambda cmd: "ON" if cmd == "OUTP?" else None)
    assert handle.call("output_state_query") is True


def test_readback_of_a_set_call():
    handle, sim = make(lambda cmd: "5.0" if cmd == "VOLT?" else None)
    assert handle.readback("set_voltage", channel_number=2) == 5.0
    assert sim.log[-1] == "VOLT?"


def test_supports_and_errors():
    handle, _ = make()
    assert handle.supports("set_voltage") and not handle.supports("set_ovp_level")
    with pytest.raises(CallNotSupportedError):
        handle.call("set_ovp_level", value=1)
    with pytest.raises(InvalidArgumentError):
        handle.call("set_voltage", channel_number=1)
