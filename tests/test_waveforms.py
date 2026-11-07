# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The Analog Discovery waveform generator driver, on a stand-in for the ``dwf`` library."""

import os

import pytest

from ola.call_errors import (
    CallNotSupportedError,
    InvalidArgumentError,
    StepFailedError,
    ValueNotHandledError,
)
from ola.drivers import driver_for, waveforms
from ola.drivers.waveforms import DwfApi, DwfError, WaveformsDriver, open_dwf, parse_address
from ola.library import Library

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
needs_model = pytest.mark.skipif(
    LIB is None or "FGEN_Digilent_AnalogDiscovery2" not in (open(LIB).read() if LIB else ""),
    reason="library with the Analog Discovery generator model not available",
)


def put(ref, value):
    """Set the value a C function returns through a pointer (``ctypes.byref``)."""
    ref._obj.value = value


class FakeDll:
    """The C functions of ``dwf`` the driver calls, on a made-up device with two channels."""

    def __init__(self, devices=(("Analog Discovery 2", "SN:210321A1B2C3"),), channels=2):
        self.devices, self.channels = list(devices), channels
        self.calls = []
        self.opened = []
        self.fail = None  # name of a function that fails
        self.error = b"device error"
        self.functions = sum(1 << n for n in (0, 1, 2, 3, 4, 5, 6))  # DC .. noise
        self.amplitude = (0.0, 5.0)
        self.offset = (-5.0, 5.0)

    def _ok(self, name, *args):
        self.calls.append((name,) + tuple(getattr(a, "value", a) for a in args))
        return 0 if self.fail == name else 1

    def FDwfGetLastErrorMsg(self, buffer):
        buffer.value = self.error

    def FDwfEnum(self, flt, count):
        put(count, len(self.devices))
        return self._ok("enum", flt)

    def FDwfEnumDeviceName(self, index, buffer):
        buffer.value = self.devices[index.value][0].encode()
        return 1

    def FDwfEnumSN(self, index, buffer):
        buffer.value = self.devices[index.value][1].encode()
        return 1

    def FDwfDeviceOpen(self, index, handle):
        put(handle, 77)
        self.opened.append(index.value)
        return self._ok("open", index)

    def FDwfDeviceClose(self, handle):
        return self._ok("close", handle)

    def FDwfAnalogOutCount(self, handle, count):
        put(count, self.channels)
        return 1

    def FDwfAnalogOutReset(self, handle, channel):
        return self._ok("reset", channel)

    def FDwfAnalogOutConfigure(self, handle, channel, start):
        return self._ok("configure", channel, start)

    def FDwfAnalogOutNodeEnableSet(self, handle, channel, node, enable):
        return self._ok("enable", channel, node, enable)

    def FDwfAnalogOutNodeFunctionSet(self, handle, channel, node, func):
        return self._ok("function", channel, node, func)

    def FDwfAnalogOutNodeFunctionInfo(self, handle, channel, node, bits):
        put(bits, self.functions)
        return 1

    def FDwfAnalogOutNodeFrequencySet(self, handle, channel, node, hz):
        return self._ok("frequency", channel, node, hz)

    def FDwfAnalogOutNodeAmplitudeSet(self, handle, channel, node, volts):
        return self._ok("amplitude", channel, node, volts)

    def FDwfAnalogOutNodeOffsetSet(self, handle, channel, node, volts):
        return self._ok("offset", channel, node, volts)

    def FDwfAnalogOutNodeAmplitudeInfo(self, handle, channel, node, low, high):
        put(low, self.amplitude[0])
        put(high, self.amplitude[1])
        return 1

    def FDwfAnalogOutNodeOffsetInfo(self, handle, channel, node, low, high):
        put(low, self.offset[0])
        put(high, self.offset[1])
        return 1

    def sent(self, name):
        return [c[1:] for c in self.calls if c[0] == name]


def driver(dll=None):
    dll = dll or FakeDll()
    device = open_dwf("DWF", loader=lambda: dll)
    return WaveformsDriver(device), dll


def test_addresses():
    assert parse_address("DWF") is None and parse_address("dwf") is None
    assert parse_address("DWF::210321A1B2C3") == "210321A1B2C3"
    assert parse_address("DWF::SN:210321A1B2C3") == "210321A1B2C3"
    for bad in ("DWF::", "DWF::a::b", "ASRL3::INSTR", "TCPIP0::1.2.3.4::inst0::INSTR"):
        with pytest.raises(ValueError):
            parse_address(bad)


