# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Dialog to edit an efficiency measurement file (``.eff``).

A thin layer over ``ola.efficiency_editor.EfficiencyEditor`` (which owns the data and is tested
without a screen). Every field of the dialog is bound to a *path* of the parameters
(``variables[1].set.call``); after every edit the model is validated again and the result is shown
where it belongs:

* a red (error) or amber (warning) border and a tooltip on the field;
* the list of all the problems at the bottom; a double click jumps to the field;
* a one-line summary: points, sweeps, cooldowns and the time spent waiting.

The order of the parameter list is the order of the sweeps and of setting (the first one is the
fastest, innermost sweep): it is changed with the up / down buttons. Strings come from
``frontend/lang/modules/efficiency/<lang>.json``. Run ``python -m frontend.ui.EfficiencyEditorDialog
[file.eff]`` to try it with a few demo instruments.
"""

import json
import os
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.efficiency_widgets import (
    text_color,
    CallEdit,
    format_number,
    format_number_list,
    mark_widget,
    parse_number,
    parse_number_list,
)
from frontend.ui.module_translator import CatalogTranslator
from ola.efficiency_editor import EditorError, EfficiencyEditor
from ola.efficiency_spec import CallChecker

SWEEP_MODES = ("none", "fixed", "list", "points", "step", "log")
OUTPUT_MODES = ("keep_on", "off_during_cooldown", "always_on")
ON_FAIL = ("ask", "warn", "stop")


class _Field:
    """One widget bound to one path of the parameters."""

    def __init__(self, widget: QWidget, path: str, kind: str, scoped: bool):
        self.widget, self.path_template, self.kind, self.scoped = widget, path, kind, scoped
        self.invalid = False
        self.default: Callable[[], dict] = dict  # new content of a checkable group

    def path(self, index: Optional[int]) -> str:
        return self.path_template.format(i=index) if self.scoped else self.path_template


class EfficiencyEditorDialog(QDialog):
    """Editor of an ``.eff`` file with live validation."""

    def __init__(
        self,
        file_path: Optional[str] = None,
        translator: Any = None,
        instruments: Sequence[str] = (),
        catalog: Optional[Callable[[str], Sequence[str]]] = None,
        checker: Optional[CallChecker] = None,
        params: Optional[dict] = None,
        parent: Optional[QWidget] = None,
    ):
        """``file_path``: the file to edit (created on save if it does not exist). ``instruments``:
        names of the instruments of the project. ``catalog(instrument)``: call names known for an
        instrument (optional). ``checker``: the library check of calls and values (optional)."""
        super().__init__(parent)
        self.tr_ = CatalogTranslator("efficiency", translator)
        self._t = self.tr_.t
        self.file_path = file_path
        self.instruments = list(instruments)
        self.catalog = catalog
        self.dirty = False
        self._loading = False
        self._current: Optional[int] = None
        self._fields: List[_Field] = []  # fixed fields of the parameter form and other tabs
        self._dynamic: List[_Field] = []  # fields of the readings / extra calls (rebuilt)
        self._calls: Dict[str, CallEdit] = {}  # CallEdit of every bound path template
        self.editor = self._open_model(params, checker)
        self.setWindowTitle(self._t("eff_title"))
        self.resize(1180, 820)
        self._build_ui()
        self._refresh_all()
        if self.editor.variables:
            self.param_list.setCurrentRow(0)

    # ================================================================ model
    def _open_model(
        self, params: Optional[dict], checker: Optional[CallChecker]
    ) -> EfficiencyEditor:
        kwargs = {"instruments": self.instruments or None, "checker": checker}
        if params is not None:
            return EfficiencyEditor(params, **kwargs)
        if self.file_path and os.path.isfile(self.file_path):
            try:
                return EfficiencyEditor.from_file(self.file_path, **kwargs)
            except Exception as exc:  # unreadable or another kind of file
                QMessageBox.critical(
                    self, self._t("eff_title"), self._t("eff_open_failed", error=exc)
                )
        return EfficiencyEditor(EfficiencyEditor.template(self.instruments), **kwargs)

    # ================================================================ building the window
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.file_label = QLabel()
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.file_label, 1)
        top.addWidget(self.summary_label, 3)
        root.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_parameters_tab(), self._t("eff_tab_parameters"))
        self.tabs.addTab(self._build_timing_tab(), self._t("eff_tab_timing"))
        self.tabs.addTab(self._build_formulas_tab(), self._t("eff_tab_formulas"))
        self.tabs.addTab(self._build_power_tab(), self._t("eff_tab_power"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.tabs.addTab(self.preview, self._t("eff_tab_file"))

        self.problem_tree = QTreeWidget()
        self.problem_tree.setHeaderLabels(
            ["", self._t("eff_problem_field"), self._t("eff_problem_message")]
        )
        self.problem_tree.setRootIsDecorated(False)
        self.problem_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.problem_tree.setColumnWidth(0, 28)
        self.problem_tree.setColumnWidth(1, 260)
        self.problem_tree.itemDoubleClicked.connect(
            lambda item, _c: self.navigate(item.data(0, Qt.ItemDataRole.UserRole))
        )
        self.problem_title = QLabel()
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self.problem_title)
        bottom_layout.addWidget(self.problem_tree)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        bottom.setMinimumHeight(190)
        root.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.status_label = QLabel()
        self.save_btn = QPushButton(self._t("eff_save"))
        self.save_btn.clicked.connect(self.save)
        self.close_btn = QPushButton(self._t("eff_close"))
        self.close_btn.clicked.connect(self.close)
        buttons.addWidget(self.status_label, 1)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

    # ---- parameters tab ---------------------------------------------------------------------
    def _build_parameters_tab(self) -> QWidget:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel(self._t("eff_param_list_help")))
        self.param_list = QListWidget()
        self.param_list.currentRowChanged.connect(self._select_parameter)
        left_layout.addWidget(self.param_list, 1)
        row = QHBoxLayout()
        for key, handler in (
            ("eff_add", self._add_parameter),
            ("eff_duplicate", self._duplicate_parameter),
            ("eff_remove", self._remove_parameter),
            ("eff_up", lambda: self._move_parameter(-1)),
            ("eff_down", lambda: self._move_parameter(+1)),
        ):
            button = QPushButton(self._t(key))
            button.clicked.connect(handler)
            setattr(self, f"btn_{key}", button)
            row.addWidget(button)
        left_layout.addLayout(row)

        self.form_container = QWidget()
        form_layout = QVBoxLayout(self.form_container)
        self.param_messages = QLabel()
        self.param_messages.setTextFormat(Qt.TextFormat.RichText)
        self.param_messages.setWordWrap(True)
        form_layout.addWidget(self.param_messages)
        name_row = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._rename_current)
        name_row.addRow(self._t("eff_name"), self.name_edit)
        form_layout.addLayout(name_row)
        form_layout.addWidget(self._build_set_group())
        form_layout.addWidget(self._build_value_group())
        form_layout.addWidget(self._build_reads_group())
        form_layout.addWidget(self._build_verify_group())
        form_layout.addWidget(self._build_limits_group())
        form_layout.addWidget(self._build_output_group())
        form_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.form_container)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        return splitter

    def _call_edit(self, path: str, scoped: bool = True) -> CallEdit:
        edit = CallEdit(
            self.instruments,
            self.catalog,
            {
                "instrument": self._t("eff_ph_instrument"),
                "call": self._t("eff_ph_call"),
                "args": self._t("eff_ph_args"),
            },
        )
        field = _Field(edit, path, "call", scoped)
        self._fields.append(field)
        self._calls[path] = edit
        edit.changed.connect(lambda f=field: self._field_changed(f))
        return edit

    def _line(self, path: str, kind: str = "text", scoped: bool = True, tip: str = "") -> QLineEdit:
        edit = QLineEdit()
        if tip:
            edit.setPlaceholderText(tip)
        field = _Field(edit, path, kind, scoped)
        self._fields.append(field)
        edit.textChanged.connect(lambda _t, f=field: self._field_changed(f))
        return edit

    def _choice(self, path: str, values: Sequence[str], labels: Dict[str, str]) -> QComboBox:
        box = QComboBox()
        for value in values:
            box.addItem(labels[value], value)
        field = _Field(box, path, "choice", True)
        self._fields.append(field)
        box.currentIndexChanged.connect(lambda _i, f=field: self._field_changed(f))
        return box

    def _group(self, title_key: str, path: str, default: Callable[[], dict]) -> QGroupBox:
        group = QGroupBox(self._t(title_key))
        group.setCheckable(True)
        group.setChecked(False)
        field = _Field(group, path, "group", True)
        field.default = default
        self._fields.append(field)
        group.toggled.connect(lambda on, f=field: self._group_toggled(f, on))
        return group

    def _build_set_group(self) -> QGroupBox:
        self.set_group = self._group(
            "eff_set", "variables[{i}].set", lambda: {"instrument": "", "call": ""}
        )
        form = QFormLayout(self.set_group)
        form.addRow(QLabel(self._t("eff_set_help")))
        form.addRow(self._t("eff_call"), self._call_edit("variables[{i}].set"))
        form.addRow(
            self._t("eff_value_arg"), self._line("variables[{i}].set.value_arg", tip="value")
        )
        return self.set_group

    def _build_value_group(self) -> QGroupBox:
        self.value_group = QGroupBox(self._t("eff_value"))
        form = QFormLayout(self.value_group)
        self.mode_box = QComboBox()
        for mode in SWEEP_MODES:
            self.mode_box.addItem(self._t(f"eff_mode_{mode}"), mode)
        self.mode_box.currentIndexChanged.connect(self._mode_changed)
        form.addRow(self._t("eff_how"), self.mode_box)
        self.sweep_rows = {}
        for key, path, kind, tip in (
            ("value", "variables[{i}].value", "number", ""),
            ("values", "variables[{i}].sweep.values", "numlist", self._t("eff_tip_list")),
            ("start", "variables[{i}].sweep.start", "number", ""),
            ("stop", "variables[{i}].sweep.stop", "number", ""),
            ("points", "variables[{i}].sweep.points", "int", ""),
            ("step", "variables[{i}].sweep.step", "number", ""),
        ):
            edit = self._line(path, kind, tip=tip)
            label = QLabel(self._t(f"eff_{key}"))
            form.addRow(label, edit)
            self.sweep_rows[key] = (label, edit)
        self.sweep_preview = QLabel()
        self.sweep_preview.setWordWrap(True)
        form.addRow(self.sweep_preview)
        return self.value_group

    def _build_reads_group(self) -> QGroupBox:
        group = QGroupBox(self._t("eff_reads"))
        layout = QVBoxLayout(group)
        layout.addWidget(QLabel(self._t("eff_reads_help")))
        self.reads_layout = QVBoxLayout()
        layout.addLayout(self.reads_layout)
        add = QPushButton(self._t("eff_add_reading"))
        add.clicked.connect(self._add_reading)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        return group

    def _build_verify_group(self) -> QGroupBox:
        self.verify_group = self._group(
            "eff_verify",
            "variables[{i}].verify",
            lambda: {"read": "", "tol_rel": 0.01, "on_fail": "ask"},
        )
        form = QFormLayout(self.verify_group)
        form.addRow(QLabel(self._t("eff_verify_help")))
        self.verify_read = QComboBox()
        self.verify_read.setEditable(True)
        field = _Field(self.verify_read, "variables[{i}].verify.read", "combo", True)
        self._fields.append(field)
        self.verify_read.currentTextChanged.connect(lambda _t, f=field: self._field_changed(f))
        form.addRow(self._t("eff_verify_read"), self.verify_read)
        form.addRow(self._t("eff_tol_abs"), self._line("variables[{i}].verify.tol_abs", "number"))
        form.addRow(
            self._t("eff_tol_rel"),
            self._line("variables[{i}].verify.tol_rel", "number", tip="0.01 = 1 %"),
        )
        labels = {v: self._t(f"eff_on_fail_{v}") for v in ON_FAIL}
        form.addRow(
            self._t("eff_on_fail"), self._choice("variables[{i}].verify.on_fail", ON_FAIL, labels)
        )
        return self.verify_group

    def _build_limits_group(self) -> QGroupBox:
        self.limits_group = self._group("eff_limits", "variables[{i}].limits", dict)
        form = QFormLayout(self.limits_group)
        form.addRow(self._t("eff_min"), self._line("variables[{i}].limits.min", "number"))
        form.addRow(self._t("eff_max"), self._line("variables[{i}].limits.max", "number"))
        return self.limits_group

    def _build_output_group(self) -> QGroupBox:
        self.output_group = self._group(
            "eff_output", "variables[{i}].output", lambda: {"mode": "keep_on"}
        )
        form = QFormLayout(self.output_group)
        form.addRow(QLabel(self._t("eff_output_help")))
        labels = {v: self._t(f"eff_out_{v}") for v in OUTPUT_MODES}
        self.output_mode = self._choice("variables[{i}].output.mode", OUTPUT_MODES, labels)
        form.addRow(self._t("eff_out_mode"), self.output_mode)
        self.output_mode_help = QLabel()
        self.output_mode_help.setWordWrap(True)
        form.addRow(self.output_mode_help)
        for key in ("on", "off", "state"):
            form.addRow(
                self._t(f"eff_out_{key}"), self._call_edit(f"variables[{{i}}].output.{key}")
            )
        return self.output_group

    # ---- timing tab -------------------------------------------------------------------------
    def _build_timing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(self._t("eff_timing_help")))
        form = QFormLayout()
        form.addRow(
            self._t("eff_settle"), self._line("timing.settle_s", "number", scoped=False, tip="s")
        )
        form.addRow(self._t("eff_samples"), self._line("timing.samples", "int", scoped=False))
        form.addRow(
            self._t("eff_interval"),
            self._line("timing.interval_s", "number", scoped=False, tip="s"),
        )
        form.addRow(
            self._t("eff_cooldown"),
            self._line("timing.cooldown_s", "number", scoped=False, tip="s"),
        )
        layout.addLayout(form)
        layout.addWidget(QLabel(self._t("eff_cooldown_help")))
        self.timing_summary = QLabel()
        self.timing_summary.setWordWrap(True)
        layout.addWidget(self.timing_summary)
        layout.addStretch(1)
        return page

    # ---- formulas tab -----------------------------------------------------------------------
    def _build_formulas_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        left = QVBoxLayout()
        left.addWidget(QLabel(self._t("eff_formulas_help")))
        self.formula_table = QTableWidget(0, 2)
        self.formula_table.setHorizontalHeaderLabels(
            [self._t("eff_f_name"), self._t("eff_f_formula")]
        )
        self.formula_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.formula_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.formula_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.formula_table.itemChanged.connect(self._formula_name_edited)
        self.formula_table.itemSelectionChanged.connect(self._formula_selected)
        left.addWidget(self.formula_table, 1)
        self.formula_edit = QLineEdit()
        self.formula_edit.setPlaceholderText(self._t("eff_f_placeholder"))
        self.formula_edit.textEdited.connect(self._formula_text_edited)
        left.addWidget(self.formula_edit)
        self.formula_message = QLabel()
        self.formula_message.setWordWrap(True)
        left.addWidget(self.formula_message)
        row = QHBoxLayout()
        add = QPushButton(self._t("eff_add"))
        add.clicked.connect(self._add_formula)
        remove = QPushButton(self._t("eff_remove"))
        remove.clicked.connect(self._remove_formula)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        left.addLayout(row)
        layout.addLayout(left, 3)
        right = QVBoxLayout()
        right.addWidget(QLabel(self._t("eff_names_help")))
        self.names_list = QListWidget()
        self.names_list.itemDoubleClicked.connect(self._insert_name)
        right.addWidget(self.names_list, 1)
        layout.addLayout(right, 1)
        return page

    # ---- power tab --------------------------------------------------------------------------
    def _build_power_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(self._t("eff_power_help")))
        row = QHBoxLayout()
        self.power_list = QListWidget()
        row.addWidget(self.power_list, 1)
        side = QVBoxLayout()
        for key, handler in (
            ("eff_up", lambda: self._move_power(-1)),
            ("eff_down", lambda: self._move_power(+1)),
            ("eff_reset_order", self._reset_power),
        ):
            button = QPushButton(self._t(key))
            button.clicked.connect(handler)
            side.addWidget(button)
        side.addStretch(1)
        row.addLayout(side)
        layout.addLayout(row, 1)
        self.always_label = QLabel()
        self.always_label.setWordWrap(True)
        layout.addWidget(self.always_label)
        self.extra_boxes = {}
        for section in ("startup", "shutdown"):
            group = QGroupBox(self._t(f"eff_{section}"))
            group_layout = QVBoxLayout(group)
            group_layout.addWidget(QLabel(self._t(f"eff_{section}_help")))
            holder = QVBoxLayout()
            group_layout.addLayout(holder)
            add = QPushButton(self._t("eff_add_call"))
            add.clicked.connect(lambda _c=False, s=section: self._add_call(s))
            group_layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
            self.extra_boxes[section] = holder
            layout.addWidget(group)
        layout.addStretch(1)
        return page

    # ================================================================ reading and writing fields
    def _write_field(self, field: _Field, index: Optional[int]) -> None:
        """Show the value of the model in a widget."""
        value = self.editor.get(field.path(index))
        widget = field.widget
        if field.kind in ("text", "combo"):
            text = "" if value is None else str(value)
            widget.setText(text) if field.kind == "text" else widget.setCurrentText(text)
        elif field.kind in ("number", "int"):
            widget.setText(format_number(value) if value is not None else "")
        elif field.kind == "numlist":
            widget.setText(format_number_list(value) if isinstance(value, list) else "")
        elif field.kind == "choice":
            position = widget.findData(value)
            widget.setCurrentIndex(position if position >= 0 else 0)
        elif field.kind == "call":
            widget.set_value(value if isinstance(value, dict) else None)
        elif field.kind == "group":
            widget.setChecked(isinstance(value, dict))
        field.invalid = False

    def _read_field(self, field: _Field):
        """The value typed in a widget: ``(ok, value)``; ``ok`` is False if it cannot be used."""
        widget = field.widget
        if field.kind == "text":
            return True, widget.text().strip() or None
        if field.kind == "combo":
            return True, widget.currentText().strip() or None
        if field.kind in ("number", "int"):
            return parse_number(widget.text(), integer=field.kind == "int")
        if field.kind == "numlist":
            values = parse_number_list(widget.text())
            return (False, None) if values is None else (True, values or None)
        if field.kind == "choice":
            return True, widget.currentData()
        return True, None

    def _field_changed(self, field: _Field) -> None:
        if self._loading:
            return
        index = self._current if field.scoped else None
        if field.scoped and index is None:
            return
        path = field.path(index)
        if field.kind == "call":
            self._write_call(field, path)
        else:
            ok, value = self._read_field(field)
            field.invalid = not ok
            if ok:
                self.editor.set(path, value)
        self._after_change()

    def _write_call(self, field: _Field, path: str) -> None:
        """Store the three parts of a CallEdit as separate keys (other keys of the block stay)."""
        edit: CallEdit = field.widget
        value = edit.value() or {}
        field.invalid = edit.args_invalid
        for key in ("instrument", "call", "args"):
            if key == "args" and edit.args_invalid:
                continue  # keep the previous arguments until the text is valid again
            self.editor.set(f"{path}.{key}", value.get(key))
        block = self.editor.get(path)
        keep_empty = path.endswith(".set")
        if isinstance(block, dict) and not block and not keep_empty:
            self.editor.set(path, None)  # an optional call with nothing in it is "not given"

    def _group_toggled(self, field: _Field, on: bool) -> None:
        if self._loading or self._current is None:
            return
        path = field.path(self._current)
        if on and not isinstance(self.editor.get(path), dict):
            default = field.default()
            if field.path_template.endswith(".verify") and not default.get("read"):
                labels = self.editor.reading_labels(self._current)
                default["read"] = labels[0] if labels else ""
            self.editor.set(path, default)
        elif not on:
            self.editor.set(path, None)
        self._load_parameter()
        self._after_change()

    def _mode_changed(self, _index: int) -> None:
        if self._loading or self._current is None:
            return
        self.editor.set_sweep_mode(self._current, self.mode_box.currentData())
        self._load_parameter()
        self._after_change()

    # ================================================================ the parameter list
    def _refresh_param_list(self, select: Optional[int] = None) -> None:
        keep = self._current if select is None else select
        self._loading = True
        self.param_list.clear()
        fastest = next(
            (
                i
                for i in range(len(self.editor.variables))
                if self.editor.sweep_mode(i) in ("list", "points", "step", "log")
            ),
            None,
        )
        for i, var in enumerate(self.editor.variables):
            mode = self.editor.sweep_mode(i)
            values = self.editor.sweep_values(i)
            if mode in ("list", "points", "step", "log"):
                note = self._t("eff_note_sweep", n=len(values) if values else "?")
                note += " · " + self._t("eff_note_fastest") if i == fastest else ""
            elif mode == "fixed":
                note = self._t("eff_note_fixed")
            elif isinstance(var.get("set"), dict):
                note = self._t("eff_note_no_value")
            else:
                note = self._t("eff_note_read_only")
            self.param_list.addItem(f"{i + 1}. {var.get('name') or '?'}   ({note})")
            severity = self._worst(self.editor.problems_at(f"variables[{i}]"))
            if severity:
                color = self._c("error" if severity == "error" else "warning")
                self.param_list.item(i).setForeground(QBrush(QColor(color)))
        if keep is not None and 0 <= keep < self.param_list.count():
            self.param_list.setCurrentRow(keep)
        self._loading = False

    def _c(self, kind: str) -> str:
        """Colour for a coloured text, readable in light and dark themes."""
        return text_color(kind, self)

    def _color(self, problem) -> str:
        return self._c("error" if problem.severity == "error" else "warning")

    @staticmethod
    def _worst(problems: Sequence) -> Optional[str]:
        if any(p.severity == "error" for p in problems):
            return "error"
        return "warning" if problems else None

    def _select_parameter(self, row: int) -> None:
        if self._loading:
            return
        self._current = row if row >= 0 else None
        self._load_parameter()

    def _add_parameter(self) -> None:
        index = self.editor.add_parameter(self._t("eff_new_name"))
        self._after_structure(select=index)

    def _duplicate_parameter(self) -> None:
        if self._current is not None:
            self._after_structure(select=self.editor.duplicate_parameter(self._current))

    def _remove_parameter(self) -> None:
        if self._current is None:
            return
        name = self.editor.names()[self._current]
        answer = QMessageBox.question(
            self, self._t("eff_title"), self._t("eff_confirm_remove", name=name)
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.editor.remove_parameter(self._current)
            self._current = None
            self._after_structure(
                select=min(self.param_list.currentRow(), len(self.editor.variables) - 1)
            )

    def _move_parameter(self, delta: int) -> None:
        if self._current is not None:
            self._after_structure(select=self.editor.move_parameter(self._current, delta))

    def _rename_current(self) -> None:
        if self._loading or self._current is None:
            return
        new = self.name_edit.text().strip()
        old = self.editor.names()[self._current]
        if new == old:
            return
        try:
            changed = self.editor.rename_parameter(self._current, new)
        except EditorError as exc:
            self.name_edit.setText(old)
            self._status(str(exc), error=True)
            return
        if changed:
            self._status(self._t("eff_renamed_formulas", n=len(changed)))
        self._after_structure(select=self._current)

    def _after_structure(self, select: Optional[int] = None) -> None:
        """The list of parameters changed (add, remove, move, rename): redraw everything."""
        self._refresh_param_list(select)
        self._current = self.param_list.currentRow() if self.param_list.count() else None
        self._load_parameter()
        self._refresh_formulas()
        self._refresh_power()
        self._after_change()

    # ================================================================ the form of one parameter
    def _load_parameter(self) -> None:
        index = self._current
        self._loading = True
        self.form_container.setEnabled(index is not None)
        if index is not None:
            self.name_edit.setText(self.editor.names()[index])
            for field in self._fields:
                if field.scoped:
                    self._write_field(field, index)
            self.mode_box.setCurrentIndex(self.mode_box.findData(self.editor.sweep_mode(index)))
            self.verify_read.clear()
            self.verify_read.addItems(self.editor.reading_labels(index))
            self._write_field(next(f for f in self._fields if f.widget is self.verify_read), index)
            self._rebuild_readings()
        else:
            self.name_edit.clear()
            self._rebuild_readings()
        self._loading = False
        self._update_dependent()
        self._apply_marks()

    def _update_dependent(self) -> None:
        """Show only the fields that mean something for the chosen mode."""
        index = self._current
        if index is None:
            return
        mode = self.editor.sweep_mode(index)
        shown = {
            "none": (), "fixed": ("value",), "list": ("values",),
            "points": ("start", "stop", "points"), "step": ("start", "stop", "step"),
            "log": ("start", "stop", "points"),
        }[mode]  # fmt: skip
        for key, (label, edit) in self.sweep_rows.items():
            label.setVisible(key in shown)
            edit.setVisible(key in shown)
        has_set = isinstance(self.editor.get(f"variables[{index}].set"), dict)
        self.value_group.setEnabled(has_set)
        values, error = self.editor.sweep_values(index), self.editor.sweep_error(index)
        if error:
            text = f"<span style='color:{self._c('error')}'>{error}</span>"
        elif values and mode not in ("none", "fixed"):
            shown_values = format_number_list(values[:8]) + (" …" if len(values) > 8 else "")
            text = self._t("eff_preview_values", n=len(values), values=shown_values)
        else:
            text = ""
        self.sweep_preview.setText(text)
        output = self.editor.get(f"variables[{index}].output")
        mode = output.get("mode", "keep_on") if isinstance(output, dict) else "keep_on"
        self.output_mode_help.setText(self._t(f"eff_out_help_{mode}"))

    # ---- readings ---------------------------------------------------------------------------
    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()  # deleteLater() is not immediate: hide and detach it at once
                widget.setParent(None)
                widget.deleteLater()

    def _dynamic_line(self, path: str, kind: str, placeholder: str = "") -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        field = _Field(edit, path, kind, False)
        self._dynamic.append(field)
        edit.textChanged.connect(lambda _t, f=field: self._field_changed(f))
        return edit

    def _dynamic_call(self, path: str) -> CallEdit:
        edit = CallEdit(
            self.instruments,
            self.catalog,
            {
                "instrument": self._t("eff_ph_instrument"),
                "call": self._t("eff_ph_call"),
                "args": self._t("eff_ph_args"),
            },
        )
        field = _Field(edit, path, "call", False)
        self._dynamic.append(field)
        edit.changed.connect(lambda f=field: self._field_changed(f))
        return edit

    def _rebuild_readings(self) -> None:
        self._dynamic = [f for f in self._dynamic if not f.path_template.startswith("variables[")]
        self._clear_layout(self.reads_layout)
        index = self._current
        if index is None:
            return
        for label in self.editor.reading_labels(index):
            base = f"variables[{index}].reads.{label}"
            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            layout = QVBoxLayout(card)
            top = QHBoxLayout()
            name = QLineEdit(label)
            name.setMaximumWidth(140)
            name.editingFinished.connect(lambda old=label, w=name: self._rename_reading(old, w))
            remove = QPushButton(self._t("eff_remove"))
            remove.clicked.connect(lambda _c=False, old=label: self._remove_reading(old))
            top.addWidget(QLabel(self._t("eff_label")))
            top.addWidget(name)
            top.addStretch(1)
            top.addWidget(remove)
            layout.addLayout(top)
            call = self._dynamic_call(base)
            call.set_value(self.editor.get(base))
            layout.addWidget(call)
            row = QHBoxLayout()
            for key in ("scale", "offset"):
                edit = self._dynamic_line(f"{base}.{key}", "number", "1" if key == "scale" else "0")
                edit.setText(format_number(self.editor.get(f"{base}.{key}")))
                row.addWidget(QLabel(self._t(f"eff_{key}")))
                row.addWidget(edit)
            layout.addLayout(row)
            self.reads_layout.addWidget(card)

    def _add_reading(self) -> None:
        if self._current is not None:
            self.editor.add_reading(self._current, self._t("eff_new_reading"))
            self._load_parameter()
            self._after_change()

    def _remove_reading(self, label: str) -> None:
        if self._current is not None:
            self.editor.remove_reading(self._current, label)
            self._load_parameter()
            self._refresh_formulas()
            self._after_change()

    def _rename_reading(self, old: str, widget: QLineEdit) -> None:
        new = widget.text().strip()
        if self._current is None or new == old:
            return
        try:
            changed = self.editor.rename_reading(self._current, old, new)
        except EditorError as exc:
            widget.setText(old)
            self._status(str(exc), error=True)
            return
        if changed:
            self._status(self._t("eff_renamed_formulas", n=len(changed)))
        self._load_parameter()
        self._refresh_formulas()
        self._after_change()

    # ================================================================ formulas tab
    def _refresh_formulas(self) -> None:
        derived = self.editor.params.get("derived") or {}
        self._loading = True
        selected = self.formula_table.currentRow()
        self.formula_table.setRowCount(0)
        self._formula_names = list(derived)
        for name, text in derived.items():
            row = self.formula_table.rowCount()
            self.formula_table.insertRow(row)
            self.formula_table.setItem(row, 0, QTableWidgetItem(name))
            cell = QTableWidgetItem(str(text))
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.formula_table.setItem(row, 1, cell)
        if not 0 <= selected < self.formula_table.rowCount():
            selected = next(
                (
                    i
                    for i, n in enumerate(self._formula_names)
                    if self.editor.problems_at(f"derived.{n}")
                ),
                0,
            )
        if 0 <= selected < self.formula_table.rowCount():
            self.formula_table.selectRow(selected)
        self._color_formula_rows()
        self.names_list.clear()
        groups = self.editor.available_names()
        for key in ("setpoints", "readings", "derived"):
            if not groups[key]:
                continue
            header = QListWidgetItem(self._t(f"eff_group_{key}"))
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setFlags(Qt.ItemFlag.NoItemFlags)  # a title: cannot be selected or inserted
            header.setData(Qt.ItemDataRole.UserRole, "header")
            self.names_list.addItem(header)
            for name in groups[key]:
                item = QListWidgetItem("   " + name)
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.names_list.addItem(item)
        self._loading = False
        self._formula_selected()

    def _color_formula_rows(self) -> None:
        """Names of the formulas with a problem are shown in red (or amber)."""
        for row, name in enumerate(getattr(self, "_formula_names", [])):
            severity = self._worst(self.editor.problems_at(f"derived.{name}"))
            color = self._c(severity and ("error" if severity == "error" else "warning") or "muted")
            item = self.formula_table.item(row, 0)
            if item is not None:
                item.setForeground(QBrush(QColor(color)) if severity else QBrush())

    def _formula_selected(self) -> None:
        if self._loading:
            return
        row = self.formula_table.currentRow()
        names = getattr(self, "_formula_names", [])
        self.formula_edit.setEnabled(0 <= row < len(names))
        text = (
            self.editor.params.get("derived", {}).get(names[row], "")
            if 0 <= row < len(names)
            else ""
        )
        self.formula_edit.blockSignals(True)
        self.formula_edit.setText(str(text))
        self.formula_edit.blockSignals(False)
        self._show_formula_problems()

    def _formula_text_edited(self, text: str) -> None:
        row = self.formula_table.currentRow()
        if not 0 <= row < len(self._formula_names):
            return
        self.editor.set_formula(self._formula_names[row], text)
        self.formula_table.item(row, 1).setText(text)
        self._after_change()

    def _formula_name_edited(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        row = item.row()
        old, new = self._formula_names[row], item.text().strip()
        if new == old:
            return
        try:
            changed = self.editor.rename_formula(old, new)
        except EditorError as exc:
            self._status(str(exc), error=True)
            self._loading = True
            item.setText(old)
            self._loading = False
            return
        if changed:
            self._status(self._t("eff_renamed_formulas", n=len(changed)))
        self._refresh_formulas()
        self.formula_table.selectRow(row)
        self._after_change()

    def _add_formula(self) -> None:
        names = set(self.editor.names()) | set(self.editor.params.get("derived") or {})
        name, n = self._t("eff_new_formula"), 2
        while name in names:
            name, n = f"{self._t('eff_new_formula')}{n}", n + 1
        self.editor.set_formula(name, "")
        self._refresh_formulas()
        self.formula_table.selectRow(self.formula_table.rowCount() - 1)
        self.formula_edit.setFocus()
        self._after_change()

    def _remove_formula(self) -> None:
        row = self.formula_table.currentRow()
        if 0 <= row < len(self._formula_names):
            self.editor.remove_formula(self._formula_names[row])
            self._refresh_formulas()
            self._after_change()

    def _insert_name(self, item) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        if name != "header" and self.formula_edit.isEnabled():
            self.formula_edit.insert(name)
            self._formula_text_edited(self.formula_edit.text())
            self.formula_edit.setFocus()

    def _show_formula_problems(self) -> None:
        self._color_formula_rows()
        row = self.formula_table.currentRow()
        names = getattr(self, "_formula_names", [])
        problems = self.editor.problems_at(f"derived.{names[row]}") if 0 <= row < len(names) else []
        self.formula_message.setText(
            "<br>".join(
                f"<span style='color:{self._color(p)}'>{p.message}</span>" for p in problems
            )
        )
        mark_widget(
            self.formula_edit, self._worst(problems), problems[0].message if problems else ""
        )

    # ================================================================ power tab
    def _refresh_power(self) -> None:
        self.power_list.clear()
        self.power_list.addItems(self.editor.power_order())
        always = [
            v.get("name", "")
            for v in self.editor.variables
            if isinstance(v.get("output"), dict) and v["output"].get("mode") == "always_on"
        ]
        if always:
            self.always_label.setText(self._t("eff_always_list", names=", ".join(always)))
        else:
            managed = bool(self.editor.power_order())
            self.always_label.setText("" if managed else self._t("eff_power_none"))

    def _move_power(self, delta: int) -> None:
        row = self.power_list.currentRow()
        if row >= 0:
            new = self.editor.move_power(row, delta)
            self._refresh_power()
            self.power_list.setCurrentRow(new)
            self._after_change()

    def _reset_power(self) -> None:
        self.editor.reset_power_order()
        self._refresh_power()
        self._after_change()

    def _rebuild_extras(self) -> None:
        self._dynamic = [
            f for f in self._dynamic if not f.path_template.startswith(("startup", "shutdown"))
        ]
        for section, holder in self.extra_boxes.items():
            self._clear_layout(holder)
            for k, block in enumerate(self.editor.calls(section)):
                row = QWidget()
                layout = QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                call = self._dynamic_call(f"{section}[{k}]")
                call.set_value(block)
                remove = QPushButton(self._t("eff_remove"))
                remove.clicked.connect(lambda _c=False, s=section, n=k: self._remove_call(s, n))
                layout.addWidget(call, 1)
                layout.addWidget(remove)
                holder.addWidget(row)

    def _add_call(self, section: str) -> None:
        self.editor.add_call(section)
        self._rebuild_extras()
        self._after_change()

    def _remove_call(self, section: str, index: int) -> None:
        self.editor.remove_call(section, index)
        self._rebuild_extras()
        self._after_change()

    # ================================================================ showing the state
    def _status(self, text: str, error: bool = False) -> None:
        color = self._c("error" if error else "muted")
        self.status_label.setText(f"<span style='color:{color}'>{text}</span>")

    def _refresh_all(self) -> None:
        """Show everything from the model (used when the window opens)."""
        self._loading = True
        for field in self._fields:
            if not field.scoped:
                self._write_field(field, None)
        self._loading = False
        self._refresh_param_list()
        self._refresh_formulas()
        self._refresh_power()
        self._rebuild_extras()
        self._refresh_problems()

    def _after_change(self) -> None:
        """Called after every edit: validate again and update everything that shows the result."""
        self.dirty = True
        self._refresh_param_list()
        self._update_dependent()
        self._refresh_problems()
        self._refresh_power()
        self._show_formula_problems()
        self._apply_marks()

    def _refresh_problems(self) -> None:
        problems = sorted(self.editor.problems(), key=lambda p: p.severity != "error")
        self.problem_tree.clear()
        for problem in problems:
            item = QTreeWidgetItem(
                ["●" if problem.severity == "error" else "▲", problem.path, problem.message]
            )
            color = self._color(problem)
            item.setForeground(0, QBrush(QColor(color)))
            item.setData(0, Qt.ItemDataRole.UserRole, problem.path)
            self.problem_tree.addTopLevelItem(item)
        errors = sum(p.severity == "error" for p in problems)
        warnings = len(problems) - errors
        self.problem_title.setText(self._t("eff_problems_title", errors=errors, warnings=warnings))
        summary = self.editor.summary()
        if summary["valid"]:
            text = self._t(
                "eff_summary_ok",
                points=summary["points"],
                sweeps=summary["sweeps"],
                cooldowns=summary["cooldowns"],
                time=self.editor.format_duration(summary["seconds"]),
            )
            color = self._c("ok")
        else:
            text = self._t("eff_summary_invalid", errors=errors)
            color = self._c("error")
        self.summary_label.setText(f"<span style='color:{color}'>{text}</span>")
        self.timing_summary.setText(text if summary["valid"] else "")
        name = os.path.basename(self.file_path) if self.file_path else self._t("eff_unsaved")
        self.file_label.setText(f"<b>{name}{' *' if self.dirty else ''}</b>")
        self.preview.setPlainText(json.dumps(self.editor.params, indent=2, ensure_ascii=False))
        self.setWindowTitle(f"{self._t('eff_title')} - {name}{' *' if self.dirty else ''}")

    def _apply_marks(self) -> None:
        """Put the red / amber border and the tooltip on every field that has a problem."""
        index = self._current
        problems = self.editor.problems()
        for field in self._fields + self._dynamic:
            if field.scoped and index is None:
                continue
            path = field.path(index)
            if field.kind == "group":
                continue
            if field.kind == "call":
                marks: Dict[str, Any] = {}
                for p in problems:
                    if p.path.startswith(path + "."):
                        key = p.path.split(path + ".", 1)[1]
                        if key in ("instrument", "call", "args") and key not in marks:
                            marks[key] = (p.severity, p.message)
                field.widget.mark(marks)
                continue
            found = [p for p in problems if p.path == path]
            if field.invalid:
                mark_widget(field.widget, "error", self._t("eff_not_a_number"))
            elif found:
                mark_widget(field.widget, self._worst(found), found[0].message)
            else:
                mark_widget(field.widget, None)
        if index is None:
            self.param_messages.setText("")
            return
        own = self.editor.problems_at(f"variables[{index}]")
        self.param_messages.setText(
            "<br>".join(
                f"<span style='color:{self._color(p)}'>"
                f"{'●' if p.severity == 'error' else '▲'} {p.message}</span>"
                for p in own
            )
        )

    # ================================================================ going to a field
    def navigate(self, path: Optional[str]) -> None:
        """Show the tab and the field a problem path points at (``variables[1].set.call``)."""
        if not path:
            return
        match = re.match(r"variables\[(\d+)\]", path)
        if match:
            self.tabs.setCurrentIndex(0)
            self.param_list.setCurrentRow(int(match.group(1)))
            for field in self._fields + self._dynamic:
                if field.kind != "group" and field.path(self._current) == path.rsplit(".", 0)[0]:
                    self._focus(field.widget)
                    return
                if field.kind == "call" and path.startswith(field.path(self._current) + "."):
                    self._focus(field.widget)
                    return
        elif path.startswith("timing"):
            self.tabs.setCurrentIndex(1)
            for field in self._fields:
                if field.path_template == path:
                    self._focus(field.widget)
        elif path.startswith("derived"):
            self.tabs.setCurrentIndex(2)
            name = path.split(".", 1)[1] if "." in path else ""
            if name in self._formula_names:
                self.formula_table.selectRow(self._formula_names.index(name))
                self.formula_edit.setFocus()
        else:  # power_order, startup, shutdown
            self.tabs.setCurrentIndex(3)

    @staticmethod
    def _focus(widget: QWidget) -> None:
        if isinstance(widget, CallEdit):
            widget.call.setFocus()
        else:
            widget.setFocus()

    # ================================================================ saving and closing
    def save(self) -> bool:
        """Write the file. With errors in it the user is asked first. Returns True if saved."""
        if self.editor.has_errors():
            answer = QMessageBox.question(
                self,
                self._t("eff_title"),
                self._t(
                    "eff_save_with_errors",
                    errors=sum(p.severity == "error" for p in self.editor.problems()),
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return False
        path = self.file_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, self._t("eff_save"), "", "Efficiency (*.eff)"
            )
            if not path:
                return False
            if not path.lower().endswith(".eff"):
                path += ".eff"
        try:
            self.editor.save(path)
        except Exception as exc:
            QMessageBox.critical(self, self._t("eff_title"), self._t("eff_save_failed", error=exc))
            return False
        self.file_path, self.dirty = path, False
        self._refresh_problems()
        self._status(self._t("eff_saved"))
        return True

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self.dirty:
            box = QMessageBox.StandardButton
            answer = QMessageBox.question(
                self,
                self._t("eff_title"),
                self._t("eff_unsaved_changes"),
                box.Save | box.Discard | box.Cancel,
            )
            if answer == box.Cancel or (answer == box.Save and not self.save()):
                event.ignore()
                return
        event.accept()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the editor on a file (or a new one) with a few demo instruments."""
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    demo_calls = [
        "set_voltage",
        "set_current",
        "output_on",
        "output_off",
        "measure_voltage",
        "measure_current",
    ]
    dialog = EfficiencyEditorDialog(
        argv[0] if argv else None,
        instruments=["psu1", "psu2", "load", "dmm"],
        catalog=lambda _name: demo_calls,
    )
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
