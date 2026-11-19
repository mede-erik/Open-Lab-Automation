# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Give every entry of an ``.inst`` file all the information its model has (no Qt).

The instrument file is what the measurements read: the channels of a supply, a load, a multimeter,
a datalogger or an oscilloscope, the slots of a datalogger or a switch unit, the ports and the usual
sweep of a network analyzer. An entry that was only added (for instance by the network scan) has
none of them until someone opens it, and a measurement would find it empty. ``complete_entry`` adds
what is missing from the library (channels disabled, with the limits of the model; nothing already
in the entry is changed or removed) and ``complete_entries`` does it for the whole file.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .inst_file import POWER_TYPES, default_sweep, entry_type, port_options, resize_ports

DEFAULT_SCOPE_CHANNELS = 4


def _caps(library: Any, entry: Dict[str, Any], kind: str) -> Dict[str, Any]:
    try:
        caps = library.get_model_capabilities(
            kind, entry.get("series", ""), entry.get("model_id")
        )
    except Exception:
        caps = None
    return caps if isinstance(caps, dict) else {}


def _ids(library: Any, entry: Dict[str, Any], kind: str) -> List[str]:
    try:
        return [str(i) for i in library.get_channel_ids(
            kind, entry.get("series", ""), entry.get("model_id"))]
    except Exception:
        return []


def _count(entry: Dict[str, Any], caps: Dict[str, Any], default: int = 0) -> int:
    value = caps.get("number_of_channels", entry.get("num_channels", default))
    if isinstance(value, list):
        value = len(value)
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _fill_channels(library: Any, entry: Dict[str, Any], kind: str, caps: Dict[str, Any]) -> None:
    count = _count(entry, caps, DEFAULT_SCOPE_CHANNELS if kind == "oscilloscope" else 0)
    ids = _ids(library, entry, kind)
    count = count or len(ids)  # a single-input load has no channel definition: CH1
    if kind == "oscilloscope" and not caps:
        count = max(count, len(entry.get("channels") or []))
    channels = entry.get("channels")
    channels = channels if isinstance(channels, list) else []
    while len(channels) < count:
        index = len(channels)
        name = ids[index] if index < len(ids) else f"CH{index + 1}"
        channel: Dict[str, Any] = {"enabled": False, "name": name}
        if kind in POWER_TYPES:
            try:
                limits = library.get_channel_limits(
                    kind, entry.get("series", ""), entry.get("model_id"))
            except Exception:
                limits = {}
            channel["max_current"] = limits.get("max_current") or 0.0
            channel["max_voltage"] = limits.get("max_voltage") or 0.0
            if limits.get("max_power"):
                channel["max_power"] = limits["max_power"]
        elif kind == "multimeter":
            channel.update(meas_type="DC_V", attenuation=1.0, unit="V", integration_time=0.0)
        elif kind == "oscilloscope":
            channel.update(channel_id=name, probe_attenuation=1.0)
        else:
            channel.update(meas_type="DC_V", unit="V")
        channels.append(channel)
    if kind == "oscilloscope":
        for index, channel in enumerate(channels):
            if isinstance(channel, dict):
                default = ids[index] if index < len(ids) else f"CH{index + 1}"
                channel.setdefault("channel_id", default)
                channel.setdefault("probe_attenuation", 1.0)
    if channels or "channels" in entry:
        entry["channels"] = channels
    if count and not entry.get("num_channels"):
        entry["num_channels"] = count


def _fill_slots(entry: Dict[str, Any], caps: Dict[str, Any], datalogger: bool) -> None:
    count = caps.get("number_of_slots")
    count = count if isinstance(count, int) and not isinstance(count, bool) and count > 0 else 0
    known = {s.get("slot_number"): s for s in entry.get("slots") or [] if isinstance(s, dict)}
    for number in range(1, count + 1):
        if number not in known:
            known[number] = (
                {"slot_number": number, "module_id": None, "channels": []}
                if datalogger
                else {"slot_number": number, "module_id": ""}
            )
    if known:
        entry["slots"] = [known[n] for n in sorted(k for k in known if isinstance(k, int))]


def complete_entry(library: Any, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Add to ``entry`` what its model has and it lacks; returns it. A manual instrument and an
    entry whose model is not in the library are left as they are (``library`` is
    ``frontend.core.LoadInstruments``: ``get_model_capabilities``, ``get_channel_ids`` and
    ``get_channel_limits``)."""
    kind = entry_type(entry)
    if entry.get("is_manual") or not kind:
        return entry
    caps = _caps(library, entry, kind)
    if kind in POWER_TYPES or kind in ("multimeter", "oscilloscope"):
        _fill_channels(library, entry, kind, caps)
    elif kind == "datalogger":
        if caps.get("number_of_slots"):
            _fill_slots(entry, caps, True)
        else:
            _fill_channels(library, entry, kind, caps)
    elif kind == "network_analyzer":
        if not entry.get("ports"):
            resize_ports(entry, port_options(caps)[0])
        if not entry.get("sweep"):
            entry["sweep"] = default_sweep(caps)
    elif kind == "switch_unit":
        _fill_slots(entry, caps, False)
    return entry


def complete_entries(library: Any, entries: Sequence[Dict[str, Any]]) -> None:
    """``complete_entry`` for every entry of the file."""
    for entry in entries:
        if isinstance(entry, dict):
            complete_entry(library, entry)
