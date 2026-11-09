# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Driver of the Zenko LiteVNA (62, 64, 67) over its USB virtual serial port.

The LiteVNA speaks a binary register protocol (the SAA2 / NanoVNA-APP protocol), described in
the appendix "USB data interface" of the LiteVNA User Guide: a one-byte opcode followed by
the address and the data, little-endian registers, a FIFO of 32-byte records. It returns raw
waves (never calibrated), so the driver divides them by the reference wave and applies the
software calibration of ``ola.vna_calibration``.

The functions are the logical VNA calls of the library (``set_frequency_sweep``,
``read_sparameters``, ...). The connection needs ``write`` (raw bytes), ``read_exact`` and
``flush_input`` (``ola.transport`` and ``ola._visa`` provide them).
"""

from __future__ import annotations

import struct
from array import array
from typing import Any, Dict, List, Optional, Tuple

from .. import vna_calibration as cal
from ..call_errors import (
    CallNotSupportedError,
    InvalidArgumentError,
    ResponseNotRecognisedError,
    ValueNotHandledError,
)

# opcodes
INDICATE, READ, READ2, READFIFO = 0x0D, 0x10, 0x11, 0x18
WRITE, WRITE2, WRITE4, WRITE8 = 0x20, 0x21, 0x22, 0x23
# registers
SWEEP_START, SWEEP_STEP, SWEEP_POINTS, VALUES_PER_FREQUENCY = 0x00, 0x10, 0x20, 0x22
VALUES_FIFO, CHANNEL_SELECT = 0x30, 0x44
DEVICE_VARIANT, HARDWARE_REVISION, FIRMWARE_MAJOR, FIRMWARE_MINOR = 0xF0, 0xF2, 0xF3, 0xF4

RECORD_SIZE = 32
MAX_RECORDS_PER_READ = 255
MAX_POINTS = 65535
CHANNELS = {("S11",): 0x01, ("S21",): 0x02, ("S11", "S21"): 0x00}


def _record(raw: bytes) -> Tuple[complex, complex, complex, int]:
    """(reference wave, S11 wave, S21 wave, frequency index) of one 32-byte FIFO record."""
    fwd_re, fwd_im, r0_re, r0_im, r1_re, r1_im = struct.unpack_from("<6i", raw, 0)
    (index,) = struct.unpack_from("<H", raw, 0x18)
    return complex(fwd_re, fwd_im), complex(r0_re, r0_im), complex(r1_re, r1_im), index


class LiteVnaDriver:
    """The logical VNA calls of the LiteVNA."""

    def __init__(self, transport):
        self.t = transport
        self._sweep: Optional[Tuple[int, int, int]] = None  # start Hz, step Hz, points
        self._selected: Tuple[str, ...] = ("S11", "S21")
        self._channels_written = False
        self._swept = False
        self._kit = cal.CalKit()  # ideal standards until set_calibration_kit
        self._kind: Optional[str] = None  # calibration kind chosen with calibration_begin
        self._ports: Tuple[int, Optional[int]] = (1, None)
        self._standards: Dict[str, List[complex]] = {}
        self._standards_grid: Optional[Tuple[int, int, int]] = None
        self._reflection: Optional[cal.Reflection] = None
        self._thru: Optional[List[complex]] = None
        self._cal_grid: Optional[Tuple[int, int, int]] = None
        self._correction = False

    # ----- entry point of the executor --------------------------------------------------
    def call(self, function: str, args: dict) -> Any:
        """Run the logical call ``function``; the errors are CALL-xxx exceptions."""
        handler = getattr(self, f"fn_{function}", None)
        if handler is None:
            raise CallNotSupportedError(
                f"call '{function}' is not available on the LiteVNA", call=function
            )
        return handler(**args)

    # ----- wire protocol ----------------------------------------------------------------
    def _write_register(self, address: int, data: bytes) -> None:
        opcode = {1: WRITE, 2: WRITE2, 4: WRITE4, 8: WRITE8}[len(data)]
        self.t.write(bytes([opcode, address]) + data)

    def _read_register(self, address: int, size: int = 1) -> bytes:
        self.t.write(bytes([{1: READ, 2: READ2}[size], address]))
        return self.t.read_exact(size)

    def _records(self):
        """Parsed FIFO records, read 255 at a time, for as long as the caller asks."""
        while True:
            self.t.write(bytes([READFIFO, VALUES_FIFO, MAX_RECORDS_PER_READ]))
            data = self.t.read_exact(MAX_RECORDS_PER_READ * RECORD_SIZE, timeout_ms=20000)
            for i in range(MAX_RECORDS_PER_READ):
                yield _record(data[i * RECORD_SIZE : (i + 1) * RECORD_SIZE])

    # ----- logical calls ----------------------------------------------------------------
    def fn_identification_query(self) -> str:
        """Identification from the device registers."""
        self.t.write(bytes([INDICATE]))
        if self.t.read_exact(1) != b"2":
            raise ResponseNotRecognisedError("the device did not answer like a LiteVNA")
        variant = self._read_register(DEVICE_VARIANT)[0]
        if variant != 0x02:
            raise ResponseNotRecognisedError(f"deviceVariant {variant:#04x}, a LiteVNA has 0x02")
        hardware = self._read_register(HARDWARE_REVISION)[0]
        major = self._read_register(FIRMWARE_MAJOR)[0]
        minor = self._read_register(FIRMWARE_MINOR)[0]
        # the usual four fields; the device has no serial number register (0 = none)
        return f"Zenko,LiteVNA,0,hardware {hardware} firmware {major}.{minor}"

    def fn_set_frequency_sweep(self, start_frequency, stop_frequency, points) -> None:
        """Linear sweep: the device takes start, step and number of points."""
        if not 1 <= points <= MAX_POINTS:
            raise InvalidArgumentError(f"points must be 1..{MAX_POINTS}, got {points}")
        if stop_frequency < start_frequency:
            raise InvalidArgumentError("stop frequency is below the start frequency")
        start = int(round(start_frequency))
        step = int(round((stop_frequency - start_frequency) / (points - 1))) if points > 1 else 0
        if points > 1 and step < 1:
            raise InvalidArgumentError("the frequency step is below 1 Hz")
        self._write_register(SWEEP_START, struct.pack("<Q", start))
        self._write_register(SWEEP_STEP, struct.pack("<Q", step))
        self._write_register(SWEEP_POINTS, struct.pack("<H", points))
        self._write_register(VALUES_PER_FREQUENCY, struct.pack("<H", 1))
        self._sweep = (start, step, points)
        self._swept = False

    def fn_set_sweep_type(self, sweep_type) -> None:
        """The LiteVNA sweeps linearly (start, step, points): a logarithmic sweep is not handled."""
        if sweep_type != "LINEAR":
            raise ValueNotHandledError(
                f"sweep type {sweep_type} is not handled by the LiteVNA (linear sweep only)",
                call="set_sweep_type",
            )

    def _select_channels(self, sparameters) -> None:
        """S11, S21 or both; the LiteVNA has one source port, so S12 and S22 do not exist."""
        wanted = tuple(p for p in ("S11", "S21") if p in sparameters)
        other = [p for p in sparameters if p not in ("S11", "S21")]
        if other or not wanted:
            raise ValueNotHandledError(
                f"{other or sparameters} cannot be measured by the LiteVNA "
                "(T/R analyzer: S11 and S21 only)",
                call="read_sparameters",
            )
        if wanted != self._selected or not self._channels_written:
            self._write_register(CHANNEL_SELECT, bytes([CHANNELS[wanted]]))
            self._selected = wanted
            self._channels_written = True
            self._swept = False  # the FIFO holds records of the other channels

    def fn_run_sweep(self) -> None:
        """Empty the FIFO: the records that follow belong to a new sweep."""
        self._write_register(VALUES_FIFO, b"\x00")
        self.t.flush_input()
        self._swept = True

    def _need_sweep(self) -> Tuple[int, int, int]:
        if self._sweep is None:
            raise InvalidArgumentError("set_frequency_sweep must be called first")
        return self._sweep

    def _read_raw(self) -> Tuple[List[float], Dict[str, List[complex]]]:
        """One sweep as frequencies and complex S-parameters (wave / reference), not corrected."""
        start, step, points = self._need_sweep()
        if not self._swept:
            self.fn_run_sweep()
        records = self._records()
        limit = 4 * points + 2 * MAX_RECORDS_PER_READ
        taken, sweep_rows = 0, []
        for fwd, r0, r1, index in records:
            taken += 1
            if taken > limit:
                raise ResponseNotRecognisedError("the FIFO never delivered a complete sweep")
            if sweep_rows:
                if index == len(sweep_rows):
                    sweep_rows.append((fwd, r0, r1))
                else:  # lost sync: start again at the next index 0
                    sweep_rows = []
            if not sweep_rows and index == 0:
                sweep_rows.append((fwd, r0, r1))
            if len(sweep_rows) == points:
                break
        frequencies = [float(start + i * step) for i in range(points)]
        result: Dict[str, List[complex]] = {}
        for name, position in (("S11", 1), ("S21", 2)):
            if name in self._selected:
                values = []
                for i, row in enumerate(sweep_rows):
                    if row[0] == 0:
                        raise ResponseNotRecognisedError(f"reference wave is zero at point {i}")
                    values.append(row[position] / row[0])
                result[name] = values
        return frequencies, result

    def fn_read_sparameters(self, sparameters) -> Dict[str, Any]:
        """Frequencies and the asked S-parameters of a sweep, with the calibration applied."""
        self._select_channels(sparameters)
        frequencies, data = self._read_raw()
        calibrated = False
        if self._correction:
            grid = self._need_sweep()
            if grid != self._cal_grid:
                raise InvalidArgumentError(
                    "the calibration was made for another frequency sweep: calibrate again or "
                    "switch the correction off"
                )
            if self._reflection is not None and "S11" in data:
                data["S11"] = self._reflection.correct(data["S11"])
                calibrated = True
            if self._thru is not None and "S21" in data:
                data["S21"] = cal.transmission_response(data["S21"], self._thru)
                calibrated = True
        parameters = {
            name: {
                "real": array("d", (v.real for v in values)),
                "imaginary": array("d", (v.imag for v in values)),
            }
            for name, values in data.items()
        }
        return {
            "frequency": array("d", frequencies),
            "parameters": parameters,
            "calibrated": calibrated,
        }

    # ----- software calibration ---------------------------------------------------------
    def fn_calibration_begin(self, kind, port, port2=None) -> None:
        """Choose the calibration: ONE_PORT on port 1 (OPEN, SHORT, LOAD) or TRANSMISSION_RESPONSE
        from port 1 to port 2 (THRU). The standards are measured with calibration_measure."""
        if kind == "TWO_PORT":
            raise ValueNotHandledError(
                "the LiteVNA is a T/R analyzer: no two-port calibration", call="calibration_begin"
            )
        if port != 1 or (kind == "TRANSMISSION_RESPONSE" and port2 != 2):
            raise ValueNotHandledError(
                "the LiteVNA has its source on port 1 and measures S21 into port 2",
                call="calibration_begin",
            )
        self._kind, self._ports = kind, (port, port2)
        self._standards, self._standards_grid = {}, None

    def fn_calibration_measure(self, standard, port, port2=None) -> None:
        """Measure a standard (OPEN, SHORT, LOAD: S11; THRU: S21), without correction."""
        if self._kind is None:
            raise InvalidArgumentError("calibration_begin must be called first")
        expected = {"ONE_PORT": ("OPEN", "SHORT", "LOAD"), "TRANSMISSION_RESPONSE": ("THRU",)}
        if standard not in expected[self._kind]:
            raise InvalidArgumentError(f"{standard} is not measured for {self._kind}")
        if (port, port2) != self._ports:
            raise InvalidArgumentError(
                f"the ports are {self._ports}, as given to calibration_begin"
            )
        needed = "S21" if standard == "THRU" else "S11"
        was_correcting, self._correction = self._correction, False
        try:
            self._select_channels([needed])
            self.fn_run_sweep()
            _, data = self._read_raw()
        finally:
            self._correction = was_correcting
        if self._standards_grid != self._need_sweep():
            self._standards = {}  # standards of another sweep cannot be mixed
        self._standards_grid = self._need_sweep()
        self._standards[standard] = data[needed]

    def fn_calibration_apply(self) -> None:
        """Compute the correction from the measured standards and switch it on."""
        if self._kind is None:
            raise InvalidArgumentError("calibration_begin must be called first")
        need = {"ONE_PORT": ("OPEN", "SHORT", "LOAD"), "TRANSMISSION_RESPONSE": ("THRU",)}[
            self._kind
        ]
        missing = [s for s in need if s not in self._standards]
        if missing:
            raise InvalidArgumentError(
                f"calibration {self._kind}: measure {', '.join(missing)} first"
            )
        if self._standards_grid != self._need_sweep():
            raise InvalidArgumentError("the standards were measured for another frequency sweep")
        if self._cal_grid not in (None, self._standards_grid):
            self._reflection = self._thru = None  # the earlier correction is for another sweep
        start, step, points = self._standards_grid
        frequencies = [start + i * step for i in range(points)]
        if self._kind == "ONE_PORT":
            s, kit = self._standards, self._kit
            self._reflection = cal.reflection_terms(
                s["OPEN"],
                s["SHORT"],
                s["LOAD"],
                cal.ideal_reflection("OPEN", frequencies, kit),
                cal.ideal_reflection("SHORT", frequencies, kit),
            )
        else:
            # the reference is the measured THRU divided by the known transmission of the THRU
            self._thru = [
                m / ideal
                for m, ideal in zip(
                    self._standards["THRU"], cal.ideal_transmission(frequencies, self._kit)
                )
            ]
        self._cal_grid = self._standards_grid
        self._correction = True

    def fn_set_calibration_kit(self, kit) -> None:
        """The kit used by the next calibration (the values of ``vna_calibration.CalKit``;
        an empty dict gives ideal standards)."""
        self._kit = cal.CalKit.from_dict(kit)

    def fn_set_correction_state(self, state) -> None:
        """Use or bypass the calibration."""
        self._correction = bool(state)

    def fn_calibration_clear(self) -> None:
        """Forget the standards and the calibration."""
        self._standards, self._standards_grid = {}, None
        self._reflection = self._thru = self._cal_grid = None
        self._correction = False
        self._kind = None

    def fn_calibration_export(self) -> Dict[str, Any]:
        """The software calibration as plain data (lists of [real, imaginary]) to be saved."""
        if self._cal_grid is None:
            raise InvalidArgumentError("there is no calibration to export")

        def pairs(values):
            return [[v.real, v.imag] for v in values]

        refl = self._reflection
        return {
            "grid": list(self._cal_grid),
            "reflection": (
                None
                if refl is None
                else {"e00": pairs(refl.e00), "e11": pairs(refl.e11), "e10e01": pairs(refl.e10e01)}
            ),
            "transmission": None if self._thru is None else pairs(self._thru),
        }

    def fn_calibration_import(self, data) -> None:
        """Restore a calibration exported earlier; the frequency sweep must be the same."""
        grid = tuple(data.get("grid", ()))
        if grid != self._need_sweep():
            raise InvalidArgumentError(
                "the calibration was made for another frequency sweep: set the same sweep first"
            )

        def values(pairs):
            return [complex(re, im) for re, im in pairs]

        refl = data.get("reflection")
        self._reflection = (
            None
            if refl is None
            else cal.Reflection(values(refl["e00"]), values(refl["e11"]), values(refl["e10e01"]))
        )
        self._thru = None if data.get("transmission") is None else values(data["transmission"])
        self._cal_grid = grid
        self._correction = True
