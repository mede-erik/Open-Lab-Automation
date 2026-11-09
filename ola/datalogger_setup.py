# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Datalogger channels of a project ``.inst`` file -> logical calls.

A datalogger entry of the ``.inst`` file lists its enabled channels (``slot_number``,
``channel_id`` such as ``"103"``, ``meas_type``, optional ``range`` and ``resolution``, and for
temperature ``probe_type`` and ``sensor_type`` with the values of the library, e.g. ``TCouple``
and ``K``). This module turns them into the ordered list of
logical calls that configure the instrument: one ``configure_...`` call per group of channels
with the same function and settings, then ``select_channels`` (the scan list). The call planner
translates each call for the model in use. No Qt, no I/O.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

Call = Tuple[str, Dict[str, Any]]

# measurement type (as written by the .inst editors) -> logical configure call
MEAS_TYPE_CALLS: Dict[str, str] = {
    "VOLT:DC": "configure_dc_voltage",
    "DC_V": "configure_dc_voltage",
    "VOLT:AC": "configure_ac_voltage",
    "AC_V": "configure_ac_voltage",
    "CURR:DC": "configure_dc_current",
    "DC_A": "configure_dc_current",
    "CURR:AC": "configure_ac_current",
    "AC_A": "configure_ac_current",
    "RES": "configure_resistance",
    "FRES": "configure_fresistance",
    "FREQ": "configure_frequency",
    "PER": "configure_period",
    "TEMP": "configure_temperature",
}


class DataloggerSetupError(ValueError):
    """The .inst entry cannot be turned into a configuration (message tells which channel)."""


def channel_number(channel: Dict[str, Any]) -> int:
    """Channel number of the instrument (slot * 100 + channel, e.g. 103).

    Uses ``channel_id`` (digits only, or ``CH3`` together with ``slot_number``); an older file
    without ``channel_id`` falls back to the ``CHn`` default name.
    """
    slot = channel.get("slot_number")
    for key in ("channel_id", "name"):
        text = str(channel.get(key, "")).strip()
        if re.fullmatch(r"\d{3,4}", text):
            return int(text)
        match = re.fullmatch(r"(?i)(?:ch|chan|channel)?\s*(\d{1,2})", text)
        if match and slot is not None:
            return int(slot) * 100 + int(match.group(1))
    raise DataloggerSetupError(
        f"channel {channel.get('name', '?')!r}: cannot tell its channel number "
        "(no 'channel_id' in the .inst file)"
    )


def _setting(channel: Dict[str, Any], key: str, default: Any) -> Any:
    value = channel.get(key)
    return default if value in (None, "") else value


def datalogger_calls(channels: List[Dict[str, Any]]) -> List[Call]:
    """The configuration calls for the enabled channels of a datalogger, in the order to send."""
    enabled = [c for c in channels if c.get("enabled", True)]
    if not enabled:
        return []
    groups: Dict[tuple, List[int]] = {}
    for ch in enabled:
        meas = str(ch.get("meas_type", "VOLT:DC")).strip().upper()
        call = MEAS_TYPE_CALLS.get(meas)
        if call is None:
            raise DataloggerSetupError(
                f"channel {ch.get('name', '?')!r}: unknown measurement type {meas!r}"
            )
        number = channel_number(ch)
        if call == "configure_temperature":
            probe, sensor = ch.get("probe_type"), ch.get("sensor_type")
            if not probe or not sensor:
                raise DataloggerSetupError(
                    f"channel {ch.get('name', '?')!r}: a TEMP channel needs 'probe_type' "
                    "and 'sensor_type' in the .inst file"
                )
            key = (call, str(probe), str(sensor), _setting(ch, "resolution", "DEF"))
        else:
            key = (call, _setting(ch, "range", "AUTO"), _setting(ch, "resolution", "DEF"))
        groups.setdefault(key, []).append(number)

    calls: List[Call] = []
    for key, numbers in groups.items():
        text = ",".join(str(n) for n in sorted(numbers))
        if key[0] == "configure_temperature":
            args = {"probe_type": key[1], "type": key[2], "resolution": key[3], "channels": text}
        else:
            args = {"range": key[1], "resolution": key[2], "channels": text}
        calls.append((key[0], args))
    scan = ",".join(str(n) for n in sorted({channel_number(c) for c in enabled}))
    calls.append(("select_channels", {"channels": scan}))
    return calls


def scan_order(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The enabled channels in the order of the readings of ``read_scan`` (by channel number)."""
    enabled = [c for c in channels if c.get("enabled", True)]
    return sorted(enabled, key=channel_number)


def signature(channels: List[Dict[str, Any]]) -> Optional[tuple]:
    """A value that changes when the configuration to send changes (to configure only once)."""
    return tuple((name, tuple(sorted(args.items()))) for name, args in datalogger_calls(channels))
