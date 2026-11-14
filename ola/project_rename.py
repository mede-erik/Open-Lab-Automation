# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Renaming an instrument of a project without breaking its measurements. No Qt.

A measurement file names the instrument of each role (``role_bindings``). When the name of an
instrument in the ``.inst`` file changes, every measurement of every project that uses that file
has to name the new one. ``find_references`` lists what would change (to show a preview),
``rename_references`` changes it. Run files are never touched: they keep the name, model and serial
number of the day (see ``ola.identity``).

Only the ``role_bindings`` of the measurement files are rewritten; every other key of the file is
kept as it is. If a file cannot be written, the ones already changed are put back.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .fileio import atomic_write_json, atomic_write_text
from .measurement import MeasurementError
from .project import Project, check_plain_filename


@dataclass(frozen=True)
class Reference:
    """One place that names an instrument: a role of a measurement of a project."""

    project: str  # name of the project
    project_path: Path
    measurement_id: str
    measurement_name: str
    file: Path  # the measurement file
    role: str


class RenameError(Exception):
    """The names could not be changed (nothing was changed)."""


def projects_using(inst_path: Union[str, Path]) -> List[Project]:
    """The projects in the folder of an ``.inst`` file that use that file. A ``.json`` that is not
    a project (or is damaged) is skipped."""
    inst_path = Path(inst_path)
    found = []
    for candidate in sorted(inst_path.parent.glob("*.json")):
        try:
            project = Project.load(candidate)
        except MeasurementError:
            continue
        if project.inst_file and Path(project.inst_file).name == inst_path.name:
            found.append(project)
    return found


def _bindings(raw: Dict[str, Any]) -> Dict[str, Any]:
    value = raw.get("role_bindings")
    return value if isinstance(value, dict) else {}


def _names(value: Any) -> List[str]:
    return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]


def find_references(inst_path: Union[str, Path], name: str) -> List[Reference]:
    """Every role of every measurement (of the projects that use ``inst_path``) that names
    instrument ``name``."""
    found: List[Reference] = []
    for project in projects_using(inst_path):
        for ref in project.measurements:
            try:
                path = project.directory / check_plain_filename(ref.file)
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (MeasurementError, OSError, ValueError):
                continue  # a missing or damaged measurement file is reported by the project
            if not isinstance(raw, dict):
                continue
            for role, value in _bindings(raw).items():
                if isinstance(value, (str, list)) and name in _names(value):
                    found.append(
                        Reference(project.name, project.path, ref.id, ref.name, path, role)
                    )
    return found


def _renamed(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return new if value == old else value
    return [new if v == old else v for v in value]


def rename_references(
    inst_path: Union[str, Path], old: str, new: str, references: Optional[List[Reference]] = None
) -> List[Reference]:
    """Name ``new`` instead of ``old`` in the measurement files that name it. Returns what was
    changed. Raises ``RenameError`` (and changes nothing) if a file cannot be written."""
    if not new.strip():
        raise RenameError("the new name is empty")
    references = find_references(inst_path, old) if references is None else references
    by_file: Dict[Path, List[Reference]] = {}
    for ref in references:
        by_file.setdefault(ref.file, []).append(ref)
    originals: Dict[Path, str] = {}
    try:
        for path, refs in by_file.items():
            text = path.read_text(encoding="utf-8")
            raw = json.loads(text)
            bindings = _bindings(raw)
            for ref in refs:
                if ref.role in bindings:
                    bindings[ref.role] = _renamed(bindings[ref.role], old, new)
            originals[path] = text
            atomic_write_json(path, raw)
    except (OSError, ValueError) as exc:
        for path, text in originals.items():  # put back what was already written
            try:
                atomic_write_text(path, text)
            except OSError:
                pass
        raise RenameError(f"cannot update the measurements: {exc}") from exc
    return references
