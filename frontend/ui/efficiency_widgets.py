# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Small widgets and helpers used by the efficiency editor dialog.

* ``CallEdit``: one line to describe a call of an instrument (instrument, call name, arguments);
  the arguments can be typed as JSON or edited in a table (``ArgsDialog``).
* ``ValuesTable``: a list of numbers (the values of a sweep) edited in a table, one per row.
* ``parse_number`` / ``parse_number_list`` / ``format_number``: read and write numbers typed by
  the user without losing precision.
* ``mark_widget``: draw a widget with a red (error) or amber (warning) border and a tooltip, which
  is how the live validation shows *where* the problem is.
"""

import json
import math
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

ERROR_COLOR = "#d32f2f"
WARNING_COLOR = "#f9a825"


# ---- numbers ---------------------------------------------------------------------------------


def parse_number(text: str, integer: bool = False) -> Tuple[bool, Optional[float]]:
    """``(True, value)`` for a number, ``(True, None)`` for an empty text, ``(False, None)`` if the
    text is not a finite number. ``integer=True`` also refuses numbers with a fraction. A comma
    between digits (``0,5``) is read as a decimal comma."""
    text = text.strip()
    if not text:
        return True, None
    if re.fullmatch(r"[+-]?\d+,\d+", text):
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return False, None
    if not math.isfinite(value):
        return False, None
    if integer:
        return (True, int(value)) if value == int(value) else (False, None)
    return True, (int(value) if re.fullmatch(r"[+-]?\d+", text) else value)


def parse_number_list(text: str) -> Optional[List[float]]:
    """``"9, 12; 15"`` -> ``[9, 12, 15]`` (separators: comma, semicolon, spaces; the decimal mark is
    the point). ``None`` if any item is not a number. An empty text gives ``[]``."""
    out: List[float] = []
    for item in [t for t in re.split(r"[,;\s]+", text.strip()) if t]:
        ok, value = parse_number(item)
        if not ok or value is None or "," in item:
            return None
        out.append(value)
    return out


def format_number(value: object) -> str:
    """A number as short text that reads back to the same value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "" if value is None else str(value)
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def format_number_list(values: Sequence[float], digits: Optional[int] = None) -> str:
    """``[9, 12.5]`` -> ``"9, 12.5"``. With ``digits`` the numbers are rounded to that many
    significant digits, for showing (``0.6000000000000001`` -> ``0.6``); without, each one reads
    back to the same value."""
    if digits is None:
        return ", ".join(format_number(v) for v in values)
    return ", ".join(format_number(float(f"{v:.{digits}g}")) for v in values)


# ---- marking widgets -------------------------------------------------------------------------


def text_color(kind: str, widget: Optional[QWidget] = None) -> str:
    """Colour of a coloured *text* (``error``, ``warning``, ``ok``, ``muted``) that is readable on
    the current theme: brighter on a dark background, darker on a light one."""
    app = QApplication.instance()
    declared = app.property("ola_dark_theme") if app is not None else None  # see main_window
    if declared is not None:
        dark = bool(declared)
    else:  # no theme was applied: the palette decides
        dark = (widget or app).palette().window().color().lightness() < 128
    light_theme = {"error": "#c62828", "warning": "#b26a00", "ok": "#2e7d32", "muted": "#666666"}
    dark_theme = {"error": "#ff6b6b", "warning": "#ffb74d", "ok": "#81c784", "muted": "#a0a0a0"}
    return (dark_theme if dark else light_theme)[kind]


def mark_widget(widget: QWidget, severity: Optional[str], message: str = "") -> None:
    """Show or clear a problem on a widget: red border for an error, amber for a warning."""
    if severity is None:
        widget.setStyleSheet("")
        widget.setToolTip("")
        return
    color = ERROR_COLOR if severity == "error" else WARNING_COLOR
    kind = (
        type(widget).__name__ if type(widget).__name__ in ("QLineEdit", "QComboBox") else "QWidget"
    )
    widget.setStyleSheet(f"{kind} {{ border: 1px solid {color}; }}")
    widget.setToolTip(message)


# ---- a list of numbers in a table ------------------------------------------------------------


