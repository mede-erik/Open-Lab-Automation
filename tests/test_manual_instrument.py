# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import os
import threading

import pytest

from ola.call_errors import (
    CallNotSupportedError,
    InvalidArgumentError,
    ManualActionCancelledError,
)
from ola.manual_instrument import ManualInstrumentHandle, manual_handle_from_inst
from ola.library import Library

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)

pytestmark = pytest.mark.skipif(LIB is None, reason="library not available")


@pytest.fixture(scope="module")
def library():
    return Library.load(LIB)


class Operator:
    """A stand-in for the person: records the requests and answers OK or Cancel."""

    def __init__(self, answer=True):
        self.answer, self.requests = answer, []

    def __call__(self, request):
        self.requests.append(request)
        return self.answer


def psu(library, operator, **limits):
    return ManualInstrumentHandle(
        "Vin", library, "power_supply", limits or {"max_voltage": 30, "max_current": 5}, operator
    )


def test_set_voltage_asks_the_operator_and_returns_after_ok(library):
    op = Operator()
    assert psu(library, op).call("set_voltage", value=10) is None
    request = op.requests[0]
    assert request.text == "Set 'Vin' 10.0 V" and request.args == {"value": 10.0}
    assert request.key == "manual_set_voltage_prompt"


def test_cancel_raises_call_006(library):
    with pytest.raises(ManualActionCancelledError) as exc:
        psu(library, Operator(False)).call("output_on")
    assert exc.value.code == "CALL-006"


def test_limits_and_schema_are_checked_before_asking(library):
    op = Operator()
    handle = psu(library, op)
    for name, args in (
        ("set_voltage", {"value": 31}),
        ("set_current", {"value": 5.5}),
        ("set_voltage", {"value": -1}),
        ("set_voltage", {}),
    ):
        with pytest.raises(InvalidArgumentError):
            handle.call(name, **args)
    assert op.requests == []


def test_channel_number_is_accepted_and_ignored(library):
    op = Operator()
    psu(library, op).call("set_current", value=1, channel_number=1)
    assert op.requests[0].args == {"value": 1.0}


def test_reading_and_other_calls_are_not_supported(library):
    handle = psu(library, Operator())
    assert handle.supports("set_voltage") and not handle.supports("read_voltage")
    for call in ("read_voltage", "set_ovp_level", "reset"):
        with pytest.raises(CallNotSupportedError):
            handle.call(call)
    with pytest.raises(CallNotSupportedError):
        handle.readback("set_voltage")


def test_electronic_load_calls_and_limits(library):
    op = Operator()
    load = ManualInstrumentHandle(
        "Load",
        library,
        "electronic_load",
        {"max_current": 10, "max_voltage": 80, "max_power": 300},
        op,
    )
    load.call("set_mode", mode="CC")
    load.call("set_current_level", value=2)
    load.call("load_on")
    assert [r.call for r in op.requests] == ["set_mode", "set_current_level", "load_on"]
    assert op.requests[0].text == "Set the mode of 'Load' to CC"
    with pytest.raises(InvalidArgumentError):
        load.call("set_power_level", value=301)
    with pytest.raises(InvalidArgumentError):
        load.call("set_mode", mode="XX")


def test_cancelled_measurement_does_not_ask(library):
    event = threading.Event()
    event.set()
    op = Operator()
    handle = ManualInstrumentHandle("Vin", library, "power_supply", {}, op, event)
    with pytest.raises(ManualActionCancelledError):
        handle.call("output_on")
    assert op.requests == []


def test_from_inst_entry(library):
    inst = {
        "instrument_type": "power_supplies",
        "instance_name": "Vaux",
        "is_manual": True,
        "channels": [{"name": "CH1", "max_voltage": 12, "max_current": 1}],
    }
    handle = manual_handle_from_inst(inst, library, Operator())
    assert handle.name == "Vaux"
    with pytest.raises(InvalidArgumentError):
        handle.call("set_voltage", value=13)


def test_unknown_type_is_refused(library):
    with pytest.raises(CallNotSupportedError):
        ManualInstrumentHandle("x", library, "oscilloscope")
