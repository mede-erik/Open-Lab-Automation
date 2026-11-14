# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the remote-control panel of an electronic load can show, and the calls it sends (no Qt).

The panel shows only what the model defines in the library: the modes its ``set_mode``
translates (CC, CV, CR, CP), the readings it has, the protections (OVP, OCP, OPP) it can set.
The load calls have no channel argument: on a load with several channels the channel is chosen
first with ``select_channel`` (when the model has it). A setpoint is checked against the limits of
the channel in the ``.inst`` file before anything is sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MODES = ("CC", "CV", "CR", "CP")
SETPOINT_CALL = {
    "CC": "set_current_level",
    "CV": "set_voltage_level",
    "CR": "set_resistance_level",
    "CP": "set_power_level",
}
UNIT = {"CC": "A", "CV": "V", "CR": "Ohm", "CP": "W"}
READINGS = (("read_voltage", "V"), ("read_current", "A"), ("read_power", "W"))
PROTECTIONS = ("ovp", "ocp", "opp")
# the channel limit (key of the .inst channel) a setpoint of each mode must not exceed
LIMIT_KEY = {"CC": "max_current", "CV": "max_voltage", "CP": "max_power"}


@dataclass
class LoadControls:
    """The controls of an electronic load model."""

    calls: List[str] = field(default_factory=list)
    modes: List[str] = field(default_factory=list)
    readings: List[Tuple[str, str]] = field(default_factory=list)
    protections: List[str] = field(default_factory=list)

    def has(self, call: str) -> bool:
        """True if the model defines this logical call."""
        return call in self.calls


def _translated(command: Optional[Dict[str, Any]], arg: str, values: Sequence[str]) -> List[str]:
    """The values of ``arg`` the command translates (the keys of its map), in schema order;
    all of them if the command has no map."""
    spec = ((command or {}).get("parameters") or {}).get(arg) or {}
    mapped = spec.get("map") if isinstance(spec.get("map"), dict) else None
    for other in ((command or {}).get("parameters") or {}).values():
        if mapped is None and isinstance(other, dict) and other.get("from") == arg:
            mapped = other.get("map") if isinstance(other.get("map"), dict) else None
    return [v for v in values if mapped is None or v in mapped]


def load_controls(library: Any, model_id: str) -> LoadControls:
    """What the panel of this electronic-load model shows (empty if it is not in the library)."""
    commands = library.commands(model_id) or {}
    calls = [name for name, spec in commands.items() if spec]
    modes = []
    if "set_mode" in calls:
        translated = _translated(commands.get("set_mode"), "mode", MODES)
        modes = [m for m in translated if SETPOINT_CALL[m] in calls]
    if not modes:  # no mode switch: the setpoints it has, without choosing a mode
        modes = [m for m in MODES if SETPOINT_CALL[m] in calls][:1]
    return LoadControls(
        calls=calls,
        modes=modes,
        readings=[(c, u) for c, u in READINGS if c in calls],
        protections=[p for p in PROTECTIONS if f"set_{p}_level" in calls or f"enable_{p}" in calls],
    )


def channel_number(channel: Mapping[str, Any]) -> Optional[int]:
    """The number of a channel of the ``.inst`` file (``channel_id`` like ``CH2`` or 2)."""
    raw = str(channel.get("channel_id", "") or "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    return int(digits) if digits else None


def select_first(controls: LoadControls, number: Optional[int]) -> List[Tuple[str, Dict[str, Any]]]:
    """The ``select_channel`` call that must come first on this channel (none if the model has
    no such call or the channel has no number)."""
    if number is None or not controls.has("select_channel"):
        return []
    return [("select_channel", {"channel_number": number})]


def check_setpoint(mode: str, value: float, channel: Mapping[str, Any]) -> List[str]:
    """Problems of a setpoint (translation keys; empty: it can be sent): negative, or above the
    limit the ``.inst`` file gives the channel for this mode (0 or missing: no limit)."""
    if value < 0:
        return ["el_err_negative"]
    key = LIMIT_KEY.get(mode)
    try:
        limit = float(channel.get(key) or 0) if key else 0.0
    except (TypeError, ValueError):
        limit = 0.0
    if limit > 0 and value > limit:
        return ["el_err_limit"]
    return []


def setpoint_calls(
    controls: LoadControls, mode: str, value: float, number: Optional[int]
) -> List[Tuple[str, Dict[str, Any]]]:
    """The calls that put the channel in ``mode`` with this setpoint."""
    calls = select_first(controls, number)
    if controls.has("set_mode"):
        calls.append(("set_mode", {"mode": mode}))
    calls.append((SETPOINT_CALL[mode], {"value": float(value)}))
    return calls


def input_calls(controls: LoadControls, on: bool, number: Optional[int]):
    """The calls that switch the input of the channel on or off."""
    return select_first(controls, number) + [("load_on" if on else "load_off", {})]


def protection_calls(
    controls: LoadControls, kind: str, enabled: bool, level: Optional[float], number: Optional[int]
) -> List[Tuple[str, Dict[str, Any]]]:
    """The calls that set a protection (``ovp``, ``ocp``, ``opp``): the level (if given) and then
    enable it, or disable it (only if the model can)."""
    calls = select_first(controls, number)
    if enabled:
        if level is not None and controls.has(f"set_{kind}_level"):
            calls.append((f"set_{kind}_level", {"value": float(level)}))
        if controls.has(f"enable_{kind}"):
            calls.append((f"enable_{kind}", {}))
    elif controls.has(f"disable_{kind}"):
        calls.append((f"disable_{kind}", {}))
    return calls
