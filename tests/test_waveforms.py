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


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch):
    """No waiting between status reads, and no device left open by another test."""
    monkeypatch.setattr(waveforms, "POLL_S", 0)
    waveforms._OPEN.clear()
    yield
    waveforms._OPEN.clear()


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

    # ---- AnalogIn (oscilloscope)
    in_channels = 2
    polls_until_done = 0  # how many status reads before the acquisition is done
    never_done = False
    ain_range = (0.2, 50.0)
    ain_offset = (-25.0, 25.0)
    ain_buffer = (16, 8192)
    ain_frequency = (1.0, 100e6)

    def _init_in(self):
        if not hasattr(self, "_in"):
            self._in = {
                "polls": 0,
                "running": False,
                "frequency": 100e6,
                "buffer": 8192,
                "range": {0: 5.0, 1: 5.0},
                "offset": {0: 0.0, 1: 0.0},
                "auto": False,
            }
        return self._in

    def FDwfAnalogInChannelCount(self, handle, count):
        put(count, self.in_channels)
        return 1

    def FDwfAnalogInReset(self, handle):
        return self._ok("in_reset")

    def FDwfAnalogInConfigure(self, handle, reconfigure, start):
        st = self._init_in()
        st["running"], st["polls"] = bool(start.value), 0
        return self._ok("in_configure", reconfigure, start)

    def FDwfAnalogInStatus(self, handle, read_data, state):
        st = self._init_in()
        self.calls.append(("in_status", read_data.value))
        if not st["running"]:
            put(state, 0)  # ready
        elif self.never_done or st["polls"] < self.polls_until_done:
            st["polls"] += 1
            put(state, 3)  # triggered / running
        else:
            put(state, 2)  # done
        return 1

    def FDwfAnalogInStatusAutoTriggered(self, handle, flag):
        put(flag, 1 if self._init_in()["auto"] else 0)
        return 1

    def FDwfAnalogInStatusData(self, handle, channel, buffer, count):
        self.calls.append(("in_data", channel.value, count.value))
        for i in range(count.value):
            buffer[i] = channel.value * 100.0 + i  # channel 0: 0, 1, 2...  channel 1: 100, 101...
        return 1

    def FDwfAnalogInFrequencyInfo(self, handle, low, high):
        put(low, self.ain_frequency[0])
        put(high, self.ain_frequency[1])
        return 1

    def FDwfAnalogInFrequencySet(self, handle, hz):
        self._init_in()["frequency"] = hz.value
        return self._ok("in_frequency", hz)

    def FDwfAnalogInFrequencyGet(self, handle, hz):
        put(hz, self._init_in()["frequency"])
        return 1

    def FDwfAnalogInBitsInfo(self, handle, bits):
        put(bits, 14)
        return 1

    def FDwfAnalogInBufferSizeInfo(self, handle, low, high):
        put(low, self.ain_buffer[0])
        put(high, self.ain_buffer[1])
        return 1

    def FDwfAnalogInBufferSizeSet(self, handle, size):
        self._init_in()["buffer"] = size.value
        return self._ok("in_buffer", size)

    def FDwfAnalogInBufferSizeGet(self, handle, size):
        put(size, self._init_in()["buffer"])
        return 1

    def FDwfAnalogInChannelEnableSet(self, handle, channel, enable):
        return self._ok("in_enable", channel, enable)

    def FDwfAnalogInChannelRangeInfo(self, handle, low, high, steps):
        put(low, self.ain_range[0])
        put(high, self.ain_range[1])
        put(steps, 100)
        return 1

    def FDwfAnalogInChannelRangeSet(self, handle, channel, volts):
        # like the device: the first range that is not smaller; the real top one is 1.2 x the one
        # RangeInfo reports (60.36 against 50 V on an Analog Discovery 2)
        self._init_in()["range"][channel.value] = min(volts.value, self.ain_range[1] * 1.2)
        return self._ok("in_range", channel, volts)

    def FDwfAnalogInChannelRangeGet(self, handle, channel, volts):
        put(volts, self._init_in()["range"][channel.value])
        return 1

    def FDwfAnalogInChannelOffsetInfo(self, handle, low, high, steps):
        put(low, self.ain_offset[0])
        put(high, self.ain_offset[1])
        put(steps, 100)
        return 1

    def FDwfAnalogInChannelOffsetSet(self, handle, channel, volts):
        self._init_in()["offset"][channel.value] = volts.value
        return self._ok("in_offset", channel, volts)

    def FDwfAnalogInChannelOffsetGet(self, handle, channel, volts):
        put(volts, self._init_in()["offset"][channel.value])
        return 1

    def FDwfAnalogInChannelAttenuationSet(self, handle, channel, factor):
        return self._ok("in_attenuation", channel, factor)

    def FDwfAnalogInTriggerSourceSet(self, handle, source):
        return self._ok("in_trigger_source", source)

    def FDwfAnalogInTriggerChannelSet(self, handle, channel):
        return self._ok("in_trigger_channel", channel)

    def FDwfAnalogInTriggerLevelSet(self, handle, volts):
        return self._ok("in_trigger_level", volts)

    def FDwfAnalogInTriggerConditionSet(self, handle, condition):
        return self._ok("in_trigger_condition", condition)

    def FDwfAnalogInTriggerAutoTimeoutSet(self, handle, seconds):
        return self._ok("in_trigger_timeout", seconds)

    def FDwfAnalogInTriggerHoldOffSet(self, handle, seconds):
        return self._ok("in_trigger_holdoff", seconds)

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


