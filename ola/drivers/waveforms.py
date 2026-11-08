# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Driver of the Digilent Analog Discovery (waveform generator and oscilloscope), through the
WaveForms runtime.

The Analog Discovery is controlled with the ``dwf`` library of the WaveForms SDK (the reference
manual is in ``Instruments_LIB/docs/Digilent``), not with text commands and not through VISA.
This module has three parts:

* ``DwfApi`` wraps the C functions of the library that the AnalogOut instrument needs (ctypes);
  every failure of the library becomes a ``DwfError`` with the message of ``FDwfGetLastErrorMsg``.
* ``DwfDevice`` is the connection the application opens for an address ``DWF`` (the first device
  found) or ``DWF::<serial number>``; ``close`` closes the device.
* ``WaveformsDriver`` implements the logical calls of the function generator category
  (``set_output_state``, ``set_frequency``, ``set_amplitude``, ``set_offset``,
  ``set_waveform_shape``, ``reset``, ``identification_query``) and of the oscilloscope category
  (``set_channel_*``, ``set_timebase_scale``, ``set_acquisition_depth``, ``run_acquisition``,
  ``stop_acquisition``, ``read_waveform``, the trigger calls...). Which of them a library model
  exposes is decided by the model. Channel numbers are 1-based in the logical calls and 0-based in
  the SDK.
* A device is opened **once**: a generator and an oscilloscope of the same address (two instruments
  of the project) share the open device, and it is closed when the last one is closed.

**To verify on a real device** (see ``Instruments_LIB/docs/proposals/function-generator-calls.md``):
the reference manual says the amplitude is "in Volts" and not whether it is the peak or the
peak-to-peak value; the driver sends half of the peak-to-peak value (``PEAK_PER_VPP``). The numeric
constants below (``ENUM_FILTER_ALL``, the carrier node, the ``FUNC_*``, ``STATE_*``,
``TRIGSRC_*`` and ``TRIGCOND_*`` values) are those of ``dwf.h`` / ``dwfconstants.py`` of the SDK
and are not in the reference manual. The oscilloscope has no divisions in the SDK: the range is
``VERTICAL_DIVISIONS`` times the volts per division and the record is ``HORIZONTAL_DIVISIONS``
times the time per division (conventions of this driver).
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from array import array
from typing import Any, Callable, Dict, List, Optional

from ..call_errors import (
    InvalidArgumentError,
    StepFailedError,
    ValueNotHandledError,
)

log = logging.getLogger(__name__)

ENUM_FILTER_ALL = 0  # enumfilterAll
NODE_CARRIER = 0  # AnalogOutNodeCarrier
# FUNC values of dwf.h; the logical shapes that map to one (PULSE and ARBITRARY are not handled)
FUNC_DC, FUNC_SINE, FUNC_SQUARE, FUNC_TRIANGLE = 0, 1, 2, 3
FUNC_RAMP_UP, FUNC_RAMP_DOWN, FUNC_NOISE = 4, 5, 6
SHAPES = {
    "SINE": FUNC_SINE,
    "SQUARE": FUNC_SQUARE,
    "TRIANGLE": FUNC_TRIANGLE,
    "RAMP": FUNC_RAMP_UP,
    "NOISE": FUNC_NOISE,
    "DC": FUNC_DC,
}
PEAK_PER_VPP = 0.5  # the amplitude sent to the device per volt peak-to-peak asked (see above)

# oscilloscope (AnalogIn): values of dwf.h, not in the reference manual
STATE_READY, STATE_ARMED, STATE_DONE, STATE_TRIGGERED = 0, 1, 2, 3
STATE_CONFIG, STATE_PREFILL, STATE_WAIT = 4, 5, 7
TRIGSRC_NONE, TRIGSRC_DETECTOR_ANALOG_IN = 0, 2
TRIGCOND_RISING, TRIGCOND_FALLING = 0, 1
VERTICAL_DIVISIONS = 10  # range = volts per division x this
HORIZONTAL_DIVISIONS = 10  # record = time per division x this
AUTO_TRIGGER_TIMEOUT_S = 1.0  # the trigger mode AUTO
POLL_S = 0.005  # how often a running acquisition is looked at
FINISH_MARGIN_S = 2.0  # waited for an acquisition on top of its record and its auto-trigger time


class DwfError(Exception):
    """A function of the WaveForms library failed (the message is the one of the library)."""


def _library_names() -> List[str]:
    if sys.platform.startswith("win"):
        return ["dwf.dll", "dwf"]
    if sys.platform == "darwin":
        return ["/Library/Frameworks/dwf.framework/dwf", "dwf"]
    return ["libdwf.so", "dwf"]


def load_library() -> Any:
    """The ``dwf`` library of the WaveForms runtime. ``DwfError`` with what to install if it is
    not there."""
    last: Optional[Exception] = None
    for name in _library_names():
        try:
            return ctypes.cdll.LoadLibrary(name)
        except OSError as exc:
            last = exc
    raise DwfError(
        "the WaveForms runtime (the dwf library) is not installed: install Digilent WaveForms "
        f"from digilent.com ({last})"
    )


