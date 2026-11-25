# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Convert the efficiency files of a project of the first format (``eff_files``) to measurements.

A project made before ``format_version`` listed its efficiency files in ``eff_files`` and each file
held only the sweeps and two delays::

    {"type": "efficiency",
     "sweeps": [{"variable": "Vin", "config": {"mode": "list", "values": [9, 12]}},
                {"variable": "Iout", "config": {"mode": "range", "start": 0.1, "stop": 1,
                                                 "points": 5}}],
     "measured_variables": ["Iout", "Vin"],
     "timing": {"delay_between_points": 0.5, "delay_between_loops": 1.0}}

The first sweep of the list was the **outer** one; in the current format the first parameter is the
innermost, so the order is reversed. ``delay_between_points`` becomes ``timing.settle_s`` and
``delay_between_loops`` becomes ``timing.cooldown_s``. The old files did not say **which
instrument call** sets a quantity: every swept variable gets its sweep and no ``set``, and the
conversion says so (the editor of the measurement asks for the call). Nothing is lost: the old file
is copied to ``<name>.bkp`` before it is overwritten, and what cannot be carried over is listed in
the notes. No Qt.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

MEASUREMENT_TYPE = "efficiency"
MODULE_VERSION = "1.0.0"


@dataclass
class Converted:
    """What happened to one entry of ``eff_files``."""

    file: str
    converted: bool  # False: left as it was (see ``notes``)
    notes: List[str] = field(default_factory=list)


def is_old_efficiency(raw: Any) -> bool:
    """True for the content of an old ``.eff`` file (sweeps, no ``params``)."""
    return isinstance(raw, Mapping) and "params" not in raw and "sweeps" in raw


def _name(text: Any) -> str:
    """A variable name the efficiency module accepts (letters, digits, underscore)."""
    name = re.sub(r"\W+", "_", str(text).strip()).strip("_")
    return name if name and not name[0].isdigit() else f"v_{name}" if name else ""


def _axis(config: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The ``sweep`` of a variable from the old ``config``; None if it cannot be read."""
    try:
        if config.get("mode") == "range" or "start" in config:
            return {
                "start": float(config["start"]),
                "stop": float(config["stop"]),
                "points": int(config["points"]),
            }
        values = [float(v) for v in config.get("values", [])]
    except (KeyError, TypeError, ValueError):
        return None
    return {"values": values} if values else None


def convert_params(old: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """The ``params`` of the new file for an old ``.eff`` content, and the notes."""
    notes: List[str] = []
    variables: List[Dict[str, Any]] = []
    swept = set()
    for sweep in reversed(list(old.get("sweeps") or [])):  # the outer sweep becomes the last
        name = _name(sweep.get("variable", "")) if isinstance(sweep, Mapping) else ""
        axis = _axis(sweep.get("config") or {}) if isinstance(sweep, Mapping) else None
        if not name or axis is None or name in swept:
            notes.append(f"sweep {sweep!r} could not be converted and was dropped")
            continue
        swept.add(name)
        variables.append({"name": name, "sweep": axis})
        notes.append(f"'{name}': choose the instrument call that sets it")
    rest = [v for v in old.get("measured_variables") or [] if _name(v) not in swept]
    if rest:
        notes.append(f"quantities to read, add their readings in the editor: {', '.join(rest)}")
    params: Dict[str, Any] = {"variables": variables}
    timing = old.get("timing") or {}
    converted: Dict[str, Any] = {}
    for old_key, key in (
        ("delay_between_points", "settle_s"),
        ("delay_between_loops", "cooldown_s"),
    ):
        value = timing.get(old_key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            converted[key] = float(value)
    if converted:
        params["timing"] = converted
    return params, notes


def _instrument_names(directory: Path, inst_file: Optional[str]) -> List[str]:
    """The names of the instruments of the project's ``.inst`` file, if it can be read."""
    if not inst_file:
        return []
    try:
        data = json.loads((directory / inst_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = data.get("instruments", data) if isinstance(data, (dict, list)) else []
    names = [i.get("name") if isinstance(i, Mapping) else i for i in found or []]
    return [n for n in names if isinstance(n, str) and n]


def convert_files(raw: Dict[str, Any], directory: Path) -> List[Converted]:
    """Convert the files of ``raw["eff_files"]`` (a project dict) in ``directory`` and add them to
    ``raw["measurements"]``. Each old file is copied to ``<name>.bkp`` (``Project.backup_path``
    rules: never overwritten) before it is replaced. Returns one ``Converted`` per entry."""
    from .measurement import MeasurementError
    from .project import MeasurementFile, Project

    listed = raw.get("eff_files")
    results: List[Converted] = []
    measurements = raw.setdefault("measurements", [])
    instruments = _instrument_names(directory, raw.get("inst_file"))
    for name in listed if isinstance(listed, list) else []:
        entry = Converted(str(name), False)
        results.append(entry)
        path = directory / str(name)
        if not isinstance(name, str) or Path(name).name != name or not path.is_file():
            entry.notes.append("the file is not in the project folder")
            continue
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            entry.notes.append(f"the file cannot be read: {exc}")
            continue
        if is_old_efficiency(content):
            params, entry.notes = convert_params(content)
            try:
                Project.make_backup(path)
                MeasurementFile(
                    type=MEASUREMENT_TYPE,
                    module_version=MODULE_VERSION,
                    role_bindings={"instruments": instruments} if instruments else {},
                    params=params,
                ).save(path)
            except MeasurementError as exc:
                entry.notes = [str(exc)]
                continue
        elif not (isinstance(content, Mapping) and isinstance(content.get("type"), str)):
            entry.notes.append("the file is not an efficiency file")
            continue
        if any(m.get("file") == name for m in measurements if isinstance(m, Mapping)):
            entry.converted = True
            continue
        taken = {m.get("id") for m in measurements if isinstance(m, Mapping)}
        n = 1
        while f"m{n}" in taken:
            n += 1
        kind = (
            content.get("type", MEASUREMENT_TYPE)
            if not is_old_efficiency(content)
            else MEASUREMENT_TYPE
        )
        measurements.append({"id": f"m{n}", "type": kind, "name": Path(name).stem, "file": name})
        entry.converted = True
    return results
