# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Driver of the Digilent Analog Discovery waveform generator, through the WaveForms runtime.

The Analog Discovery is controlled with the ``dwf`` library of the WaveForms SDK (the reference
manual is in ``Instruments_LIB/docs/Digilent``), not with text commands and not through VISA.
This module has three parts:

* ``DwfApi`` wraps the C functions of the library that the AnalogOut instrument needs (ctypes);
  every failure of the library becomes a ``DwfError`` with the message of ``FDwfGetLastErrorMsg``.
* ``DwfDevice`` is the connection the application opens for an address ``DWF`` (the first device
  found) or ``DWF::<serial number>``; ``close`` closes the device.
* ``WaveformsDriver`` implements the logical calls of the function generator category
  (``set_output_state``, ``set_frequency``, ``set_amplitude``, ``set_offset``,
  ``set_waveform_shape``, ``reset``, ``identification_query``). Channel numbers are 1-based in the
  logical calls and 0-based in the SDK.

**To verify on a real device** (see ``Instruments_LIB/docs/proposals/function-generator-calls.md``):
the reference manual says the amplitude is "in Volts" and not whether it is the peak or the
peak-to-peak value; the driver sends half of the peak-to-peak value (``PEAK_PER_VPP``). The numeric
constants below (``ENUM_FILTER_ALL``, the carrier node, the ``FUNC_*`` values) are those of
``dwf.h`` / ``dwfconstants.py`` of the SDK and are not in the reference manual.
"""

from __future__ import annotations

import ctypes
import logging
import sys
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


class DwfDevice:
    """An open Analog Discovery: what ``WaveformsDriver`` is given as its connection."""

    def __init__(self, api: DwfApi, handle: int, name: str, serial: str):
        self.api, self.handle, self.name, self.serial = api, handle, name, serial
        self.closed = False

    def close(self) -> None:
        """Close the device (the outputs keep the state the device gives them when closed)."""
        if not self.closed:
            self.closed = True
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
    handle = api.open(index)
    serial = devices[index]["serial"]
    return DwfDevice(
        api,
        handle,
        devices[index]["name"],
        serial[3:] if serial.upper().startswith("SN:") else serial,
    )


class WaveformsDriver:
    """The logical calls of the function generator category on an Analog Discovery."""

    def __init__(self, transport: DwfDevice):
        self.device = transport
        self.api, self.handle = transport.api, transport.handle
        self._channels: Optional[int] = None

    # ----- entry point of the executor --------------------------------------------------
    def call(self, function: str, args: dict) -> Any:
        """Run the logical call ``function``; the errors are CALL-xxx exceptions."""
        from ..call_errors import CallNotSupportedError

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