def test_the_device_is_found_by_its_serial_number():
    dll = FakeDll(devices=[("Analog Discovery 2", "SN:AAA"), ("Analog Discovery 2", "SN:BBB")])
    device = open_dwf("DWF::bbb", loader=lambda: dll)
    assert dll.opened == [1] and device.serial == "BBB" and device.handle == 77
    assert open_dwf("DWF", loader=lambda: dll).serial == "AAA"  # no serial: the first one
    with pytest.raises(DwfError, match="no device with serial number ZZZ.*AAA, BBB"):
        open_dwf("DWF::ZZZ", loader=lambda: dll)
    with pytest.raises(DwfError, match="no Digilent device"):
        open_dwf("DWF", loader=lambda: FakeDll(devices=[]))


def test_a_failing_library_call_gives_the_message_of_the_library():
    dll = FakeDll()
    dll.fail = "open"
    dll.error = b"Device already opened."
    with pytest.raises(DwfError, match="Device already opened"):
        open_dwf("DWF", loader=lambda: dll)


def test_closing_closes_the_device_once():
    dll = FakeDll()
    device = open_dwf("DWF", loader=lambda: dll)
    device.close()
    device.close()
    assert dll.sent("close") == [(77,)]


def test_identification_has_the_usual_four_fields_without_a_firmware():
    drv, _ = driver()
    assert drv.call("identification_query", {}) == "Digilent,Analog Discovery 2,210321A1B2C3,"


def test_output_on_enables_the_carrier_and_starts_the_channel():
    drv, dll = driver()
    drv.call("set_output_state", {"channel_number": 2, "state": True})
    assert dll.sent("enable") == [(1, 0, 1)]  # channel index 1, carrier node, on
    assert dll.sent("configure") == [(1, 1)]


def test_output_off_stops_the_channel_then_disables_the_carrier():
    drv, dll = driver()
    drv.call("set_output_state", {"channel_number": 1, "state": False})
    assert [c[0] for c in dll.calls if c[0] in ("configure", "enable")] == ["configure", "enable"]
    assert dll.sent("configure") == [(0, 0)] and dll.sent("enable") == [(0, 0, 0)]


def test_the_first_channel_is_used_when_none_is_given():
    drv, dll = driver()
    drv.call("set_frequency", {"value": 1000.0})
    assert dll.sent("frequency") == [(0, 0, 1000.0)]


def test_a_channel_the_device_does_not_have_is_an_invalid_argument():
    drv, _ = driver()
    for number in (0, 3):
        with pytest.raises(InvalidArgumentError, match="2 waveform channel"):
            drv.call("set_frequency", {"channel_number": number, "value": 10.0})


def test_amplitude_is_sent_as_half_of_the_peak_to_peak_value():
    drv, dll = driver()
    drv.call("set_amplitude", {"channel_number": 1, "value": 2.0})
    assert dll.sent("amplitude") == [(0, 0, 1.0)]  # to be verified on a device


def test_an_amplitude_or_offset_the_device_cannot_give_is_not_handled_by_the_model():
    drv, dll = driver()
    with pytest.raises(ValueNotHandledError, match="12 Vpp.*0 to 10 Vpp"):
        drv.call("set_amplitude", {"value": 12.0})
    with pytest.raises(ValueNotHandledError, match="offset of 6 V"):
        drv.call("set_offset", {"value": 6.0})
    assert dll.sent("amplitude") == [] and dll.sent("offset") == []
    drv.call("set_offset", {"value": -1.5})
    assert dll.sent("offset") == [(0, 0, -1.5)]


@pytest.mark.parametrize(
    "shape, func",
    [("SINE", 1), ("SQUARE", 2), ("TRIANGLE", 3), ("RAMP", 4), ("NOISE", 6), ("DC", 0)],
)
def test_waveforms(shape, func):
    drv, dll = driver()
    drv.call("set_waveform_shape", {"channel_number": 1, "shape": shape})
    assert dll.sent("function") == [(0, 0, func)]


def test_pulse_and_arbitrary_are_not_handled_and_neither_is_a_function_the_device_lacks():
    drv, dll = driver()
    for shape in ("PULSE", "ARBITRARY"):
        with pytest.raises(ValueNotHandledError, match="not handled by this model"):
            drv.call("set_waveform_shape", {"shape": shape})
    dll.functions = 1 << 1  # only a sine
    with pytest.raises(ValueNotHandledError, match="does not give a SQUARE"):
        drv.call("set_waveform_shape", {"shape": "SQUARE"})
    assert dll.sent("function") == []


