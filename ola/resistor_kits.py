# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Kits of resistors, saved once and used in many measurements (no Qt).

The power resistors of a bench are the same from one measurement to the next: a kit keeps them,
with the name each one has, its value, its tolerance and its power rating, and the relay of the
multiplexer that connects it if it is always wired the same way. A measurement then writes
``{"kit": "PWR", "ref": "R22"}`` instead of the values, or, with a default kit
(``"resistor_kit": "PWR"``), only ``{"ref": "R22"}``::

    kits = KitRegistry()                         # ~/.open_lab_automation/resistor_kits.json
    kits.put(Kit("PWR", [KitResistor("R22", 22, tol_pct=1, power_w=50), ...]))
    loads = kits.resolve_loads(params["loads"], params.get("resistor_kit", ""))

``resolve_loads`` gives the loads with every reference replaced by the values of the kit (and
``kit`` / ``ref`` kept, to know where they came from). What the entry says besides ``kit`` and
``ref`` wins over the kit, so a relay can be given for one measurement without changing the kit.
The project does this when a measurement starts and saves the resolved loads in the header of the
run: the values that were used stay with the results, whatever happens to the kit later.

The file is ``$OLA_RESISTOR_KITS_FILE``, else ``~/.open_lab_automation/resistor_kits.json``; it is
written whole, to a temporary file first, so a failure cannot leave half a file, and the previous
one is kept as ``resistor_kits.json.bak``.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

ENV_FILE = "OLA_RESISTOR_KITS_FILE"
FORMAT_VERSION = 1
NAME_PATTERN = re.compile(r"^[^\s\"'{}\[\]|]+(?: [^\s\"'{}\[\]|]+)*$")  # no quotes or brackets
MAX_RESISTORS = 200


class KitError(ValueError):
    """A kit or a reference cannot be used; the message says why."""