def test_without_a_channel_the_configured_channels_start_together():
    """Started one call after the other, two channels have a random phase between them."""
    drv, dll = driver()
    drv.call("set_frequency", {"channel_number": 1, "value": 1000.0})
    drv.call("set_frequency", {"channel_number": 2, "value": 1000.0})
    drv.call("set_output_state", {"state": True})
    assert dll.sent("enable") == [(0, 0, 1), (1, 0, 1)]
    assert dll.sent("configure") == [(-1, 1)]  # one start for the whole generator
    drv.call("set_output_state", {"state": False})
    assert dll.sent("configure") == [(-1, 1), (-1, 0)]
    assert dll.sent("enable")[2:] == [(0, 0, 0), (1, 0, 0)]


def test_a_channel_that_was_not_configured_is_not_started_by_the_group_call():
    drv, dll = driver()
    drv.call("set_frequency", {"channel_number": 1, "value": 1000.0})
    drv.call("set_output_state", {"state": True})
    assert dll.sent("enable") == [(0, 0, 1)]  # W2 keeps the default signal off


def test_without_a_channel_and_nothing_configured_the_first_channel_is_used():
    drv, dll = driver()
    drv.call("set_output_state", {"state": True})
    assert dll.sent("enable") == [(0, 0, 1)] and dll.sent("configure") == [(-1, 1)]


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


# ====================================================================== oscilloscope
def scope(dll=None):
    dll = dll or FakeDll()
    return WaveformsDriver(open_dwf("DWF", loader=lambda: dll)), dll


def test_channels_are_enabled_and_the_scale_is_a_range_of_ten_divisions():
    drv, dll = scope()
    drv.call("set_channel_state", {"channel_number": 2, "state": True})
    drv.call("set_channel_scale", {"channel_number": 2, "value": 0.5})
    drv.call("set_channel_offset", {"channel_number": 1, "value": -1.0})
    drv.call("set_probe_attenuation", {"channel_number": 1, "value": 10.0})
    assert dll.sent("in_enable") == [(1, 1)]
    assert dll.sent("in_range") == [(1, 5.0)]  # 0.5 V/div x 10 divisions
    assert dll.sent("in_offset") == [(0, -1.0)] and dll.sent("in_attenuation") == [(0, 10.0)]
    assert drv.call("query_channel_scale", {"channel_number": 2}) == 0.5
    assert drv.call("query_channel_offset", {"channel_number": 1}) == -1.0


def test_a_range_offset_or_depth_the_device_cannot_give_is_not_handled():
    drv, dll = scope()
    with pytest.raises(ValueNotHandledError, match="V/div is outside"):
        drv.call("set_channel_scale", {"channel_number": 1, "value": 10.0})
    with pytest.raises(ValueNotHandledError, match="offset of 30 V"):
        drv.call("set_channel_offset", {"channel_number": 1, "value": 30.0})
    with pytest.raises(ValueNotHandledError, match="16 to 8192 points"):
        drv.call("set_acquisition_depth", {"depth": 100000})
    # the range was tried and put back as it was; nothing was set for the depth
    assert dll.sent("in_range")[-1] == (0, 5.0) and dll.sent("in_buffer") == []
    drv.call("set_acquisition_depth", {"depth": 4096})
    assert dll.sent("in_buffer") == [(4096,)]
    with pytest.raises(InvalidArgumentError, match="2 oscilloscope channel"):
        drv.call("set_channel_state", {"channel_number": 3, "state": True})


