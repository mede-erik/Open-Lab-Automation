# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Make the labels of cables and devices: choose the format, see them, save a PDF or an image.

A thin layer over ``ola.labels`` (layout, QR code, SVG; tested without a screen) and
``frontend/ui/label_paint.py`` (drawing). You choose:

* the **format**: a single label (50 x 25 mm, 62 x 29 mm for a Brother QL tape, ...), a **flag**
  for a thin cable (the same text either side of a fold) or a **sheet of labels** for a normal
  printer, with how many of its places are already used;
* the **lines**: the code (always), name, description, connectors, length, date, the latest
  measurement, owner, serial number, notes; and whether there is a QR code and a border.

The preview is at scale. Lines that do not fit, or a QR code too small to read, are listed under it
(nothing is dropped silently). *Save PDF* writes every label at its real size (one page per label,
or one page per sheet), *Save image* and *Save SVG* the label on show. The PDF is printed with the
printer's own program, at 100 % (no "fit to page").
Strings: ``frontend/lang/modules/assets/<lang>.json``.
"""

from typing import Any, Callable, List, Optional, Sequence

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.label_paint import paint_drawing, render_image, write_pdf
from frontend.ui.module_translator import CatalogTranslator
from ola.assets import Asset
from ola.labels import (
    FIELDS,
    PRESETS,
    SHEETS,
    Drawing,
    LabelSpec,
    build_drawing,
    render_svg,
    sheet_drawings,
)

SHEET = "sheet"
SINGLE = "single"
OPTIONAL_FIELDS = FIELDS[1:]  # the code ("id") is always there


class LabelPreview(QWidget):
    """A drawing at scale, centred, on a grey background."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.drawing: Optional[Drawing] = None
        self.setMinimumSize(360, 260)

    def set_drawing(self, drawing: Optional[Drawing]) -> None:
        self.drawing = drawing
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().alternateBase())
        d = self.drawing
        if d is None:
            return
        scale = min((self.width() - 24) / d.width, (self.height() - 24) / d.height)
        dx, dy = (self.width() - d.width * scale) / 2, (self.height() - d.height * scale) / 2
        paint_drawing(painter, d, scale, dx, dy)
        painter.setPen(QPen(QColor("#888888"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(dx, dy, d.width * scale, d.height * scale))


class LabelDialog(QDialog):
    """The label window for one or more cards (see the module docstring)."""

    def __init__(
        self,
        assets: Sequence[Asset],
        translator: Any = None,
        last_line: Optional[Callable[[Asset], str]] = None,
        parent: Optional[QWidget] = None,
    ):
        """``last_line(asset)``: the text of the "latest measurement" line for a card (``""``
        if it has none); without it that line is empty."""
        super().__init__(parent)
        self.tr_ = CatalogTranslator("assets", translator)
        self._t = self.tr_.t
        self.assets = list(assets)
        self.last_line = last_line or (lambda _a: "")
        self.pages: List[Drawing] = []
        self.error = ""
        self._loading = False
        self.setWindowTitle(self._t("lbl_title", n=len(self.assets)))
        self.resize(900, 600)
        self._build_ui()
        self._format_changed()

    # ================================================================ building
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        side = QVBoxLayout()
        self.format_box = QComboBox()
        for name in PRESETS:
            self.format_box.addItem(self._format_text(name, PRESETS[name]), f"{SINGLE}:{name}")
        for name in SHEETS:
            self.format_box.addItem(f"{self._t('lbl_sheet')}: {name}", f"{SHEET}:{name}")
        self.format_box.currentIndexChanged.connect(self._format_changed)
        side.addWidget(QLabel(self._t("lbl_format")))
        side.addWidget(self.format_box)
        group = QGroupBox(self._t("lbl_lines"))
        grid = QGridLayout(group)
        grid.addWidget(QCheckBox(self._t("lbl_field_id")), 0, 0)
        grid.itemAtPosition(0, 0).widget().setChecked(True)
        grid.itemAtPosition(0, 0).widget().setEnabled(False)  # the code is always printed
        self.field_boxes = {}
        for n, key in enumerate(OPTIONAL_FIELDS, 1):
            box = QCheckBox(self._t(f"lbl_field_{key}"))
            box.toggled.connect(self._redraw)
            self.field_boxes[key] = box
            grid.addWidget(box, n % 5, n // 5)
        side.addWidget(group)
        self.qr_box = QCheckBox(self._t("lbl_qr"))
        self.border_box = QCheckBox(self._t("lbl_border"))
        self.qr_box.toggled.connect(self._redraw)
        self.border_box.toggled.connect(self._redraw)
        side.addWidget(self.qr_box)
        side.addWidget(self.border_box)
        skip_row = QHBoxLayout()
        self.skip_label = QLabel(self._t("lbl_skip"))
        self.skip_box = QSpinBox()
        self.skip_box.setRange(0, 200)
        self.skip_box.valueChanged.connect(self._redraw)
        skip_row.addWidget(self.skip_label, 1)
        skip_row.addWidget(self.skip_box)
        side.addLayout(skip_row)
        side.addStretch(1)
        self.pdf_btn = QPushButton(self._t("lbl_save_pdf"))
        self.png_btn = QPushButton(self._t("lbl_save_png"))
        self.svg_btn = QPushButton(self._t("lbl_save_svg"))
        self.pdf_btn.clicked.connect(self.save_pdf)
        self.png_btn.clicked.connect(self.save_png)
        self.svg_btn.clicked.connect(self.save_svg)
        for button in (self.pdf_btn, self.png_btn, self.svg_btn):
            side.addWidget(button)
        root.addLayout(side)

        view = QVBoxLayout()
        pick = QHBoxLayout()
        self.page_label = QLabel()
        self.page_box = QComboBox()
        self.page_box.currentIndexChanged.connect(self._show_page)
        pick.addWidget(self.page_label, 1)
        pick.addWidget(self.page_box)
        view.addLayout(pick)
        self.preview = LabelPreview()
        view.addWidget(self.preview, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        view.addWidget(self.message)
        root.addLayout(view, 1)

    @staticmethod
    def _format_text(name: str, spec: LabelSpec) -> str:
        return f"{name}  ({spec.width_mm:g} x {spec.height_mm:g} mm)"

    # ================================================================ the format
    def _kind_and_name(self):
        """``("single", "50x25")`` or ``("sheet", "A4 3x8 (70x37)")`` from the format chosen."""
        kind, _, name = (self.format_box.currentData() or f"{SINGLE}:50x25").partition(":")
        return kind, name

    def _base_spec(self) -> LabelSpec:
        """The format chosen, with the lines, QR and border as ticked."""
        kind, name = self._kind_and_name()
        base = PRESETS[name] if kind == SINGLE else PRESETS["50x25"]
        fields = ["id"] + [k for k in OPTIONAL_FIELDS if self.field_boxes[k].isChecked()]
        spec = base.with_fields(fields, qr=self.qr_box.isChecked())
        from dataclasses import replace

        return replace(spec, border=self.border_box.isChecked())

    def _format_changed(self) -> None:
        """A format was chosen: its lines, QR and border become the ticks (which can be changed)."""
        kind, name = self._kind_and_name()
        spec = PRESETS[name] if kind == SINGLE else PRESETS["50x25"]
        self._loading = True
        for key, box in self.field_boxes.items():
            box.setChecked(key in spec.fields)
        self.qr_box.setChecked(spec.qr)
        self.border_box.setChecked(spec.border)
        self._loading = False
        sheet = kind == SHEET
        self.skip_box.setEnabled(sheet)
        self.skip_label.setEnabled(sheet)
        self._redraw()

    # ================================================================ drawing
    def _redraw(self, *_args: Any) -> None:
        if self._loading:
            return
        kind, name = self._kind_and_name()
        spec = self._base_spec()
        self.error = ""
        try:
            if kind == SINGLE:
                self.pages = [build_drawing(spec, a, self.last_line(a)) for a in self.assets]
            else:
                lines = {a.id: self.last_line(a) for a in self.assets}
                self.pages = sheet_drawings(
                    SHEETS[name], spec, self.assets, self.skip_box.value(), lines
                )
        except RuntimeError as exc:  # the QR code needs segno
            self.pages, self.error = [], str(exc)
        keep = self.page_box.currentIndex()
        self.page_box.blockSignals(True)
        self.page_box.clear()
        for n in range(len(self.pages)):
            label = self.assets[n].id if kind == SINGLE and n < len(self.assets) else str(n + 1)
            self.page_box.addItem(label, n)
        self.page_box.setCurrentIndex(min(max(keep, 0), len(self.pages) - 1) if self.pages else -1)
        self.page_box.blockSignals(False)
        self.page_label.setText(
            self._t("lbl_count", n=len(self.assets), pages=len(self.pages)) if self.pages else ""
        )
        self._show_page()

    def _show_page(self, *_args: Any) -> None:
        n = self.page_box.currentIndex()
        drawing = self.pages[n] if 0 <= n < len(self.pages) else None
        self.preview.set_drawing(drawing)
        lines = []
        if self.error:
            lines.append(self._t("lbl_error", error=self.error))
        for page in self.pages:
            for fields in sorted({d for d in page.dropped}):
                lines.append(self._t("lbl_dropped", fields=fields.replace(":", " - ")))
            lines += sorted({w for w in page.warnings})
        self.message.setText("<br>".join(dict.fromkeys(lines)))
        enabled = bool(self.pages)
        for button in (self.pdf_btn, self.png_btn, self.svg_btn):
            button.setEnabled(enabled)

    def current(self) -> Optional[Drawing]:
        """The drawing on show."""
        n = self.page_box.currentIndex()
        return self.pages[n] if 0 <= n < len(self.pages) else None

    # ================================================================ saving
    def _ask(self, title_key: str, default: str, pattern: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, self._t(title_key), default, pattern)
        return path

    def save_pdf(self) -> None:
        """Every label, at its real size."""
        path = self._ask("lbl_save_pdf", "labels.pdf", "PDF (*.pdf)")
        if path:
            self._do(lambda: write_pdf(path, self.pages), path)

    def save_png(self) -> None:
        """The label on show, at 300 dpi."""
        drawing = self.current()
        path = self._ask("lbl_save_png", "label.png", "PNG (*.png)") if drawing else ""
        if path:
            self._do(lambda: render_image(drawing, 300).save(path) or True, path)

    def save_svg(self) -> None:
        """The label on show as SVG (millimetres)."""
        drawing = self.current()
        path = self._ask("lbl_save_svg", "label.svg", "SVG (*.svg)") if drawing else ""
        if path:
            self._do(lambda: open(path, "w", encoding="utf-8").write(render_svg(drawing)), path)

    def _do(self, action: Callable[[], Any], path: str) -> None:
        try:
            action()
        except Exception as exc:
            QMessageBox.critical(self, self.windowTitle(), self._t("lbl_failed", error=exc))
            return
        self.message.setText(self._t("lbl_saved", path=path))