class ValuesTable(QWidget):
    """The values of a sweep, one per row, with add / remove buttons. It reads and writes the same
    text as a line (``"9, 12, 15"``) so that it can stand in for the line edit of a list: ``text``,
    ``setText`` and the ``textChanged`` signal."""

    textChanged = pyqtSignal(str)

    def __init__(self, labels: Optional[Dict[str, str]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        texts = labels or {}
        self._busy = False
        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels([texts.get("value", "")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMaximumHeight(150)
        self.table.itemChanged.connect(lambda _item: self._emit())
        add = QPushButton(texts.get("add", "+"))
        add.clicked.connect(self.add_row)
        remove = QPushButton(texts.get("remove", "-"))
        remove.clicked.connect(self.remove_selected)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

    def text(self) -> str:
        """The values as one line, in row order (empty rows are left out)."""
        cells = (self.table.item(r, 0) for r in range(self.table.rowCount()))
        return ", ".join(c.text().strip() for c in cells if c is not None and c.text().strip())

    def setText(self, text: str) -> None:  # noqa: N802 (the name of QLineEdit.setText)
        """Show the values of a line (emits ``textChanged`` if they changed, like a line edit)."""
        before = self.text()
        self._busy = True
        items = [t for t in re.split(r"[,;\s]+", text.strip()) if t]
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(item))
        self._busy = False
        if self.text() != before:
            self.textChanged.emit(self.text())

    def add_row(self, value: str = "") -> None:
        """A new row at the end (after the selected one if there is one), ready to type in."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(value if isinstance(value, str) else ""))
        self.table.setCurrentCell(row, 0)
        self.table.editItem(self.table.item(row, 0))
        self._emit()

    def remove_selected(self) -> None:
        """Remove the selected rows."""
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._emit()

    def _emit(self) -> None:
        if not self._busy:
            self.textChanged.emit(self.text())


# ---- the arguments of a call in a table ------------------------------------------------------


class ArgsDialog(QDialog):
    """The arguments of a call as a table of name and value (a number, ``true`` / ``false`` or
    text), so that no JSON has to be typed."""

    def __init__(
        self,
        args: Optional[dict],
        labels: Optional[Dict[str, str]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        texts = labels or {}
        self.setWindowTitle(texts.get("title", ""))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([texts.get("name", ""), texts.get("value", "")])
        self.table.horizontalHeader().setStretchLastSection(True)
        for name, value in (args or {}).items():
            self.add_row(str(name), self._show(value))
        add = QPushButton(texts.get("add", "+"))
        add.clicked.connect(lambda: self.add_row())
        remove = QPushButton(texts.get("remove", "-"))
        remove.clicked.connect(self.remove_selected)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(row)
        layout.addWidget(buttons)

    @staticmethod
    def _show(value: object) -> str:
        return value if isinstance(value, str) else json.dumps(value)

    @staticmethod
    def _parse(text: str) -> object:
        """``4`` -> 4, ``true`` -> True, ``1.5`` -> 1.5; anything else stays text."""
        try:
            value = json.loads(text)
        except ValueError:
            return text
        return value if isinstance(value, (int, float, bool)) else text

    def add_row(self, name: str = "", value: str = "") -> None:
        """A new row."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(value))

    def remove_selected(self) -> None:
        """Remove the selected rows."""
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)

    def args(self) -> dict:
        """The arguments of the table (rows without a name are left out)."""
        out: dict = {}
        for row in range(self.table.rowCount()):
            name = (self.table.item(row, 0).text() if self.table.item(row, 0) else "").strip()
            cell = self.table.item(row, 1)
            if name:
                out[name] = self._parse(cell.text().strip() if cell else "")
        return out


# ---- one call of an instrument ---------------------------------------------------------------


class CallEdit(QWidget):
    """Instrument, call name and arguments of one call, on one line.

    ``catalog(instrument)`` may return the call names known for that instrument (from the
    instrument library); the call box stays editable either way. The arguments can be edited in a
    table (the ``...`` button) or typed as a JSON object (``{"channel_number": 1}``); while the text
    is not valid JSON ``args_invalid`` is True.
    """

    changed = pyqtSignal()

    def __init__(
        self,
        instruments: Sequence[str] = (),
        catalog: Optional[Callable[[str], Sequence[str]]] = None,
        placeholders: Optional[Dict[str, str]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._catalog = catalog
        self.args_invalid = False
        texts = placeholders or {}
        self._texts = texts
        self.instrument = QComboBox()
        self.instrument.setEditable(True)
        self.instrument.setMinimumWidth(90)
        self.instrument.lineEdit().setPlaceholderText(texts.get("instrument", ""))
        self.call = QComboBox()
        self.call.setEditable(True)
        self.call.setMinimumWidth(140)
        self.call.lineEdit().setPlaceholderText(texts.get("call", ""))
        self.args = QLineEdit()
        self.args.setPlaceholderText(texts.get("args", ""))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.instrument, 2)
        layout.addWidget(self.call, 3)
        layout.addWidget(self.args, 3)
        self.args_button = QPushButton("...")
        self.args_button.setFixedWidth(32)
        self.args_button.setToolTip(texts.get("args_title", ""))
        self.args_button.clicked.connect(self.edit_args)
        layout.addWidget(self.args_button)
        self.set_instruments(instruments)
        self.instrument.currentTextChanged.connect(self._instrument_changed)
        self.call.currentTextChanged.connect(lambda _: self.changed.emit())
        self.args.textChanged.connect(self._args_changed)

    # ----- reading and writing the value -------------------------------------------------------
    def value(self) -> Optional[dict]:
        """The call as a dictionary, or ``None`` if every part is empty. With invalid argument text
        the arguments are left out (``args_invalid`` tells)."""
        out: dict = {}
        if self.instrument.currentText().strip():
            out["instrument"] = self.instrument.currentText().strip()
        if self.call.currentText().strip():
            out["call"] = self.call.currentText().strip()
        text = self.args.text().strip()
        self.args_invalid = False
        if text:
            try:
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise ValueError("not an object")
                if parsed:
                    out["args"] = parsed
            except ValueError:
                self.args_invalid = True
        return out or None

    def set_value(self, value: Optional[dict]) -> None:
        """Show a call without emitting ``changed``."""
        value = value if isinstance(value, dict) else {}
        for widget in (self.instrument, self.call, self.args):
            widget.blockSignals(True)
        self.instrument.setCurrentText(str(value.get("instrument", "")))
        self._fill_calls()
        self.call.setCurrentText(str(value.get("call", "")))
        args = value.get("args")
        self.args.setText(json.dumps(args, separators=(", ", ": ")) if args else "")
        for widget in (self.instrument, self.call, self.args):
            widget.blockSignals(False)
        self.args_invalid = False
        self.args.setStyleSheet("")

    def edit_args(self) -> None:
        """Edit the arguments in a table; the line shows the result."""
        current = (self.value() or {}).get("args") or {}
        dialog = ArgsDialog(current, self._texts, self)
        if dialog.exec():
            args = dialog.args()
            self.args.setText(json.dumps(args, separators=(", ", ": ")) if args else "")

    def set_instruments(self, names: Sequence[str]) -> None:
        """The instruments offered in the first box."""
        current = self.instrument.currentText()
        self.instrument.blockSignals(True)
        self.instrument.clear()
        self.instrument.addItems(list(names))
        self.instrument.setCurrentText(current)
        self.instrument.blockSignals(False)

    # ----- internals ---------------------------------------------------------------------------
    def _fill_calls(self) -> None:
        current = self.call.currentText()
        self.call.blockSignals(True)
        self.call.clear()
        if self._catalog is not None:
            try:
                self.call.addItems(list(self._catalog(self.instrument.currentText().strip())))
            except Exception:  # a broken catalog must not break the editor
                pass
        self.call.setCurrentText(current)
        self.call.blockSignals(False)

    def _instrument_changed(self, _text: str) -> None:
        self._fill_calls()
        self.changed.emit()

    def _args_changed(self, _text: str) -> None:
        self.value()  # refreshes args_invalid
        self.changed.emit()

    # ----- showing problems --------------------------------------------------------------------
    def mark(self, marks: Dict[str, Tuple[Optional[str], str]]) -> None:
        """``{"instrument"|"call"|"args": (severity or None, message)}``; other keys are cleared."""
        for key, widget in (
            ("instrument", self.instrument),
            ("call", self.call),
            ("args", self.args),
        ):
            severity, message = marks.get(key, (None, ""))
            if key == "args" and self.args_invalid:
                severity, message = "error", "not a valid JSON object"
            mark_widget(widget, severity, message)
