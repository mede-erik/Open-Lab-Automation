# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Label templates the user writes and keeps (no Qt): size, layout and free lines of text.

The built-in formats of ``ola.labels`` (``PRESETS``) are fixed. A template is a format of your own:
a name, a size in millimetres, the layout (``single`` or ``flag``), QR code and border on or off,
and a list of **lines**, each a text with places for the data of the card::

    LabelTemplate("Bench", 60, 30, lines=("{id}", "{name}", "Rev {version}", "S/N {serial}"))

The names between braces are the lines of ``ola.labels.FIELDS`` (``{id}``, ``{name}``,
``{version}``, ``{description}``, ``{specs}``, ``{connectors}``, ``{length}``, ``{date}``,
``{last_measurement}``, ``{owner}``, ``{serial}``, ``{notes}``). A line whose places are all empty
is not printed. The code of the card must be in some line (the QR code holds it, but a person
must be able to read it too). The QR code itself always holds ``OLA:<code>``: it cannot be edited,
so that a scan always gives the code back.

Besides the named templates the file keeps the **label of each kind of object**
(``ola.label_design``): one ``LabelSetup`` (the size of the label the user prints on, the same for
every kind) and a ``KindDesign`` for the kinds the user changed (cable, attenuator, amplifier,
adapter, antenna, filter, converter, generic); a kind that was not changed has the ready-made design
(``default_design``). ``TemplateStore.drawing`` lays out the label of a card with the design of its
kind.

``TemplateStore`` keeps all of it in one JSON file (``$OLA_LABEL_TEMPLATES``, else
``~/.open_lab_automation/label_templates.json``) shared by all projects, written atomically; a
damaged file is reported and never overwritten.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .assets import Asset
from .fileio import atomic_write_json
from .label_design import (
    DesignError,
    KindDesign,
    LabelSetup,
    build_kind_drawing,
    default_design,
    design_problems,
    setup_problems,
)
from .labels import PRESETS, Drawing, LabelSpec, Measure, unknown_placeholders

ENV_FILE = "OLA_LABEL_TEMPLATES"
FORMAT_VERSION = 2  # 1: only the named templates (still read)
LAYOUTS = ("single", "flag")
MAX_LINES = 12
MAX_LINE_CHARS = 80
WIDTH_RANGE = (10.0, 300.0)
HEIGHT_RANGE = (8.0, 200.0)
MARGIN_RANGE = (0.0, 10.0)


class LabelTemplateError(Exception):
    """The template file is damaged or a template is not valid."""


@dataclass
class LabelTemplate:
    """A label format of the user."""

    name: str
    width_mm: float = 50.0
    height_mm: float = 25.0
    layout: str = "single"
    lines: Sequence[str] = ("{id}", "{name}")
    qr: bool = True
    border: bool = False
    margin_mm: float = 1.5

    def to_spec(self) -> LabelSpec:
        """The format as ``build_drawing`` takes it."""
        return LabelSpec(
            self.name,
            float(self.width_mm),
            float(self.height_mm),
            self.layout,
            qr=self.qr,
            border=self.border,
            margin_mm=float(self.margin_mm),
            lines=tuple(self.lines),
        )

    def to_dict(self) -> Dict[str, Any]:
        """As written in the file."""
        return {
            "name": self.name,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "layout": self.layout,
            "lines": list(self.lines),
            "qr": self.qr,
            "border": self.border,
            "margin_mm": self.margin_mm,
        }

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "LabelTemplate":
        """Read one entry of the file; ``LabelTemplateError`` if it is not an object with a name."""
        if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str):
            raise LabelTemplateError(f"not a label template: {raw!r}")
        try:
            return LabelTemplate(
                name=raw["name"],
                width_mm=float(raw.get("width_mm", 50)),
                height_mm=float(raw.get("height_mm", 25)),
                layout=str(raw.get("layout", "single")),
                lines=tuple(str(x) for x in raw.get("lines", ("{id}",))),
                qr=bool(raw.get("qr", True)),
                border=bool(raw.get("border", False)),
                margin_mm=float(raw.get("margin_mm", 1.5)),
            )
        except (TypeError, ValueError) as exc:
            raise LabelTemplateError(f"template '{raw['name']}': {exc}") from exc


def problems(template: LabelTemplate) -> List[str]:
    """What is wrong with a template, one sentence each (empty if it is fine)."""
    found: List[str] = []
    name = template.name.strip()
    if not name:
        found.append("the template needs a name")
    elif name in PRESETS:
        found.append(f"'{name}' is the name of a built-in format")
    for label, value, (low, high) in (
        ("width", template.width_mm, WIDTH_RANGE),
        ("height", template.height_mm, HEIGHT_RANGE),
        ("margin", template.margin_mm, MARGIN_RANGE),
    ):
        if not low <= value <= high:
            found.append(f"the {label} must be between {low:g} and {high:g} mm")
    if template.layout not in LAYOUTS:
        found.append(f"the layout must be one of: {', '.join(LAYOUTS)}")
    lines = list(template.lines)
    if not lines:
        found.append("the template needs at least one line")
    if len(lines) > MAX_LINES:
        found.append(f"at most {MAX_LINES} lines")
    for n, line in enumerate(lines, 1):
        if len(line) > MAX_LINE_CHARS:
            found.append(f"line {n} is longer than {MAX_LINE_CHARS} characters")
        bad = unknown_placeholders(line)
        if bad:
            found.append(f"line {n}: unknown {', '.join('{' + b + '}' for b in bad)}")
    if lines and not any("{id}" in line for line in lines):
        found.append("a line must show the code: {id}")
    return found


