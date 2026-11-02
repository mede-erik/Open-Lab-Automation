"""Oscilloscope settings of a project ``.was`` file -> logical calls.

The ``.was`` file holds vendor-agnostic settings (time/div, volt/div, offset, coupling, trigger
source/level/slope/mode). This module turns them into an ordered list of logical calls
``(call_name, arguments)``; the call planner translates each call for the model in use.
No Qt, no I/O.
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


def oscilloscope_calls_from_was(was_data: Dict[str, Any]) -> List[Call]:
    """Ordered logical calls that apply the settings of a ``.was`` file."""
    calls: List[Call] = [("reset", {})]

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
            ch = {"scale": ch.get("volt_per_div"), "offset": ch.get("offset"), "coupling": ch.get("coupling")}
        number = extract_channel_number(ch_ref) if isinstance(ch_ref, str) else ch_ref
        scale = parse_voltage_value(ch.get("scale"))
        if scale is not None:
            calls.append(("set_channel_scale", {"channel_number": number, "value": scale}))
        if ch.get("offset") is not None:
            calls.append(("set_channel_offset", {"channel_number": number, "value": ch["offset"]}))
        if ch.get("coupling") is not None:
            calls.append(("set_channel_coupling", {"channel_number": number, "coupling_type": ch["coupling"]}))

    trigger = was_data.get("trigger", {})
    if trigger:
        trigger_ch = extract_channel_number(trigger.get("source", ""))
        if "source" in trigger and trigger_ch:
            calls.append(("set_trigger_source", {"channel_number": trigger_ch}))
        if "level" in trigger:
            calls.append(("set_trigger_level", {"value": trigger["level"], "channel_number": trigger_ch}))
        if "slope" in trigger:
            calls.append(("set_trigger_slope", {"slope": trigger["slope"]}))
        if "mode" in trigger:
            calls.append(("set_trigger_mode", {"mode": trigger["mode"]}))

    calls.append(("auto_setup", {}))
    return calls
