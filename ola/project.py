# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Project files with several measurements.

``<project>.json``::

    {"format_version": 2, "project_name": "Pippo", "inst_file": "pippo.inst",
     "scope_settings": "scope.was",
     "measurements": [{"id": "m1", "type": "efficiency", "name": "Efficiency",
                       "file": "efficiency.eff"}, ...]}

``inst_file`` and ``scope_settings`` are **project definition files**, not measurements: the
instruments, and the settings of the oscilloscopes (a ``.was`` file, applied by the remote control
and, later, by the measurements that acquire waveforms). A project has one active
``scope_settings``. If it has more ``.was`` files, ``scope_files`` lists all of them with an
``enabled`` flag, exactly one true: the others are kept in the folder and listed as disabled, never
deleted or renamed.

Each measurement lives in its own file whose extension identifies the measurement type
(``.eff``, ``.tlg``...), so files can be recognised, copied and deleted one by one::

    {"type": "time_log", "module_version": "1.0.0", "api_version": 1,
     "role_bindings": {"instruments": ["dmm1", "psu1"]}, "params": {...}}

Keys the program does not know are preserved when a project is saved. No compatibility with the
old ``eff_files`` project format (decision recorded in PLAN.md). The key ``was_files`` of the
early projects of format 2 is still read: its first file is the ``scope_settings`` and the others
are disabled scope files; it is not written any more.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from .fileio import atomic_write_json
from .measurement import API_VERSION, MeasurementError
from .registry import ModuleRegistry

FORMAT_VERSION = 2
# the keys that ``Project`` itself reads and writes (the others are kept as they are)
_KNOWN_KEYS = (
    "format_version", "project_id", "project_name", "inst_file", "scope_settings", "scope_files",
    "measurements",
)  # fmt: skip
_PLAIN_NAME = re.compile(r"^[^/\\\x00]+$")


def check_plain_filename(name: str) -> str:
    """Files named by a project must sit in the project folder (no paths, no '..')."""
    if (
        not isinstance(name, str)
        or not _PLAIN_NAME.match(name)
        or name in (".", "..")
        or ":" in name
    ):
        raise MeasurementError(f"invalid file name {name!r}: it must be a plain file name")
    return name


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "measurement"


@dataclass
class MeasurementRef:
    """Entry of the project's ``measurements`` list."""

    id: str
    type: str
    name: str
    file: str


@dataclass
class MeasurementFile:
    """Content of one measurement file (what the editor of that measurement type edits)."""

    type: str
    module_version: str = ""
    api_version: int = API_VERSION
    role_bindings: Dict[str, Union[str, List[str]]] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Content as a dict, ready to be written as JSON."""
        return {
            "type": self.type,
            "module_version": self.module_version,
            "api_version": self.api_version,
            "role_bindings": self.role_bindings,
            "params": self.params,
        }

    def save(self, path: Union[str, Path]) -> None:
        """Write the measurement file as JSON."""
        atomic_write_json(path, self.to_dict())

    @staticmethod
    def load(path: Union[str, Path]) -> "MeasurementFile":
        """Read a measurement file; ``MeasurementError`` if it is missing or invalid."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MeasurementError(f"cannot read measurement file {path}: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
            raise MeasurementError(f"{path}: not a measurement file (missing 'type')")
        return MeasurementFile(
            type=raw["type"],
            module_version=str(raw.get("module_version", "")),
            api_version=int(raw.get("api_version", API_VERSION)),
            role_bindings=dict(raw.get("role_bindings", {})),
            params=dict(raw.get("params", {})),
        )


# keys of the project file that are written directly, not through ``Project``: on a save the file
# on disk is the newest
# Keys written straight to the file by other parts of the program (the calibration window, the
# main window's file list): when the project is saved the file is the newest.
DISK_KEYS = (
    "calibrations",
    "last_opened",
)
LEGACY_KEYS = ("was_files",)  # read when a project is opened, never written again


