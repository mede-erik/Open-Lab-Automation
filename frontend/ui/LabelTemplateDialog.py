# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Write your own label formats: size, layout and the lines of text with the data of the card.

A thin window over ``ola.label_templates`` (the file, the checks) and ``ola.labels`` (the layout).
On the left the templates you made, *New* (a copy of the format selected in the label window, or
an empty one) and *Delete*; on the right the form: name, size in mm, single label or flag, margin,
QR code, border and the **lines**, one per row, with the data of the card between braces
(``{id}``, ``{name}``, ``Rev {version}``...; the menu inserts a field). The preview shows the label
of a sample card (the first one of the label window) and what is wrong is written under it. Nothing
is saved until *Save* and a template that is not valid is not saved.
Strings: ``frontend/lang/modules/assets/<lang>.json``.
"""

from dataclasses import replace
from typing import Any, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.LabelDialog import LabelPreview
from frontend.ui.label_paint import text_measure
from frontend.ui.module_translator import CatalogTranslator
from ola.assets import Asset
from ola.label_templates import LAYOUTS, LabelTemplate, LabelTemplateError, TemplateStore, problems
from ola.labels import FIELDS, PRESETS, build_drawing


class LabelTemplateDialog(QDialog):
    """The editor of the label templates (see the module docstring)."""

    def __init__(
        self,
        store: TemplateStore,
        sample: Asset,
        translator: Any = None,
        start_from: str = "",
        parent: Optional[QWidget] = None,
    ):
        """``sample``: the card drawn in the preview. ``start_from``: the name of the format
        (a template or a built-in one) that *New* copies."""
        super().__init__(parent)
        self.tr_ = CatalogTranslator("assets", translator)
        self._t = self.tr_.t
        self.store, self.sample, self.start_from = store, sample, start_from
        self.current: Optional[str] = None  # the template being edited (None: a new one)
        self._loading = False
        self.setWindowTitle(self._t("lbl_tpl_title"))
        self.resize(900, 560)
        self._build()
        self._fill_list()
        if store.names():
            self.list.setCurrentRow(0)
        else:
            self._load(LabelTemplate(""))

    # ================================================================ building
    def _build(self) -> None:
        root = QHBoxLayout(self)
        side = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(220)
        self.list.currentRowChanged.connect(self._row_changed)
        side.addWidget(self.list, 1)
        self.new_btn = QPushButton(self._t("lbl_tpl_new"))
        self.new_btn.clicked.connect(self.new_template)
        self.delete_btn = QPushButton(self._t("lbl_tpl_delete"))
        self.delete_btn.clicked.connect(self.delete_template)
        side.addWidget(self.new_btn)
        side.addWidget(self.delete_btn)
        root.addLayout(side)

        form_side = QVBoxLayout()
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.width_box, self.height_box, self.margin_box = (QDoubleSpinBox() for _ in range(3))
        for box, low, high in ((self.width_box, 10, 300), (self.height_box, 8, 200)):
            box.setRange(low, high)
            box.setDecimals(1)
            box.setSuffix(" mm")
        self.margin_box.setRange(0, 10)
        self.margin_box.setDecimals(1)
        self.margin_box.setSuffix(" mm")
        self.layout_box = QComboBox()
        for layout in LAYOUTS:
            self.layout_box.addItem(self._t(f"lbl_tpl_layout_{layout}"), layout)
        self.qr_box = QCheckBox(self._t("lbl_qr"))
        self.border_box = QCheckBox(self._t("lbl_border"))
        form.addRow(self._t("lbl_tpl_name"), self.name_edit)
        form.addRow(self._t("lbl_tpl_width"), self.width_box)
        form.addRow(self._t("lbl_tpl_height"), self.height_box)
        form.addRow(self._t("lbl_tpl_layout"), self.layout_box)
        form.addRow(self._t("lbl_tpl_margin"), self.margin_box)
        form.addRow(self.qr_box)
        form.addRow(self.border_box)
        form_side.addLayout(form)
        form_side.addWidget(QLabel(self._t("lbl_tpl_lines")))
        self.lines_edit = QPlainTextEdit()
        self.lines_edit.setMaximumHeight(130)
        form_side.addWidget(self.lines_edit)
        insert_row = QHBoxLayout()
        self.insert_box = QComboBox()
        self.insert_box.addItem(self._t("lbl_tpl_insert"), "")
        for key in FIELDS:
            self.insert_box.addItem(f"{{{key}}}  {self._t(f'lbl_field_{key}')}", key)
        self.insert_box.activated.connect(self._insert_field)
        insert_row.addWidget(self.insert_box, 1)
        form_side.addLayout(insert_row)
        for widget in (self.name_edit, self.lines_edit):
            widget.textChanged.connect(self._redraw)
        for box in (self.width_box, self.height_box, self.margin_box):
            box.valueChanged.connect(self._redraw)
        self.layout_box.currentIndexChanged.connect(self._redraw)
        self.qr_box.toggled.connect(self._redraw)
        self.border_box.toggled.connect(self._redraw)
        self.save_btn = QPushButton(self._t("lbl_tpl_save"))
        self.save_btn.clicked.connect(self.save)
        form_side.addWidget(self.save_btn)
        root.addLayout(form_side, 1)

        view = QVBoxLayout()
        self.preview = LabelPreview()
        view.addWidget(self.preview, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.RichText)
        view.addWidget(self.message)
        root.addLayout(view, 1)

    # ================================================================ the list
    def _fill_list(self, select: str = "") -> None:
        self.list.blockSignals(True)
        self.list.clear()
        self.list.addItems(self.store.names())
        if select in self.store.names():
            self.list.setCurrentRow(self.store.names().index(select))
        self.list.blockSignals(False)
        self.delete_btn.setEnabled(bool(self.store.names()))

    def _row_changed(self, row: int) -> None:
        names = self.store.names()
        if 0 <= row < len(names):
            self._load(self.store.get(names[row]), names[row])

    def _load(self, template: LabelTemplate, name: Optional[str] = None) -> None:
        """Show a template in the form; ``name`` is the one it replaces when saved."""
        self._loading = True
        self.current = name
        self.name_edit.setText(template.name)
        self.width_box.setValue(template.width_mm)
        self.height_box.setValue(template.height_mm)
        self.margin_box.setValue(template.margin_mm)
        self.layout_box.setCurrentIndex(max(self.layout_box.findData(template.layout), 0))
        self.qr_box.setChecked(template.qr)
        self.border_box.setChecked(template.border)
        self.lines_edit.setPlainText("\n".join(template.lines))
        self._loading = False
        self._redraw()

    def form_template(self) -> LabelTemplate:
        """The template as the form shows it now."""
        lines = [x for x in self.lines_edit.toPlainText().splitlines() if x.strip()]
        return LabelTemplate(
            self.name_edit.text().strip(),
            self.width_box.value(),
            self.height_box.value(),
            self.layout_box.currentData(),
            tuple(lines),
            self.qr_box.isChecked(),
            self.border_box.isChecked(),
            self.margin_box.value(),
        )

    # ================================================================ actions
    def new_template(self) -> None:
        """A new template: a copy of the format the label window had selected, or an empty one."""
        source = self.start_from
        if source in PRESETS or self.store.get(source):
            copy = self.store.duplicate(source)
            self._fill_list(copy.name)
            self._load(copy, copy.name)
        else:
            self.list.blockSignals(True)
            self.list.clearSelection()
            self.list.setCurrentRow(-1)
            self.list.blockSignals(False)
            self._load(LabelTemplate(""))

    def delete_template(self) -> None:
        """Delete the selected template, after asking."""
        name = self.current
        if not name:
            return
        ask = QMessageBox.question(
            self, self._t("lbl_tpl_title"), self._t("lbl_tpl_confirm_delete", name=name)
        )
        if ask != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(name)
        self._fill_list()
        if self.store.names():
            self.list.setCurrentRow(0)
        else:
            self._load(LabelTemplate(""))

    def save(self) -> bool:
        """Save the form; what is wrong is written under the preview. True if saved."""
        template = self.form_template()
        try:
            self.store.put(template, replace=self.current)
        except LabelTemplateError as exc:
            self.message.setText(self._t("lbl_tpl_problems", problems=str(exc)))
            return False
        self.current = template.name
        self._fill_list(template.name)
        self.message.setText(self._t("lbl_tpl_saved", name=template.name))
        return True

    def _insert_field(self, index: int) -> None:
        key = self.insert_box.itemData(index)
        if key:
            self.lines_edit.insertPlainText("{" + key + "}")
        self.insert_box.setCurrentIndex(0)
        self.lines_edit.setFocus()

    # ================================================================ preview
    def _redraw(self, *_args: Any) -> None:
        if self._loading:
            return
        template = self.form_template()
        wrong: List[str] = problems(replace(template, name=template.name or "x"))
        try:
            drawing = build_drawing(template.to_spec(), self.sample, "", text_measure)
        except RuntimeError as exc:  # the QR code needs segno
            drawing, wrong = None, wrong + [str(exc)]
        self.preview.set_drawing(drawing)
        if drawing is not None:
            wrong += [self._t("lbl_dropped", fields=d) for d in dict.fromkeys(drawing.dropped)]
            wrong += list(dict.fromkeys(drawing.warnings))
        self.message.setText("<br>".join(wrong))
