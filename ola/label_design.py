# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The design of the labels, one per kind of object (no Qt).

The user has **one label size** (a roll or a sheet of one format): ``LabelSetup`` (width, height,
single label or flag, margin, QR, border). Each kind of object (cable, attenuator, amplifier,
adapter and the devices under test: antenna, filter, converter, generic) has a ``KindDesign``, in
one of two ways:

* **automatic**: a list of lines (``{id}``, ``{name}``, ``Rev {version}``...) that the program
  stacks, QR code on the left, shrinking the text to fit (``ola.labels``);
* **manual**: a list of ``Element`` with a **position and a size in mm**: texts (the text with its
  places, ``x``, ``y`` of the top left corner, ``w`` the width it may take, ``size`` the height of
  the letters, bold, alignment) and the QR code (``x``, ``y``, ``size`` of the square that holds
  it, quiet zone included). ``auto_elements`` turns the automatic layout into elements, as a
  starting point to move around.

``default_design(kind)`` is the ready-made design of each kind. ``build_kind_drawing`` lays out the
label of a card with the design of its kind; a text that does not fit its width is shrunk down to
``MIN_FONT_MM`` and then cut with an ellipsis, and what is cut, outside the label or too small is
listed in ``drawing.warnings``. A **flag** is always automatic (two panels round a fold).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .assets import Asset, qr_text
from .labels import (
    MIN_FONT_MM,
    MIN_MODULE_MM,
    QUIET_MODULES,
    QR,
    Box,
    Drawing,
    LabelSpec,
    Measure,
    Text,
    build_drawing,
    fill_line,
    fit_text,
    qr_matrix,
    unknown_placeholders,
)

KINDS = ("cable", "attenuator", "amplifier", "adapter", "antenna", "filter", "converter", "generic")
ALIGNS = ("left", "middle", "end")
LAYOUTS = ("single", "flag")
ELEMENT_TYPES = ("text", "qr")
MAX_ELEMENTS = 30
WIDTH_RANGE = (10.0, 300.0)
HEIGHT_RANGE = (8.0, 200.0)
MARGIN_RANGE = (0.0, 10.0)

_DEVICE_LINES = ("{id}", "{name}", "{version}", "{specs}", "{last_measurement}")
DEFAULT_LINES: Dict[str, Tuple[str, ...]] = {
    "cable": ("{id}", "{name}", "{connectors}  {length}", "{last_measurement}"),
    "attenuator": ("{id}", "{name}", "{specs}", "{connectors}", "{last_measurement}"),
    "amplifier": ("{id}", "{name}", "{specs}", "{connectors}", "{last_measurement}"),
    "adapter": ("{id}", "{name}", "{connectors}", "{last_measurement}"),
    "antenna": _DEVICE_LINES,
    "filter": _DEVICE_LINES,
    "converter": _DEVICE_LINES,
    "generic": _DEVICE_LINES,
}


class DesignError(ValueError):
    """A design or a setup is not valid; the message says what."""


@dataclass
class LabelSetup:
    """The label the user prints on: one size for every kind."""

    width_mm: float = 50.0
    height_mm: float = 25.0
    layout: str = "single"
    margin_mm: float = 1.5
    qr: bool = True
    border: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """As written in the file."""
        return {
            "width_mm": self.width_mm, "height_mm": self.height_mm, "layout": self.layout,
            "margin_mm": self.margin_mm, "qr": self.qr, "border": self.border,
        }  # fmt: skip

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "LabelSetup":
        """Read it from the file; ``DesignError`` if a value is not usable."""
        try:
            return LabelSetup(
                float(raw.get("width_mm", 50)), float(raw.get("height_mm", 25)),
                str(raw.get("layout", "single")), float(raw.get("margin_mm", 1.5)),
                bool(raw.get("qr", True)), bool(raw.get("border", False)),
            )  # fmt: skip
        except (AttributeError, TypeError, ValueError) as exc:
            raise DesignError(f"the label size is not valid: {exc}") from exc


