# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The archive of the devices under test (DUT). No Qt.

A **DUT** is what is tested in a measurement: an antenna, a filter, a converter, anything else.
It is not part of the set-up of the measurement, so it is kept apart from the components
(cables, amplifiers, attenuators and adapters, ``ola.assets``) and it is **optional**: a
measurement can be made without naming one, and then nothing is remembered about it.

Every DUT has a **code** (``DUT-0001``, never used again), a **name** the user chooses to
recognise it (``Pippo``), a **category** and any number of **versions**. A version is free text
(``rev A``, ``RFB``, ``V01``): it is written the way it is used in the lab.

    archive = DutRegistry()                          # the default file
    dut = archive.create("converter", "Pippo", version="rev A")
    dut.id                                           # "DUT-0001"
    archive.add_version(dut.id, "rev B", "new inductor")
    archive.current_version(dut.id)                  # "rev B"
    archive.find("OLA:dut-1")                        # what a barcode scanner or a QR gives
    archive.migrate_from(AssetRegistry())            # the antennas and filters of the components

The file is one JSON file for all projects (default ``~/.open_lab_automation/duts.json``, or the
file named by ``OLA_DUTS_FILE``), written the same way as the registry of components: atomically,
with the previous one kept as ``duts.json.bak``. A card is the ``Asset`` card of the components with
a list of versions, so the labels of the components (``ola.labels``) print a DUT as they are.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .assets import Asset, AssetError, AssetRegistry, normalize_code

ENV_FILE = "OLA_DUTS_FILE"
PREFIX = "DUT"  # one sequence of codes for every category: DUT-0001, DUT-0002...

# category -> the prefix of its codes (the same for all) and the attributes its card suggests
CATEGORIES: Dict[str, Dict[str, Any]] = {
    "antenna": {
        "prefix": PREFIX,
        "attributes": [("frequency_range", ""), ("connector", ""), ("gain_dbi", "dBi")],
    },
    "filter": {
        "prefix": PREFIX,
        "attributes": [("filter_type", ""), ("frequency", "Hz"), ("connectors", "")],
    },
    "converter": {
        "prefix": PREFIX,
        "attributes": [
            ("topology", ""),
            ("input_voltage", "V"),
            ("output_voltage", "V"),
            ("max_power_w", "W"),
        ],
    },
    "generic": {"prefix": PREFIX, "attributes": []},
}

# the kinds of the registry of components that are devices under test, and the category they get
MIGRATED_KINDS: Dict[str, str] = {"antenna": "antenna", "filter": "filter", "other": "generic"}


def default_path() -> Path:
    """The archive file: ``$OLA_DUTS_FILE``, else ``~/.open_lab_automation/duts.json``."""
    env = os.environ.get(ENV_FILE)
    return Path(env) if env else Path.home() / ".open_lab_automation" / "duts.json"


def _version(raw: Any) -> Optional[Dict[str, Any]]:
    """One version from JSON (``label``, ``date``, ``note``, ``retired``); None if no label."""
    if not isinstance(raw, Mapping) or not str(raw.get("label", "")).strip():
        return None
    return {
        "label": str(raw["label"]).strip(),
        "date": str(raw.get("date", "")),
        "note": str(raw.get("note", "")),
        "retired": bool(raw.get("retired", False)),
    }


@dataclass
class Dut(Asset):
    """The card of one device under test: the card of a component, with its versions. The
    ``kind`` is the category (``antenna``, ``filter``, ``converter``, ``generic``)."""

    versions: List[Dict[str, Any]] = field(default_factory=list)  # oldest first, label is free text

    @property
    def category(self) -> str:
        """The category of the device (the ``kind`` of the card)."""
        return self.kind

    def to_dict(self) -> Dict[str, Any]:
        """As JSON: the card of a component and the versions."""
        return {**super().to_dict(), "versions": [dict(v) for v in self.versions]}

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "Dut":
        """Build a card from JSON; ``AssetError`` if it has no code. A version without a label is
        left out."""
        base = Asset.from_dict(raw)
        values = {f.name: getattr(base, f.name) for f in fields(Asset)}
        values["extra"] = {k: v for k, v in base.extra.items() if k != "versions"}
        raw_versions = raw.get("versions")
        versions = [_version(v) for v in raw_versions] if isinstance(raw_versions, list) else []
        return Dut(versions=[v for v in versions if v is not None], **values)

    def version_labels(self, include_retired: bool = True) -> List[str]:
        """The labels of the versions, oldest first."""
        return [v["label"] for v in self.versions if include_retired or not v["retired"]]