@dataclass
class Project:
    """A project: name, folder, instrument file and its measurements."""

    name: str
    directory: Path
    path: Path
    inst_file: Optional[str] = None
    measurements: List[MeasurementRef] = field(default_factory=list)
    scope_settings: Optional[str] = None  # the active file of the settings of the oscilloscopes
    scope_files: List[Dict[str, Any]] = field(default_factory=list)  # all of them, with ``enabled``
    extra: Dict[str, Any] = field(default_factory=dict)  # unknown keys, preserved on save
    # who this project is, for ever: the name is only a label and the folder can be moved or
    # renamed; a shared archive (docs/proposals/shared-archive.md) finds the project by this
    project_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # ----- creation / persistence ---------------------------------------------------------
    @staticmethod
    def new(name: str, directory: Union[str, Path], inst_file: Optional[str] = None) -> "Project":
        """Create an empty project (not saved yet)."""
        directory = Path(directory)
        return Project(
            name=name,
            directory=directory,
            path=directory / f"{_slug(name)}.json",
            inst_file=inst_file,
        )

    @staticmethod
    def load(path: Union[str, Path]) -> "Project":
        """Read ``<project>.json``; ``MeasurementError`` if unreadable or in the old unsupported
        format."""
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MeasurementError(f"cannot read project {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise MeasurementError(f"{path}: not a project file")
        if raw.get("format_version") != FORMAT_VERSION:
            raise MeasurementError(
                f"{path}: project format {raw.get('format_version')!r} is not supported "
                f"(expected {FORMAT_VERSION}; the old eff_files format is not read)"
            )
        refs = []
        for m in raw.get("measurements", []):
            try:
                refs.append(MeasurementRef(m["id"], m["type"], m["name"], m["file"]))
            except (KeyError, TypeError) as exc:
                raise MeasurementError(f"{path}: invalid measurement entry {m!r}") from exc
        known = set(_KNOWN_KEYS) | set(LEGACY_KEYS)
        project = Project(
            name=str(raw.get("project_name", path.stem)),
            directory=path.parent,
            path=path,
            inst_file=raw.get("inst_file"),
            measurements=refs,
            extra={k: v for k, v in raw.items() if k not in known},
        )
        project._read_scope_files(raw)
        if raw.get("project_id"):
            project.project_id = str(raw["project_id"])
        else:  # a project made before the id existed: give it one and keep it
            try:
                project.save()
            except OSError:  # read-only folder: it will be given again until it can be saved
                pass
        return project

    def save(self) -> None:
        """Write the project file, keeping the keys this program does not know."""
        data: Dict[str, Any] = {
            **self._written_elsewhere(),
            **self.extra,
            "format_version": FORMAT_VERSION,
            "project_id": self.project_id,
            "project_name": self.name,
            "inst_file": self.inst_file,
            "scope_settings": self.scope_settings,
            "measurements": [vars(m) for m in self.measurements],
        }
        if len(self.scope_files) > 1:  # one file is just ``scope_settings``
            data["scope_files"] = [dict(entry) for entry in self.scope_files]
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, data)

    def _written_elsewhere(self) -> Dict[str, Any]:
        """The keys of the file on disk that other parts of the program write directly (the list
        of the calibrations, saved by the calibration window while this object was already
        loaded): they must not be lost when the project is saved. Keys this object knows win,
        except the ones in ``DISK_KEYS``, where the file is the newest."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        known = set(_KNOWN_KEYS) | set(LEGACY_KEYS)  # the legacy keys are dropped on a save
        on_disk = {k: v for k, v in raw.items() if k not in known}
        keep = {k: v for k, v in on_disk.items() if k not in self.extra or k in DISK_KEYS}
        for key in DISK_KEYS:
            self.extra.pop(key, None)  # the file is the newest: ``keep`` has it
        return keep

    @staticmethod
    def upgrade_legacy(path: Union[str, Path]) -> bool:
        """Turn a project file of the first format (``eff_files`` / ``was_files``) into a current
        one, in place and without losing a key: it only gains ``format_version`` and an empty
        ``measurements`` list. Returns True if the file was changed; a file that is already
        current, or is not a project, is left alone."""
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(raw, dict) or "format_version" in raw or "project_name" not in raw:
            return False
        raw["format_version"] = FORMAT_VERSION
        raw.setdefault("measurements", [])
        path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True

    # ----- the settings of the oscilloscopes ------------------------------------------------
    def _read_scope_files(self, raw: Mapping[str, Any]) -> None:
        """The scope settings files of a project file: ``scope_settings`` (the active one),
        ``scope_files`` (all of them, with their flags) or, in an early project, ``was_files``."""
        entries: List[str] = []
        listed = raw.get("scope_files")
        if isinstance(listed, list):
            for item in listed:
                name = item.get("file") if isinstance(item, Mapping) else item
                if isinstance(name, str) and name and name not in entries:
                    entries.append(name)
        legacy = raw.get("was_files")
        legacy = [f for f in legacy if isinstance(f, str) and f] if isinstance(legacy, list) else []
        active = raw.get("scope_settings")
        active = active if isinstance(active, str) and active else None
        if active is None and not isinstance(listed, list) and legacy:
            active = legacy[0]  # an early project: its first file stays the one that is applied
        for name in legacy + ([active] if active else []):
            if name not in entries:
                entries.append(name)
        if active is None and isinstance(listed, list):
            enabled = [
                i.get("file") for i in listed if isinstance(i, Mapping) and i.get("enabled")
            ]
            active = enabled[0] if enabled else None
        self.scope_settings = active
        self.scope_files = [{"file": n, "enabled": n == active} for n in entries]

    def scope_file_names(self) -> List[str]:
        """Every scope settings file of the project, the active one included, in the order they
        were added."""
        return [entry["file"] for entry in self.scope_files]

    def add_scope_file(self, name: str) -> None:
        """Put a ``.was`` file of the project folder in the project. It becomes the active one if
        there is none; otherwise it is added **disabled** (see ``set_active_scope``)."""
        check_plain_filename(name)
        if name in self.scope_file_names():
            return
        first = self.scope_settings is None
        self.scope_files.append({"file": name, "enabled": first})
        if first:
            self.scope_settings = name

    def remove_scope_file(self, name: str) -> None:
        """Take a file out of the project (the file itself is not touched). If it was the active
        one, the project has no active scope settings until one is chosen."""
        self.scope_files = [e for e in self.scope_files if e["file"] != name]
        if self.scope_settings == name:
            self.scope_settings = None

    def set_active_scope(self, name: str) -> None:
        """Make ``name`` the active scope settings file; the others stay in the project, disabled.
        ``MeasurementError`` if it is not one of them."""
        if name not in self.scope_file_names():
            raise MeasurementError(f"{name!r} is not a scope settings file of the project")
        self.scope_settings = name
        for entry in self.scope_files:
            entry["enabled"] = entry["file"] == name

    def scope_path(self) -> Optional[Path]:
        """The path of the active scope settings file, or None if the project has none."""
        if not self.scope_settings:
            return None
        return self.directory / check_plain_filename(self.scope_settings)

    # ----- measurements ---------------------------------------------------------------------
    def get(self, measurement_id: str) -> MeasurementRef:
        """Measurement with this id (``MeasurementError`` if there is none)."""
        for m in self.measurements:
            if m.id == measurement_id:
                return m
        raise MeasurementError(f"no measurement with id {measurement_id!r}")

    def file_path(self, ref: MeasurementRef) -> Path:
        """Path of the measurement's file, checked to stay inside the project folder."""
        return self.directory / check_plain_filename(ref.file)

    def add_measurement(
        self,
        type: str,
        name: str,
        registry: ModuleRegistry,
        params: Optional[Mapping[str, Any]] = None,
    ) -> MeasurementRef:
        """Add a measurement of a known type: picks a unique id and a file name with the
        extension of the type, and writes the (initial) measurement file."""
        info = registry.get(type)
        taken_ids = {m.id for m in self.measurements}
        n = 1
        while f"m{n}" in taken_ids:
            n += 1
        taken_files = {m.file.lower() for m in self.measurements}
        base, candidate, i = _slug(name), None, 1
        while (
            candidate is None
            or candidate.lower() in taken_files
            or (self.directory / candidate).exists()
        ):
            candidate = f"{base}{info.extension}" if i == 1 else f"{base}_{i}{info.extension}"
            i += 1
        ref = MeasurementRef(f"m{n}", type, name, candidate)
        self.directory.mkdir(parents=True, exist_ok=True)
        MeasurementFile(type=type, module_version=info.version, params=dict(params or {})).save(
            self.directory / candidate
        )
        self.measurements.append(ref)
        return ref

    def remove_measurement(self, measurement_id: str, delete_file: bool = False) -> None:
        """Remove a measurement from the project; its file is deleted only with
        ``delete_file=True``."""
        ref = self.get(measurement_id)
        self.measurements.remove(ref)
        if delete_file:
            self.file_path(ref).unlink(missing_ok=True)

    def validate(self, registry: ModuleRegistry) -> List[str]:
        """Consistency problems (empty list = OK): unknown types, wrong extensions, duplicate
        ids/files, unsafe file names, missing files."""
        problems: List[str] = []
        ids: Dict[str, int] = {}
        files: Dict[str, str] = {}
        for m in self.measurements:
            ids[m.id] = ids.get(m.id, 0) + 1
            try:
                check_plain_filename(m.file)
            except MeasurementError as exc:
                problems.append(f"{m.id}: {exc}")
                continue
            if m.file.lower() in files:
                problems.append(f"{m.id}: file {m.file!r} also used by {files[m.file.lower()]}")
            files[m.file.lower()] = m.id
            try:
                info = registry.get(m.type)
            except MeasurementError:
                problems.append(f"{m.id}: unknown measurement type {m.type!r}")
                continue
            if not m.file.lower().endswith(info.extension):
                problems.append(f"{m.id}: file {m.file!r} should end with {info.extension}")
            if not (self.directory / m.file).is_file():
                problems.append(f"{m.id}: file {m.file!r} is missing")
        problems += [f"duplicate measurement id {i!r}" for i, c in ids.items() if c > 1]
        return problems
