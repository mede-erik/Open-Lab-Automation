# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Whole-memory waveform transfer built from the logical calls.

``read_waveform`` transfers one block (an instrument can send only so many points in one
transfer). ``read_waveform_full`` stops the acquisition, so that every block comes from the same
capture, and reads the blocks one after the other until the whole memory is transferred.
"""

from __future__ import annotations

import re
from array import array
from typing import Any, Dict, Optional

from .call_errors import CallError

_POINTS = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([KkMm]?)\s*(?:pts)?\s*$")
_MULTIPLIER = {"": 1, "K": 1_000, "M": 1_000_000}


def parse_points(value: Any) -> Optional[int]:
    """'10M' -> 10000000, '500k' -> 500000, 1000 -> 1000. None if it is not a point count."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    match = _POINTS.match(str(value))
    if not match:
        return None
    return int(float(match.group(1)) * _MULTIPLIER[match.group(2).upper()])


def read_waveform_full(
    handle: Any,
    channel_number: int,
    bits: int = 8,
    stop: bool = True,
    max_blocks: int = 1000,
) -> Dict[str, Any]:
    """Read the whole acquisition memory of a channel as one ``read_waveform`` result.

    * ``stop``: stop the acquisition first (``stop_acquisition``). The acquisition is left
      stopped; start it again with ``run_acquisition``.
    * The block size is the model's ``query_waveform_max_points``; the total is the memory depth
      (``set_acquisition_depth`` read back). Without a depth the blocks are read until one comes
      back shorter than the block size.
    * The result has the keys of ``read_waveform`` plus ``blocks``.
    """
    if stop and handle.supports("stop_acquisition"):
        handle.call("stop_acquisition")

    block = None
    if handle.supports("query_waveform_max_points"):
        block = parse_points(handle.call("query_waveform_max_points"))
    depth = None
    if handle.supports("set_acquisition_depth"):
        try:
            depth = parse_points(handle.readback("set_acquisition_depth"))
        except CallError:
            depth = None

    result: Optional[Dict[str, Any]] = None
    time, voltage = array("d"), array("d")
    blocks = 0
    while blocks < max_blocks:
        got = handle.call(
            "read_waveform",
            channel_number=channel_number,
            bits=bits,
            start=len(voltage),
            points=block or 0,
        )
        if result is None:
            result = got
        n = got["points"]
        if n <= 0:
            break
        time.extend(got["time"])
        voltage.extend(got["voltage"])
        blocks += 1
        if depth is not None and len(voltage) >= depth:
            break
        if block is None or n < block:
            break

    if result is None or not len(voltage):
        raise CallError(
            "read_waveform_full: the instrument returned no points", call="read_waveform"
        )
    full = dict(result)
    full.update(time=time, voltage=voltage, points=len(voltage), blocks=blocks)
    return full
