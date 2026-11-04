"""Labels for cables and devices (no Qt): what to print, where, at what size.

A label shows the **code** of an object (``CBL-0042``) big and clear, a **QR code** that holds
it (``OLA:CBL-0042``, so a scan, or a barcode scanner that types, gives the code back) and a few
lines of what it is. Everything is drawn in millimetres on a ``Drawing``: texts, a rectangle for the
border and the QR code as its modules. The same drawing is written as **SVG** here
(``render_svg``) and painted to a PDF, an image or the screen by the window.

    spec = PRESETS["50x25"]                       # a label of 50 x 25 mm: QR on the left
    drawing = build_drawing(spec, asset)          # drawing.items, drawing.warnings, drawing.dropped
    svg = render_svg(drawing)
    pages = sheet_drawings(SHEETS["A4 3x8 (70x37)"], spec, [asset, asset2], skip=3)   # a sheet

Layouts: ``single`` (QR left, text right) and ``flag``, a strip for a thin cable that wraps
around it and sticks to itself: the same panel is drawn twice, either side of a fold line. Lines
that do not fit are left out in a fixed order (the last first) and listed in ``drawing.dropped``;
a QR code whose modules would print smaller than ``MIN_MODULE_MM`` is flagged in
``drawing.warnings``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from .assets import Asset, qr_text

MIN_MODULE_MM = 0.3  # a QR module smaller than this is hard to print and to read
QUIET_MODULES = (
    2  # empty border around a QR code, in modules (the standard asks 4; labels are small)
)
MIN_FONT_MM = 1.8  # about 5 pt: below this a label cannot be read
# the lines of a label: the first is always kept, the last goes first when there is no room
FIELDS = ("id", "name", "description", "connectors", "length", "date", "last_measurement",
          "owner", "serial", "notes")  # fmt: skip
DEFAULT_FIELDS = ("id", "name", "description", "length", "date")


@dataclass(frozen=True)
class LabelSpec:
    """The format of a label."""

    name: str
    width_mm: float
    height_mm: float
    layout: str = "single"  # "single" or "flag"
    fields: Tuple[str, ...] = DEFAULT_FIELDS
    qr: bool = True
    border: bool = False
    margin_mm: float = 1.5

    def with_fields(self, fields: Sequence[str], qr: Optional[bool] = None) -> "LabelSpec":
        """The same format with other lines (and QR on or off)."""
        return replace(self, fields=tuple(fields), qr=self.qr if qr is None else qr)


@dataclass(frozen=True)
class SheetSpec:
    """A sheet of labels on a normal printer: the page, the grid and where it starts."""

    name: str
    page_w_mm: float
    page_h_mm: float
    cols: int
    rows: int
    label_w_mm: float
    label_h_mm: float
    left_mm: float
    top_mm: float
    gap_x_mm: float = 0.0
    gap_y_mm: float = 0.0

    @property
    def per_page(self) -> int:
        """Labels on one sheet."""
        return self.cols * self.rows

    def position(self, index: int) -> Tuple[float, float]:
        """Where the top left corner of label ``index`` (0 .. per_page - 1) is, in mm."""
        row, col = divmod(index, self.cols)
        return (
            self.left_mm + col * (self.label_w_mm + self.gap_x_mm),
            self.top_mm + row * (self.label_h_mm + self.gap_y_mm),
        )

    def label_spec(self, base: LabelSpec) -> LabelSpec:
        """The label format of this sheet (its size), with the lines of ``base``."""
        return replace(base, name=self.name, width_mm=self.label_w_mm, height_mm=self.label_h_mm)


PRESETS: Dict[str, LabelSpec] = {
    "50x25": LabelSpec("50x25", 50, 25),
    "40x20": LabelSpec("40x20", 40, 20, fields=("id", "name", "length")),
    "62x29": LabelSpec("62x29", 62, 29),  # the Brother QL 62 mm tape
    "70x37": LabelSpec("70x37", 70, 37, fields=FIELDS[:6] + ("owner",)),
    "flag 60x15": LabelSpec("flag 60x15", 60, 15, layout="flag", fields=("id", "name"), qr=False),
}


def _sheet(name, cols, rows, w, h, left, top, gap_x=0.0, gap_y=0.0):
    return SheetSpec(name, 210, 297, cols, rows, w, h, left, top, gap_x, gap_y)


SHEETS: Dict[str, SheetSpec] = {
    s.name: s
    for s in (
        _sheet("A4 3x8 (70x37)", 3, 8, 70, 37, 0, 0),
        _sheet("A4 3x7 (63.5x38.1)", 3, 7, 63.5, 38.1, 7.2, 15.1, 2.5),
        _sheet("A4 5x13 (38.1x21.2)", 5, 13, 38.1, 21.2, 4.7, 10.7, 2.5),
        _sheet("A4 2x7 (99.1x38.1)", 2, 7, 99.1, 38.1, 4.6, 15.1, 2.5),
    )
}


# ----- what is drawn -------------------------------------------------------------------------
@dataclass
class Text:
    """A text with its baseline at ``(x, y)`` mm; ``anchor`` is ``start`` or ``middle``."""

    x: float
    y: float
    size: float
    text: str
    bold: bool = False
    anchor: str = "start"


@dataclass
class Line:
    """A straight line (the fold of a flag label is dashed)."""

    x1: float
    y1: float
    x2: float
    y2: float
    dashed: bool = False


@dataclass
class Box:
    """A rectangle outline (the border of a label)."""

    x: float
    y: float
    w: float
    h: float


@dataclass
class QR:
    """A QR code: ``matrix[row][col]`` is True for a dark module; ``module`` is its size in mm and
    ``(x, y)`` the corner of the code itself (the quiet zone is around it)."""

    x: float
    y: float
    module: float
    matrix: List[List[bool]]

    @property
    def size(self) -> float:
        """Side of the code in mm."""
        return self.module * len(self.matrix)


Item = Any  # Text | Line | Box | QR


@dataclass
class Drawing:
    """One label, or one page of labels, in millimetres from the top left."""

    width: float
    height: float
    items: List[Item] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    dropped: List[str] = field(default_factory=list)  # the lines that did not fit, by field name

    def translated(self, dx: float, dy: float) -> List[Item]:
        """The items moved by ``(dx, dy)`` (to place a label on a sheet)."""
        moved: List[Item] = []
        for it in self.items:
            if isinstance(it, Text):
                moved.append(replace(it, x=it.x + dx, y=it.y + dy))
            elif isinstance(it, Line):
                moved.append(
                    replace(it, x1=it.x1 + dx, x2=it.x2 + dx, y1=it.y1 + dy, y2=it.y2 + dy)
                )
            elif isinstance(it, Box):
                moved.append(replace(it, x=it.x + dx, y=it.y + dy))
            else:
                moved.append(replace(it, x=it.x + dx, y=it.y + dy))
        return moved


# ----- the lines of text ---------------------------------------------------------------------
def qr_matrix(text: str, error: str = "q") -> List[List[bool]]:
    """The modules of a QR code (a normal QR, not a Micro QR: phones do not read those well).
    ``RuntimeError`` with the fix if ``segno`` is not installed."""
    try:
        import segno
    except ImportError as exc:
        raise RuntimeError("the QR code needs the 'segno' package: pip install segno") from exc
    code = segno.make(text, error=error, micro=False)
    return [[bool(v) for v in row] for row in code.matrix]


def field_text(key: str, asset: Asset, last_measurement: str = "") -> str:
    """The text of one line of a label ('' if the card has nothing for it)."""
    if key == "id":
        return asset.id
    if key == "name":
        return asset.name
    if key == "description":
        return asset.description
    if key == "connectors":
        value = asset.attributes.get("connectors") or asset.attributes.get("connector")
        return str(value) if value else ""
    if key == "length":
        length = asset.attributes.get("length_m")
        return f"{float(length):g} m" if isinstance(length, (int, float)) and length else ""
    if key == "date":
        return asset.created
    if key == "last_measurement":
        return last_measurement
    if key == "owner":
        return asset.owner
    if key == "serial":
        return f"S/N {asset.serial}" if asset.serial else ""
    if key == "notes":
        return asset.notes.replace("\n", " ").strip()
    return ""


def char_width(ch: str) -> float:
    """The width of one character as a fraction of the font size, for a typical sans-serif font:
    capitals and digits are wide, lower case narrower, spaces and punctuation narrow. Rounded up,
    so that text is never wider than estimated."""
    if ch == " ":
        return 0.32
    if ch in "il.,:;'|!":
        return 0.30
    if ch in "-()[]/\\":
        return 0.40
    if ch in "mwMW@%":
        return 1.10
    if ch.isupper() or ch.isdigit():
        return 0.70
    return 0.58  # lower case


def text_width(text: str, size: float, bold: bool = False) -> float:
    """The width a text takes at font size ``size`` mm (an estimate that errs on the long side)."""
    return sum(char_width(c) for c in text) * size * (1.08 if bold else 1.0)


def fit_text(text: str, width: float, start: float, floor: float = MIN_FONT_MM, bold: bool = False):
    """``(size, text)``: the largest font size from ``start`` down to ``floor`` at which the text
    fits ``width`` mm; if even ``floor`` is too big the text is cut with an ellipsis."""
    size = start
    while size > floor and text_width(text, size, bold) > width:
        size = max(floor, size - 0.1)
    if text_width(text, size, bold) <= width:
        return size, text
    cut = text
    while len(cut) > 1 and text_width(cut + "…", size, bold) > width:
        cut = cut[:-1]
    return size, cut.rstrip() + "…"


# ----- one label -----------------------------------------------------------------------------
def build_drawing(spec: LabelSpec, asset: Asset, last_measurement: str = "") -> Drawing:
    """Lay out the label of ``asset``. ``last_measurement`` is the text of that line (the window
    makes it from the latest run); an empty line is not drawn."""
    drawing = Drawing(spec.width_mm, spec.height_mm)
    if spec.border:
        drawing.items.append(Box(0.2, 0.2, spec.width_mm - 0.4, spec.height_mm - 0.4))
    if spec.layout == "flag":
        _flag(drawing, spec, asset, last_measurement)
    else:
        _panel(drawing, spec, asset, last_measurement, 0.0, spec.width_mm, spec.qr)
    return drawing


def _lines(spec: LabelSpec, asset: Asset, last: str) -> List[Tuple[str, str]]:
    keys = [k for k in FIELDS if k in spec.fields]
    return [(k, field_text(k, asset, last)) for k in keys if field_text(k, asset, last)]


def _panel(d: Drawing, spec: LabelSpec, asset: Asset, last: str, x0: float, width: float, qr: bool):
    """The content of one label (or one side of a flag) in the box from ``x0`` of ``width`` mm."""
    m, h = spec.margin_mm, spec.height_mm
    left = x0 + m
    text_left, text_width_ = left, width - 2 * m
    if qr:
        text_left, text_width_ = _place_qr(d, asset, x0, width, h, m)
    lines = _lines(spec, asset, last)
    if not lines:
        return
    id_size = min(h * 0.3, 7.0)
    size_other = max(MIN_FONT_MM, min(h * 0.17, 3.2))
    available = h - 2 * m
    placed: List[Tuple[str, str, float, bool]] = []  # key, text, size, bold
    for key, text in lines:
        if key == "id":
            size, shown = fit_text(text, text_width_, id_size, 2.5, bold=True)
            placed.append((key, shown, size, True))
        else:
            size, shown = fit_text(text, text_width_, size_other)
            placed.append((key, shown, size, False))
    # drop the least important lines until the rest fits the height (the code is always kept)
    while sum(p[2] * 1.2 for p in placed) > available and len(placed) > 1:
        gone = placed.pop()  # the last one in FIELDS order
        d.dropped.append(gone[0])
    y = m
    for key, text, size, bold in placed:
        y += size
        d.items.append(Text(text_left, y, size, text, bold))
        y += size * 0.2


def _place_qr(d: Drawing, asset: Asset, x0: float, width: float, h: float, m: float):
    """Put the QR code at the left of the box; returns the left and the width left for the text."""
    matrix = qr_matrix(qr_text(asset.id))
    count = len(matrix)
    side = min(h - 2 * m, width * 0.42)
    module = side / (count + 2 * QUIET_MODULES)
    inner = module * count
    qx, qy = x0 + m + module * QUIET_MODULES, (h - inner) / 2
    d.items.append(QR(qx, qy, module, matrix))
    if module < MIN_MODULE_MM:
        d.warnings.append(
            f"the QR code is too small ({module:.2f} mm per module, at least {MIN_MODULE_MM} mm): "
            "use a bigger label or leave the QR code out"
        )
    text_left = x0 + m + side + m
    return text_left, x0 + width - m - text_left


def _flag(d: Drawing, spec: LabelSpec, asset: Asset, last: str) -> None:
    """A strip that wraps round a cable: the same panel either side of a dashed fold line."""
    panel = (spec.width_mm - 1.0) / 2
    qr = spec.qr and spec.height_mm >= 8
    if spec.qr and not qr:
        d.warnings.append("a flag this narrow cannot have a QR code: only the code is written")
    _panel(d, spec, asset, last, 0.0, panel, qr)
    _panel(d, spec, asset, last, panel + 1.0, panel, qr)
    d.items.append(Line(spec.width_mm / 2, 0, spec.width_mm / 2, spec.height_mm, dashed=True))


# ----- sheets --------------------------------------------------------------------------------
def sheet_drawings(
    sheet: SheetSpec,
    base: LabelSpec,
    assets: Sequence[Asset],
    skip: int = 0,
    last_measurements: Optional[Dict[str, str]] = None,
) -> List[Drawing]:
    """The pages of a sheet of labels, one label per asset, **skipping the first ``skip`` positions
    of the first sheet** (the labels already used). Each page is one ``Drawing`` of the page size;
    the warnings and dropped lines of the labels are collected on the page."""
    spec = sheet.label_spec(base)
    last_measurements = last_measurements or {}
    pages: List[Drawing] = []
    index = skip % sheet.per_page if skip else 0
    page: Optional[Drawing] = None
    for asset in assets:
        if page is None or index >= sheet.per_page:
            page = Drawing(sheet.page_w_mm, sheet.page_h_mm)
            pages.append(page)
            index = skip if len(pages) == 1 else 0
            if index >= sheet.per_page:  # the first sheet is used up: start on a fresh one
                index = 0
        label = build_drawing(spec, asset, last_measurements.get(asset.id, ""))
        dx, dy = sheet.position(index)
        page.items.extend(label.translated(dx, dy))
        page.warnings += [
            f"{asset.id}: {w}" for w in label.warnings if f"{asset.id}: {w}" not in page.warnings
        ]
        page.dropped += [f"{asset.id}:{k}" for k in label.dropped]
        index += 1
    return pages


# ----- SVG -----------------------------------------------------------------------------------
def _qr_path(qr: QR) -> str:
    """The dark modules as one path: a horizontal run per row (``M x y h w v m h -w z``)."""
    parts: List[str] = []
    m = qr.module
    for r, row in enumerate(qr.matrix):
        c = 0
        while c < len(row):
            if row[c]:
                start = c
                while c < len(row) and row[c]:
                    c += 1
                x, y, run = qr.x + start * m, qr.y + r * m, (c - start) * m
                parts.append(f"M{x:.4f} {y:.4f}h{run:.4f}v{m:.4f}h-{run:.4f}z")
            else:
                c += 1
    return "".join(parts)


def render_svg(drawing: Drawing) -> str:
    """The drawing as an SVG document in millimetres (it prints at its real size)."""
    w, h = drawing.width, drawing.height
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w:g}mm" height="{h:g}mm" viewBox="0 0 {w:g} {h:g}">',
        f'<rect width="{w:g}" height="{h:g}" fill="white"/>',
    ]
    for it in drawing.items:
        if isinstance(it, Text):
            weight = ' font-weight="bold"' if it.bold else ""
            anchor = f' text-anchor="{it.anchor}"' if it.anchor != "start" else ""
            out.append(
                f'<text x="{it.x:.3f}" y="{it.y:.3f}" font-size="{it.size:.3f}" '
                'font-family="Helvetica, Arial, sans-serif"'
                f"{weight}{anchor}>{escape(it.text)}</text>"
            )
        elif isinstance(it, Box):
            out.append(
                f'<rect x="{it.x:g}" y="{it.y:g}" width="{it.w:g}" height="{it.h:g}" '
                'fill="none" stroke="black" stroke-width="0.2"/>'
            )
        elif isinstance(it, Line):
            dash = ' stroke-dasharray="1 1"' if it.dashed else ""
            out.append(
                f'<line x1="{it.x1:g}" y1="{it.y1:g}" x2="{it.x2:g}" y2="{it.y2:g}" '
                f'stroke="black" stroke-width="0.15"{dash}/>'
            )
        elif isinstance(it, QR):
            out.append(f'<path d="{_qr_path(it)}" fill="black" shape-rendering="crispEdges"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