class DwfApi:
    """The functions of the ``dwf`` library the AnalogOut instrument needs, with Python values.

    ``dll`` is the loaded library (or an object with the same C functions, for the tests)."""

    def __init__(self, dll: Any):
        self.dll = dll

    # ----- errors -------------------------------------------------------------------------
    def _message(self) -> str:
        buffer = ctypes.create_string_buffer(512)
        self.dll.FDwfGetLastErrorMsg(buffer)
        return buffer.value.decode("ascii", errors="replace").strip() or "unknown error"

    def _check(self, ok: Any, what: str) -> None:
        if not ok:
            raise DwfError(f"{what}: {self._message()}")

    # ----- devices ------------------------------------------------------------------------
    def enumerate(self) -> List[Dict[str, str]]:
        """The connected devices: ``[{"name": ..., "serial": ...}]`` (index = position)."""
        count = ctypes.c_int()
        self._check(self.dll.FDwfEnum(ctypes.c_int(ENUM_FILTER_ALL), ctypes.byref(count)), "enum")
        devices = []
        for index in range(count.value):
            name, serial = ctypes.create_string_buffer(32), ctypes.create_string_buffer(32)
            self.dll.FDwfEnumDeviceName(ctypes.c_int(index), name)
            self.dll.FDwfEnumSN(ctypes.c_int(index), serial)
            devices.append(
                {
                    "name": name.value.decode("ascii", errors="replace"),
                    "serial": serial.value.decode("ascii", errors="replace"),
                }
            )
        return devices

    def open(self, index: int) -> int:
        """Open the device at ``index`` of the enumeration; returns its handle."""
        handle = ctypes.c_int()
        self._check(
            self.dll.FDwfDeviceOpen(ctypes.c_int(index), ctypes.byref(handle)),
            f"cannot open device {index}",
        )
        if handle.value == 0:  # hdwfNone
            raise DwfError(f"cannot open device {index}: {self._message()}")
        return handle.value

    def close(self, handle: int) -> None:
        """Close a device."""
        self.dll.FDwfDeviceClose(ctypes.c_int(handle))

    # ----- AnalogOut ----------------------------------------------------------------------
    def channel_count(self, handle: int) -> int:
        """The number of AnalogOut channels."""
        count = ctypes.c_int()
        self._check(
            self.dll.FDwfAnalogOutCount(ctypes.c_int(handle), ctypes.byref(count)), "channel count"
        )
        return count.value

    def reset(self, handle: int, channel: int = -1) -> None:
        """Default parameters on one channel, or on all of them (-1)."""
        self._check(
            self.dll.FDwfAnalogOutReset(ctypes.c_int(handle), ctypes.c_int(channel)), "reset"
        )

    def configure(self, handle: int, channel: int, start: bool) -> None:
        """Start or stop a channel."""
        self._check(
            self.dll.FDwfAnalogOutConfigure(
                ctypes.c_int(handle), ctypes.c_int(channel), ctypes.c_int(1 if start else 0)
            ),
            "configure",
        )

    def node_enable(self, handle: int, channel: int, enable: bool) -> None:
        """Enable or disable the carrier node (the channel)."""
        self._check(
            self.dll.FDwfAnalogOutNodeEnableSet(
                ctypes.c_int(handle),
                ctypes.c_int(channel),
                ctypes.c_int(NODE_CARRIER),
                ctypes.c_int(1 if enable else 0),
            ),
            "enable",
        )

    def set_function(self, handle: int, channel: int, func: int) -> None:
        """The waveform of the carrier."""
        self._check(
            self.dll.FDwfAnalogOutNodeFunctionSet(
                ctypes.c_int(handle),
                ctypes.c_int(channel),
                ctypes.c_int(NODE_CARRIER),
                ctypes.c_ubyte(func),
            ),
            "waveform",
        )

    def functions(self, handle: int, channel: int) -> int:
        """The bit field of the waveforms the carrier supports (bit ``n`` = FUNC value ``n``)."""
        bits = ctypes.c_int()
        self._check(
            self.dll.FDwfAnalogOutNodeFunctionInfo(
                ctypes.c_int(handle),
                ctypes.c_int(channel),
                ctypes.c_int(NODE_CARRIER),
                ctypes.byref(bits),
            ),
            "waveform info",
        )
        return bits.value

    def _set_double(self, name: str, what: str, handle: int, channel: int, value: float) -> None:
        self._check(
            getattr(self.dll, name)(
                ctypes.c_int(handle),
                ctypes.c_int(channel),
                ctypes.c_int(NODE_CARRIER),
                ctypes.c_double(value),
            ),
            what,
        )

    def _range(self, name: str, what: str, handle: int, channel: int):
        low, high = ctypes.c_double(), ctypes.c_double()
        self._check(
            getattr(self.dll, name)(
                ctypes.c_int(handle),
                ctypes.c_int(channel),
                ctypes.c_int(NODE_CARRIER),
                ctypes.byref(low),
                ctypes.byref(high),
            ),
            what,
        )
        return low.value, high.value

    def set_frequency(self, handle: int, channel: int, hertz: float) -> None:
        """The frequency of the waveform, in Hz."""
        self._set_double("FDwfAnalogOutNodeFrequencySet", "frequency", handle, channel, hertz)

    def set_amplitude(self, handle: int, channel: int, volts: float) -> None:
        """The amplitude, in the Volts of the SDK."""
        self._set_double("FDwfAnalogOutNodeAmplitudeSet", "amplitude", handle, channel, volts)

    def set_offset(self, handle: int, channel: int, volts: float) -> None:
        """The offset, in Volts."""
        self._set_double("FDwfAnalogOutNodeOffsetSet", "offset", handle, channel, volts)

    def amplitude_range(self, handle: int, channel: int):
        """The ``(minimum, maximum)`` amplitude of the carrier."""
        return self._range("FDwfAnalogOutNodeAmplitudeInfo", "amplitude info", handle, channel)

    def offset_range(self, handle: int, channel: int):
        """The ``(minimum, maximum)`` offset of the carrier."""
        return self._range("FDwfAnalogOutNodeOffsetInfo", "offset info", handle, channel)

    # ----- AnalogIn (oscilloscope) --------------------------------------------------------
    def _get_int(self, name: str, what: str, handle: int) -> int:
        value = ctypes.c_int()
        self._check(getattr(self.dll, name)(ctypes.c_int(handle), ctypes.byref(value)), what)
        return value.value

    def _get_doubles(self, name: str, what: str, handle: int, count: int):
        values = [ctypes.c_double() for _ in range(count)]
        self._check(
            getattr(self.dll, name)(ctypes.c_int(handle), *[ctypes.byref(v) for v in values]),
            what,
        )
        return tuple(v.value for v in values)

    def ain_channel_count(self, handle: int) -> int:
        """The number of AnalogIn (oscilloscope) channels."""
        return self._get_int("FDwfAnalogInChannelCount", "oscilloscope channel count", handle)

    def ain_reset(self, handle: int) -> None:
        """Default parameters of the AnalogIn instrument."""
        self._check(self.dll.FDwfAnalogInReset(ctypes.c_int(handle)), "oscilloscope reset")

    def ain_configure(self, handle: int, reconfigure: bool, start: bool) -> None:
        """Configure the instrument and start (or stop) the acquisition."""
        self._check(
            self.dll.FDwfAnalogInConfigure(
                ctypes.c_int(handle),
                ctypes.c_int(1 if reconfigure else 0),
                ctypes.c_int(1 if start else 0),
            ),
            "oscilloscope configure",
        )

    def ain_status(self, handle: int, read_data: bool) -> int:
        """The state of the acquisition (``STATE_*``); with ``read_data`` the samples are read
        from the device when the acquisition is done."""
        state = ctypes.c_byte()
        self._check(
            self.dll.FDwfAnalogInStatus(
                ctypes.c_int(handle), ctypes.c_int(1 if read_data else 0), ctypes.byref(state)
            ),
            "oscilloscope status",
        )
        return state.value

    def ain_auto_triggered(self, handle: int) -> bool:
        """True if the last acquisition was auto triggered."""
        flag = ctypes.c_int()
        self._check(
            self.dll.FDwfAnalogInStatusAutoTriggered(ctypes.c_int(handle), ctypes.byref(flag)),
            "auto trigger status",
        )
        return bool(flag.value)

    def ain_data(self, handle: int, channel: int, count: int) -> List[float]:
        """The samples of a channel (volts) of the last status read."""
        buffer = (ctypes.c_double * count)()
        self._check(
            self.dll.FDwfAnalogInStatusData(
                ctypes.c_int(handle), ctypes.c_int(channel), buffer, ctypes.c_int(count)
            ),
            "oscilloscope data",
        )
        return list(buffer)

    def ain_frequency_range(self, handle: int):
        """``(minimum, maximum)`` sample frequency."""
        return self._get_doubles("FDwfAnalogInFrequencyInfo", "sample frequency info", handle, 2)

    def ain_frequency_set(self, handle: int, hertz: float) -> None:
        """The sample frequency."""
        self._check(
            self.dll.FDwfAnalogInFrequencySet(ctypes.c_int(handle), ctypes.c_double(hertz)),
            "sample frequency",
        )

    def ain_frequency_get(self, handle: int) -> float:
        """The sample frequency the device uses."""
        return self._get_doubles("FDwfAnalogInFrequencyGet", "sample frequency", handle, 1)[0]

    def ain_bits(self, handle: int) -> int:
        """The bits of the ADC."""
        return self._get_int("FDwfAnalogInBitsInfo", "ADC bits", handle)

    def ain_buffer_range(self, handle: int):
        """``(minimum, maximum)`` buffer size in samples."""
        low, high = ctypes.c_int(), ctypes.c_int()
        self._check(
            self.dll.FDwfAnalogInBufferSizeInfo(
                ctypes.c_int(handle), ctypes.byref(low), ctypes.byref(high)
            ),
            "buffer size info",
        )
        return low.value, high.value

    def ain_buffer_set(self, handle: int, size: int) -> None:
        """The buffer size in samples."""
        self._check(
            self.dll.FDwfAnalogInBufferSizeSet(ctypes.c_int(handle), ctypes.c_int(size)),
            "buffer size",
        )

    def ain_buffer_get(self, handle: int) -> int:
        """The buffer size in use."""
        return self._get_int("FDwfAnalogInBufferSizeGet", "buffer size", handle)

    def ain_channel_enable(self, handle: int, channel: int, enable: bool) -> None:
        """Enable or disable an AnalogIn channel."""
        self._check(
            self.dll.FDwfAnalogInChannelEnableSet(
                ctypes.c_int(handle), ctypes.c_int(channel), ctypes.c_int(1 if enable else 0)
            ),
            "channel enable",
        )

    def _channel_double(self, name: str, what: str, handle: int, channel: int, value: float):
        self._check(
            getattr(self.dll, name)(
                ctypes.c_int(handle), ctypes.c_int(channel), ctypes.c_double(value)
            ),
            what,
        )

    def _channel_get(self, name: str, what: str, handle: int, channel: int) -> float:
        value = ctypes.c_double()
        self._check(
            getattr(self.dll, name)(
                ctypes.c_int(handle), ctypes.c_int(channel), ctypes.byref(value)
            ),
            what,
        )
        return value.value

    def ain_range_info(self, handle: int):
        """``(minimum, maximum)`` peak-to-peak range."""
        low, high, steps = (ctypes.c_double() for _ in range(3))
        self._check(
            self.dll.FDwfAnalogInChannelRangeInfo(
                ctypes.c_int(handle), ctypes.byref(low), ctypes.byref(high), ctypes.byref(steps)
            ),
            "range info",
        )
        return low.value, high.value

    def ain_range_set(self, handle: int, channel: int, volts: float) -> None:
        """The peak-to-peak range of a channel."""
        self._channel_double("FDwfAnalogInChannelRangeSet", "range", handle, channel, volts)

    def ain_range_get(self, handle: int, channel: int) -> float:
        """The range the device really uses."""
        return self._channel_get("FDwfAnalogInChannelRangeGet", "range", handle, channel)

    def ain_offset_info(self, handle: int):
        """``(minimum, maximum)`` offset."""
        low, high, steps = (ctypes.c_double() for _ in range(3))
        self._check(
            self.dll.FDwfAnalogInChannelOffsetInfo(
                ctypes.c_int(handle), ctypes.byref(low), ctypes.byref(high), ctypes.byref(steps)
            ),
            "offset info",
        )
        return low.value, high.value

    def ain_offset_set(self, handle: int, channel: int, volts: float) -> None:
        """The offset of a channel."""
        self._channel_double("FDwfAnalogInChannelOffsetSet", "offset", handle, channel, volts)

    def ain_offset_get(self, handle: int, channel: int) -> float:
        """The offset the device really uses."""
        return self._channel_get("FDwfAnalogInChannelOffsetGet", "offset", handle, channel)

    def ain_attenuation_set(self, handle: int, channel: int, factor: float) -> None:
        """The attenuation applied outside the device (a probe)."""
        self._channel_double(
            "FDwfAnalogInChannelAttenuationSet", "attenuation", handle, channel, factor
        )

    def ain_trigger_source_set(self, handle: int, source: int) -> None:
        """The trigger source (``TRIGSRC_*``)."""
        self._check(
            self.dll.FDwfAnalogInTriggerSourceSet(ctypes.c_int(handle), ctypes.c_ubyte(source)),
            "trigger source",
        )

    def ain_trigger_channel_set(self, handle: int, channel: int) -> None:
        """The channel the trigger detector looks at."""
        self._check(
            self.dll.FDwfAnalogInTriggerChannelSet(ctypes.c_int(handle), ctypes.c_int(channel)),
            "trigger channel",
        )

    def ain_trigger_level_set(self, handle: int, volts: float) -> None:
        """The trigger level."""
        self._check(
            self.dll.FDwfAnalogInTriggerLevelSet(ctypes.c_int(handle), ctypes.c_double(volts)),
            "trigger level",
        )

    def ain_trigger_condition_set(self, handle: int, condition: int) -> None:
        """The trigger condition (``TRIGCOND_*``)."""
        self._check(
            self.dll.FDwfAnalogInTriggerConditionSet(ctypes.c_int(handle), ctypes.c_int(condition)),
            "trigger condition",
        )

    def ain_trigger_timeout_set(self, handle: int, seconds: float) -> None:
        """The auto trigger timeout (0: wait for the trigger)."""
        self._check(
            self.dll.FDwfAnalogInTriggerAutoTimeoutSet(
                ctypes.c_int(handle), ctypes.c_double(seconds)
            ),
            "auto trigger timeout",
        )

    def ain_trigger_holdoff_set(self, handle: int, seconds: float) -> None:
        """The trigger hold-off."""
        self._check(
            self.dll.FDwfAnalogInTriggerHoldOffSet(ctypes.c_int(handle), ctypes.c_double(seconds)),
            "trigger hold-off",
        )