@dataclass
class Element:
    """One thing on a manual label, positioned in mm from the top left corner."""

    type: str = "text"  # "text" or "qr"
    text: str = ""  # a text: the line with its places ("Rev {version}")
    x: float = 0.0
    y: float = 0.0
    w: float = 20.0  # a text: the width it may take (it shrinks to fit)
    size: float = 3.0  # a text: height of the letters; a QR code: side of its square
    bold: bool = False
    align: str = "left"  # "left", "middle" or "end"

    def to_dict(self) -> Dict[str, Any]:
        """As written in the file (a QR code has no text, width or alignment)."""
        if self.type == "qr":
            return {"type": "qr", "x": self.x, "y": self.y, "size": self.size}
        return {
            "type": "text", "text": self.text, "x": self.x, "y": self.y, "w": self.w,
            "size": self.size, "bold": self.bold, "align": self.align,
        }  # fmt: skip

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "Element":
        """Read one element; ``DesignError`` if it is not usable."""
        try:
            return Element(
                str(raw.get("type", "text")), str(raw.get("text", "")),
                float(raw.get("x", 0)), float(raw.get("y", 0)), float(raw.get("w", 20)),
                float(raw.get("size", 3)), bool(raw.get("bold", False)),
                str(raw.get("align", "left")),
            )  # fmt: skip
        except (AttributeError, TypeError, ValueError) as exc:
            raise DesignError(f"an element is not valid: {exc}") from exc

    def box(self) -> Tuple[float, float, float, float]:
        """``(x, y, w, h)`` of the element on the label, in mm (to draw a frame, to pick it)."""
        if self.type == "qr":
            return self.x, self.y, self.size, self.size
        return self.x, self.y, self.w, self.size * 1.2


@dataclass
class KindDesign:
    """The label of one kind: lines (automatic) or elements (manual, if ``elements`` is a list)."""

    lines: Tuple[str, ...] = ("{id}", "{name}")
    elements: Optional[List[Element]] = None

    @property
    def manual(self) -> bool:
        """True if the positions are the user's."""
        return self.elements is not None

    def to_dict(self) -> Dict[str, Any]:
        """As written in the file."""
        return {
            "lines": list(self.lines),
            "elements": None if self.elements is None else [e.to_dict() for e in self.elements],
        }

    @staticmethod
    def from_dict(raw: Mapping[str, Any]) -> "KindDesign":
        """Read it from the file; ``DesignError`` if it is not usable."""
        if not isinstance(raw, Mapping):
            raise DesignError("a design is an object")
        listed = raw.get("elements")
        return KindDesign(
            tuple(str(x) for x in raw.get("lines", ("{id}",))),
            None if listed is None else [Element.from_dict(e) for e in listed],
        )


def default_design(kind: str) -> KindDesign:
    """The ready-made design of a kind (automatic); an unknown kind gets the generic one."""
    return KindDesign(DEFAULT_LINES.get(kind, DEFAULT_LINES["generic"]))


# ----- the checks ----------------------------------------------------------------------------
def setup_problems(setup: LabelSetup) -> List[str]:
    """What is wrong with the label size, one sentence each (empty if it is fine)."""
    found = []
    for label, value, (low, high) in (
        ("width", setup.width_mm, WIDTH_RANGE),
        ("height", setup.height_mm, HEIGHT_RANGE),
        ("margin", setup.margin_mm, MARGIN_RANGE),
    ):
        if not low <= value <= high:
            found.append(f"the {label} must be between {low:g} and {high:g} mm")
    if setup.layout not in LAYOUTS:
        found.append(f"the layout must be one of: {', '.join(LAYOUTS)}")
    return found


