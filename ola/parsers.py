# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Named parsers: turn the raw answers of several steps into one logical value.

A library call can name a parser, for example
``"parse": {"name": "siglent_waveform", "from_steps": [3, 4, 2]}``, when the answer is not a
simple number or text: a waveform described by a binary descriptor plus a block of samples.
Parsers are pure functions, no I/O; they receive the raw results of the listed steps.
"""

from __future__ import annotations

import re
import struct
import sys
from array import array
from typing import Any, Callable, Dict, List

from .call_errors import ResponseNotRecognisedError

# Siglent SDS horizontal divisions of the models of the programming guide (10 for the SDS800X HD,
# SDS1000X HD, SDS2000X HD, ...)
SIGLENT_GRID = 10
WAVEDESC_SIZE = 346


def siglent_waveform(
    descriptor: bytes,
    data: bytes,
    timebase: float,
    first_index: int = 0,
    call: str = "read_waveform",
):
    """Siglent SDS waveform (``:WAVeform:PREamble?`` descriptor + ``:WAVeform:DATA?`` samples).

    Uses the formulas of the programming guide (BYTE format, signed 8-bit codes):
        voltage = code * (vertical_gain / code_per_div) - vertical_offset
        time    = delay - timebase * grid / 2 + index * sample_interval
    ``timebase`` is the horizontal scale in s/div (queried with ``:TIMebase:SCALe?``);
    ``first_index`` the index of the first transferred point (``:WAVeform:STARt?``).
    Returns a dict with ``time`` and ``voltage`` (arrays of floats) and the descriptor values.
    """
    descriptor, data = bytes(descriptor), bytes(data)
    if len(descriptor) < WAVEDESC_SIZE or not descriptor.startswith(b"WAVEDESC"):
        raise ResponseNotRecognisedError(
            f"call '{call}': the preamble is not a Siglent WAVEDESC descriptor "
            f"({len(descriptor)} bytes)",
            call=call,
        )
    comm_type = struct.unpack_from("<h", descriptor, 32)[0]
    if comm_type not in (0, 1):
        raise ResponseNotRecognisedError(
            f"call '{call}': only the BYTE (COMM_TYPE 0) and WORD (1) formats are supported, "
            f"got {comm_type}",
            call=call,
        )
    word = comm_type == 1
    big_endian = struct.unpack_from("<h", descriptor, 34)[0] == 1  # COMM_ORDER: 0 = LSB first
    count = struct.unpack_from("<i", descriptor, 116)[0]
    gain = struct.unpack_from("<f", descriptor, 156)[0]
    offset = struct.unpack_from("<f", descriptor, 160)[0]
    code_per_div = struct.unpack_from("<f", descriptor, 164)[0]
    interval = struct.unpack_from("<f", descriptor, 176)[0]
    delay = struct.unpack_from("<d", descriptor, 180)[0]
    if code_per_div == 0 or interval <= 0:
        raise ResponseNotRecognisedError(
            f"call '{call}': invalid descriptor (code_per_div={code_per_div}, interval={interval})",
            call=call,
        )
    width = 2 if word else 1
    n = min(count, len(data) // width) if count > 0 else len(data) // width
    codes = array("h" if word else "b")
    codes.frombytes(data[: n * width])
    if word and big_endian != (sys.byteorder == "big"):
        codes.byteswap()
    if code_per_div >= 256 and not word:
        # SDS HD scopes report the 16-bit scale (30 codes/div * 256 = 7680) in the descriptor even
        # when the data are bytes (verified on an SDS824X HD with a 3 V probe-compensation signal):
        # a byte code is worth 256 times more than the descriptor says.
        code_per_div = code_per_div / 256.0
    scale = gain / code_per_div
    # ``first_index`` is the index of the first transferred point (:WAVeform:STARt) when the
    # memory is read in blocks
    start = delay - timebase * SIGLENT_GRID / 2.0 + int(first_index) * interval
    try:
        import numpy as np

        c = np.frombuffer(codes, dtype=np.int16 if word else np.int8).astype(np.float64)
        voltage = array("d")
        voltage.frombytes((c * scale - offset).tobytes())
        time = array("d")
        time.frombytes((start + np.arange(n, dtype=np.float64) * interval).tobytes())
    except ImportError:
        voltage = array("d", (code * scale - offset for code in codes))
        time = array("d", (start + i * interval for i in range(n)))
    return {
        "time": time,
        "voltage": voltage,
        "points": n,
        "sample_interval": interval,
        "vertical_gain": gain,
        "vertical_offset": offset,
        "trigger_delay": delay,
        "timebase": timebase,
    }


def _numbers(text: Any, call: str, what: str) -> List[float]:
    """Comma-separated numbers of an ASCII answer."""
    try:
        return [float(x) for x in str(text).replace("\n", ",").split(",") if x.strip()]
    except ValueError:
        raise ResponseNotRecognisedError(
            f"call '{call}': the answer for {what} is not a list of numbers: {str(text)[:40]!r}",
            call=call,
        )


def vna_sparameters(
    correction_state: Any,
    frequencies: Any,
    *data: Any,
    sparameters,
    call: str = "read_sparameters",
):
    """Result of ``read_sparameters`` of an SCPI network analyzer (ASCII answers).

    The answers, in order: the state of the error correction (``1``/``0``/``ON``/``OFF``), the
    frequencies of the sweep points, and one list ``real, imaginary, real, imaginary, ...`` for each
    requested S-parameter. Returns ``{"frequency", "parameters": {name: {"real", "imaginary"}},
    "calibrated"}`` with arrays of floats.
    """
    if len(data) != len(sparameters):
        raise ResponseNotRecognisedError(
            f"call '{call}': {len(sparameters)} S-parameters asked, {len(data)} answers received",
            call=call,
        )
    freq = _numbers(frequencies, call, "the frequencies")
    parameters = {}
    for name, text in zip(sparameters, data):
        values = _numbers(text, call, name)
        if len(values) != 2 * len(freq):
            raise ResponseNotRecognisedError(
                f"call '{call}': {name} has {len(values)} values for {len(freq)} frequencies "
                "(expected real and imaginary parts)",
                call=call,
            )
        parameters[name] = {"real": array("d", values[0::2]), "imaginary": array("d", values[1::2])}
    state = str(correction_state).strip().upper() in ("1", "ON", "TRUE")
    return {"frequency": array("d", freq), "parameters": parameters, "calibrated": state}


_HP6030_READBACK = re.compile(r"^\s*([NLF])\s*([VA])\s*([-+]?\d*\.?\d+)\s*$")


def _hp6030_readback(answer: Any, quantity: str, call: str) -> float:
    """The readback of an HP 6030-series supply (6034A): ``<status><unit><number>``.

    The status letter is ``N`` (normal), ``L`` (limit mode) or ``F`` (a fault, a disabled supply, or
    no measurement taken: the manual gives ``FV999999``); the unit letter is ``V`` or ``A``. The
    supply reads the load-dependent quantity only: the current while it is a voltage source and the
    voltage while it is a current source, so a readback of the other quantity is refused.
    """
    text = str(answer).strip()
    match = _HP6030_READBACK.match(text)
    if match is None:
        raise ResponseNotRecognisedError(
            f"call '{call}': {text[:40]!r} is not a readback of the supply (a status letter, "
            "V or A, and a number)",
            call=call,
        )
    status, unit, number = match.groups()
    if status == "F":
        raise ResponseNotRecognisedError(
            f"call '{call}': the supply answered {text!r}: it is unregulated, disabled or in a "
            "fault mode, or no measurement was taken",
            call=call,
        )
    if unit != quantity:
        raise ResponseNotRecognisedError(
            f"call '{call}': the supply reads {'current' if unit == 'A' else 'voltage'}: it can "
            "only read the quantity it does not regulate (the current in voltage mode, the "
            "voltage in current mode)",
            call=call,
        )
    return float(number)


def hp6030_readback_voltage(answer: Any, call: str = "read_voltage") -> float:
    """Voltage, in volts, of an HP 6030-series readback (see ``_hp6030_readback``)."""
    return _hp6030_readback(answer, "V", call)


def hp6030_readback_current(answer: Any, call: str = "read_current") -> float:
    """Current, in amperes, of an HP 6030-series readback (see ``_hp6030_readback``)."""
    return _hp6030_readback(answer, "A", call)


def spectrum_trace_ascii(answer: Any, call: str = "read_trace") -> List[float]:
    """The points of a spectrum analyzer trace read in the ASCII format.

    The Rigol analyzers (DSA800, RSA3000) put a definite length block header (``#9000009014``) in
    front of the numbers, the Siglent ones do not; the numbers are separated by commas (and a
    space) and may end with a comma. Returns the list of floats; ``ResponseNotRecognisedError`` for
    an empty answer or a point that is not a number.
    """
    text = str(answer).strip()
    if text.startswith("#"):
        digits = int(text[1]) if len(text) > 1 and text[1].isdigit() else 0
        text = text[2 + digits :]
    parts = [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]
    if not parts:
        raise ResponseNotRecognisedError(
            f"call '{call}': the trace answer has no points", call=call
        )
    try:
        return [float(x) for x in parts]
    except ValueError:
        raise ResponseNotRecognisedError(
            f"call '{call}': a point of the trace is not a number: {text[:40]!r}", call=call
        ) from None


PARSERS: Dict[str, Callable[..., Any]] = {
    "siglent_waveform": siglent_waveform,
    "vna_sparameters": vna_sparameters,
    "hp6030_readback_voltage": hp6030_readback_voltage,
    "hp6030_readback_current": hp6030_readback_current,
    "spectrum_trace_ascii": spectrum_trace_ascii,
}


def get_parser(name: str, call: str = "?") -> Callable[..., Any]:
    """The named parser of a library ``parse`` entry; CALL-005 if the name is unknown."""
    try:
        return PARSERS[name]
    except KeyError:
        raise ResponseNotRecognisedError(f"call '{call}': unknown parser {name!r}", call=call)