class _Shared:
    """An open device and how many connections use it."""

    def __init__(self, api: DwfApi, handle: int, name: str, serial: str):
        self.api, self.handle, self.name, self.serial = api, handle, name, serial
        self.refs = 0


_OPEN: Dict[tuple, _Shared] = {}  # (library, serial number) -> the open device


class DwfDevice:
    """An open Analog Discovery: what ``WaveformsDriver`` is given as its connection. Two
    instruments of the same device (its waveform generator and its oscilloscope) share the open
    device; it is closed when the last connection is closed."""

    def __init__(self, shared: _Shared):
        self._shared = shared
        shared.refs += 1
        self.api, self.handle = shared.api, shared.handle
        self.name, self.serial = shared.name, shared.serial
        self.closed = False

    def close(self) -> None:
        """Close this connection; the device itself when no connection is left (the outputs keep
        the state the device gives them when closed)."""
        if self.closed:
            return
        self.closed = True
        self._shared.refs -= 1
        if self._shared.refs <= 0:
            for key, value in list(_OPEN.items()):
                if value is self._shared:
                    del _OPEN[key]
            self.api.close(self.handle)


def parse_address(address: str) -> Optional[str]:
    """The serial number of ``DWF::<serial number>`` (the ``SN:`` prefix of the SDK is accepted),
    or None for ``DWF`` alone (the first device found). ``ValueError`` for anything else."""
    parts = str(address).strip().split("::")
    if parts[0].upper() != "DWF" or len(parts) > 2 or (len(parts) == 2 and not parts[1].strip()):
        raise ValueError(f"not a WaveForms address: {address!r} (use DWF or DWF::<serial number>)")
    if len(parts) == 1:
        return None
    serial = parts[1].strip()
    return serial[3:] if serial.upper().startswith("SN:") else serial


