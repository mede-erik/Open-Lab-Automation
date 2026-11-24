# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The tool that designs the labels: the size, and for each kind of object where things go.

A thin window over ``ola.label_design`` (the model, the layout, the checks) and
``ola.label_templates`` (the file). At the top the **size of the label** you print on, the same for
every kind (width, height, single label or flag, margin, QR code, border). Below, choose a **kind**
(cable, attenuator, amplifier, adapter, antenna, filter, converter, generic):

* **Automatic**: the lines of text, one per row, with the data of the card between braces
  (``{id}``, ``{name}``, ``Rev {version}``, ``{nominal_db}``...); the program stacks them and
  shrinks the text to fit.
* **Manual**: a list of elements, each a text or the QR code, with its **position** (x, y of the
  top left corner, in mm), the **width** it may take, the **letter height** (a QR code: the side),
  bold and alignment. Pick an element in the list or **click it in the preview** and drag it; the
  numbers follow. *Start from the automatic layout* turns the lines into elements as the program
  drew them. A flag is always automatic.

The preview shows a sample card of the kind; what is cut, too small or outside the label is
written under it. Nothing is kept until *Save*, which saves the size and every kind that was
changed; *Back to the ready-made design* forgets what you did for a kind.
Strings: ``frontend/lang/modules/assets/<lang>.json``.
"""

from dataclasses import replace
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.LabelDialog import LabelPreview
from frontend.ui.label_paint import text_measure
from frontend.ui.module_translator import CatalogTranslator
from ola.label_design import (
    ALIGNS,
    KINDS,
    Element,
    KindDesign,
    LabelSetup,
    auto_elements,
    build_kind_drawing,
    default_design,
    design_problems,
    sample_asset,
    setup_problems,
)
from ola.label_templates import LabelTemplateError, TemplateStore
from ola.labels import FIELDS, placeholder_names


class DesignPreview(LabelPreview):
    """The label with a frame round the picked element; a click picks, a drag moves it."""

    picked = pyqtSignal(int)
    moved = pyqtSignal(int, float, float)  # index, new x and y in mm

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.elements: List[Element] = []
        self.current = -1
        self.editable = False
        self._grab: Optional[tuple] = None  # (index, x offset, y offset) in mm

    def set_elements(self, elements: List[Element], current: int, editable: bool) -> None:
        """The elements to frame (``editable``: manual mode, where they can be picked)."""
        self.elements, self.current, self.editable = list(elements), current, editable
        self.update()

    def _mm(self, point: QPointF) -> tuple:
        scale, dx, dy = self.scale_dx_dy
        return (point.x() - dx) / scale, (point.y() - dy) / scale

    def element_at(self, x: float, y: float) -> int:
        """The topmost element whose box holds the point (mm); -1 if none."""
        for index in range(len(self.elements) - 1, -1, -1):
            ex, ey, ew, eh = self.elements[index].box()
            if ex <= x <= ex + ew and ey <= y <= ey + eh:
                return index
        return -1

    def paint_over(self, painter: QPainter, scale: float, dx: float, dy: float) -> None:
        if not self.editable:
            return
        for index, element in enumerate(self.elements):
            x, y, w, h = element.box()
            chosen = index == self.current
            pen = QPen(QColor("#1976d2" if chosen else "#bbbbbb"), 2 if chosen else 1)
            pen.setStyle(Qt.PenStyle.SolidLine if chosen else Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(dx + x * scale, dy + y * scale, w * scale, h * scale))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt name)
        if not self.editable or event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self._mm(event.position())
        index = self.element_at(x, y)
        if index >= 0:
            self._grab = (index, x - self.elements[index].x, y - self.elements[index].y)
            self.picked.emit(index)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt name)
        if self._grab is None:
            return
        index, ox, oy = self._grab
        x, y = self._mm(event.position())
        self.moved.emit(index, round(x - ox, 1), round(y - oy, 1))

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802 (Qt name)
        self._grab = None


def _spin(low: float, high: float, step: float = 0.5, suffix: str = " mm") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(1)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    return box


class LabelDesignDialog(QDialog):
    """The label design tool (see the module docstring)."""

    def __init__(
        self, store: TemplateStore, translator: Any = None, parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.tr_ = CatalogTranslator("assets", translator)
        self._t = self.tr_.t
        self.store = store
        self.drafts: Dict[str, KindDesign] = {}  # what is being edited, by kind
        self.kind = KINDS[0]
        self._loading = False
        self.setWindowTitle(self._t("ldg_title"))
        self.resize(1100, 680)
        self._build()
        self._load_setup()
        self._load_kind()

    # ================================================================ building
    def _build(self) -> None:
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        size_group = QGroupBox(self._t("ldg_size"))
        form = QFormLayout(size_group)
        self.width_box, self.height_box = _spin(10, 300), _spin(8, 200)
        self.margin_box = _spin(0, 10, 0.5)
        self.layout_box = QComboBox()
        self.layout_box.addItem(self._t("lbl_tpl_layout_single"), "single")
        self.layout_box.addItem(self._t("lbl_tpl_layout_flag"), "flag")
        self.qr_box = QCheckBox(self._t("lbl_qr"))
        self.border_box = QCheckBox(self._t("lbl_border"))
        form.addRow(self._t("lbl_tpl_width"), self.width_box)
        form.addRow(self._t("lbl_tpl_height"), self.height_box)
        form.addRow(self._t("lbl_tpl_layout"), self.layout_box)
        form.addRow(self._t("lbl_tpl_margin"), self.margin_box)
        form.addRow(self.qr_box)
        form.addRow(self.border_box)
        left.addWidget(size_group)
        for widget in (self.width_box, self.height_box, self.margin_box):
            widget.valueChanged.connect(self._setup_changed)
        self.layout_box.currentIndexChanged.connect(self._setup_changed)
        self.qr_box.toggled.connect(self._setup_changed)
        self.border_box.toggled.connect(self._setup_changed)

        self.kind_box = QComboBox()
        for kind in KINDS:
            self.kind_box.addItem(self._t(f"ldg_kind_{kind}"), kind)
        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        self.state_label = QLabel()
        left.addWidget(QLabel(self._t("ldg_kind")))
        left.addWidget(self.kind_box)
        left.addWidget(self.state_label)
        mode_row = QHBoxLayout()
        self.auto_radio = QRadioButton(self._t("ldg_mode_auto"))
        self.manual_radio = QRadioButton(self._t("ldg_mode_manual"))
        self.auto_radio.setChecked(True)
        self.auto_radio.toggled.connect(self._mode_changed)
        mode_row.addWidget(self.auto_radio)
        mode_row.addWidget(self.manual_radio)
        left.addLayout(mode_row)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_auto())
        self.stack.addWidget(self._build_manual())
        left.addWidget(self.stack, 1)
        buttons = QHBoxLayout()
        self.save_btn = QPushButton(self._t("ldg_save"))
        self.save_btn.clicked.connect(self.save)
        self.reset_btn = QPushButton(self._t("ldg_reset"))
        self.reset_btn.clicked.connect(self.reset_kind)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.reset_btn)
        left.addLayout(buttons)
        root.addLayout(left, 1)

        view = QVBoxLayout()
        self.preview = DesignPreview()
        self.preview.picked.connect(self._pick)
        self.preview.moved.connect(self._moved)
        view.addWidget(self.preview, 1)
        self.hint = QLabel(self._t("ldg_hint"))
        self.hint.setWordWrap(True)
        view.addWidget(self.hint)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        view.addWidget(self.message)
        root.addLayout(view, 1)

    def _insert_box(self, target) -> QComboBox:
        """A menu that inserts the place of a field in a text box."""
        box = QComboBox()
        box.addItem(self._t("lbl_tpl_insert"), "")
        for key in placeholder_names():
            text = (
                self._t(f"lbl_field_{key}")
                if key in FIELDS or key in ("kind", "manufacturer")
                else ""
            )
            box.addItem(
                f"{{{key}}}" + (f"  {text}" if text and text != f"lbl_field_{key}" else ""), key
            )

        def insert(index: int) -> None:
            key = box.itemData(index)
            if key:
                if isinstance(target, QLineEdit):
                    target.insert("{" + key + "}")
                else:
                    target.insertPlainText("{" + key + "}")
            box.setCurrentIndex(0)
            target.setFocus()

        box.activated.connect(insert)
        return box

    def _build_auto(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel(self._t("lbl_tpl_lines"))
        label.setWordWrap(True)
        layout.addWidget(label)
        self.lines_edit = QPlainTextEdit()
        self.lines_edit.textChanged.connect(self._lines_changed)
        layout.addWidget(self.lines_edit, 1)
        layout.addWidget(self._insert_box(self.lines_edit))
        return page

    def _build_manual(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.element_list = QListWidget()
        self.element_list.setMaximumHeight(140)
        self.element_list.currentRowChanged.connect(self._row_changed)
        layout.addWidget(self.element_list)
        row = QHBoxLayout()
        self.add_text_btn = QPushButton(self._t("ldg_add_text"))
        self.add_qr_btn = QPushButton(self._t("ldg_add_qr"))
        self.remove_btn = QPushButton(self._t("ldg_remove"))
        self.add_text_btn.clicked.connect(lambda: self.add_element("text"))
        self.add_qr_btn.clicked.connect(lambda: self.add_element("qr"))
        self.remove_btn.clicked.connect(self.remove_element)
        for button in (self.add_text_btn, self.add_qr_btn, self.remove_btn):
            row.addWidget(button)
        layout.addLayout(row)
        self.from_auto_btn = QPushButton(self._t("ldg_from_auto"))
        self.from_auto_btn.clicked.connect(self.start_from_automatic)
        layout.addWidget(self.from_auto_btn)
        self.element_form = QWidget()
        form = QFormLayout(self.element_form)
        self.text_edit = QLineEdit()
        self.x_box, self.y_box = _spin(-50, 400), _spin(-50, 300)
        self.w_box, self.size_box = _spin(0.5, 400), _spin(0.5, 200, 0.1)
        self.bold_box = QCheckBox(self._t("ldg_bold"))
        self.align_box = QComboBox()
        for align in ALIGNS:
            self.align_box.addItem(self._t(f"ldg_align_{align}"), align)
        self.text_label = QLabel(self._t("ldg_text"))
        self.size_label = QLabel(self._t("ldg_el_size"))
        form.addRow(self.text_label, self.text_edit)
        form.addRow(self._t("ldg_pos_x"), self.x_box)
        form.addRow(self._t("ldg_pos_y"), self.y_box)
        self.w_label = QLabel(self._t("ldg_el_width"))
        form.addRow(self.w_label, self.w_box)
        form.addRow(self.size_label, self.size_box)
        form.addRow(self.bold_box)
        self.align_label = QLabel(self._t("ldg_align"))
        form.addRow(self.align_label, self.align_box)
        form.addRow(self._insert_box(self.text_edit))
        layout.addWidget(self.element_form)
        for widget in (self.x_box, self.y_box, self.w_box, self.size_box):
            widget.valueChanged.connect(self._element_edited)
        self.text_edit.textChanged.connect(self._element_edited)
        self.bold_box.toggled.connect(self._element_edited)
        self.align_box.currentIndexChanged.connect(self._element_edited)
        layout.addStretch(1)
        return page

    # ================================================================ the data being edited
    def setup(self) -> LabelSetup:
        """The label size as the form shows it."""
        return LabelSetup(
            self.width_box.value(), self.height_box.value(), self.layout_box.currentData(),
            self.margin_box.value(), self.qr_box.isChecked(), self.border_box.isChecked(),
        )  # fmt: skip

    def draft(self) -> KindDesign:
        """The design of the current kind being edited (a copy of the saved one at first)."""
        if self.kind not in self.drafts:
            saved = self.store.design(self.kind)
            self.drafts[self.kind] = KindDesign(
                tuple(saved.lines),
                None if saved.elements is None else [replace(e) for e in saved.elements],
            )
        return self.drafts[self.kind]

    def _load_setup(self) -> None:
        setup = self.store.setup
        self._loading = True
        self.width_box.setValue(setup.width_mm)
        self.height_box.setValue(setup.height_mm)
        self.margin_box.setValue(setup.margin_mm)
        self.layout_box.setCurrentIndex(max(self.layout_box.findData(setup.layout), 0))
        self.qr_box.setChecked(setup.qr)
        self.border_box.setChecked(setup.border)
        self._loading = False

    def _load_kind(self) -> None:
        """Show the design of the current kind in the form."""
        design = self.draft()
        self._loading = True
        self.lines_edit.setPlainText("\n".join(design.lines))
        self.manual_radio.setChecked(design.manual)
        self.auto_radio.setChecked(not design.manual)
        self.stack.setCurrentIndex(1 if design.manual else 0)
        self._fill_elements(0)
        self._loading = False
        self._update_state()
        self._redraw()

    def _update_state(self) -> None:
        changed = self.draft().to_dict() != default_design(self.kind).to_dict()
        self.state_label.setText(self._t("ldg_changed" if changed else "ldg_default"))
        flag = self.setup().layout == "flag"
        self.manual_radio.setEnabled(not flag)
        if flag and self.draft().manual:
            self.state_label.setText(self._t("ldg_flag_auto"))

    # ================================================================ events
    def _setup_changed(self, *_args: Any) -> None:
        if not self._loading:
            self._update_state()
            self._redraw()

    def _kind_changed(self, index: int) -> None:
        self.kind = self.kind_box.itemData(index)
        self._load_kind()

    def _mode_changed(self, *_args: Any) -> None:
        if self._loading:
            return
        design = self.draft()
        if self.manual_radio.isChecked() and not design.manual:
            design.elements = auto_elements(
                self.setup(), design.lines, sample_asset(self.kind), text_measure
            )
        elif self.auto_radio.isChecked():
            design.elements = None
        self._load_kind()

    def _lines_changed(self) -> None:
        if self._loading:
            return
        self.draft().lines = tuple(
            x for x in self.lines_edit.toPlainText().splitlines() if x.strip()
        )
        self._update_state()
        self._redraw()

    def start_from_automatic(self) -> None:
        """Turn the lines into elements as the automatic layout draws them."""
        design = self.draft()
        design.elements = auto_elements(
            self.setup(), design.lines, sample_asset(self.kind), text_measure
        )
        self._load_kind()

    def _fill_elements(self, select: int) -> None:
        design = self.draft()
        self.element_list.blockSignals(True)
        self.element_list.clear()
        for n, element in enumerate(design.elements or [], 1):
            what = self._t("ldg_el_type_qr") if element.type == "qr" else element.text
            self.element_list.addItem(f"{n}. {what}")
        count = self.element_list.count()
        self.element_list.setCurrentRow(min(max(select, 0), count - 1) if count else -1)
        self.element_list.blockSignals(False)
        self._show_element()

    def current_index(self) -> int:
        """The element picked, -1 if none."""
        return self.element_list.currentRow()

    def _row_changed(self, _row: int) -> None:
        self._show_element()
        self._redraw()

    def _pick(self, index: int) -> None:
        self.element_list.setCurrentRow(index)

    def _moved(self, index: int, x: float, y: float) -> None:
        elements = self.draft().elements or []
        if 0 <= index < len(elements):
            elements[index].x, elements[index].y = x, y
            self._show_element()
            self._redraw()

    def _show_element(self) -> None:
        elements = self.draft().elements or []
        index = self.current_index()
        has = 0 <= index < len(elements)
        self.element_form.setEnabled(has)
        self.remove_btn.setEnabled(has)
        if not has:
            return
        element = elements[index]
        text = element.type == "text"
        self._loading = True
        self.text_edit.setText(element.text)
        self.x_box.setValue(element.x)
        self.y_box.setValue(element.y)
        self.w_box.setValue(element.w)
        self.size_box.setValue(element.size)
        self.bold_box.setChecked(element.bold)
        self.align_box.setCurrentIndex(max(self.align_box.findData(element.align), 0))
        for widget in (self.text_edit, self.text_label, self.w_box, self.w_label, self.bold_box,
                       self.align_box, self.align_label):  # fmt: skip
            widget.setEnabled(text)
        self.size_label.setText(self._t("ldg_el_size" if text else "ldg_el_side"))
        self._loading = False

    def _element_edited(self, *_args: Any) -> None:
        if self._loading:
            return
        elements = self.draft().elements or []
        index = self.current_index()
        if not 0 <= index < len(elements):
            return
        e = elements[index]
        e.x, e.y, e.size = self.x_box.value(), self.y_box.value(), self.size_box.value()
        if e.type == "text":
            e.text, e.w = self.text_edit.text(), self.w_box.value()
            e.bold, e.align = self.bold_box.isChecked(), self.align_box.currentData()
            item = self.element_list.item(index)
            item.setText(f"{index + 1}. {e.text}")
        self._update_state()
        self._redraw()

    def add_element(self, kind: str) -> None:
        """A new text (or the QR code) in the middle of the label."""
        design = self.draft()
        if design.elements is None:
            design.elements = []
        setup = self.setup()
        if kind == "qr":
            if any(e.type == "qr" for e in design.elements):
                return
            side = round(min(setup.height_mm - 2 * setup.margin_mm, setup.width_mm * 0.42), 1)
            design.elements.append(Element("qr", x=setup.margin_mm, y=setup.margin_mm, size=side))
        else:
            design.elements.append(
                Element("text", "{name}", setup.margin_mm, setup.margin_mm,
                        max(setup.width_mm - 2 * setup.margin_mm, 5), 3.0)
            )  # fmt: skip
        self._fill_elements(len(design.elements) - 1)
        self._update_state()
        self._redraw()

    def remove_element(self) -> None:
        """Take the picked element away."""
        elements = self.draft().elements or []
        index = self.current_index()
        if 0 <= index < len(elements):
            del elements[index]
            self._fill_elements(index)
            self._update_state()
            self._redraw()

    # ================================================================ the preview
    def _redraw(self) -> None:
        if self._loading:
            return
        setup, design = self.setup(), self.draft()
        wrong = setup_problems(setup) + design_problems(design, setup)
        card = sample_asset(self.kind)
        drawing = None
        if not setup_problems(setup):
            try:
                drawing = build_kind_drawing(setup, design, card, "", text_measure)
            except RuntimeError as exc:  # the QR code needs segno
                wrong.append(str(exc))
        self.preview.set_drawing(drawing)
        manual = design.manual and setup.layout != "flag"
        self.preview.set_elements(design.elements or [], self.current_index(), manual)
        if drawing is not None:
            wrong += list(dict.fromkeys(drawing.warnings))
            wrong += [self._t("lbl_dropped", fields=d) for d in dict.fromkeys(drawing.dropped)
                      if d not in " ".join(drawing.warnings)]  # fmt: skip
        self.message.setText("<br>".join(wrong))

    # ================================================================ saving
    def save(self) -> bool:
        """Save the size and every kind that was changed; what is wrong is written under the
        preview and nothing is saved. True if saved."""
        try:
            self.store.set_setup(self.setup())
            for kind, design in self.drafts.items():
                if design.to_dict() != self.store.design(kind).to_dict():
                    self.store.set_design(kind, design)
        except LabelTemplateError as exc:
            self.message.setText(self._t("lbl_tpl_problems", problems=str(exc)))
            return False
        self.message.setText(self._t("ldg_saved"))
        self._update_state()
        return True

    def reset_kind(self) -> None:
        """Forget the changes to this kind (after asking): the ready-made design again."""
        ask = QMessageBox.question(
            self,
            self._t("ldg_title"),
            self._t("ldg_confirm_reset", kind=self.kind_box.currentText()),
        )
        if ask != QMessageBox.StandardButton.Yes:
            return
        self.drafts.pop(self.kind, None)
        self.store.reset_design(self.kind)
        self._load_kind()
