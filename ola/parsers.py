"""Named parsers: turn the raw answers of several steps into one logical value.

A library call can name a parser, for example
``"parse": {"name": "siglent_waveform", "from_steps": [3, 4, 2]}``, when the answer is not a
simple number or text: a waveform described by a binary descriptor plus a block of samples.
Parsers are pure functions, no I/O; they receive the raw results of the listed steps.
"""

from __future__ import annotations

import struct
from array import array
from typing import Any, Callable, Dict

from .call_errors import ResponseNotRecognisedError

# Siglent SDS horizontal divisions of the models of the programming guide (10 for the SDS800X HD,
# SDS1000X HD, SDS2000X HD, ...)
SIGLENT_GRID = 10
WAVEDESC_SIZE = 346


def siglent_waveform(descriptor: bytes, data: bytes, timebase: float, call: str = "read_waveform"):
    """Siglent SDS waveform (``:WAVeform:PREamble?`` descriptor + ``:WAVeform:DATA?`` samples).

    Uses the formulas of the programming guide (BYTE format, signed 8-bit codes):
        voltage = code * (vertical_gain / code_per_div) - vertical_offset
        time    = delay - timebase * grid / 2 + index * sample_interval
    ``timebase`` is the horizontal scale in s/div (queried with ``:TIMebase:SCALe?``).
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
    if comm_type != 0:
        raise ResponseNotRecognisedError(
            f"call '{call}': only the BYTE format (COMM_TYPE 0) is supported, got {comm_type}",
            call=call,
        )
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
    n = min(count, len(data)) if count > 0 else len(data)
    codes = array("b")
    codes.frombytes(data[:n])
    scale = gain / code_per_div
    start = delay - timebase * SIGLENT_GRID / 2.0
    try:
        import numpy as np

        c = np.frombuffer(codes, dtype=np.int8).astype(np.float64)
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


PARSERS: Dict[str, Callable[..., Any]] = {"siglent_waveform": siglent_waveform}


def get_parser(name: str, call: str = "?") -> Callable[..., Any]:
    try:
        return PARSERS[name]
    except KeyError:
        raise ResponseNotRecognisedError(f"call '{call}': unknown parser {name!r}", call=call)