def test_only_dc_coupling_exists():
    drv, _ = scope()
    drv.call("set_channel_coupling", {"channel_number": 1, "coupling_type": "DC"})
    for coupling in ("AC", "GND"):
        with pytest.raises(ValueNotHandledError, match="inputs are DC coupled"):
            drv.call("set_channel_coupling", {"channel_number": 1, "coupling_type": coupling})


def test_the_sample_frequency_follows_the_timebase_and_the_depth():
    drv, dll = scope()
    drv.call("set_acquisition_depth", {"depth": 8000})
    drv.call("set_timebase_scale", {"value": 1e-3})  # 10 ms record: 800 kSa/s
    drv.call("run_acquisition", {})
    assert dll.sent("in_frequency") == [(800000.0,)]
    assert dll.sent("in_configure") == [(1, 1)]  # reconfigure and start
    assert drv.call("query_sample_rate", {}) == 800000.0
    drv.call("set_timebase_scale", {"value": 1e-9})  # more than the ADC does: the maximum
    drv.call("run_acquisition", {})
    assert dll.sent("in_frequency")[-1] == (100e6,)


def test_a_capture_is_read_for_every_enabled_channel_at_once():
    """The second channel comes from the same capture, without a new acquisition."""
    drv, dll = scope()
    drv.call("set_channel_state", {"channel_number": 1, "state": True})
    drv.call("set_channel_state", {"channel_number": 2, "state": True})
    drv.call("set_acquisition_depth", {"depth": 1000})
    drv.call("set_timebase_scale", {"value": 1e-4})
    drv.call("run_acquisition", {})
    drv.call("stop_acquisition", {})
    first = drv.call("read_waveform", {"channel_number": 1})
    second = drv.call("read_waveform", {"channel_number": 2})
    assert dll.sent("in_configure") == [(1, 1)]  # one acquisition only
    assert [c for c in dll.calls if c[0] == "in_data"] == [
        ("in_data", 0, 1000),
        ("in_data", 1, 1000),
    ]
    assert first["points"] == 1000 and list(first["voltage"][:3]) == [0.0, 1.0, 2.0]
    assert list(second["voltage"][:2]) == [100.0, 101.0]
    assert first["sample_interval"] == pytest.approx(1e-6)  # 1000 points in 10 x 0.1 ms
    # time is relative to the middle of the buffer (where the trigger is by default)
    assert first["time"][500] == pytest.approx(0.0) and first["time"][0] == pytest.approx(-5e-4)
    assert set(first) >= {
        "time",
        "voltage",
        "points",
        "sample_interval",
        "vertical_gain",
        "vertical_offset",
        "trigger_delay",
        "timebase",
    }


def test_a_waveform_is_read_in_blocks():
    drv, _ = scope()
    drv.call("set_channel_state", {"channel_number": 1, "state": True})
    drv.call("set_acquisition_depth", {"depth": 1000})
    block = drv.call("read_waveform", {"channel_number": 1, "start": 990, "points": 100})
    assert block["points"] == 10 and block["voltage"][0] == 990.0  # up to the end of the memory
    assert drv.call("read_waveform", {"channel_number": 1, "start": 2000})["points"] == 0
    assert drv.call("query_waveform_max_points", {}) == 8192


def test_reading_without_an_acquisition_makes_one():
    drv, dll = scope()
    drv.call("set_channel_state", {"channel_number": 1, "state": True})
    assert drv.call("read_waveform", {"channel_number": 1})["points"] == 8192
    assert dll.sent("in_configure") == [(1, 1)]


def test_a_channel_that_was_not_enabled_is_not_in_the_capture():
    drv, _ = scope()
    drv.call("set_channel_state", {"channel_number": 1, "state": True})
    drv.call("run_acquisition", {})
    with pytest.raises(InvalidArgumentError, match="channel 2 was not enabled"):
        drv.call("read_waveform", {"channel_number": 2})


def test_stopping_waits_for_a_running_acquisition_to_be_done():
    drv, dll = scope()
    dll.polls_until_done = 5
    drv.call("set_channel_state", {"channel_number": 1, "state": True})
    drv.call("run_acquisition", {})
    drv.call("stop_acquisition", {})
    assert len([c for c in dll.calls if c[0] == "in_status"]) == 6
    assert dll.sent("in_data") == [(0, 8192)]
    drv.call("stop_acquisition", {})  # nothing is running any more: nothing is done
    assert len(dll.sent("in_data")) == 1