def open_dwf(address: str, loader: Optional[Callable[[], Any]] = None) -> DwfDevice:
    """Open the device of ``address`` (see ``parse_address``). ``DwfError`` with the devices that
    were found if the serial number is not among them."""
    wanted = parse_address(address)
    api = DwfApi((loader or load_library)())
    devices = api.enumerate()
    if not devices:
        raise DwfError("no Digilent device found: check the USB cable and that WaveForms sees it")
    index = 0
    if wanted is not None:
        serials = [
            d["serial"][3:] if d["serial"].upper().startswith("SN:") else d["serial"]
            for d in devices
        ]
        matches = [i for i, s in enumerate(serials) if s.upper() == wanted.upper()]
        if not matches:
            raise DwfError(
                f"no device with serial number {wanted} (found: {', '.join(serials) or 'none'})"
            )
        index = matches[0]
    serial = devices[index]["serial"]
    serial = serial[3:] if serial.upper().startswith("SN:") else serial
    key = (id(api.dll), serial.upper())
    shared = _OPEN.get(key)
    if shared is None:  # not open yet (a second instrument of the same device finds it open)
        shared = _Shared(api, api.open(index), devices[index]["name"], serial)
        _OPEN[key] = shared
    return DwfDevice(shared)


class WaveformsDriver:
    """The logical calls of the function generator category on an Analog Discovery."""

    def __init__(self, transport: DwfDevice):
        self.device = transport
        self.api, self.handle = transport.api, transport.handle
        self._channels: Optional[int] = None
        # oscilloscope
        self._in_channels: Optional[int] = None
        self._enabled: set = set()  # AnalogIn channel indexes enabled through this driver
        self._attenuation: Dict[int, float] = {}  # probe factor per AnalogIn channel (default 1)
        self._timebase: Optional[float] = None  # seconds per division
        self._depth: Optional[int] = None  # points
        self._state = "idle"  # idle | running | done
        self._deadline = 0.0  # when a running acquisition is given up
        self._capture: Dict[int, List[float]] = {}
        self._capture_rate = 0.0
        self._capture_range: Dict[int, float] = {}
        self._capture_offset: Dict[int, float] = {}
        self._trigger_timeout = 0.0

    # ----- entry point of the executor --------------------------------------------------
    def call(self, function: str, args: dict) -> Any:
        """Run the logical call ``function``; the errors are CALL-xxx exceptions."""
        from ..call_errors import CallNotSupportedError

        if function.startswith(
            "unsupported_"
        ):  # a mandatory call this device has no equivalent for
            name = function[len("unsupported_") :]
            raise CallNotSupportedError(
                f"call '{name}' has no equivalent on the Analog Discovery (see the model "
                f"description in the instrument library)",
                call=name,
            )
        handler = getattr(self, f"fn_{function}", None)
        if handler is None:
            raise CallNotSupportedError(
                f"call '{function}' is not available on the Analog Discovery", call=function
            )
        try:
            return handler(**args)
        except DwfError as exc:  # the library refused: the same error as a failed step
            raise StepFailedError(function, 0, exc) from exc

    # ----- helpers ------------------------------------------------------------------------
    def _channel(self, channel_number: Optional[int], call: str) -> int:
        """The SDK index of a 1-based channel number (the first channel if none is given)."""
        number = 1 if channel_number is None else int(channel_number)
        if self._channels is None:
            self._channels = self.api.channel_count(self.handle)
        if not 1 <= number <= self._channels:
            raise InvalidArgumentError(
                f"channel {number} does not exist: the device has {self._channels} waveform "
                f"channel(s)",
                call=call,
            )
        return number - 1

    # ----- logical calls ------------------------------------------------------------------
    def fn_identification_query(self) -> str:
        """``Digilent,<device name>,<serial number>,`` (the library gives no firmware version)."""
        return f"Digilent,{self.device.name},{self.device.serial},"

    def fn_reset(self) -> None:
        """Default parameters on all the channels (this also stops them)."""
        self.api.reset(self.handle, -1)

    def fn_set_output_state(self, state: bool, channel_number: Optional[int] = None) -> None:
        """On: enable the carrier and start the channel. Off: stop the channel and disable the
        carrier."""
        channel = self._channel(channel_number, "set_output_state")
        if state:
            self.api.node_enable(self.handle, channel, True)
            self.api.configure(self.handle, channel, True)
        else:
            self.api.configure(self.handle, channel, False)
            self.api.node_enable(self.handle, channel, False)

    def fn_set_frequency(self, value: float, channel_number: Optional[int] = None) -> None:
        """The frequency in Hz (the range the library reports is the DAC rate, so the device itself
        refuses what it cannot do)."""
        channel = self._channel(channel_number, "set_frequency")
        self.api.set_frequency(self.handle, channel, float(value))

    def fn_set_amplitude(self, value: float, channel_number: Optional[int] = None) -> None:
        """The peak-to-peak amplitude (see ``PEAK_PER_VPP``); a value the device cannot give is
        not handled by this model."""
        channel = self._channel(channel_number, "set_amplitude")
        volts = float(value) * PEAK_PER_VPP
        low, high = self.api.amplitude_range(self.handle, channel)
        if not low <= volts <= high:
            raise ValueNotHandledError(
                f"{value:g} Vpp is outside what this device gives "
                f"({2 * low:g} to {2 * high:g} Vpp)",
                call="set_amplitude",
            )
        self.api.set_amplitude(self.handle, channel, volts)

    def fn_set_offset(self, value: float, channel_number: Optional[int] = None) -> None:
        """The offset in volts; a value the device cannot give is not handled by this model."""
        channel = self._channel(channel_number, "set_offset")
        low, high = self.api.offset_range(self.handle, channel)
        if not low <= float(value) <= high:
            raise ValueNotHandledError(
                f"an offset of {value:g} V is outside what this device gives "
                f"({low:g} to {high:g} V)",
                call="set_offset",
            )
        self.api.set_offset(self.handle, channel, float(value))

    def fn_set_waveform_shape(self, shape: str, channel_number: Optional[int] = None) -> None:
        """The waveform. PULSE and ARBITRARY are not handled; neither is a shape the device does not
        list among its functions."""
        channel = self._channel(channel_number, "set_waveform_shape")
        func = SHAPES.get(shape)
        if func is None:
            raise ValueNotHandledError(
                f"the waveform {shape} is not handled by this model (it needs data or a pulse "
                f"generator)",
                call="set_waveform_shape",
            )
        if not self.api.functions(self.handle, channel) >> func & 1:
            raise ValueNotHandledError(
                f"this device does not give a {shape} waveform", call="set_waveform_shape"
            )
        self.api.set_function(self.handle, channel, func)

    # ================================================================ oscilloscope (AnalogIn)
    def _in_channel(self, channel_number: Optional[int], call: str) -> int:
        """The SDK index of a 1-based oscilloscope channel number."""
        number = 1 if channel_number is None else int(channel_number)
        if self._in_channels is None:
            self._in_channels = self.api.ain_channel_count(self.handle)
        if not 1 <= number <= self._in_channels:
            raise InvalidArgumentError(
                f"channel {number} does not exist: the device has {self._in_channels} "
                f"oscilloscope channel(s)",
                call=call,
            )
        return number - 1

    def fn_scope_reset(self) -> None:
        """Default parameters of the oscilloscope (the generator is not touched)."""
        self.api.ain_reset(self.handle)
        self._enabled.clear()
        self._attenuation.clear()  # the device goes back to no probe
        self._timebase = self._depth = None
        self._state, self._capture = "idle", {}
        self._trigger_timeout = 0.0

    def fn_set_channel_state(self, state: bool, channel_number: Optional[int] = None) -> None:
        """Enable or disable a channel."""
        channel = self._in_channel(channel_number, "set_channel_state")
        self.api.ain_channel_enable(self.handle, channel, bool(state))
        (self._enabled.add if state else self._enabled.discard)(channel)

    def fn_set_channel_scale(self, value: float, channel_number: Optional[int] = None) -> None:
        """Volts per division at the probe tip: the range is ``VERTICAL_DIVISIONS`` times that; a
        range the device does not have is not handled by this model.

        The range the library reports is the one at the device input. With a probe attenuation set
        the library applies it to the range (measured on an Analog Discovery 2: with a x10 probe
        every request between 0.5 and 10 V gave 54.9 V, ten times the 5.49 V minimum without a
        probe), so the limits are multiplied by the attenuation and the scale is the one of the
        signal being measured. Asking for less than that used to be rounded up silently."""
        channel = self._in_channel(channel_number, "set_channel_scale")
        volts = float(value) * VERTICAL_DIVISIONS
        attenuation = self._attenuation.get(channel, 1.0)
        low, high = self.api.ain_range_info(self.handle)
        low, high = low * attenuation, high * attenuation
        if not low <= volts <= high:
            probe = f" with a x{attenuation:g} probe" if attenuation != 1.0 else ""
            raise ValueNotHandledError(
                f"{value:g} V/div is outside what this device gives{probe} "
                f"({low / VERTICAL_DIVISIONS:g} to {high / VERTICAL_DIVISIONS:g} V/div)",
                call="set_channel_scale",
            )
        self.api.ain_range_set(self.handle, channel, volts)

    def fn_query_channel_scale(self, channel_number: Optional[int] = None) -> float:
        """Volts per division the device really uses."""
        channel = self._in_channel(channel_number, "query_channel_scale")
        return self.api.ain_range_get(self.handle, channel) / VERTICAL_DIVISIONS

    def fn_set_channel_offset(self, value: float, channel_number: Optional[int] = None) -> None:
        """The offset in volts; one the device does not have is not handled by this model."""
        channel = self._in_channel(channel_number, "set_channel_offset")
        low, high = self.api.ain_offset_info(self.handle)
        if not low <= float(value) <= high:
            raise ValueNotHandledError(
                f"an offset of {value:g} V is outside what this device gives "
                f"({low:g} to {high:g} V)",
                call="set_channel_offset",
            )
        self.api.ain_offset_set(self.handle, channel, float(value))

    def fn_query_channel_offset(self, channel_number: Optional[int] = None) -> float:
        """The offset the device really uses."""
        channel = self._in_channel(channel_number, "query_channel_offset")
        return self.api.ain_offset_get(self.handle, channel)

    def fn_set_channel_coupling(self, coupling_type: str, channel_number: Optional[int] = None):
        """The SDK has no coupling control for the oscilloscope inputs: DC is what they are."""
        self._in_channel(channel_number, "set_channel_coupling")
        if coupling_type != "DC":
            raise ValueNotHandledError(
                f"{coupling_type} coupling is not handled by this model (the inputs are DC "
                f"coupled)",
                call="set_channel_coupling",
            )

    def fn_set_probe_attenuation(self, value: float, channel_number: Optional[int] = None):
        """Tell the library about the attenuation applied outside the device."""
        channel = self._in_channel(channel_number, "set_probe_attenuation")
        self.api.ain_attenuation_set(self.handle, channel, float(value))
        self._attenuation[channel] = float(value)

    def fn_set_timebase_scale(self, value: float) -> None:
        """Time per division (``HORIZONTAL_DIVISIONS`` divisions); the sample frequency is set
        from it and from the depth when the acquisition starts."""
        self._timebase = float(value)

    def fn_query_timebase_scale(self) -> float:
        """The time per division last set."""
        if self._timebase is None:
            raise InvalidArgumentError(
                "no time per division has been set", call="query_timebase_scale"
            )
        return self._timebase

    def fn_set_acquisition_depth(self, depth: int) -> None:
        """The buffer size in points; one the device does not have is not handled."""
        low, high = self.api.ain_buffer_range(self.handle)
        if not low <= int(depth) <= high:
            raise ValueNotHandledError(
                f"{depth} points is outside what this device gives ({low} to {high} points)",
                call="set_acquisition_depth",
            )
        self._depth = int(depth)
        self.api.ain_buffer_set(self.handle, self._depth)

    def fn_query_waveform_max_points(self) -> int:
        """The largest buffer: the whole capture comes as one block."""
        return self.api.ain_buffer_range(self.handle)[1]

    def fn_query_sample_rate(self) -> float:
        """Samples per second."""
        return self.api.ain_frequency_get(self.handle)

    def fn_set_trigger_source(self, channel_number: Optional[int] = None) -> None:
        """Trigger on the AnalogIn detector, on this channel."""
        channel = self._in_channel(channel_number, "set_trigger_source")
        self.api.ain_trigger_source_set(self.handle, TRIGSRC_DETECTOR_ANALOG_IN)
        self.api.ain_trigger_channel_set(self.handle, channel)

    def fn_set_trigger_level(self, value: float, channel_number: Optional[int] = None) -> None:
        """The trigger level (the detector has one channel: the one of ``set_trigger_source``)."""
        self.api.ain_trigger_level_set(self.handle, float(value))

    def fn_set_trigger_slope(self, slope: str) -> None:
        """Rising or falling edge; EITHER is not handled by this model."""
        conditions = {"RISE": TRIGCOND_RISING, "FALL": TRIGCOND_FALLING}
        if slope not in conditions:
            raise ValueNotHandledError(
                f"the trigger slope {slope} is not handled by this model", call="set_trigger_slope"
            )
        self.api.ain_trigger_condition_set(self.handle, conditions[slope])

    def fn_set_trigger_mode(self, mode: str) -> None:
        """AUTO: an auto trigger timeout; NORMAL and SINGLE: wait for the trigger."""
        self._trigger_timeout = AUTO_TRIGGER_TIMEOUT_S if mode == "AUTO" else 0.0
        self.api.ain_trigger_timeout_set(self.handle, self._trigger_timeout)

    def fn_set_trigger_holdoff(self, value: float) -> None:
        """The trigger hold-off in seconds."""
        self.api.ain_trigger_holdoff_set(self.handle, float(value))

    def fn_query_trigger_status(self) -> str:
        """``READY``, ``ARMED``, ``TRIGGERED``, ``STOPPED`` or ``AUTO``."""
        state = self.api.ain_status(self.handle, False)
        if state == STATE_DONE:
            return "AUTO" if self.api.ain_auto_triggered(self.handle) else "STOPPED"
        if state == STATE_TRIGGERED:
            return "TRIGGERED"
        if state in (STATE_ARMED, STATE_CONFIG, STATE_PREFILL, STATE_WAIT):
            return "ARMED"
        return "READY"

    # ----- acquisition --------------------------------------------------------------------
    def _apply_timebase(self) -> float:
        """Set the sample frequency from the timebase and the depth; returns the one in use."""
        depth = self._depth or self.api.ain_buffer_range(self.handle)[1]
        if self._depth is None:
            self.api.ain_buffer_set(self.handle, depth)
        if self._timebase:
            low, high = self.api.ain_frequency_range(self.handle)
            wanted = depth / (HORIZONTAL_DIVISIONS * self._timebase)
            self.api.ain_frequency_set(self.handle, min(max(wanted, low), high))
        return self.api.ain_frequency_get(self.handle)

    def fn_run_acquisition(self) -> None:
        """Start one single acquisition of the buffer."""
        rate = self._apply_timebase()
        depth = self.api.ain_buffer_get(self.handle)
        self.api.ain_configure(self.handle, True, True)
        self._state, self._capture = "running", {}
        self._deadline = time.monotonic() + depth / rate + self._trigger_timeout + FINISH_MARGIN_S

    def _finish(self) -> None:
        """Wait for the running acquisition to be done and keep the samples of every enabled
        channel (one read: the channels come from the same capture)."""
        if self._state != "running":
            return
        while True:
            state = self.api.ain_status(self.handle, True)
            if state == STATE_DONE:
                break
            if time.monotonic() > self._deadline:
                self.api.ain_configure(self.handle, False, False)
                self._state = "idle"
                raise DwfError(
                    "the acquisition did not finish (is there a trigger? a trigger mode AUTO "
                    "gives one after a time)"
                )
            time.sleep(POLL_S)
        if self._in_channels is None:
            self._in_channels = self.api.ain_channel_count(self.handle)
        channels = sorted(self._enabled) or list(range(self._in_channels))
        depth = self.api.ain_buffer_get(self.handle)
        self._capture = {c: self.api.ain_data(self.handle, c, depth) for c in channels}
        self._capture_rate = self.api.ain_frequency_get(self.handle)
        self._capture_range = {c: self.api.ain_range_get(self.handle, c) for c in channels}
        self._capture_offset = {c: self.api.ain_offset_get(self.handle, c) for c in channels}
        self._state = "done"

    def fn_stop_acquisition(self) -> None:
        """Finish the running acquisition (the device has no frozen screen: the capture is
        completed, not interrupted) and keep its samples."""
        self._finish()

    def fn_read_waveform(
        self,
        channel_number: Optional[int] = None,
        bits: Optional[int] = None,
        start: int = 0,
        points: int = 0,
    ) -> Dict[str, Any]:
        """The samples of a channel of the last acquisition (one is made if none was started):
        ``time`` (relative to the middle of the buffer), ``voltage`` and the acquisition values."""
        channel = self._in_channel(channel_number, "read_waveform")
        if self._state == "idle" and not self._capture:
            self.fn_run_acquisition()
        self._finish()
        samples = self._capture.get(channel)
        if samples is None:
            raise InvalidArgumentError(
                f"channel {channel + 1} was not enabled for the last acquisition",
                call="read_waveform",
            )
        first = max(int(start), 0)
        last = first + int(points) if points else len(samples)
        volts = samples[first:last]
        interval = 1.0 / self._capture_rate
        middle = len(samples) / 2.0
        bits_of_adc = self.api.ain_bits(self.handle)
        return {
            "time": array("d", ((first + i - middle) * interval for i in range(len(volts)))),
            "voltage": array("d", volts),
            "points": len(volts),
            "sample_interval": interval,
            "vertical_gain": self._capture_range[channel] / 2**bits_of_adc,
            "vertical_offset": self._capture_offset[channel],
            "trigger_delay": 0.0,
            "timebase": self._timebase if self._timebase is not None else 0.0,
        }