def design_problems(design: KindDesign, setup: Optional[LabelSetup] = None) -> List[str]:
    """What is wrong with a design, one sentence each (empty if it is fine). With the setup, an
    element outside the label is listed too."""
    found: List[str] = []
    for n, line in enumerate(design.lines, 1):
        if len(line) > 80:
            found.append(f"line {n} is longer than 80 characters")
        bad = unknown_placeholders(line)
        if bad:
            found.append(f"line {n}: unknown {', '.join('{' + b + '}' for b in bad)}")
    if not design.manual:
        if not design.lines:
            found.append("the design needs at least one line")
        elif not any("{id}" in line for line in design.lines):
            found.append("a line must show the code: {id}")
        if len(design.lines) > 12:
            found.append("at most 12 lines")
        return found
    elements = design.elements or []
    if len(elements) > MAX_ELEMENTS:
        found.append(f"at most {MAX_ELEMENTS} elements")
    if sum(1 for e in elements if e.type == "qr") > 1:
        found.append("only one QR code")
    if not any(e.type == "text" and "{id}" in e.text for e in elements):
        found.append("a text must show the code: {id}")
    for n, e in enumerate(elements, 1):
        if e.type not in ELEMENT_TYPES:
            found.append(f"element {n}: the type must be one of: {', '.join(ELEMENT_TYPES)}")
            continue
        if e.size <= 0:
            found.append(f"element {n}: the size must be above 0")
        if e.type == "text":
            if e.w <= 0:
                found.append(f"element {n}: the width must be above 0")
            if e.align not in ALIGNS:
                found.append(f"element {n}: the alignment must be one of: {', '.join(ALIGNS)}")
            if len(e.text) > 80:
                found.append(f"element {n}: the text is longer than 80 characters")
            bad = unknown_placeholders(e.text)
            if bad:
                found.append(f"element {n}: unknown {', '.join('{' + b + '}' for b in bad)}")
    return found


# ----- from automatic to manual --------------------------------------------------------------
def auto_elements(
    setup: LabelSetup,
    lines: Sequence[str],
    asset: Optional[Asset] = None,
    measure: Optional[Measure] = None,
) -> List[Element]:
    """The automatic layout of ``lines`` on a label of this size as elements: the QR code on the
    left, the lines stacked at the right. With ``asset`` (a sample card) the elements are what the
    automatic layout really drew for it, sizes after shrinking included, so the manual label starts
    out the same; a line the card has nothing for, or that did not fit, is put below the others
    at the usual size. Without a card the nominal sizes are used. A starting point to move around.
    """
    m, h, w = setup.margin_mm, setup.height_mm, setup.width_mm
    elements: List[Element] = []
    text_left, text_width = m, w - 2 * m
    side = 0.0
    if setup.qr:
        side = min(h - 2 * m, w * 0.42)
        elements.append(Element("qr", x=m, y=(h - side) / 2, size=round(side, 2)))
        text_left = m + side + m
        text_width = w - m - text_left
    id_size = min(h * 0.3, 7.0)
    other = max(MIN_FONT_MM, min(h * 0.17, 3.2))
    drawn: List[Text] = []
    dropped: List[str] = []
    if asset is not None:
        spec = LabelSpec(
            "design", w, h, "single", qr=setup.qr, margin_mm=m, lines=tuple(lines)
        )  # fmt: skip
        picture = build_drawing(spec, asset, "", measure)
        drawn = [i for i in picture.items if isinstance(i, Text)]
        dropped = list(picture.dropped)
    queue = list(drawn)
    y = m
    for line in lines:
        is_id = line.strip() == "{id}"
        key = "id" if is_id else line
        if asset is not None and fill_line(line, asset, "") and key not in dropped and queue:
            item = queue.pop(0)
            size, top = item.size, item.y - item.size
        else:
            size, top = (id_size if is_id else other), y
        elements.append(
            Element("text", line, round(text_left, 2), round(top, 2), round(max(text_width, 1), 2),
                    round(size, 2), is_id)
        )  # fmt: skip
        y = max(y, top + size * 1.2)
    return elements


# ----- laying out a label --------------------------------------------------------------------
def build_kind_drawing(
    setup: LabelSetup,
    design: KindDesign,
    asset: Asset,
    last_measurement: str = "",
    measure: Optional[Measure] = None,
) -> Drawing:
    """The label of ``asset`` with ``design`` on a label of ``setup``'s size."""
    if design.manual and setup.layout != "flag":
        return _manual(setup, design, asset, last_measurement, measure)
    spec = LabelSpec(
        "design", setup.width_mm, setup.height_mm, setup.layout, qr=setup.qr,
        border=setup.border, margin_mm=setup.margin_mm, lines=tuple(design.lines),
    )  # fmt: skip
    return build_drawing(spec, asset, last_measurement, measure)