def test_an_acquisition_that_never_finishes_is_given_up_with_a_clear_message(monkeypatch):
    drv, dll = scope()
    dll.never_done = True
    monkeypatch.setattr(waveforms, "FINISH_MARGIN_S", -1.0)  # the deadline has already passed
    drv.call("run_acquisition", {})
    with pytest.raises(StepFailedError, match="did not finish"):
        drv.call("stop_acquisition", {})
    assert dll.sent("in_configure")[-1] == (0, 0)  # and it was stopped


def test_the_trigger():
    drv, dll = scope()
    drv.call("set_trigger_source", {"channel_number": 2})
    drv.call("set_trigger_level", {"value": 0.5})
    drv.call("set_trigger_slope", {"slope": "FALL"})
    drv.call("set_trigger_holdoff", {"value": 1e-3})
    drv.call("set_trigger_mode", {"mode": "AUTO"})
    assert dll.sent("in_trigger_source") == [(2,)] and dll.sent("in_trigger_channel") == [(1,)]
    assert dll.sent("in_trigger_level") == [(0.5,)] and dll.sent("in_trigger_condition") == [(1,)]
    assert dll.sent("in_trigger_holdoff") == [(1e-3,)]
    assert dll.sent("in_trigger_timeout") == [(1.0,)]
    drv.call("set_trigger_mode", {"mode": "NORMAL"})
    assert dll.sent("in_trigger_timeout")[-1] == (0.0,)
    with pytest.raises(ValueNotHandledError, match="slope EITHER"):
        drv.call("set_trigger_slope", {"slope": "EITHER"})


def test_the_trigger_status():
    drv, dll = scope()
    assert drv.call("query_trigger_status", {}) == "READY"
    drv.call("run_acquisition", {})
    dll.polls_until_done = 1
    assert drv.call("query_trigger_status", {}) in ("TRIGGERED", "STOPPED")
    dll.never_done = False
    dll.polls_until_done = 0
    assert drv.call("query_trigger_status", {}) == "STOPPED"
    dll._init_in()["auto"] = True
    assert drv.call("query_trigger_status", {}) == "AUTO"


def test_scope_reset_does_not_touch_the_generator():
    drv, dll = scope()
    drv.call("set_channel_state", {"channel_number": 1, "state": True})
    drv.call("scope_reset", {})
    assert dll.sent("in_reset") == [()] and dll.sent("reset") == []  # no AnalogOut reset
    drv.call("run_acquisition", {})
    assert drv.call("read_waveform", {"channel_number": 1, "points": 4})["points"] == 4


def test_a_generator_and_a_scope_of_the_same_device_share_the_open_device():
    dll = FakeDll()
    generator = open_dwf("DWF::210321A1B2C3", loader=lambda: dll)
    oscilloscope = open_dwf("DWF", loader=lambda: dll)  # the first device is the same one
    assert dll.opened == [0] and generator.handle == oscilloscope.handle
    generator.close()
    assert dll.sent("close") == []  # the scope still uses it
    oscilloscope.close()
    oscilloscope.close()
    assert dll.sent("close") == [(77,)]
    open_dwf("DWF", loader=lambda: dll)  # closed: a new open
    assert dll.opened == [0, 0]


