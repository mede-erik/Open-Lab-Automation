# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Project files with several measurements.

``<project>.json``::

    {"format_version": 2, "project_name": "Pippo", "inst_file": "pippo.inst",
     "scope_settings": [{"file": "scope.was", "enabled": true}],
     "measurements": [{"id": "m1", "type": "efficiency", "name": "Efficiency",
                       "file": "efficiency.eff"}, ...]}

``inst_file`` and ``scope_settings`` are **project definition files**, not measurements: the
instruments, and the settings of the oscilloscopes. ``scope_settings`` is an ordered list of
``.was`` files, each ``{"file": "rise.was", "enabled": true, "scope": "osc1"}``: every one is a
different acquisition (a long view of the signal, a rising edge, a falling edge...). ``scope`` is
the oscilloscope the file applies to (the name in the ``.inst`` file); without it the file applies
to every oscilloscope, which is what one oscilloscope needs. A measurement that acquires waveforms
runs the files that are **enabled one after another, in this order**, on each oscilloscope they
apply to; the remote control lets the user choose which one to apply. Any file can be switched off;
it stays in the folder and in the list, never deleted or renamed. An empty list is valid.

Each measurement lives in its own file whose extension identifies the measurement type
(``.eff``, ``.tlg``...), so files can be recognised, copied and deleted one by one::

    {"type": "time_log", "module_version": "1.0.0", "api_version": 1,
     "role_bindings": {"instruments": ["dmm1", "psu1"]}, "params": {...}}

