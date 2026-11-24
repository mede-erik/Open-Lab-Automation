# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Oscilloscope settings of a project ``.was`` file -> logical calls.

The ``.was`` file holds vendor-agnostic settings (time/div, volt/div, offset, coupling, trigger
source/level/slope/mode). This module turns them into an ordered list of logical calls
``(call_name, arguments)``; the call planner translates each call for the model in use.
No Qt, no I/O.

The file is the **scope settings** of a project (``Project.scope_settings``, a project definition
file like the ``.inst``, not a measurement). The key ``reset`` (default true: the instrument is
reset first, as it always was) can be false to apply only what the file says and keep the rest of
what is set on the oscilloscope. ``check_was`` says what is wrong with a file.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

Call = Tuple[str, Dict[str, Any]]


def extract_channel_number(ch_ref) -> Optional[int]:
    """'CH1', 'CHAN1', 'C1', '1' -> 1; None if there is no number."""
    if ch_ref is None:
        return None
    if isinstance(ch_ref, (int, float)):
        return int(ch_ref)
    digits = "".join(d for d in str(ch_ref) if d.isdigit())
    return int(digits) if digits else None


def parse_voltage_value(value) -> Optional[float]:
    """'2V', '2', '0.5V', '100mV' -> volts; None if not parsable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower().replace(",", ".")
    try:
        if s.endswith("mv"):
            return float(s[:-2]) * 1e-3
        if s.endswith("v"):
            return float(s[:-1])
        return float(s)
    except ValueError:
        return None


TRIGGER_SLOPES = ("RISE", "FALL")
TRIGGER_MODES = ("AUTO", "NORM", "NORMAL", "SINGLE")


def reset_wanted(was_data: Dict[str, Any]) -> bool:
    """True if the instrument is reset before the settings are applied (the default: the key
    ``reset`` is missing or true)."""
    return was_data.get("reset", True) is not False


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_was(was_data: Any) -> List[str]:
    """What is wrong with the content of a ``.was`` file, as readable sentences (empty list: it can
    be applied). An empty object is valid: nothing is set."""
    if not isinstance(was_data, dict):
        return ["the settings must be an object"]
    problems: List[str] = []
    if "reset" in was_data and not isinstance(was_data["reset"], bool):
        problems.append("'reset' must be true or false")
    settings = was_data.get("settings", {})
    if not isinstance(settings, dict):
        problems.append("'settings' must be an object")
    elif "time_per_div" in settings:
        tdiv = settings["time_per_div"]
        if not _number(tdiv) or tdiv <= 0:
            problems.append("the time base (settings.time_per_div) must be a number above 0")
    channels = was_data.get("channels", [])
    if not isinstance(channels, (list, dict)):
        problems.append("'channels' must be a list")
        channels = []
    seen = set()
    items = channels.items() if isinstance(channels, dict) else enumerate(channels)
    for key, ch in items:
        if not isinstance(ch, dict):
            problems.append(f"channel {key}: must be an object")
            continue
        ref = ch.get("channel_id", key)
        number = extract_channel_number(ref) if isinstance(ref, str) else ref
        if not isinstance(number, int) or number < 1:
            problems.append(f"channel {ref!r}: no channel number")
        elif number in seen:
            problems.append(f"channel {number} is set twice")
        else:
            seen.add(number)
        if "enabled" in ch and not isinstance(ch["enabled"], bool):
            problems.append(f"channel {ref!r}: 'enabled' must be true or false")
        for field in ("offset", "probe_attenuation"):
            if field in ch and not _number(ch[field]):
                problems.append(f"channel {ref!r}: '{field}' must be a number")
        scale = ch.get("volt_per_div", ch.get("scale"))
        if scale is not None and parse_voltage_value(scale) is None:
            problems.append(f"channel {ref!r}: the volts per division {scale!r} is not a number")
    trigger = was_data.get("trigger", {})
    if not isinstance(trigger, dict):
        problems.append("'trigger' must be an object")
    else:
        if "source" in trigger and not extract_channel_number(str(trigger["source"])):
            problems.append(f"trigger: the source {trigger['source']!r} is not a channel")
        if "level" in trigger and not _number(trigger["level"]):
            problems.append("trigger: the level must be a number")
        if "slope" in trigger and str(trigger["slope"]).upper() not in TRIGGER_SLOPES:
            problems.append(f"trigger: the slope must be one of {', '.join(TRIGGER_SLOPES)}")
        if "mode" in trigger and str(trigger["mode"]).upper() not in TRIGGER_MODES:
            problems.append(f"trigger: the mode must be one of {', '.join(TRIGGER_MODES)}")
    return problems


def oscilloscope_calls_from_was(was_data: Dict[str, Any]) -> List[Call]:
    """Ordered logical calls that apply the settings of a ``.was`` file. The first one is the
    ``reset`` of the instrument, unless the file says ``"reset": false``."""
    calls: List[Call] = [("reset", {})] if reset_wanted(was_data) else []

    settings = was_data.get("settings", {})
    if "time_per_div" in settings:
        calls.append(("set_timebase_scale", {"value": settings["time_per_div"]}))

    channels = was_data.get("channels", [])
    if isinstance(channels, dict):
        items = list(channels.items())
    else:
        items = [(ch.get("channel_id", ""), ch) for ch in channels]
    for ch_ref, ch in items:
        if isinstance(ch, dict) and "channel_id" in ch:
            ch = {
                "scale": ch.get("volt_per_div"),
                "offset": ch.get("offset"),
                "coupling": ch.get("coupling"),
                "enabled": ch.get("enabled"),
                "attenuation": ch.get("probe_attenuation"),
            }
        number = extract_channel_number(ch_ref) if isinstance(ch_ref, str) else ch_ref
        enabled = ch.get("enabled")
        if enabled is not None:
            # a channel that is off ignores its settings: turn it on first, or just off
            calls.append(("set_channel_state", {"channel_number": number, "state": bool(enabled)}))
            if not enabled:
                continue
        if ch.get("attenuation") is not None:
            # before the scale: the scale is the one at the probe tip
            calls.append(
                ("set_probe_attenuation", {"channel_number": number, "value": ch["attenuation"]})
            )
        scale = parse_voltage_value(ch.get("scale"))
        if scale is not None:
            calls.append(("set_channel_scale", {"channel_number": number, "value": scale}))
        if ch.get("offset") is not None:
            calls.append(("set_channel_offset", {"channel_number": number, "value": ch["offset"]}))
        if ch.get("coupling") is not None:
            calls.append(
                (
                    "set_channel_coupling",
                    {"channel_number": number, "coupling_type": ch["coupling"]},
                )
            )

    trigger = was_data.get("trigger", {})
    if trigger:
        trigger_ch = extract_channel_number(trigger.get("source", ""))
        if "source" in trigger and trigger_ch:
            calls.append(("set_trigger_source", {"channel_number": trigger_ch}))
        if "level" in trigger:
            calls.append(
                ("set_trigger_level", {"value": trigger["level"], "channel_number": trigger_ch})
            )
        if "slope" in trigger:
            calls.append(("set_trigger_slope", {"slope": trigger["slope"]}))
        if "mode" in trigger:
            calls.append(("set_trigger_mode", {"mode": trigger["mode"]}))

    return calls
