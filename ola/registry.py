"""Measurement modules: discovery from ``module.json`` manifests and on-demand loading.

Layout of a module (a folder)::

    my_module/
        module.json     # manifest (below)
        measurement.py  # the class named by "entry"

    {"id": "time_log", "name": "Time log", "version": "1.0.0", "api_version": 1,
     "extension": ".tlg", "entry": "measurement.py:TimeLog",
     "roles": [{"name": "instruments", "category": "any", "multiple": true}],
     "params_schema": {...}, "description": "..."}

Security: ``discover()`` only reads JSON, it never executes module code, so listing modules
is safe. Code is imported by ``load_class()`` / ``create()``; a module that is not built in
needs ``allow_user_code=True`` (the caller asks the user first). A module that can be
discovered but not loaded is reported, it never breaks the others.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .measurement import API_VERSION, Measurement, MeasurementError, Role

_ID = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_EXT = re.compile(r"^\.[a-z][a-z0-9]{1,7}$")
_ENTRY = re.compile(r"^([A-Za-z0-9_]+\.py):([A-Za-z_][A-Za-z0-9_]*)$")
# Extensions already used by the application or too generic to identify a measurement.
RESERVED_EXTENSIONS = frozenset(
    {
        ".json",
        ".inst",
        ".was",
        ".csv",
        ".txt",
        ".md",
        ".py",
        ".exe",
        ".dll",
        ".so",
        ".bat",
        ".sh",
        ".xml",
        ".zip",
        ".log",
        ".db",
        ".ini",
        ".cfg",
        ".yaml",
        ".yml",
    }
)
BUILTIN_DIR = Path(__file__).resolve().parent / "modules"


class ModuleNotTrustedError(MeasurementError):
    """Loading this module would run code that is not built in and was not allowed."""


class ModuleLoadError(MeasurementError):
    """The module code could not be imported or does not provide a valid measurement class."""


@dataclass(frozen=True)
class ModuleInfo:
    """What a module's manifest says (read without running any module code)."""

    id: str
    name: str
    version: str
    extension: str
    entry_file: str
    entry_class: str
    roles: Tuple[Role, ...]
    params_schema: Dict[str, Any]
    description: str
    path: Path
    builtin: bool
    api_version: int = API_VERSION