def _manual(
    setup: LabelSetup,
    design: KindDesign,
    asset: Asset,
    last: str,
    measure: Optional[Measure],
) -> Drawing:
    d = Drawing(setup.width_mm, setup.height_mm)
    if setup.border:
        d.items.append(Box(0.2, 0.2, setup.width_mm - 0.4, setup.height_mm - 0.4))
    eps = 0.05
    for element in design.elements or []:
        x, y, w, h = element.box()
        outside = x < -eps or y < -eps or x + w > setup.width_mm + eps
        outside = outside or y + h > setup.height_mm + eps
        if element.type == "qr":
            if not setup.qr:
                continue
            matrix = qr_matrix(qr_text(asset.id))
            module = element.size / (len(matrix) + 2 * QUIET_MODULES)
            d.items.append(
                QR(element.x + module * QUIET_MODULES, element.y + module * QUIET_MODULES,
                   module, matrix)
            )  # fmt: skip
            if module < MIN_MODULE_MM:
                d.warnings.append(
                    f"the QR code is too small ({module:.2f} mm per module, at least "
                    f"{MIN_MODULE_MM} mm): make it bigger or leave it out"
                )
            if outside:
                d.warnings.append("the QR code is outside the label")
            continue
        text = fill_line(element.text, asset, last)
        if not text:
            continue
        size, shown = fit_text(
            text, element.w, element.size, min(MIN_FONT_MM, element.size), element.bold, measure
        )
        if shown != text:
            d.dropped.append(element.text)
            d.warnings.append(f"'{element.text}' was cut to fit its width")
        if outside:
            d.warnings.append(f"'{element.text}' is outside the label")
        anchor_x = {"left": element.x, "middle": element.x + element.w / 2}.get(
            element.align, element.x + element.w
        )
        d.items.append(Text(anchor_x, element.y + size, size, shown, element.bold, element.align))
    return d


# ----- sample cards for the preview ----------------------------------------------------------
def sample_asset(kind: str) -> Asset:
    """A card with plausible data of ``kind``, to show in the preview of a design."""
    samples: Dict[str, Dict[str, Any]] = {
        "cable": {"name": "RG316 SMA-SMA",
                  "attributes": {"connectors": "SMA - SMA", "length_m": 1.0}},
        "attenuator": {"name": "10 dB attenuator", "attributes": {
            "nominal_db": 10, "max_power_w": 2, "max_frequency": 6e9, "connectors": "SMA"}},
        "amplifier": {"name": "LNA 20 dB",
                      "attributes": {"nominal_gain_db": 20, "connectors": "SMA"}},
        "adapter": {"name": "SMA to N", "attributes": {"connectors": "SMA - N"}},
        "antenna": {"name": "Whip 868 MHz", "attributes": {
            "frequency_range": "863-870 MHz", "gain_dbi": 2.1}},
        "filter": {"name": "Band pass 868", "attributes": {
            "filter_type": "band pass", "frequency": 868e6}},
        "converter": {"name": "Buck 12 V to 5 V", "attributes": {
            "topology": "buck", "input_voltage": 12, "output_voltage": 5, "max_power_w": 15}},
    }  # fmt: skip
    data = samples.get(kind, {"name": "Device under test", "attributes": {}})
    return Asset(
        f"{kind[:3].upper()}-0042", kind, data["name"], "", serial="SN1234", owner="Lab",
        created="2026-11-24", attributes=dict(data["attributes"]),
    )  # fmt: skip


__all__ = [
    "ALIGNS", "DEFAULT_LINES", "DesignError", "Element", "KINDS", "KindDesign", "LabelSetup",
    "auto_elements", "build_kind_drawing", "default_design", "design_problems", "sample_asset",
    "setup_problems",
]  # fmt: skip
