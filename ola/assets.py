# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The registry of cables and devices: every physical object that measurements are made on has a
**code** (``CBL-0042``), printed on a label, and a card with what it is.

The registry is one JSON file shared by all projects (default
``~/.open_lab_automation/assets.json``; set the environment variable ``OLA_ASSETS_FILE`` or pass a
path to use another, for example in a shared folder). It keeps cards only, not results: the
measurements made on an object are found by the code that every run of it has saved
(``history``).

    registry = AssetRegistry()                       # the default file
    cable = registry.create("cable", "RG316 SMA-SMA", attributes={"length_m": 1.0})
    cable.id                                         # "CBL-0001"; codes are never reused
    registry.find("OLA:CBL-0001")                    # what a barcode scanner or a QR gives
    history("CBL-0001", [project_dir / "runs"])      # the runs that used this cable

Kinds: ``cable``, ``antenna``, ``filter``, ``amplifier``, ``attenuator``, ``adapter``, ``other``
(see ``KINDS``).
Reading is forgiving (keys it does not know are kept) and saving is atomic (a power cut never
leaves a half-written file; the previous version is kept as ``assets.json.bak``).
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Union

FORMAT_VERSION = 1
ENV_FILE = "OLA_ASSETS_FILE"
QR_PREFIX = "OLA:"  # what the QR code of a label holds before the code: "OLA:CBL-0042"

# kind -> the prefix of its codes, and the attributes its card suggests (name, unit)
KINDS: Dict[str, Dict[str, Any]] = {
    "cable": {
        "prefix": "CBL",
        "attributes": [("cable_type", ""), ("connectors", ""), ("length_m", "m")],
    },
    "antenna": {
        "prefix": "ANT",
        "attributes": [("frequency_range", ""), ("connector", ""), ("gain_dbi", "dBi")],
    },
    "filter": {
        "prefix": "FLT",
        "attributes": [("filter_type", ""), ("frequency", "Hz"), ("connectors", "")],
    },
    "amplifier": {
        "prefix": "AMP",
        "attributes": [("nominal_gain_db", "dB"), ("supply", ""), ("connectors", "")],
    },
    "attenuator": {
        "prefix": "ATT",
        "attributes": [
            ("nominal_db", "dB"),
            ("tolerance_db", "dB"),
            ("max_power_w", "W"),
            ("max_frequency", "Hz"),
            ("connectors", ""),
        ],
    },
    "adapter": {"prefix": "ADP", "attributes": [("connectors", "")]},
    "other": {"prefix": "DUT", "attributes": []},
}
PREFIX_KIND = {v["prefix"]: k for k, v in KINDS.items()}
ASSET_GROUPS = (
    "cable",
    "device",
    "filter",
    "attenuator",
)  # where a measurement file names what it measures
_CODE = re.compile(r"^(?:OLA:)?\s*([A-Za-z]{3})\s*-\s*(\d{1,6})\s*$", re.I)


class AssetError(ValueError):
    """Something about the registry cannot be done; the message says what."""