def _parse_manifest(path: Path, builtin: bool) -> ModuleInfo:
    """Raises ``ValueError`` with a readable message if the manifest is not valid."""
    try:
        raw = json.loads((path / "module.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read module.json: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("module.json must contain a JSON object")

    def need(key: str, kind: type) -> Any:
        if key not in raw:
            raise ValueError(f"missing '{key}'")
        if not isinstance(raw[key], kind) or isinstance(raw[key], bool) and kind is int:
            raise ValueError(f"'{key}' must be {kind.__name__}")
        return raw[key]

    mid, name, version = need("id", str), need("name", str), need("version", str)
    api, ext, entry = need("api_version", int), need("extension", str), need("entry", str)
    if not _ID.match(mid):
        raise ValueError(f"invalid id {mid!r} (lowercase letters, digits, '_', 2-40 chars)")
    if api != API_VERSION:
        raise ValueError(f"api_version {api} not supported (this software uses {API_VERSION})")
    if not _EXT.match(ext):
        raise ValueError(f"invalid extension {ext!r} (e.g. '.eff')")
    if ext in RESERVED_EXTENSIONS:
        raise ValueError(f"extension {ext!r} is reserved")
    m = _ENTRY.match(entry)
    if not m:
        raise ValueError(f"invalid entry {entry!r} (expected 'file.py:ClassName')")

    roles = []
    seen = set()
    for r in raw.get("roles", []):
        if (
            not isinstance(r, dict)
            or not isinstance(r.get("name"), str)
            or not isinstance(r.get("category"), str)
        ):
            raise ValueError("each role needs string 'name' and 'category'")
        if r["name"] in seen:
            raise ValueError(f"duplicate role {r['name']!r}")
        seen.add(r["name"])
        unknown = set(r) - {"name", "category", "required", "multiple", "description"}
        if unknown:
            raise ValueError(f"role {r['name']!r}: unknown field(s) {sorted(unknown)}")
        roles.append(Role(**r))
    schema = raw.get("params_schema", {})
    if not isinstance(schema, dict):
        raise ValueError("'params_schema' must be an object")
    return ModuleInfo(
        id=mid,
        name=name,
        version=version,
        extension=ext,
        entry_file=m.group(1),
        entry_class=m.group(2),
        roles=tuple(roles),
        params_schema=schema,
        description=str(raw.get("description", "")),
        path=path,
        builtin=builtin,
    )


class ModuleRegistry:
    """Finds measurement modules in a list of folders and loads them on request."""

    def __init__(self, search_dirs: Optional[Sequence[Tuple[Path, bool]]] = None):
        """``search_dirs``: (folder, is_builtin) pairs, in priority order (first wins)."""
        self.search_dirs = [(Path(p), b) for p, b in (search_dirs or [(BUILTIN_DIR, True)])]
        self._modules: Dict[str, ModuleInfo] = {}
        self.problems: List[Tuple[Path, str]] = []

    def discover(self) -> List[ModuleInfo]:
        """(Re)scan the folders. Invalid modules are skipped and listed in ``problems``."""
        self._modules, self.problems = {}, []
        by_ext: Dict[str, str] = {}
        for root, builtin in self.search_dirs:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not (child / "module.json").is_file():
                    continue
                try:
                    info = _parse_manifest(child, builtin)
                except ValueError as exc:
                    self.problems.append((child, str(exc)))
                    continue
                if info.id in self._modules:
                    self.problems.append((child, f"duplicate module id {info.id!r}"))
                elif info.extension in by_ext:
                    owner = by_ext[info.extension]
                    self.problems.append(
                        (child, f"extension {info.extension!r} already used by '{owner}'")
                    )
                else:
                    self._modules[info.id] = info
                    by_ext[info.extension] = info.id
        return self.list()

    def list(self) -> List[ModuleInfo]:
        """All valid modules found, in search order."""
        return list(self._modules.values())

    def get(self, module_id: str) -> ModuleInfo:
        """Module with this id (``MeasurementError`` if unknown)."""
        try:
            return self._modules[module_id]
        except KeyError:
            raise MeasurementError(f"unknown measurement type {module_id!r}") from None

    def by_extension(self, extension: str) -> Optional[ModuleInfo]:
        """Module that owns this file extension, or ``None``."""
        return next((m for m in self._modules.values() if m.extension == extension.lower()), None)

    def load_class(self, module_id: str, allow_user_code: bool = False) -> type:
        """Import the module code and return its measurement class."""
        info = self.get(module_id)
        if not info.builtin and not allow_user_code:
            raise ModuleNotTrustedError(
                f"module '{info.id}' is not built in and runs its own code ({info.path}); "
                "ask the user before loading it"
            )
        file = info.path / info.entry_file
        name = f"ola_modules.{info.id}"
        spec = importlib.util.spec_from_file_location(name, file)
        if spec is None or spec.loader is None:
            raise ModuleLoadError(f"cannot load {file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(name, None)
            raise ModuleLoadError(f"error importing {file}: {type(exc).__name__}: {exc}") from exc
        cls = getattr(module, info.entry_class, None)
        if not (isinstance(cls, type) and issubclass(cls, Measurement)):
            sys.modules.pop(name, None)
            raise ModuleLoadError(f"{info.entry_class} in {file} is not a Measurement subclass")
        return cls

    def create(
        self, module_id: str, params: Mapping[str, Any], allow_user_code: bool = False
    ) -> Measurement:
        """Instantiate a measurement of this type with the given parameters."""
        info = self.get(module_id)
        instance = self.load_class(module_id, allow_user_code)(params)
        instance.info = info
        instance.roles = info.roles
        return instance


def default_registry(
    project_dir: Optional[Path] = None, user_dir: Optional[Path] = None
) -> ModuleRegistry:
    """Built-in modules, then the user folder, then the project's own ``modules/`` folder."""
    dirs: List[Tuple[Path, bool]] = [(BUILTIN_DIR, True)]
    user = user_dir if user_dir is not None else Path.home() / ".open_lab_automation" / "modules"
    dirs.append((user, False))
    if project_dir is not None:
        dirs.append((Path(project_dir) / "modules", False))
    registry = ModuleRegistry(dirs)
    registry.discover()
    return registry
