"""Small widgets and helpers used by the efficiency editor dialog.

* ``CallEdit``: one line to describe a call of an instrument (instrument, call name, arguments).
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
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QWidget

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


def format_number_list(values: Sequence[float]) -> str:
    """``[9, 12.5]`` -> ``"9, 12.5"``."""
    return ", ".join(format_number(v) for v in values)


# ---- marking widgets -------------------------------------------------------------------------


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


# ---- one call of an instrument ---------------------------------------------------------------


class CallEdit(QWidget):
    """Instrument, call name and arguments of one call, on one line.

    ``catalog(instrument)`` may return the call names known for that instrument (from the
    instrument library); the call box stays editable either way. The arguments are typed as a JSON
    object (``{"channel_number": 1}``); while the text is not valid JSON ``args_invalid`` is True.
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
