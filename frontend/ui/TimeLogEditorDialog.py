# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Editor of a time log (``.tlg``): its sources, one per instrument, each at its own interval.

Layout and signal wiring only. The rules (what is a valid source, what a datalogger scan needs)
are the time_log module's own: the window asks it for the problems before saving, and the file is
written with ``MeasurementFile``. The calls offered for a reading come from the instrument
library, so a call that the model does not have cannot be chosen.
"""

import json
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.module_translator import CatalogTranslator
from ola.project import MeasurementFile

DATALOGGER_TYPES = (
    "VOLT:DC", "VOLT:AC", "CURR:DC", "CURR:AC", "RES", "FRES", "FREQ", "PER", "TEMP",
)
TEMPERATURE_TYPE = "TEMP"


def _text(edit: QLineEdit) -> str:
    return edit.text().strip()


def _empty_source(number: int) -> Dict[str, Any]:
    return {"name": f"source{number}", "instrument": "", "interval_s": 60.0,
            "samples": None, "scan": False, "readings": [], "channels": []}


class TimeLogEditorDialog(QDialog):
    """The sources of a time log and its duration; saves the file when it is valid."""

    def __init__(
        self,
        path: str,
        instruments: Mapping[str, Mapping[str, Any]],
        validate: Callable[[Dict[str, Any]], List[str]],
        calls: Callable[[Mapping[str, Any]], Sequence[Any]],
        translator: Any = None,
        parent: Optional[QWidget] = None,
    ):
        """``instruments``: the entries of the ``.inst`` file by name. ``validate(params)``: the
        problems of the parameters (the module's own check). ``calls(entry)``: the readings of an
        instrument's model in the library (``ola.readings.Readable``: name, unit, channel)."""
        super().__init__(parent)
        self.tr_ = CatalogTranslator("timelog", translator)
        self.path = path
        self.instruments = dict(instruments)
        self.validate = validate
        self.calls_of = calls
        exists = self._exists(path)
        self.file = MeasurementFile.load(path) if exists else MeasurementFile("time_log")
        params = self.file.params or {}
        self.duration: Optional[float] = params.get("duration_s")
        self.sources: List[Dict[str, Any]] = [dict(s) for s in params.get("sources", [])]
        self._current = -1
        self._loading = False  # True while the tables are being filled: nothing is stored then
        self.setWindowTitle(self._t("tlg_title"))
        self.resize(900, 620)
        self._build()
        self._fill_sources()

    @staticmethod
    def _exists(path: str) -> bool:
        import os

        return os.path.isfile(path)

    def _t(self, key: str, **values: Any) -> str:
        return self.tr_.t(key, **values)

    # ----- layout ---------------------------------------------------------------------------
    def _build(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(self._t("tlg_duration")))
        self.duration_edit = QLineEdit("" if self.duration is None else f"{self.duration:g}")
        self.duration_edit.setPlaceholderText(self._t("tlg_duration_hint"))
        top.addWidget(self.duration_edit)
        top.addStretch(1)
        root.addLayout(top)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel(self._t("tlg_sources")))
        self.source_list = QListWidget()
        self.source_list.currentRowChanged.connect(self._select)
        left.addWidget(self.source_list, 1)
        row = QHBoxLayout()
        add = QPushButton(self._t("tlg_add"))
        add.clicked.connect(self._add_source)
        remove = QPushButton(self._t("tlg_remove"))
        remove.clicked.connect(self._remove_source)
        row.addWidget(add)
        row.addWidget(remove)
        left.addLayout(row)
        body.addLayout(left, 1)

        self.detail = QGroupBox()
        form = QFormLayout(self.detail)
        self.name_edit = QLineEdit()
        form.addRow(self._t("tlg_name"), self.name_edit)
        self.instrument_combo = QComboBox()
        self.instrument_combo.addItem("", "")
        for name in self.instruments:
            self.instrument_combo.addItem(name, name)
        self.instrument_combo.currentIndexChanged.connect(self._instrument_changed)
        form.addRow(self._t("tlg_instrument"), self.instrument_combo)
        self.interval_edit = QLineEdit()
        form.addRow(self._t("tlg_interval"), self.interval_edit)
        self.samples_edit = QLineEdit()
        self.samples_edit.setPlaceholderText(self._t("tlg_samples_hint"))
        form.addRow(self._t("tlg_samples"), self.samples_edit)
        self.scan_check = QCheckBox(self._t("tlg_scan"))
        self.scan_check.setToolTip(self._t("tlg_scan_tip"))
        self.scan_check.toggled.connect(self._scan_toggled)
        form.addRow("", self.scan_check)

        self.readings_label = QLabel(self._t("tlg_readings"))
        self.readings = QTableWidget(0, 4)
        self.readings.itemChanged.connect(lambda _item: self._store())
        self.readings.setHorizontalHeaderLabels([
            self._t("tlg_col_name"), self._t("tlg_col_call"), self._t("tlg_col_channel"),
            self._t("tlg_col_args"),
        ])
        self._readable: Dict[str, Any] = {}  # the readings of the chosen instrument, by call
        self.readings_add = QPushButton(self._t("tlg_add_reading"))
        self.readings_add.clicked.connect(lambda: self._add_row(self.readings))
        self.readings_del = QPushButton(self._t("tlg_remove_row"))
        self.readings_del.clicked.connect(lambda: self._remove_row(self.readings))
        form.addRow(self.readings_label, self.readings)
        form.addRow(self._row_widget(self.readings_add, self.readings_del))

        self.channels_label = QLabel(self._t("tlg_channels"))
        self.channels = QTableWidget(0, 6)
        self.channels.itemChanged.connect(lambda _item: self._store())
        self.channels.setHorizontalHeaderLabels([
            self._t("tlg_col_name"), self._t("tlg_col_channel"), self._t("tlg_col_type"),
            self._t("tlg_col_range"), self._t("tlg_col_probe"), self._t("tlg_col_sensor"),
        ])
        self.channels_add = QPushButton(self._t("tlg_add_channel"))
        self.channels_add.clicked.connect(lambda: self._add_row(self.channels))
        self.channels_del = QPushButton(self._t("tlg_remove_row"))
        self.channels_del.clicked.connect(lambda: self._remove_row(self.channels))
        form.addRow(self.channels_label, self.channels)
        form.addRow(self._row_widget(self.channels_add, self.channels_del))
        body.addWidget(self.detail, 2)
        root.addLayout(body, 1)

        self.problems = QLabel("")
        self.problems.setWordWrap(True)
        root.addWidget(self.problems)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton(self._t("tlg_save"))
        save.clicked.connect(self.save)
        cancel = QPushButton(self._t("tlg_cancel"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

    @staticmethod
    def _row_widget(*buttons: QPushButton) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        for button in buttons:
            row.addWidget(button)
        row.addStretch(1)
        return holder

    # ----- the list of sources ---------------------------------------------------------------
    def _fill_sources(self) -> None:
        self.source_list.blockSignals(True)
        self.source_list.clear()
        for source in self.sources:
            self.source_list.addItem(self._title(source))
        self.source_list.blockSignals(False)
        self.source_list.setCurrentRow(0 if self.sources else -1)

    def _title(self, source: Mapping[str, Any]) -> str:
        name = source.get("name") or "?"
        instrument = source.get("instrument") or "-"
        return f"{name}  ({instrument})"

    def _add_source(self) -> None:
        self._store()
        self.sources.append(_empty_source(len(self.sources) + 1))
        self._fill_sources()
        self.source_list.setCurrentRow(len(self.sources) - 1)

    def _remove_source(self) -> None:
        row = self.source_list.currentRow()
        if row < 0:
            return
        self._current = -1  # what is shown is dropped with the source
        del self.sources[row]
        self._fill_sources()

    def _select(self, row: int) -> None:
        self._store()
        self._current = row
        self._show(self.sources[row] if 0 <= row < len(self.sources) else None)

    # ----- one source ------------------------------------------------------------------------
    def _show(self, source: Optional[Mapping[str, Any]]) -> None:
        self.detail.setEnabled(source is not None)
        if source is None:
            return
        self._loading = True
        self.name_edit.setText(str(source.get("name", "")))
        index = self.instrument_combo.findData(source.get("instrument", ""))
        self.instrument_combo.setCurrentIndex(max(index, 0))
        interval = source.get("interval_s")
        self.interval_edit.setText("" if interval is None else f"{float(interval):g}")
        samples = source.get("samples")
        self.samples_edit.setText("" if samples is None else str(samples))
        self.scan_check.setChecked(bool(source.get("scan")))
        self._fill_rows(self.readings, [
            [r.get("name", ""), r.get("call", ""),
             "" if r.get("channel") is None else str(r["channel"]), _dump(r.get("args"))]
            for r in source.get("readings", [])
        ])
        self._fill_rows(self.channels, [
            [c.get("name", ""), c.get("channel_id", ""), c.get("meas_type", "VOLT:DC"),
             c.get("range", ""), c.get("probe_type", ""), c.get("sensor_type", "")]
            for c in source.get("channels", [])
        ])
        self._loading = False
        self._scan_toggled(self.scan_check.isChecked())
        self._instrument_changed()

    def _scan_toggled(self, scan: bool) -> None:
        for widget in (self.readings_label, self.readings, self.readings_add, self.readings_del):
            widget.setVisible(not scan)
        for widget in (self.channels_label, self.channels, self.channels_add, self.channels_del):
            widget.setVisible(scan)
        self._store()

    def _instrument_changed(self, *_args) -> None:
        """The calls offered for a reading are the readings of the chosen instrument's model."""
        entry = self.instruments.get(self.instrument_combo.currentData() or "")
        offered = list(self.calls_of(entry)) if entry else []
        self._readable = {getattr(r, "name", str(r)): r for r in offered}
        for row in range(self.readings.rowCount()):
            combo = self.readings.cellWidget(row, 1)
            if isinstance(combo, QComboBox):
                current = _call_of(combo)
                combo.blockSignals(True)
                combo.clear()
                for name, reading in self._readable.items():
                    unit = getattr(reading, "unit", "")
                    combo.addItem(f"{name} ({unit})" if unit else name, name)
                self._set_call(combo, current)
                combo.blockSignals(False)
        self._store()

    @staticmethod
    def _set_call(combo: QComboBox, call: str) -> None:
        """Show a call: the entry of the list if it is there, otherwise the text as it is."""
        index = combo.findData(call) if call else -1
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setEditText(call)

    def _call_changed(self, row: int) -> None:
        """A reading that takes a channel starts with channel 1 (an empty channel would fail)."""
        combo = self.readings.cellWidget(row, 1)
        reading = self._readable.get(_call_of(combo)) if isinstance(combo, QComboBox) else None
        if reading is not None and getattr(reading, "channel", False):
            item = self.readings.item(row, 2)
            if item is not None and not item.text().strip():
                item.setText("1")
        self._store()

    def _fill_rows(self, table: QTableWidget, rows: List[List[str]]) -> None:
        table.setRowCount(0)
        for values in rows:
            self._add_row(table, values)

    def _add_row(self, table: QTableWidget, values: Optional[List[str]] = None) -> None:
        row = table.rowCount()
        table.insertRow(row)
        values = values or [""] * table.columnCount()
        if table is self.channels:
            combo = QComboBox()
            combo.addItems(DATALOGGER_TYPES)
            combo.setCurrentText(values[2] or "VOLT:DC")
            combo.currentTextChanged.connect(lambda _t: self._store())
            table.setCellWidget(row, 2, combo)
            values = [values[0], values[1], None, values[3], values[4], values[5]]
        if table is self.readings:
            combo = QComboBox()
            combo.setEditable(True)
            combo.setEditText(values[1])
            combo.currentTextChanged.connect(lambda _t, r=row: self._call_changed(r))
            table.setCellWidget(row, 1, combo)
            values = [values[0], None, values[2], values[3]]
            if not self._loading:
                self._instrument_changed()
        for column, value in enumerate(values):
            if value is not None:
                table.setItem(row, column, QTableWidgetItem(str(value)))

    def _remove_row(self, table: QTableWidget) -> None:
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)
            self._store()

    def _store(self) -> None:
        """Copy what the window shows into the source it is about (the model of the file)."""
        if self._loading or self._current < 0 or self._current >= len(self.sources):
            return
        source = self.sources[self._current]
        source["name"] = _text(self.name_edit)
        source["instrument"] = self.instrument_combo.currentData() or ""
        source["interval_s"] = _number(_text(self.interval_edit))
        source["samples"] = _count(_text(self.samples_edit))
        source["scan"] = self.scan_check.isChecked()
        source["readings"] = [
            {"name": self._cell(self.readings, row, 0),
             "call": _call_of(self.readings.cellWidget(row, 1)),
             **({"channel": _channel(self._cell(self.readings, row, 2))}
                if self._cell(self.readings, row, 2) else {}),
             **({"args": _load(self._cell(self.readings, row, 3))}
                if self._cell(self.readings, row, 3) else {})}
            for row in range(self.readings.rowCount())
        ]
        source["channels"] = [
            _drop_empty({
                "name": self._cell(self.channels, row, 0),
                "channel_id": self._cell(self.channels, row, 1),
                "meas_type": self._combo(self.channels, row, 2),
                "range": self._cell(self.channels, row, 3),
                "probe_type": self._cell(self.channels, row, 4),
                "sensor_type": self._cell(self.channels, row, 5),
            })
            for row in range(self.channels.rowCount())
        ]
        self.source_list.blockSignals(True)
        item = self.source_list.item(self._current)
        if item is not None:
            item.setText(self._title(source))
        self.source_list.blockSignals(False)

    @staticmethod
    def _cell(table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item is not None else ""

    @staticmethod
    def _combo(table: QTableWidget, row: int, column: int) -> str:
        widget = table.cellWidget(row, column)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return ""

    # ----- the parameters and the file -------------------------------------------------------
    def params(self) -> Dict[str, Any]:
        """The parameters as the file keeps them (the duration only if one is typed)."""
        self._store()
        params: Dict[str, Any] = {"sources": [_clean_source(s) for s in self.sources]}
        duration = _number(_text(self.duration_edit))
        if duration is not None:
            params["duration_s"] = duration
        return params

    def save(self) -> bool:
        """Check the parameters with the module and write the file if they are valid."""
        params = self.params()
        try:
            problems = self.validate(params)
        except Exception as exc:  # the module refuses what it cannot read: say why
            problems = [str(exc)]
        if problems:
            self.problems.setText("\n".join(self._t("tlg_problem", text=text) for text in problems))
            return False
        self.file.params = params
        self.file.save(self.path)
        self.accept()
        return True


def _call_of(widget: Any) -> str:
    """The call a reading's combo shows: the list entry's call, or the text typed."""
    if not isinstance(widget, QComboBox):
        return ""
    text = widget.currentText().strip()
    data = widget.currentData()
    return data if data and widget.itemText(widget.currentIndex()) == widget.currentText() else text


def _channel(text: str) -> Any:
    try:
        return int(text)
    except ValueError:
        return text  # not a number: the module says so


def _number(text: str) -> Optional[float]:
    try:
        return float(text.replace(",", ".")) if text else None
    except ValueError:
        return None  # the module says the value is not a number


def _count(text: str) -> Optional[Any]:
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text  # not a number: the module says so


def _dump(args: Any) -> str:
    return json.dumps(args, ensure_ascii=False) if args else ""


def _load(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text  # not JSON: the module says the arguments must be an object


def _clean_source(source: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "name": source.get("name", ""),
        "instrument": source.get("instrument", ""),
        "interval_s": source.get("interval_s"),
    }
    if source.get("samples") is not None:
        out["samples"] = source["samples"]
    if source.get("scan"):
        out["scan"] = True
        out["channels"] = list(source.get("channels", []))
    else:
        out["readings"] = list(source.get("readings", []))
    return out


def _drop_empty(values: Mapping[str, str]) -> Dict[str, str]:
    return {k: v for k, v in values.items() if v}