class DutRegistry(AssetRegistry):
    """The cards of the devices under test, in a JSON file (see the module docstring). Everything
    of the registry of components works the same (``get``, ``list``, ``update``, ``delete``...);
    the kinds are the categories."""

    card_class = Dut
    kinds = CATEGORIES
    title = "archive of devices under test"
    what = "device under test"

    def _default_path(self) -> Path:
        return default_path()

    # ----- the cards --------------------------------------------------------------------------
    def get(self, code: str) -> Optional[Dut]:  # type: ignore[override]
        """The card with this code (as typed, scanned or stored). A code the card had before (an
        antenna that was ``ANT-0003`` in the components) finds it too, so the old labels still
        work."""
        found = super().get(code)
        if found is not None:
            return found  # type: ignore[return-value]
        wanted = normalize_code(code) or code
        for card in self.assets:
            if wanted in {normalize_code(old) or old for old in card.former_codes}:
                return card  # type: ignore[return-value]
        return None

    find = get

    def create(  # type: ignore[override]
        self,
        kind: str,
        name: str,
        description: str = "",
        attributes: Optional[Mapping[str, Any]] = None,
        save: bool = True,
        version: str = "",
        **fields_: str,
    ) -> Dut:
        """Add a DUT of a category (``antenna``, ``filter``, ``converter``, ``generic``) with the
        next code. ``version`` (free text) gives it a first version. ``AssetError`` for an unknown
        category or an empty name."""
        card = super().create(kind, name, description, attributes, save=False, **fields_)
        if version.strip():
            self._append_version(card, version, "")  # type: ignore[arg-type]
        if save:
            self.save()
        return card  # type: ignore[return-value]

    # ----- the versions -----------------------------------------------------------------------
    def add_version(
        self, code: str, label: str, note: str = "", save: bool = True
    ) -> Dict[str, Any]:
        """Add a version to a DUT (free text, ``rev B``). ``AssetError`` if the label is empty or
        the DUT already has it (a capital or a space around it does not make another)."""
        card = self._need(code)
        entry = self._append_version(card, label, note)  # type: ignore[arg-type]
        if save:
            self.save()
        return entry

    def versions_of(self, code: str, include_retired: bool = True) -> List[str]:
        """The versions of a DUT, oldest first."""
        return self._need(code).version_labels(include_retired)  # type: ignore[attr-defined]

    def has_version(self, code: str, label: str) -> bool:
        """True if the DUT has this version (the spelling is compared without capitals or spaces
        around it)."""
        wanted = label.strip().casefold()
        return any(v.casefold() == wanted for v in self.versions_of(code))

    def current_version(self, code: str) -> Optional[str]:
        """The latest version in use (the last one that is not retired), or None."""
        labels = self.versions_of(code, include_retired=False)
        return labels[-1] if labels else None

    def retire_version(
        self, code: str, label: str, retired: bool = True, save: bool = True
    ) -> None:
        """Take a version out of use (or back): it stays, so that its old results still make sense.
        ``AssetError`` if the DUT has no such version."""
        card = self._need(code)
        wanted = label.strip().casefold()
        for entry in card.versions:  # type: ignore[attr-defined]
            if entry["label"].casefold() == wanted:
                entry["retired"] = bool(retired)
                if save:
                    self.save()
                return
        raise AssetError(f"{card.id} has no version {label!r}")

    @staticmethod
    def _append_version(card: Dut, label: str, note: str) -> Dict[str, Any]:
        label = label.strip()
        if not label:
            raise AssetError("the version cannot be empty")
        if label.casefold() in {v.casefold() for v in card.version_labels()}:
            raise AssetError(f"{card.id} already has the version {label!r}")
        entry = {"label": label, "date": time.strftime("%Y-%m-%d"), "note": note, "retired": False}
        card.versions.append(entry)
        return entry

    # ----- from the components ----------------------------------------------------------------
    def migrate_from(self, components: AssetRegistry) -> List[Dut]:
        """Move the antennas, the filters and the generic devices of the registry of components
        here (see ``MIGRATED_KINDS``), and return the cards that moved.

        A card keeps its ``uid``, so the runs it was measured in still find it. It gets the next
        ``DUT`` code and its old code goes to ``former_codes``, where ``get`` finds it (a label
        already stuck on the antenna keeps working). A card that already has a ``DUT`` code (the
        generic ones) keeps it, unless the archive has that code for another device. This archive is
        written first and the components after, so a stop in the middle loses nothing; doing it
        again moves what is left."""
        moving = [c for c in components.assets if c.kind in MIGRATED_KINDS]
        known = {c.uid for c in self.assets}

        def keeps_code(card: Asset) -> bool:
            code = normalize_code(card.id) or ""
            owner = self.get(code) if code else None
            return code.startswith(PREFIX + "-") and (owner is None or owner.uid == card.uid)

        for card in moving:  # the codes that stay, first: the new numbers go after the highest
            if card.uid not in known and keeps_code(card):
                number = int((normalize_code(card.id) or f"{PREFIX}-0").split("-")[1])
                self.counters[PREFIX] = max(self.counters.get(PREFIX, 0), number)
        moved: List[Dut] = []
        for card in moving:
            if card.uid in known:  # already here (a stop between the two files): only take it out
                continue
            code = card.id
            former = list(card.former_codes)
            if not keeps_code(card):
                self.counters[PREFIX] = self.counters.get(PREFIX, 0) + 1
                code = f"{PREFIX}-{self.counters[PREFIX]:04d}"
                former.append(card.id)
            values = {f.name: getattr(card, f.name) for f in fields(Asset)}
            values.update(id=code, kind=MIGRATED_KINDS[card.kind], former_codes=former)
            moved.append(Dut(**values))
        self.assets.extend(moved)
        if moved:
            self.save()
        gone = {c.uid for c in moving}
        components.assets = [c for c in components.assets if c.uid not in gone]
        if moving:
            components.save()
        return moved


__all__ = [
    "CATEGORIES",
    "Dut",
    "DutRegistry",
    "ENV_FILE",
    "MIGRATED_KINDS",
    "PREFIX",
    "default_path",
]