def test_reset_resets_every_channel():
    drv, dll = driver()
    drv.call("reset", {})
    assert dll.sent("reset") == [(-1,)]


def test_a_refusal_of_the_library_is_a_failed_step_with_its_message():
    drv, dll = driver()
    dll.fail = "frequency"
    dll.error = b"Invalid parameter 3"
    with pytest.raises(StepFailedError, match="Invalid parameter 3"):
        drv.call("set_frequency", {"value": 1e12})


def test_a_call_the_driver_does_not_have_is_not_supported():
    drv, _ = driver()
    with pytest.raises(CallNotSupportedError):
        drv.call("set_remote", {})


def test_the_library_names_missing_means_a_clear_error(monkeypatch):
    def nothing(name):
        raise OSError("not found")

    monkeypatch.setattr(waveforms.ctypes.cdll, "LoadLibrary", nothing)
    with pytest.raises(DwfError, match="install Digilent WaveForms"):
        waveforms.load_library()


def test_the_wrapper_passes_c_values_to_the_library():
    """DwfApi gives the library C types (the fake reads their values)."""
    dll = FakeDll()
    api = DwfApi(dll)
    assert api.enumerate() == [{"name": "Analog Discovery 2", "serial": "SN:210321A1B2C3"}]
    api.set_frequency(5, 1, 2500.0)
    assert dll.sent("frequency") == [(1, 0, 2500.0)]


@needs_model
def test_the_library_model_gives_this_driver_and_runs_the_logical_calls():
    library = Library.load(LIB)
    dll = FakeDll()
    device = open_dwf("DWF::210321A1B2C3", loader=lambda: dll)
    built = driver_for(library, "FGEN_Digilent_AnalogDiscovery2", device)
    assert isinstance(built, WaveformsDriver)

    from ola.instrument import Instrument
    from ola.instrument_handle import InstrumentHandle

    handle = InstrumentHandle(
        "GEN", library, "FGEN_Digilent_AnalogDiscovery2", Instrument("GEN", device, built)
    )
    handle.call("set_output_state", channel_number=1, state=False)
    handle.call("set_waveform_shape", channel_number=1, shape="SINE")
    handle.call("set_frequency", channel_number=1, value=1000.0)
    handle.call("set_amplitude", channel_number=1, value=1.0)
    handle.call("set_output_state", channel_number=1, state=True)
    assert [c[0] for c in dll.calls if c[0] not in ("enum", "open")] == [
        "configure",
        "enable",
        "function",
        "frequency",
        "amplitude",
        "enable",
        "configure",
    ]
    assert dll.sent("amplitude") == [(0, 0, 0.5)]
    with pytest.raises(ValueNotHandledError):
        handle.call("set_waveform_shape", channel_number=1, shape="PULSE")
    with pytest.raises(InvalidArgumentError):  # the schema refuses a negative frequency
        handle.call("set_frequency", channel_number=1, value=-1.0)
    assert handle.call("identification_query").startswith("Digilent,Analog Discovery 2,")
    assert not handle.supports("set_remote")


@needs_model
def test_a_project_opens_the_device_by_its_dwf_address(tmp_path, monkeypatch):
    """ProjectConnector with the default opener: a DWF address does not go through VISA."""
    import json

    from ola.connection import ProjectConnector

    dll = FakeDll()
    monkeypatch.setattr(waveforms, "load_library", lambda: dll)
    inst = tmp_path / "lab.inst"
    inst.write_text(
        json.dumps(
            {
                "instruments": [
                    {
                        "instrument_type": "function_generator",
                        "instance_name": "GEN",
                        "model_id": "FGEN_Digilent_AnalogDiscovery2",
                        "visa_address": "DWF::210321A1B2C3",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    connector = ProjectConnector(Library.load(LIB), lambda: inst)
    handle = connector("GEN")
    handle.call("set_frequency", channel_number=2, value=50.0)
    assert dll.opened == [0] and dll.sent("frequency") == [(1, 0, 50.0)]
    connector("GEN")  # the open connection is reused
    assert dll.opened == [0]
    connector.close()
    assert dll.sent("close") == [(77,)]
