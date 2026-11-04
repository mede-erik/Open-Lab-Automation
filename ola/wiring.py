"""Connection diagram of a measurement: which instrument goes where. No Qt, no I/O but the file.

Every measurement module can ship a ``wiring.json`` next to its ``module.json`` (so the diagram is
updated with the module)::

    {"nodes": [
        {"id": "vna", "role": "vna", "at": [0, 0], "title": {"en": "VNA", "it": "VNA"},
         "ports": [{"id": "p1", "side": "right", "label": {"en": "Port 1"}}]},
        {"id": "dut", "kind": "device", "at": [1, 0], "title": "{device.label|Device}",
         "ports": [{"id": "in", "side": "left", "label": {"en": "Input"}}]}],
     "links": [{"from": "vna.p1", "to": "dut.in", "label": {"en": "coax"}, "style": "dashed"}],
     "notes": [{"en": "Calibrate the VNA at the end of the test lead."}]}

* ``at`` is ``[column, row]``: the boxes are laid out on that grid.
* A text is a string or a dictionary of languages (the English one is the fallback). ``{path}`` or
  ``{path|default}`` is replaced by a value of the measurement's parameters (``scope.channel``).
* A node, port, link or note can have ``"when": "path"``: it is only drawn if that parameter is set
  (true, a non-empty text, a non-zero number or a non-empty list); ``"!path"`` means the opposite;
  ``"path=value"`` and ``"path!=value"`` compare the parameter with a text (a missing parameter
  is not equal to anything, so ``mode!=reflection`` is true when ``mode`` is not given). A list
  of conditions needs all of them.
* A node with a ``role`` shows the names of the instruments bound to that role under its title.
* A ``link`` goes from a port to a port (``node.port``); ``style`` can be ``dashed`` for a link that
  is not a signal (a control line).

``diagram_for`` builds the diagram for a measurement, ``layout`` draws it as a
``ola.labels.Drawing`` (millimetres, so it can be painted, written as SVG, or printed) and
``connection_lines`` lists the same connections as sentences.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .labels import Box, Drawing, Line, Text, text_width

FALLBACK_LANG = "en"
FILE_NAME = "wiring.json"
TITLE_MM = 3.4
PORT_MM = 2.7
LINK_MM = 2.4
SUB_MM = 2.4
PAD_MM = 2.5
PORT_STEP_MM = 5.0
HEAD_MM = 9.0
GAP_X_MM = 34.0
GAP_Y_MM = 10.0
MARGIN_MM = 5.0
_FIELD = re.compile(r"\{([A-Za-z_][\w.]*)(?:\|([^}]*))?\}")


class WiringError(ValueError):
    """The wiring file of a module is not valid; the message says where."""


@dataclass
class Port:
    """A connector of a node, on its left or right side."""

    id: str
    label: str
    side: str = "right"


@dataclass
class Node:
    """An instrument or the device under test."""

    id: str
    title: str
    column: int
    row: int
    kind: str = "instrument"  # or "device"
    subtitle: str = ""  # the names of the instruments bound to the role
    ports: List[Port] = field(default_factory=list)


@dataclass
class Link:
    """A cable from ``source`` (``node.port``) to ``target``."""

    source: str
    target: str
    label: str = ""
    dashed: bool = False


@dataclass
class Diagram:
    """The nodes, links and notes of one measurement."""

    nodes: List[Node] = field(default_factory=list)
    links: List[Link] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def node(self, node_id: str) -> Node:
        """The node with this id (``KeyError`` if there is none)."""
        return next(n for n in self.nodes if n.id == node_id)

    def port(self, ref: str) -> Tuple[Node, Port]:
        """The node and the port of a ``node.port`` reference (``KeyError`` if not drawn)."""
        node_id, _, port_id = ref.partition(".")
        node = self.node(node_id)
        return node, next(p for p in node.ports if p.id == port_id)


# ----- reading the file -----------------------------------------------------------------------
def load_wiring(module_path: Any) -> Optional[Dict[str, Any]]:
    """The ``wiring.json`` of a module folder, or None if it has none. ``WiringError`` if it
    cannot be read or is not an object with a list of ``nodes``."""
    path = Path(module_path) / FILE_NAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WiringError(f"{path}: cannot read: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("nodes"), list) or not raw["nodes"]:
        raise WiringError(f"{path}: needs an object with a non-empty list of 'nodes'")
    return raw


def lookup(params: Mapping[str, Any], path: str) -> Any:
    """The value at a dotted path of the parameters (``scope.channel``), or None."""
    value: Any = params
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def text_of(value: Any, lang: str, params: Mapping[str, Any]) -> str:
    """A text of the file in ``lang`` (English if missing) with its ``{fields}`` filled in."""
    if isinstance(value, Mapping):
        value = value.get(lang) or value.get(FALLBACK_LANG) or next(iter(value.values()), "")
    text = str(value if value is not None else "")

    def fill(match: "re.Match[str]") -> str:
        found = lookup(params, match.group(1))
        if found in (None, "", []):
            return match.group(2) if match.group(2) is not None else "?"
        return f"{found:g}" if isinstance(found, float) else str(found)

    return _FIELD.sub(fill, text)


def is_on(condition: Any, params: Mapping[str, Any]) -> bool:
    """Whether a ``when`` condition holds (no condition: always)."""
    if not condition:
        return True
    if isinstance(condition, (list, tuple)):  # a list: every condition must hold
        return all(is_on(c, params) for c in condition)
    text = str(condition)
    for operator in ("!=", "="):
        if operator in text:
            path, _, wanted = text.partition(operator)
            same = str(lookup(params, path)) == wanted
            return same if operator == "=" else not same
    negate = text.startswith("!")
    value = lookup(params, text.lstrip("!"))
    return (not value) if negate else bool(value)


def diagram_for(
    wiring: Mapping[str, Any],
    params: Optional[Mapping[str, Any]] = None,
    names: Optional[Mapping[str, Sequence[str]]] = None,
    lang: str = FALLBACK_LANG,
) -> Diagram:
    """The diagram of a measurement: the file's nodes and links that apply to ``params``, with
    their texts in ``lang`` and, under each node that has a ``role``, the instrument names of
    ``names`` (role -> names). ``WiringError`` for a link to a port that is not drawn."""
    params = params or {}
    names = names or {}
    diagram = Diagram()
    for raw in wiring["nodes"]:
        if not is_on(raw.get("when"), params):
            continue
        at = raw.get("at") or [0, 0]
        node = Node(
            id=str(raw["id"]),
            title=text_of(raw.get("title", raw["id"]), lang, params),
            column=int(at[0]),
            row=int(at[1]),
            kind=raw.get("kind", "instrument"),
            subtitle=", ".join(names.get(raw.get("role", ""), ())),
        )
        for port in raw.get("ports", []):
            if is_on(port.get("when"), params):
                label = text_of(port.get("label", port["id"]), lang, params)
                node.ports.append(Port(str(port["id"]), label, port.get("side", "right")))
        diagram.nodes.append(node)
    for raw in wiring.get("links", []):
        if not is_on(raw.get("when"), params):
            continue
        link = Link(
            raw["from"], raw["to"], text_of(raw.get("label", ""), lang, params),
            raw.get("style") == "dashed",
        )  # fmt: skip
        try:
            diagram.port(link.source), diagram.port(link.target)
        except (KeyError, StopIteration):
            raise WiringError(
                f"link {link.source} -> {link.target}: no such node or port"
            ) from None
        diagram.links.append(link)
    for note in wiring.get("notes", []):
        if isinstance(note, Mapping) and not is_on(note.get("when"), params):
            continue
        if isinstance(note, Mapping) and "text" in note:
            note = note["text"]
        diagram.notes.append(text_of(note, lang, params))
    return diagram


def connection_lines(diagram: Diagram) -> List[str]:
    """The links as sentences: ``VNA Port 1 -> Filter Input (coax)``."""
    out = []
    for link in diagram.links:
        a, pa = diagram.port(link.source)
        b, pb = diagram.port(link.target)
        extra = f" ({link.label})" if link.label else ""
        out.append(f"{a.title} {pa.label} -> {b.title} {pb.label}{extra}")
    return out


# ----- drawing --------------------------------------------------------------------------------
def _box_size(node: Node) -> Tuple[float, float]:
    left_labels = [text_width(p.label, PORT_MM) for p in node.ports if p.side == "left"]
    right_labels = [text_width(p.label, PORT_MM) for p in node.ports if p.side != "left"]
    both = max(left_labels, default=0.0) + max(right_labels, default=0.0) + 2 * PAD_MM
    widest = max(text_width(node.title, TITLE_MM, True), text_width(node.subtitle, SUB_MM), both)
    height = HEAD_MM + PORT_STEP_MM * max(len(left_labels), len(right_labels), 1)
    return widest + 2 * PAD_MM, height + (SUB_MM if node.subtitle else 0)


def layout(diagram: Diagram) -> Drawing:
    """The diagram as a ``Drawing`` in millimetres: a box per node with its ports, the links as
    right-angled lines with their labels, a double border for the device under test."""
    sizes = {n.id: _box_size(n) for n in diagram.nodes}
    columns = sorted({n.column for n in diagram.nodes})
    rows = sorted({n.row for n in diagram.nodes})
    col_w = {c: max(sizes[n.id][0] for n in diagram.nodes if n.column == c) for c in columns}
    row_h = {r: max(sizes[n.id][1] for n in diagram.nodes if n.row == r) for r in rows}
    x_at: Dict[int, float] = {}
    x = MARGIN_MM
    for c in columns:
        x_at[c] = x
        x += col_w[c] + GAP_X_MM
    y_at: Dict[int, float] = {}
    y = MARGIN_MM
    for r in rows:
        y_at[r] = y
        y += row_h[r] + GAP_Y_MM
    drawing = Drawing(x - GAP_X_MM + MARGIN_MM, y - GAP_Y_MM + MARGIN_MM)
    anchor: Dict[str, Tuple[float, float, str]] = {}
    for node in diagram.nodes:
        w = col_w[node.column]
        h = sizes[node.id][1]
        left, top = x_at[node.column], y_at[node.row]
        drawing.items.append(Box(left, top, w, h))
        if node.kind == "device":
            drawing.items.append(Box(left + 0.8, top + 0.8, w - 1.6, h - 1.6))
        drawing.items.append(Text(left + w / 2, top + 5.0, TITLE_MM, node.title, True, "middle"))
        if node.subtitle:
            drawing.items.append(
                Text(left + w / 2, top + 8.2, SUB_MM, node.subtitle, False, "middle")
            )
        counts = {"left": 0, "right": 0}
        base = top + HEAD_MM + (SUB_MM if node.subtitle else 0)
        for port in node.ports:
            side = "left" if port.side == "left" else "right"
            py = base + PORT_STEP_MM * (counts[side] + 0.5)
            counts[side] += 1
            px = left if side == "left" else left + w
            pad = PAD_MM * 0.6
            tx, align = (left + pad, "start") if side == "left" else (left + w - pad, "end")
            drawing.items.append(Text(tx, py + 1.0, PORT_MM, port.label, False, align))
            drawing.items.append(Line(px - 0.9, py, px + 0.9, py))
            anchor[f"{node.id}.{port.id}"] = (px, py, side)
    for link in diagram.links:
        _route(drawing, anchor[link.source], anchor[link.target], link)
    return drawing


def _route(drawing: Drawing, a: Tuple[float, float, str], b: Tuple[float, float, str], link: Link):
    """Draw a link as a path of straight pieces from port ``a`` to port ``b``."""
    (x1, y1, side1), (x2, y2, side2) = a, b
    out1 = x1 + (3.0 if side1 == "right" else -3.0)
    out2 = x2 + (3.0 if side2 == "right" else -3.0)
    if side1 == "right" and side2 == "left" and out1 < out2:
        mid = (out1 + out2) / 2
        points = [(x1, y1), (mid, y1), (mid, y2), (x2, y2)]
    else:  # facing the same way: go round
        far = max(out1, out2) if side1 == "right" else min(out1, out2)
        points = [(x1, y1), (far, y1), (far, y2), (x2, y2)]
    horizontal = []
    for (xa, ya), (xb, yb) in zip(points, points[1:]):
        if (xa, ya) != (xb, yb):
            drawing.items.append(Line(xa, ya, xb, yb, link.dashed))
        if ya == yb and xa != xb:
            horizontal.append((abs(xb - xa), (xa + xb) / 2, ya))
    if link.label and horizontal:  # the label goes over the longest straight piece
        if y1 == y2:  # one straight line from port to port
            horizontal = [(0, (x1 + x2) / 2, y1)]
        _, cx, cy = max(horizontal)
        drawing.items.append(Text(cx, cy - 1.2, LINK_MM, link.label, False, "middle"))


__all__ = [
    "Diagram", "Link", "Node", "Port", "WiringError", "connection_lines", "diagram_for",
    "is_on", "layout", "load_wiring", "lookup", "text_of",
]  # fmt: skip