Keys the program does not know are preserved when a project is saved. No compatibility with the
old ``eff_files`` project format (decision recorded in PLAN.md). The key ``was_files`` of the
early projects of format 2 is still read: its files become the ``scope_settings`` list, all
enabled; it is not written any more.
"""

from __future__ import annotations

import json
import re
import shutil
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
    "format_version", "project_id", "project_name", "inst_file", "scope_settings", "measurements",
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
    # the files of the settings of the oscilloscopes, in order: [{"file": ..., "enabled": ...}]
    scope_settings: List[Dict[str, Any]] = field(default_factory=list)
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
        project._read_scope_settings(raw)
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
            "scope_settings": [dict(entry) for entry in self.scope_settings],
            "measurements": [vars(m) for m in self.measurements],
        }
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
    def needs_upgrade(path: Union[str, Path]) -> bool:
        """True if ``path`` is a project file of the first format (no ``format_version``): opening
        it means changing the file, so the program asks first (see ``upgrade_legacy``)."""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(raw, dict) and "format_version" not in raw and "project_name" in raw

    @staticmethod
    def backup_path(path: Union[str, Path]) -> Path:
        """Where the backup of a project file goes: the same name with ``.bkp`` added
        (``Name.json.bkp``), or ``.bkp.1``, ``.bkp.2``... if that exists, so that a backup is never
        overwritten."""
        path = Path(path)
        target = path.with_name(path.name + ".bkp")
        number = 0
        while target.exists():
            number += 1
            target = path.with_name(f"{path.name}.bkp.{number}")
        return target

    @staticmethod
    def make_backup(path: Union[str, Path]) -> Path:
        """Copy the project file byte for byte to ``backup_path`` and return the copy;
        ``MeasurementError`` if it cannot be written."""
        path = Path(path)
        target = Project.backup_path(path)
        try:
            shutil.copy2(path, target)
        except OSError as exc:
            raise MeasurementError(f"cannot write the backup {target}: {exc}") from exc
        return target

    @staticmethod
    def upgrade_legacy(path: Union[str, Path], backup: bool = True) -> bool:
        """Turn a project file of the first format (``eff_files`` / ``was_files``) into a current
        one, in place and without losing a key: it only gains ``format_version`` and an empty
        ``measurements`` list (the old ``eff_files`` are kept as they are, they are not turned
        into measurements). Before the first write the file is copied to ``Name.json.bkp``
        (``make_backup``) unless ``backup`` is False. Returns True if the file was changed; a file
        that is already current, or is not a project, is left alone."""
        path = Path(path)
        if not Project.needs_upgrade(path):
            return False
        raw = json.loads(path.read_text(encoding="utf-8"))
        if backup:
            Project.make_backup(path)
        raw["format_version"] = FORMAT_VERSION
        raw.setdefault("measurements", [])
        path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True

    # ----- the settings of the oscilloscopes ------------------------------------------------
    def _read_scope_settings(self, raw: Mapping[str, Any]) -> None:
        """The scope settings files of a project file: the list ``scope_settings``, a single name
        (one file) or, in an early project, ``was_files`` (every file active)."""
        listed = raw.get("scope_settings")
        if isinstance(listed, str):
            listed = [listed]
        if not isinstance(listed, list):
            legacy = raw.get("was_files")
            listed = legacy if isinstance(legacy, list) else []
        found: List[Dict[str, Any]] = []
        for item in listed:
            name = item.get("file") if isinstance(item, Mapping) else item
            enabled = item.get("enabled", True) is not False if isinstance(item, Mapping) else True
            target = item.get("scope") if isinstance(item, Mapping) else None
            if isinstance(name, str) and name and name not in [e["file"] for e in found]:
                entry: Dict[str, Any] = {"file": name, "enabled": enabled}
                if isinstance(target, str) and target.strip():
                    entry["scope"] = target.strip()
                found.append(entry)
        self.scope_settings = found

    def scope_file_names(self) -> List[str]:
        """Every scope settings file of the project, in order (the order of the acquisitions)."""
        return [entry["file"] for entry in self.scope_settings]

    def active_scope_files(self, scope: Optional[str] = None) -> List[str]:
        """The scope settings files that are on, in order: a measurement that acquires waveforms
        runs them one after another, in this order. With ``scope`` (the name of an oscilloscope)
        only the ones that apply to it: those that name it and those that name none."""
        return [
            entry["file"]
            for entry in self.scope_settings
            if entry["enabled"] and (scope is None or entry.get("scope", scope) == scope)
        ]

    def scope_target(self, name: str) -> str:
        """The oscilloscope a scope settings file applies to, or '' for every oscilloscope."""
        for entry in self.scope_settings:
            if entry["file"] == name:
                return entry.get("scope", "")
        return ""

    def set_scope_target(self, name: str, scope: str = "") -> None:
        """Say which oscilloscope a file applies to (``''``: every oscilloscope).
        ``MeasurementError`` if the file is not in the project."""
        for entry in self.scope_settings:
            if entry["file"] == name:
                if scope.strip():
                    entry["scope"] = scope.strip()
                else:
                    entry.pop("scope", None)
                return
        raise MeasurementError(f"{name!r} is not a scope settings file of the project")

    def add_scope_file(self, name: str, scope: str = "") -> None:
        """Put a ``.was`` file of the project folder in the project, at the end, active (for the
        oscilloscope ``scope``, or for every one)."""
        check_plain_filename(name)
        if name not in self.scope_file_names():
            entry: Dict[str, Any] = {"file": name, "enabled": True}
            if scope.strip():
                entry["scope"] = scope.strip()
            self.scope_settings.append(entry)

    def remove_scope_file(self, name: str) -> None:
        """Take a file out of the project (the file itself is not touched)."""
        self.scope_settings = [e for e in self.scope_settings if e["file"] != name]

    def set_scope_enabled(self, name: str, enabled: bool) -> None:
        """Switch a scope settings file on or off. Any file can be off, not only the last ones; it
        stays in the project and in the folder. ``MeasurementError`` if it is not in the project."""
        for entry in self.scope_settings:
            if entry["file"] == name:
                entry["enabled"] = bool(enabled)
                return
        raise MeasurementError(f"{name!r} is not a scope settings file of the project")

    def move_scope_file(self, name: str, delta: int) -> None:
        """Move a file up (``delta=-1``) or down (``+1``) in the order of the acquisitions."""
        names = self.scope_file_names()
        if name not in names:
            raise MeasurementError(f"{name!r} is not a scope settings file of the project")
        i = names.index(name)
        j = max(0, min(len(names) - 1, i + delta))
        self.scope_settings.insert(j, self.scope_settings.pop(i))

    def scope_path(self, name: str) -> Path:
        """The path of a scope settings file of the project."""
        return self.directory / check_plain_filename(name)

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