@dataclass
class Asset:
    """The card of one cable or device."""

    id: str
    kind: str
    name: str
    description: str = ""  # what it is: "RG316, SMA male to SMA male"
    manufacturer: str = ""
    serial: str = ""
    owner: str = ""
    notes: str = ""
    attributes: Dict[str, Any] = field(
        default_factory=dict
    )  # kind-specific: length_m, connectors...
    created: str = ""
    retired: bool = False  # taken out of use: kept, so that its old results still make sense
    extra: Dict[str, Any] = field(default_factory=dict)  # keys this program does not know

    def to_dict(self) -> Dict[str, Any]:
        """As JSON; the keys of ``extra`` are written back."""
        data = {
            "id": self.id, "kind": self.kind, "name": self.name, "description": self.description,
            "manufacturer": self.manufacturer, "serial": self.serial, "owner": self.owner,
            "notes": self.notes, "attributes": self.attributes, "created": self.created,
            "retired": self.retired,
        }  # fmt: skip
        return {**self.extra, **data}

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "Asset":
        """Build a card from JSON; ``AssetError`` if it has no id or no name."""
        if not isinstance(raw.get("id"), str) or not raw["id"]:
            raise AssetError(f"a card without a code: {dict(raw)!r}")
        known = {"id", "kind", "name", "description", "manufacturer", "serial", "owner", "notes",
                 "attributes", "created", "retired"}  # fmt: skip
        attributes = raw.get("attributes")
        return Asset(
            id=raw["id"],
            kind=str(raw.get("kind", "other")),
            name=str(raw.get("name", "")),
            description=str(raw.get("description", "")),
            manufacturer=str(raw.get("manufacturer", "")),
            serial=str(raw.get("serial", "")),
            owner=str(raw.get("owner", "")),
            notes=str(raw.get("notes", "")),
            attributes=dict(attributes) if isinstance(attributes, dict) else {},
            created=str(raw.get("created", "")),
            retired=bool(raw.get("retired", False)),
            extra={k: v for k, v in raw.items() if k not in known},
        )

    def snapshot(self) -> Dict[str, Any]:
        """A copy of the card, to be saved with a run: what the object was when it was measured."""
        return copy.deepcopy(self.to_dict())


def default_path() -> Path:
    """The registry file: ``$OLA_ASSETS_FILE``, else ``~/.open_lab_automation/assets.json``."""
    env = os.environ.get(ENV_FILE)
    return Path(env) if env else Path.home() / ".open_lab_automation" / "assets.json"


def normalize_code(text: str) -> Optional[str]:
    """``"OLA:cbl-42"``, ``" CBL - 0042 "`` -> ``"CBL-0042"``; None if it is not a code. What a QR
    scan or a barcode scanner types is accepted with or without the ``OLA:`` and in any case."""
    match = _CODE.match((text or "").strip())
    if not match:
        return None
    return f"{match.group(1).upper()}-{int(match.group(2)):04d}"


def qr_text(code: str) -> str:
    """What the QR code of a label holds: ``OLA:CBL-0042``."""
    return QR_PREFIX + code


