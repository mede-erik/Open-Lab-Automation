# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Multimeter channel of a project ``.inst`` file -> logical calls (no Qt, no I/O).

A multimeter is set by its ``.inst`` entry, as a datalogger is (``ola.datalogger_setup``): the
measurement type of its channel (``meas_type``: ``DC_V``, ``DC_A``, ``AC_V``, ``AC_A``, ``RES``,
``FREQ``, or the ``VOLT:DC`` forms) and an optional ``range`` (automatic when missing or
``AUTO``). A multimeter has one input: the first enabled channel of the entry is the one that is
measured. The integration time of the file is not sent: the logical calls of the multimeter
category have none (the datalogger does not send it either).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

Call = Tuple[str, Dict[str, Any]]

# measurement type written by the .inst editors -> function of the multimeter calls
MEAS_TYPE_FUNCTION: Dict[str, str] = {
    "DC_V": "DC_VOLTAGE",
    "VOLT:DC": "DC_VOLTAGE",
    "AC_V": "AC_VOLTAGE",
    "VOLT:AC": "AC_VOLTAGE",
    "DC_A": "DC_CURRENT",
    "CURR:DC": "DC_CURRENT",
    "AC_A": "AC_CURRENT",
    "CURR:AC": "AC_CURRENT",
    "RES": "RESISTANCE_2W",
    "FRES": "RESISTANCE_4W",
    "FREQ": "FREQUENCY",
    "PER": "PERIOD",
}


class MultimeterSetupError(ValueError):
    """The .inst entry cannot be turned into a configuration (the message tells why)."""


def measured_channel(channels: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """The channel a multimeter measures: the first enabled one (None if none is enabled)."""
    for channel in channels:
        if channel.get("enabled", True):
            return channel
    return None


def _range(channel: Mapping[str, Any]) -> Any:
    value = channel.get("range")
    if value in (None, "") or str(value).strip().upper() == "AUTO":
        return "AUTO"
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MultimeterSetupError(
            f"channel {channel.get('name', '?')!r}: range {value!r} is not a number"
        ) from exc
    if number <= 0:
        raise MultimeterSetupError(f"channel {channel.get('name', '?')!r}: range must be positive")
    return number


Accepts = Callable[[str, str], bool]  # (call, function) -> the model can send it


def accepts_from(commands: Optional[Mapping[str, Any]]) -> Accepts:
    """What a model's command set can send: the call exists and, if it translates ``function``
    with a map, the function is in it (the 34401A has no range for a frequency)."""

    def accepts(call: str, function: str) -> bool:
        command = (commands or {}).get(call)
        if not command:
            return False
        spec = (command.get("parameters") or {}).get("function") or {}
        mapped = spec.get("map")
        return not isinstance(mapped, dict) or function in mapped

    return accepts


def multimeter_calls(
    channel: Mapping[str, Any], accepts: Accepts = lambda call, function: True
) -> List[Call]:
    """The calls that set the multimeter for this channel, in the order to send: the function,
    then the automatic range or the range of the file (only if the model can send that call for
    this function)."""
    meas = str(channel.get("meas_type", "DC_V") or "DC_V").strip().upper()
    function = MEAS_TYPE_FUNCTION.get(meas)
    if function is None:
        raise MultimeterSetupError(
            f"channel {channel.get('name', '?')!r}: unknown measurement type {meas!r}"
        )
    calls: List[Call] = [("set_function", {"function": function})]
    range_ = _range(channel)
    if range_ == "AUTO":
        if accepts("set_auto_range", function):
            calls.append(("set_auto_range", {"function": function, "state": True}))
    elif accepts("set_range", function):
        calls.append(("set_range", {"function": function, "range": range_}))
    return calls


def signature(channel: Mapping[str, Any]) -> tuple:
    """A value that changes when the configuration to send changes (to configure only once)."""
    meas = str(channel.get("meas_type", "DC_V") or "DC_V").strip().upper()
    return (meas, str(channel.get("range", "AUTO") or "AUTO").strip().upper())