@needs_model
def test_the_library_scope_model_runs_the_calls_of_the_bode_measurement(tmp_path, monkeypatch):
    """The calls the Bode measurement sends to its scope, through the library, a project and the
    whole-memory read; the generator of the same device in the same project."""
    import json

    from ola.connection import ProjectConnector

    if "OSC_Digilent_AnalogDiscovery2" not in (open(LIB).read() if LIB else ""):
        pytest.skip("library without the Analog Discovery oscilloscope model")
    dll = FakeDll()
    monkeypatch.setattr(waveforms, "load_library", lambda: dll)
    inst = tmp_path / "lab.inst"
    inst.write_text(
        json.dumps(
            {
                "instruments": [
                    {
                        "instrument_type": "oscilloscope",
                        "instance_name": "OSC",
                        "model_id": "OSC_Digilent_AnalogDiscovery2",
                        "visa_address": "DWF::210321A1B2C3",
                    },
                    {
                        "instrument_type": "function_generator",
                        "instance_name": "GEN",
                        "model_id": "FGEN_Digilent_AnalogDiscovery2",
                        "visa_address": "DWF::210321A1B2C3",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    connector = ProjectConnector(Library.load(LIB), lambda: inst)
    scope_handle, gen = connector("OSC"), connector("GEN")
    assert dll.opened == [0]  # one device, two instruments
    for channel in (1, 2):
        scope_handle.call("set_channel_state", channel_number=channel, state=True)
        scope_handle.call("set_probe_attenuation", channel_number=channel, value=1.0)
        scope_handle.call("set_channel_coupling", channel_number=channel, coupling_type="DC")
        scope_handle.call("set_channel_scale", channel_number=channel, value=0.1)
    scope_handle.call("set_timebase_scale", value=1e-3)
    scope_handle.call("set_acquisition_depth", depth=2000)
    gen.call("set_frequency", channel_number=1, value=1000.0)
    gen.call("set_output_state", channel_number=1, state=True)
    scope_handle.call("run_acquisition")
    a = scope_handle.read_waveform_full(1, bits=8, stop=True)
    b = scope_handle.read_waveform_full(2, bits=8, stop=False)  # the same capture
    assert (
        a["points"] == b["points"] == 2000 and a["voltage"][1] == 1.0 and b["voltage"][0] == 100.0
    )
    assert len(dll.sent("in_configure")) == 1  # one acquisition for both channels
    # what the AD2 does not have is not supported, not silently ignored
    with pytest.raises(CallNotSupportedError, match="no equivalent on the Analog Discovery"):
        scope_handle.call("set_channel_bandwidth_limit", channel_number=1, bandwidth=20e6)
    with pytest.raises(ValueNotHandledError):
        scope_handle.call("set_channel_coupling", channel_number=1, coupling_type="AC")
    assert scope_handle.call("query_trigger_status") in (
        "STOPPED",
        "READY",
        "AUTO",
        "ARMED",
        "TRIGGERED",
    )
    connector.close()
    assert dll.sent("close") == [(77,)]


@pytest.mark.parametrize(
    "call",
    [
        "operation_complete_query",
        "auto_setup",
        "force_trigger",
        "set_timebase_delay",
        "set_channel_bandwidth_limit",
        "set_acquisition_type",
        "set_waveform_source",
        "set_waveform_format",
        "query_waveform_preamble",
        "query_waveform_data",
    ],
)
def test_the_mandatory_calls_the_device_has_no_equivalent_for_say_so(call):
    drv, _ = scope()
    with pytest.raises(CallNotSupportedError, match=f"call '{call}' has no equivalent"):
        drv.call(f"unsupported_{call}", {})


def test_the_scale_limits_follow_the_probe_attenuation():
    """Measured on a real Analog Discovery 2: with a x10 probe the library gives at least ten
    times the minimum range, and a smaller request was rounded up silently."""
    drv, dll = scope()  # the fake device gives 0.2 to 50 V of range, 0.02 to 5 V/div
    drv.call("set_probe_attenuation", {"channel_number": 1, "value": 10.0})
    with pytest.raises(ValueNotHandledError, match=r"with a x10 probe \(at least 0.2 V/div\)"):
        drv.call("set_channel_scale", {"channel_number": 1, "value": 0.1})
    drv.call("set_channel_scale", {"channel_number": 1, "value": 0.5})  # 5 V range at the tip
    assert dll.sent("in_range") == [(0, 5.0)]
    drv.call("set_channel_scale", {"channel_number": 2, "value": 0.05})  # channel 2 has no probe
    # the real top range is above what RangeInfo says (60 against 50 V): 6 V/div is served,
    # 7 V/div is not, and the range is put back as it was
    drv.call("set_channel_scale", {"channel_number": 2, "value": 6.0})
    with pytest.raises(ValueNotHandledError, match=r"at most 6 V/div"):
        drv.call("set_channel_scale", {"channel_number": 2, "value": 7.0})
    assert dll.sent("in_range")[-1] == (1, 60.0)
    drv.call("set_probe_attenuation", {"channel_number": 1, "value": 1.0})
    drv.call("set_channel_scale", {"channel_number": 1, "value": 0.1})  # fine without the probe
    with pytest.raises(ValueNotHandledError):
        drv.call("set_channel_scale", {"channel_number": 1, "value": 0.01})


def test_a_scope_reset_forgets_the_probe_attenuation():
    drv, _ = scope()
    drv.call("set_probe_attenuation", {"channel_number": 1, "value": 10.0})
    drv.call("scope_reset", {})
    drv.call("set_channel_scale", {"channel_number": 1, "value": 0.05})  # allowed without a probe