class AssetRegistry:
    """The cards, in a JSON file (see the module docstring)."""

    def __init__(self, path: Union[str, Path, None] = None):
        self.path = Path(path) if path else default_path()
        self.assets: List[Asset] = []
        self.counters: Dict[str, int] = {}  # prefix -> the last number given (never goes back)
        self._extra: Dict[str, Any] = {}
        self.load()

    # ----- file -------------------------------------------------------------------------------
    def load(self) -> None:
        """Read the file (a missing file is an empty registry). ``AssetError`` if it is damaged:
        nothing is overwritten, so it can be repaired by hand."""
        self.assets, self.counters, self._extra = [], {}, {}
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AssetError(f"cannot read the registry {self.path}: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("assets", []), list):
            raise AssetError(f"{self.path}: not a registry of cables and devices")
        if raw.get("format_version", FORMAT_VERSION) > FORMAT_VERSION:
            raise AssetError(f"{self.path}: made by a newer version of the program")
        self.assets = [Asset.from_dict(item) for item in raw.get("assets", [])]
        counters = raw.get("counters", {})
        self.counters = (
            {k: int(v) for k, v in counters.items()} if isinstance(counters, dict) else {}
        )
        self._extra = {
            k: v for k, v in raw.items() if k not in ("format_version", "counters", "assets")
        }
        for asset in self.assets:  # a number written by hand must not be given again
            code = normalize_code(asset.id)
            if code:
                prefix, number = code.split("-")
                self.counters[prefix] = max(self.counters.get(prefix, 0), int(number))

    def save(self) -> None:
        """Write the file atomically; the previous one is kept as ``<name>.bak``."""
        data = {
            **self._extra,
            "format_version": FORMAT_VERSION,
            "counters": self.counters,
            "assets": [a.to_dict() for a in self.assets],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if self.path.is_file():
            backup = self.path.with_name(self.path.name + ".bak")
            backup.write_bytes(self.path.read_bytes())
        os.replace(temp, self.path)

    # ----- the cards --------------------------------------------------------------------------
    def get(self, code: str) -> Optional[Asset]:
        """The card with this code (as typed, scanned or stored), or None."""
        wanted = normalize_code(code) or code
        return next((a for a in self.assets if (normalize_code(a.id) or a.id) == wanted), None)

    find = get  # a scan gives "OLA:CBL-0042": same thing

    def list(self, kind: Optional[str] = None, include_retired: bool = True) -> List[Asset]:
        """The cards, in the order they were made, of one kind or all."""
        return [
            a for a in self.assets
            if (kind is None or a.kind == kind) and (include_retired or not a.retired)
        ]  # fmt: skip

    def create(
        self,
        kind: str,
        name: str,
        description: str = "",
        attributes: Optional[Mapping[str, Any]] = None,
        save: bool = True,
        **fields: str,
    ) -> Asset:
        """Add a card with the next code of its kind (``manufacturer``, ``serial``, ``owner`` and
        ``notes`` can be given as keywords). ``AssetError`` for an unknown kind or an empty name."""
        if kind not in KINDS:
            raise AssetError(f"unknown kind {kind!r}: use one of {', '.join(KINDS)}")
        if not name.strip():
            raise AssetError("the name cannot be empty")
        unknown = set(fields) - {"manufacturer", "serial", "owner", "notes"}
        if unknown:
            raise AssetError(f"unknown field(s) {sorted(unknown)}")
        prefix = KINDS[kind]["prefix"]
        number = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = number
        asset = Asset(
            id=f"{prefix}-{number:04d}",
            kind=kind,
            name=name.strip(),
            description=description,
            attributes=dict(attributes or {}),
            created=time.strftime("%Y-%m-%d"),
            **fields,
        )
        self.assets.append(asset)
        if save:
            self.save()
        return asset

    def update(self, code: str, save: bool = True, **changes: Any) -> Asset:
        """Change fields of a card (not its code or kind). ``AssetError`` if there is no such card
        or a field is unknown."""
        asset = self._need(code)
        allowed = {
            "name",
            "description",
            "manufacturer",
            "serial",
            "owner",
            "notes",
            "attributes",
            "retired",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise AssetError(f"cannot change {sorted(unknown)}: the code and the kind are fixed")
        if "name" in changes and not str(changes["name"]).strip():
            raise AssetError("the name cannot be empty")
        for key, value in changes.items():
            setattr(asset, key, value)
        if save:
            self.save()
        return asset

    def delete(self, code: str, save: bool = True) -> None:
        """Remove a card. Its code is **not** given again. (Retiring it keeps old results readable:
        prefer ``update(code, retired=True)`` for a cable that was used.)"""
        asset = self._need(code)
        self.assets.remove(asset)
        if save:
            self.save()

    def _need(self, code: str) -> Asset:
        asset = self.get(code)
        if asset is None:
            raise AssetError(f"no cable or device with the code {code!r}")
        return asset

    def choices(self, kind: Optional[str] = None) -> List[str]:
        """``"CBL-0042 - RG316 SMA-SMA"`` for every card that is in use, for a list to pick from."""
        return [f"{a.id} - {a.name}" for a in self.list(kind, include_retired=False)]


# ----- the cards and the measurements ------------------------------------------------------------
def asset_ids_in(params: Mapping[str, Any]) -> List[str]:
    """The codes a measurement file names (``cable.asset_id``, ``device.asset_id``,
    ``filter.asset_id``, ``attenuator.asset_id``), normalised, without repeats."""
    found: List[str] = []
    for group in ASSET_GROUPS:
        item = params.get(group)
        if isinstance(item, dict) and isinstance(item.get("asset_id"), str):
            code = normalize_code(item["asset_id"])
            if code and code not in found:
                found.append(code)
    return found


@dataclass
class RunRef:
    """A run file that used an object: where it is, its date, the measurement, how it ended."""

    path: Path
    when: str
    measurement: str
    state: str


def read_header(path: Path) -> Optional[Dict[str, Any]]:
    """The header line of a run file (its first line), or None if there is none. The rest of the
    file is not read."""
    try:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
        header = json.loads(first)
    except (OSError, ValueError):
        return None
    return header if isinstance(header, dict) and header.get("kind") == "run" else None


def _end_state(path: Path) -> str:
    """How the run ended, from the last lines of the file (``interrupted`` if there is no end)."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4096))
            tail = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return "interrupted"
    for line in reversed(tail):
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("kind") == "end":
            return str(item.get("state", "interrupted"))
    return "interrupted"


def index_runs(run_dirs: Iterable[Union[str, Path]]) -> Dict[str, List[RunRef]]:
    """Every run file of the folders, grouped by the codes it names: ``{code: [RunRef, ...]}``,
    each list oldest first. One pass over the files (the first line of each), for a table of all
    the cables with how many times each was measured."""
    from .compare import run_date

    out: Dict[str, List[RunRef]] = {}
    for folder in run_dirs:
        folder = Path(folder)
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.jsonl")):
            header = read_header(path)
            if header is None:
                continue
            codes = asset_ids_in(header.get("params") or {})
            if not codes:
                continue
            ref = RunRef(
                path, run_date(path), str(header.get("measurement", "?")), _end_state(path)
            )
            for code in codes:
                out.setdefault(code, []).append(ref)
    for refs in out.values():
        refs.sort(key=lambda r: (r.when, r.path.name))
    return out


def history(code: str, run_dirs: Iterable[Union[str, Path]]) -> List[RunRef]:
    """The runs that used the object with this code, oldest first: found by the code every run
    saved in its header (only the first line of each file is read). Folders that do not exist
    are skipped."""
    return index_runs(run_dirs).get(normalize_code(code) or code, [])


# the figure that tells the most about each kind of measurement, in order of preference
_FIGURES = (
    (re.compile(r"^loss_(.+)_db$"), "{v:.2g} dB @ {f}"),  # a cable's loss at a chosen frequency
    (re.compile(r"^(max_loss)_db$"), "max loss {v:.2g} dB"),
    (re.compile(r"^(insertion_loss)_db$"), "insertion loss {v:.2g} dB"),
    (re.compile(r"^(peak_gain)_db$"), "gain {v:.3g} dB"),
    (re.compile(r"^(min_vswr)$"), "VSWR {v:.2g}"),
)


def last_measurement_line(ref: Optional[RunRef]) -> str:
    """One line for a label from a run (the latest of an object, see ``history``): its most telling
    figure and the date, for example ``"0.6 dB @ 868MHz, 2026-11-03"``. ``""`` if there is no run
    or nothing to say. The figure is only as current as the run: reprint after a new measurement."""
    if ref is None:
        return ""
    from .compare import CompareError, load_run

    try:
        summary = load_run(ref.path).summary
    except CompareError:
        return ""
    for pattern, template in _FIGURES:
        for key, value in summary.items():
            match = pattern.match(key)
            if match and isinstance(value, (int, float)) and not isinstance(value, bool):
                freq = match.group(1) if match.groups() else ""
                return template.format(v=value, f=freq) + f", {ref.when[:10]}"
    return ""


def snapshots_for(params: Mapping[str, Any], registry: Optional[AssetRegistry]) -> Dict[str, Any]:
    """The cards of the objects a measurement names, as they are now: ``{code: card}``. Saved in the
    header of the run, so the card of that day stays with its results. A code that is not in the
    registry is left out."""
    if registry is None:
        return {}
    out = {}
    for code in asset_ids_in(params):
        asset = registry.get(code)
        if asset is not None:
            out[code] = asset.snapshot()
    return out


__all__: Sequence[str] = [
    "Asset", "AssetError", "AssetRegistry", "KINDS", "RunRef", "asset_ids_in", "default_path",
    "history", "index_runs", "last_measurement_line", "normalize_code", "qr_text", "read_header",
    "snapshots_for",
]  # fmt: skip