def default_path() -> Path:
    """The templates file: ``$OLA_LABEL_TEMPLATES``, else ``~/.open_lab_automation/...``."""
    env = os.environ.get(ENV_FILE)
    if env:
        return Path(env)
    return Path.home() / ".open_lab_automation" / "label_templates.json"


class TemplateStore:
    """The templates of the user, in one file."""

    def __init__(self, path: Union[str, Path, None] = None):
        self.path = Path(path) if path else default_path()
        self.templates: List[LabelTemplate] = []
        self.setup = LabelSetup()
        self.designs: Dict[str, KindDesign] = {}  # only the kinds the user changed
        self.load()

    def load(self) -> None:
        """Read the file (a missing file is an empty list); ``LabelTemplateError`` if damaged: the
        file is not touched, so it can be repaired by hand."""
        self.templates, self.setup, self.designs = [], LabelSetup(), {}
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            items = raw["templates"]
            if not isinstance(items, list):
                raise TypeError("'templates' is not a list")
            self.templates = [LabelTemplate.from_dict(x) for x in items]
            if "setup" in raw:
                self.setup = LabelSetup.from_dict(raw["setup"])
            self.designs = {
                str(kind): KindDesign.from_dict(body)
                for kind, body in (raw.get("designs") or {}).items()
            }
        except (OSError, ValueError, KeyError, TypeError, DesignError) as exc:
            raise LabelTemplateError(f"{self.path}: {exc}") from exc

    def save(self) -> None:
        """Write the file (the folder is made if needed)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self.path,
            {
                "format_version": FORMAT_VERSION,
                "setup": self.setup.to_dict(),
                "designs": {k: d.to_dict() for k, d in self.designs.items()},
                "templates": [t.to_dict() for t in self.templates],
            },
        )

    # ----- the label of each kind ---------------------------------------------------------
    def set_setup(self, setup: LabelSetup) -> None:
        """Change the size of the label (for every kind); ``LabelTemplateError`` if not valid.
        Saved at once."""
        wrong = setup_problems(setup)
        if wrong:
            raise LabelTemplateError("; ".join(wrong))
        self.setup = setup
        self.save()

    def design(self, kind: str) -> KindDesign:
        """The design of a kind: the one the user made, else the ready-made one."""
        return self.designs.get(kind) or default_design(kind)

    def is_customised(self, kind: str) -> bool:
        """True if the user changed the design of this kind."""
        return kind in self.designs

    def set_design(self, kind: str, design: KindDesign) -> None:
        """Keep the design of a kind; ``LabelTemplateError`` if it is not valid. Saved at once."""
        wrong = design_problems(design, self.setup)
        if wrong:
            raise LabelTemplateError("; ".join(wrong))
        self.designs[kind] = design
        self.save()

    def reset_design(self, kind: str) -> bool:
        """Go back to the ready-made design of a kind; False if it had not been changed."""
        if kind not in self.designs:
            return False
        del self.designs[kind]
        self.save()
        return True

    def drawing(
        self,
        asset: Asset,
        last_measurement: str = "",
        measure: Optional[Measure] = None,
        setup: Optional[LabelSetup] = None,
    ) -> Drawing:
        """The label of a card, with the design of its kind on the label size of the user.
        ``setup`` replaces the saved size for this drawing (the label window can switch the QR
        code or the border off for one printing without changing the design)."""
        return build_kind_drawing(
            setup or self.setup, self.design(asset.kind), asset, last_measurement, measure
        )

    def names(self) -> List[str]:
        """The names, in the order they were made."""
        return [t.name for t in self.templates]

    def get(self, name: str) -> Optional[LabelTemplate]:
        """The template called ``name``, or None."""
        return next((t for t in self.templates if t.name == name), None)

    def put(self, template: LabelTemplate, replace: Optional[str] = None) -> None:
        """Add a template, or replace the one called ``replace`` (a rename keeps its place);
        ``LabelTemplateError`` if it is not valid or the name is taken. Saved at once."""
        template.name = template.name.strip()
        template.lines = tuple(template.lines)
        wrong = problems(template)
        if wrong:
            raise LabelTemplateError("; ".join(wrong))
        clash = self.get(template.name)
        if clash is not None and template.name != replace:
            raise LabelTemplateError(f"there is already a template called '{template.name}'")
        old = self.get(replace) if replace else None
        if old is not None:
            self.templates[self.templates.index(old)] = template
        else:
            self.templates.append(template)
        self.save()

    def delete(self, name: str) -> bool:
        """Remove a template; False if there was none. Saved at once."""
        found = self.get(name)
        if found is None:
            return False
        self.templates.remove(found)
        self.save()
        return True

    def duplicate(self, name: str) -> LabelTemplate:
        """A copy of a template (or of a built-in format, with its lines) as ``<name> copy``,
        saved; ``LabelTemplateError`` if there is no such format."""
        source = self.get(name)
        if source is None and name in PRESETS:
            spec = PRESETS[name]
            lines = tuple("{%s}" % k for k in spec.fields)
            source = LabelTemplate(
                name, spec.width_mm, spec.height_mm, spec.layout, lines, spec.qr, spec.border
            )
        if source is None:
            raise LabelTemplateError(f"no format called '{name}'")
        base, n, new = f"{name} copy", 1, f"{name} copy"
        while self.get(new) or new in PRESETS:
            n += 1
            new = f"{base} {n}"
        copy = LabelTemplate(
            new, source.width_mm, source.height_mm, source.layout, tuple(source.lines),
            source.qr, source.border, source.margin_mm,
        )  # fmt: skip
        self.put(copy)
        return copy


__all__ = [
    "LabelTemplate", "LabelTemplateError", "TemplateStore", "default_path", "problems",
]  # fmt: skip
