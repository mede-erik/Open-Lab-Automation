# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Using a project that names instruments you do not have. No Qt.

A project can be sent to another person. Its measurements name the instruments of the sender
(``role_bindings``); the receiver's ``.inst`` file has other ones. ``find_gaps`` lists the names the
measurements use that are not in the instrument file, with the category each role asks for;
``candidates_for`` lists the receiver's instruments that can fill them (the same category, or any
instrument for a role of category ``any``); ``preview`` says what a candidate would have less
than the instrument the measurement was made with (``ola.compat``); ``map_instrument`` names the
chosen instrument in the measurements (``ola.project_rename``). Runs already made are never touched:
they keep the instruments of the sender in their snapshot. A calibration made for another
apparatus is not used (``ola.vna_calibration_flow``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .compat import Finding
from .connection import ConnectionProblem, read_inst_entries
from .inst_file import entry_type
from .project import MeasurementRef
from .project_rename import Reference, find_references, rename_references
from .project_session import ProjectSession


@dataclass(frozen=True)
class Gap:
    """An instrument name that measurements use and the instrument file does not have."""

    name: str
    category: str  # what the roles that name it ask for ("any" if they disagree or ask for any)
    measurements: Tuple[str, ...]  # names of the measurements that use it
    roles: Tuple[str, ...]


def _inst_path(session: ProjectSession):
    project = session.project
    return project.directory / project.inst_file if project.inst_file else None


def find_gaps(session: ProjectSession) -> List[Gap]:
    """The instrument names the measurements of the project use that are not in the instrument
    file, in the order they appear. A measurement that cannot be read, or whose module is missing,
    is skipped (the project window already shows its problem)."""
    known = set(session.instruments)
    if (
        not known
    ):  # no instrument file (or an empty one): the session does not check the names either
        return []
    found: Dict[str, Dict[str, Any]] = {}
    for row in session.rows():
        if row.info is None:
            continue
        try:
            bindings = session.load(row.ref).role_bindings
        except Exception:
            continue
        categories = {r.name: r.category for r in row.info.roles}
        for role, value in bindings.items():
            names = [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]
            for name in names:
                if name in known:
                    continue
                gap = found.setdefault(name, {"categories": set(), "measurements": [], "roles": []})
                gap["categories"].add(categories.get(role, "any"))
                if row.ref.name not in gap["measurements"]:
                    gap["measurements"].append(row.ref.name)
                if role not in gap["roles"]:
                    gap["roles"].append(role)
    gaps = []
    for name, gap in found.items():
        kinds = gap["categories"] - {"any"}
        category = next(iter(kinds)) if len(kinds) == 1 else "any"
        gaps.append(Gap(name, category, tuple(gap["measurements"]), tuple(gap["roles"])))
    return gaps


def candidates_for(session: ProjectSession, gap: Gap) -> List[str]:
    """The instruments of the instrument file that can take the place of ``gap.name``: the same
    category, or all of them if the roles that name it accept any instrument."""
    try:
        entries = read_inst_entries(_inst_path(session))
    except ConnectionProblem:
        return []
    return [
        name
        for name, entry in entries.items()
        if gap.category == "any" or entry_type(entry) == gap.category
    ]


def preview(
    session: ProjectSession,
    gap: Gap,
    candidate: str,
    characteristics_of: Callable[[str], Dict[str, float]],
    abilities_of: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> List[Finding]:
    """What ``candidate`` would have less than the instrument that was used (see
    ``ProjectSession.compatibility``), over every measurement that names ``gap.name``. A finding
    that blocks a run (a sweep the instrument cannot do) has ``blocking`` set."""
    findings: List[Finding] = []
    inst_path = _inst_path(session)
    for ref in _measurements_naming(session, gap.name, inst_path):
        raw = _bindings_of(session, ref)
        swapped = {
            role: [candidate if n == gap.name else n for n in _as_list(value)]
            for role, value in raw.items()
        }
        findings += session.compatibility(ref, characteristics_of, abilities_of, bindings=swapped)
    return findings


def _as_list(value: Any) -> List[str]:
    return [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]


def _bindings_of(session: ProjectSession, ref: MeasurementRef) -> Dict[str, Any]:
    try:
        return dict(session.load(ref).role_bindings)
    except Exception:
        return {}


def _measurements_naming(session: ProjectSession, name: str, inst_path) -> List[MeasurementRef]:
    return [
        ref
        for ref in session.project.measurements
        if any(name in _as_list(v) for v in _bindings_of(session, ref).values())
    ]


def map_instrument(session: ProjectSession, old: str, new: str) -> List[Reference]:
    """Name instrument ``new`` instead of ``old`` in the measurements. Returns what was changed;
    raises ``ola.project_rename.RenameError`` (nothing changed) if a file cannot be written."""
    inst_path = _inst_path(session)
    return rename_references(inst_path, old, new, find_references(inst_path, old))


__all__ = ["Gap", "find_gaps", "candidates_for", "preview", "map_instrument", "json"]