def default_path() -> Path:
    """The kits file: ``$OLA_RESISTOR_KITS_FILE``, else
    ``~/.open_lab_automation/resistor_kits.json``."""
    env = os.environ.get(ENV_FILE)
    return Path(env) if env else Path.home() / ".open_lab_automation" / "resistor_kits.json"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _name(text: Any, what: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise KitError(f"{what}: give a name")
    text = text.strip()
    if not NAME_PATTERN.match(text) or len(text) > 60:
        raise KitError(
            f"{what}: {text!r} cannot be used (up to 60 characters, no quotes, brackets or |)"
        )
    return text


@dataclass
class KitResistor:
    """One resistor of a kit."""

    name: str
    r_ohm: float
    tol_pct: float = 0.0
    power_w: Optional[float] = None
    channel: str = ""  # the relay of the multiplexer, if it is always wired to the same one
    note: str = ""

    def check(self, where: str = "") -> None:
        """``KitError`` if a value cannot be used."""
        at = f"{where}: " if where else ""
        _name(self.name, f"{at}the name of a resistor")
        if not _number(self.r_ohm) or self.r_ohm <= 0:
            raise KitError(f"{at}{self.name}: the resistance must be a number of ohms above 0")
        if not _number(self.tol_pct) or not 0 <= self.tol_pct < 100:
            raise KitError(
                f"{at}{self.name}: the tolerance must be a percentage from 0 to below 100"
            )
        if self.power_w is not None and (not _number(self.power_w) or self.power_w <= 0):
            raise KitError(f"{at}{self.name}: the rating must be a number of watts above 0")
        if not isinstance(self.channel, str) or not isinstance(self.note, str):
            raise KitError(f"{at}{self.name}: the relay and the note must be text")

    def to_dict(self) -> Dict[str, Any]:
        """The resistor as it is written in the file (only what it has)."""
        out: Dict[str, Any] = {"name": self.name, "r_ohm": self.r_ohm}
        if self.tol_pct:
            out["tol_pct"] = self.tol_pct
        if self.power_w:
            out["power_w"] = self.power_w
        if self.channel:
            out["channel"] = self.channel
        if self.note:
            out["note"] = self.note
        return out

    @classmethod
    def from_dict(cls, raw: Any, where: str = "") -> "KitResistor":
        """A resistor from its dictionary; ``KitError`` for anything that cannot be used."""
        if not isinstance(raw, Mapping):
            raise KitError(f"{where}: a resistor must be an object")
        unknown = sorted(set(raw) - {"name", "r_ohm", "tol_pct", "power_w", "channel", "note"})
        if unknown:
            raise KitError(f"{where}: unknown field(s) {unknown}")
        resistor = cls(
            str(raw.get("name", "")).strip() if raw.get("name") is not None else "",
            raw.get("r_ohm"),  # type: ignore[arg-type]
            raw.get("tol_pct", 0.0),
            raw.get("power_w"),
            raw.get("channel", ""),
            raw.get("note", ""),
        )
        resistor.check(where)
        return resistor


@dataclass
class Kit:
    """A named set of resistors."""

    name: str
    resistors: List[KitResistor] = field(default_factory=list)
    note: str = ""

    def check(self) -> None:
        """``KitError`` if the name is not usable, two resistors share a name, or too many."""
        _name(self.name, "the name of the kit")
        if len(self.resistors) > MAX_RESISTORS:
            raise KitError(f"{self.name}: too many resistors (at most {MAX_RESISTORS})")
        seen = set()
        for resistor in self.resistors:
            resistor.check(self.name)
            if resistor.name in seen:
                raise KitError(f"{self.name}: two resistors are called {resistor.name!r}")
            seen.add(resistor.name)

    def get(self, name: str) -> Optional[KitResistor]:
        """The resistor of that name, or None."""
        return next((r for r in self.resistors if r.name == name), None)


class KitRegistry:
    """The kits of resistors in their file (see the module docstring)."""

    def __init__(self, path: Union[str, Path, None] = None):
        """``KitError`` if the file exists and cannot be read; a file that is not there is an empty
        registry (it is made by the first ``save``)."""
        self.path = Path(path) if path else default_path()
        self.kits: Dict[str, Kit] = {}
        self._read()

    # ----- the file ---------------------------------------------------------------------------
    def _read(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise KitError(f"{self.path}: cannot read the kits ({exc})") from exc
        if not isinstance(data, dict) or not isinstance(data.get("kits"), dict):
            raise KitError(f"{self.path}: not a file of resistor kits")
        if data.get("format_version", FORMAT_VERSION) > FORMAT_VERSION:
            raise KitError(f"{self.path}: made by a newer version of the program")
        for name, body in data["kits"].items():
            if not isinstance(body, dict):
                raise KitError(f"{self.path}: the kit {name!r} must be an object")
            resistors = [
                KitResistor.from_dict(r, f"{name}[{i}]")
                for i, r in enumerate(body.get("resistors", []))
            ]
            kit = Kit(name, resistors, str(body.get("note", "")))
            kit.check()
            self.kits[name] = kit

    def save(self) -> None:
        """Write the kits: all of them, to a temporary file first and then moved in place; the
        previous file is kept as ``<name>.bak``."""
        data = {
            "format_version": FORMAT_VERSION,
            "kits": {
                name: {
                    **({"note": kit.note} if kit.note else {}),
                    "resistors": [r.to_dict() for r in kit.resistors],
                }
                for name, kit in sorted(self.kits.items())
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if self.path.is_file():
            self.path.with_name(self.path.name + ".bak").write_bytes(self.path.read_bytes())
        os.replace(temp, self.path)

    # ----- the kits ---------------------------------------------------------------------------
    def names(self) -> List[str]:
        """The names of the kits, sorted."""
        return sorted(self.kits)

    def get(self, name: str) -> Optional[Kit]:
        """The kit of that name, or None."""
        return self.kits.get(name)

    def put(self, kit: Kit, save: bool = True) -> None:
        """Add a kit or replace the one of the same name. ``KitError`` if it cannot be used (nothing
        is changed)."""
        kit.check()
        self.kits[kit.name] = copy.deepcopy(kit)
        if save:
            self.save()

    def rename(self, old: str, new: str, save: bool = True) -> None:
        """Give a kit another name. ``KitError`` if there is no such kit or the name is taken."""
        if old not in self.kits:
            raise KitError(f"there is no kit called {old!r}")
        new = _name(new, "the new name of the kit")
        if new != old and new in self.kits:
            raise KitError(f"there is already a kit called {new!r}")
        kit = self.kits.pop(old)
        kit.name = new
        self.kits[new] = kit
        if save:
            self.save()

    def delete(self, name: str, save: bool = True) -> None:
        """Remove a kit. ``KitError`` if there is no such kit."""
        if name not in self.kits:
            raise KitError(f"there is no kit called {name!r}")
        del self.kits[name]
        if save:
            self.save()

    def reference(self, kit: str, resistor: str) -> Dict[str, str]:
        """What to write in a load to use a resistor of a kit: ``{"kit": ..., "ref": ...}``."""
        return {"kit": kit, "ref": resistor}

    # ----- the references ---------------------------------------------------------------------
    def resolve(self, entry: Mapping[str, Any], default_kit: str = "") -> Dict[str, Any]:
        """One resistor entry with its ``ref`` replaced by the values of the kit; what the entry
        says besides ``kit`` and ``ref`` wins. An entry that is not a reference is returned as it
        is. ``KitError`` for an unknown kit or resistor."""
        if "ref" not in entry:
            return dict(entry)
        name = entry.get("kit") or default_kit
        if not name:
            raise KitError(
                f"the resistor {entry['ref']!r} names no kit: write \"kit\" in it, or give "
                '"resistor_kit" in the measurement'
            )
        kit = self.kits.get(str(name))
        if kit is None:
            known = ", ".join(self.names()) or "none"
            raise KitError(f"there is no kit of resistors called {name!r} (the kits are: {known})")
        resistor = kit.get(str(entry["ref"]))
        if resistor is None:
            known = ", ".join(r.name for r in kit.resistors) or "none"
            raise KitError(f"the kit {name!r} has no resistor {entry['ref']!r} (it has: {known})")
        values = resistor.to_dict()
        values.pop("note", None)
        values.pop("name", None)  # the name of the resistor is the one in the kit
        out: Dict[str, Any] = {"name": resistor.name, **values}
        out.update({k: v for k, v in entry.items() if k not in ("kit", "ref")})
        out["kit"], out["ref"] = str(name), resistor.name
        return out

    def resolve_node(self, raw: Any, default_kit: str = "") -> Any:
        """A load or a group (or a list of them) with every reference resolved, as a new object."""
        if isinstance(raw, list):
            return [self.resolve_node(item, default_kit) for item in raw]
        if not isinstance(raw, Mapping):
            return raw
        if "ref" in raw:
            return self.resolve(raw, default_kit)
        out = dict(raw)
        for key in ("series", "parallel"):
            if key in out:
                out[key] = self.resolve_node(out[key], default_kit)
        return out

    def resolve_loads(self, loads: Any, default_kit: str = "") -> Any:
        """The loads of a measurement with every reference to a kit replaced by its values. A load
        that is only a reference to one resistor is called as that resistor, unless it has a name.
        """
        return self.resolve_node(loads, default_kit)


__all__ = [
    "Kit", "KitError", "KitRegistry", "KitResistor", "default_path",
]  # fmt: skip
