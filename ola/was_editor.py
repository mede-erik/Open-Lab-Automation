# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the editor of a ``.was`` file (oscilloscope settings) does with the file. No Qt.

``frontend/ui/WasFileDialog.py`` only draws the form; this module owns the data:

* ``WasEditor`` keeps the content of the file (``data``), reads it (a missing or broken file starts
  from an empty one), turns it into the values the form shows (``form``), takes the values of the
  form back (``apply``), reads and writes the text of the JSON editor (``text``, ``set_text``) and
  saves the file atomically (``save``);
* ``parse_time`` and ``parse_level`` read what the person types (``1ms``, ``100us``, ``1,5``);
* ``oscilloscopes`` lists the oscilloscopes of the ``.inst`` file with their channels.

``reset`` is written only when it is false (the default is to reset the instrument first), so the
files made before the key existed stay as they are. The checks of the content are in
``ola.was_calls.check_was``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from .fileio import atomic_write_text

VOLT_OPTIONS = (
    "1mV", "2mV", "5mV", "10mV", "20mV", "50mV", "100mV", "200mV", "500mV",
    "1V", "2V", "5V", "10V", "20V", "50V", "100V",
)  # fmt: skip
DEFAULT_CHANNELS = 4
_MULTIPLIERS = {"k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}


def empty_data() -> Dict[str, Any]:
    """The content of a new file."""
    return {"type": "oscilloscope_settings", "channels": [], "settings": {}}


def parse_time(text: Any) -> Optional[float]:
    """A time in seconds from what the person typed: plain numbers (``0.001``, ``1e-3``) and SI
    suffixes with or without ``s`` (``ks``, ``ms``, ``100us``, ``µs``, ``ns``, ``ps``, ``m``...);
    None if it is not a time."""
    clean = str(text).strip().lower().replace(",", ".").replace(" ", "").replace("µ", "u")
    if clean.endswith("s"):
        clean = clean[:-1]
    factor = 1.0
    if clean and clean[-1] in _MULTIPLIERS:
        factor = _MULTIPLIERS[clean[-1]]
        clean = clean[:-1]
    try:
        return float(clean) * factor
    except ValueError:
        return None


def parse_level(text: Any) -> Optional[float]:
    """A trigger level in volts from what was typed (``1,5`` is 1.5); None if not a number."""
    try:
        return float(str(text).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def default_channels() -> List[Dict[str, Any]]:
    """The channels shown when the project has no oscilloscope: four, all off."""
    return [
        {"channel_id": f"CH{i + 1}", "name": f"CH{i + 1}", "enabled": False,
         "volt_per_div": "1V", "probe_attenuation": 1.0}
        for i in range(DEFAULT_CHANNELS)
    ]  # fmt: skip


def oscilloscopes(inst_path: Union[str, Path, None]) -> List[Dict[str, Any]]:
    """The oscilloscopes of an ``.inst`` file: ``{"instance_name", "model_id", "channels"}``.
    Empty if there is no file or it cannot be read."""
    if not inst_path:
        return []
    try:
        data = json.loads(Path(inst_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = []
    for inst in data.get("instruments", []) if isinstance(data, Mapping) else []:
        if isinstance(inst, Mapping) and inst.get("instrument_type") in (
            "oscilloscope", "oscilloscopes",
        ):  # fmt: skip
            found.append({
                "instance_name": inst.get("instance_name", "OSC"),
                "model_id": inst.get("model_id", inst.get("model", "")),
                "channels": inst.get("channels", []),
            })  # fmt: skip
    return found


def channels_of(scopes: List[Dict[str, Any]], instance_name: Optional[str] = None) -> list:
    """The channels of one oscilloscope of ``oscilloscopes`` (first one if the name is unknown)."""
    if not scopes:
        return []
    if instance_name is not None:
        for scope in scopes:
            if scope["instance_name"] == instance_name:
                return scope["channels"]
    return scopes[0]["channels"]


class WasEditor:
    """The content of one ``.was`` file and the operations of the editor on it."""

    def __init__(self, data: Optional[Mapping[str, Any]] = None):
        self.data: Dict[str, Any] = dict(data) if data is not None else empty_data()

    @staticmethod
    def load(path: Union[str, Path]) -> "WasEditor":
        """Read a file; a missing, unreadable or not-an-object file gives an empty editor."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return WasEditor()
        return WasEditor(data if isinstance(data, dict) else None)

    def save(self, path: Union[str, Path]) -> None:
        """Write the file (atomically, indented)."""
        atomic_write_text(path, json.dumps(self.data, indent=2) + "\n")

    def text(self) -> str:
        """The content as the JSON editor shows it."""
        return json.dumps(self.data, indent=2)

    def set_text(self, text: str) -> None:
        """Take the text of the JSON editor; ``ValueError`` if it is not a JSON object (the
        content is left as it was)."""
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("a .was file is a JSON object")
        self.data = data

    def form(self) -> Dict[str, Any]:
        """The values of the form: ``reset``, ``time_per_div`` (text, '' if none), ``channels``
        (id -> ``(enabled, volt_per_div)``) and ``trigger`` (the dict of the file)."""
        settings = self.data.get("settings") or {}
        channels = {}
        for ch in self.data.get("channels") or []:
            if isinstance(ch, Mapping) and ch.get("channel_id"):
                channels[ch["channel_id"]] = (
                    bool(ch.get("enabled", False)),
                    str(ch.get("volt_per_div", "1V")),
                )
        return {
            "reset": self.data.get("reset", True) is not False,
            "time_per_div": str(settings.get("time_per_div", "")),
            "channels": channels,
            "trigger": dict(self.data.get("trigger") or {}),
        }

    def apply(
        self,
        reset: bool,
        time_text: str,
        channels: List[Mapping[str, Any]],
        trigger: Optional[Mapping[str, Any]],
    ) -> None:
        """Put the values of the form in the content. ``channels`` is every channel of the form
        with ``channel_id``, ``name``, ``enabled``, ``volt_per_div`` and ``probe_attenuation``:
        only the enabled ones are written. A time that does not parse leaves the old one."""
        if reset:
            self.data.pop("reset", None)
        else:
            self.data["reset"] = False
        seconds = parse_time(time_text)
        if seconds is not None:
            self.data.setdefault("settings", {})["time_per_div"] = seconds
        self.data["channels"] = [
            {
                "channel_id": ch["channel_id"],
                "name": ch.get("name", ch["channel_id"]),
                "enabled": True,
                "volt_per_div": ch.get("volt_per_div", "1V"),
                "probe_attenuation": ch.get("probe_attenuation", 1.0),
            }
            for ch in channels
            if ch.get("enabled")
        ]
        if trigger:
            self.data["trigger"] = dict(trigger)


__all__ = [
    "DEFAULT_CHANNELS", "VOLT_OPTIONS", "WasEditor", "channels_of", "default_channels",
    "empty_data", "oscilloscopes", "parse_level", "parse_time",
]  # fmt: skip
