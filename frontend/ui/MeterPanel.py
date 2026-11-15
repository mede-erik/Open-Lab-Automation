# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Remote-control panel of a multimeter or a datalogger: one row per enabled channel with its
function, range and value, a single reading or a continuous one.

Layout and signal wiring only: the functions offered and the calls sent come from
``ola.meter_controls``; every command goes through ``run(call, **args)`` (the logical calls of
the Remote control tab). The choices made here are sent to the instrument; they do not change
the ``.inst`` file. No SCPI is written here.
"""

from typing import Any, Callable, Dict, List, Mapping, Sequence

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ola import meter_controls as mc

VALUE_STYLE = "QLabel { font-family: 'Courier New', monospace; font-weight: 600; padding: 2px; }"


def _format(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:.2f}"
    if abs(value) >= 1:
        return f"{value:.4f}"
    return f"{value:.6g}"


class MeterPanel(QGroupBox):
    """The channels of one multimeter or datalogger."""

    def __init__(
        self,
        title: str,
        controls: mc.MeterControls,
        channels: Sequence[Mapping[str, Any]],
        run: Callable[..., Any],
        t: Callable[[str], str],
        parent=None,
    ):
        super().__init__(title, parent)
        self.controls = controls
        self.channels = [dict(c) for c in channels]
        self.run = run
        self.t = t
        self.rows: List[Dict[str, Any]] = []
        self._applied = False  # the instrument has the settings shown (sent and unchanged)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        layout = QVBoxLayout(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        if not controls.kind:
            layout.addWidget(QLabel(t("mt_not_supported")))
            return
        if not self.channels:
            layout.addWidget(QLabel(t("mt_no_channel")))
            return

        grid = QGridLayout()
        for column, key in enumerate(("mt_channel", "mt_function", "mt_range", "mt_value")):
            grid.addWidget(QLabel(f"<b>{t(key)}</b>"), 0, column)
        for index, channel in enumerate(self.channels, start=1):
            name = channel.get("measured_variable") or channel.get("name") or f"CH{index}"
            function = QComboBox()
            for f in controls.functions:
                label = t(f"mt_fn_{f.lower().replace(':', '_')}")
                function.addItem(label if not label.startswith("mt_fn_") else f, f)
            start = mc.default_function(controls, channel)
            function.setCurrentIndex(max(0, function.findData(start)))
            range_edit = QLineEdit(str(channel.get("range", "")) if channel.get("range") not in
                                   (None, "", "AUTO") else "")
            range_edit.setPlaceholderText(t("mt_auto"))
            value = QLabel("---")
            value.setStyleSheet(VALUE_STYLE)
            function.currentIndexChanged.connect(self._changed)
            range_edit.textChanged.connect(self._changed)
            grid.addWidget(QLabel(str(name)), index, 0)
            grid.addWidget(function, index, 1)
            grid.addWidget(range_edit, index, 2)
            grid.addWidget(value, index, 3)
            self.rows.append({"function": function, "range": range_edit, "value": value})
        layout.addLayout(grid)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton(t("mt_apply"))
        self.apply_button.clicked.connect(self.apply)
        self.read_button = QPushButton(t("mt_read"))
        self.read_button.clicked.connect(self.read)
        self.continuous = QCheckBox(t("mt_continuous"))
        self.continuous.toggled.connect(self.set_continuous)
        self.interval = QSpinBox()
        self.interval.setRange(1, 600)
        self.interval.setValue(2)
        self.interval.setSuffix(" s")
        self.interval.valueChanged.connect(lambda s: self.timer.setInterval(s * 1000))
        for w in (self.apply_button, self.read_button, self.continuous, self.interval):
            buttons.addWidget(w)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addWidget(self.status)

    # ----- helpers --------------------------------------------------------------------------
    def _changed(self, *_args):
        self._applied = False

    def _settings(self):
        """(function, range) of every row; ``RangeError`` if a range is not a number."""
        return [
            (row["function"].currentData(), mc.parse_range(row["range"].text()))
            for row in self.rows
        ]

    def _datalogger_rows(self, settings):
        return mc.datalogger_rows(self.channels, dict(enumerate(settings)))

    def _send(self, calls):
        for call, args in calls:
            self.run(call, **args)

    def _show(self, index: int, value: Any, function: str):
        number = mc.scaled(value, self.channels[index]) if value is not None else None
        unit = self.channels[index].get("unit") or mc.unit_of(self.controls, function)
        self.rows[index]["value"].setText(
            f"{_format(number)} {unit}".strip() if number is not None else "N/A"
        )

    # ----- actions --------------------------------------------------------------------------
    def apply(self) -> bool:
        """Send the function and range of every row to the instrument."""
        try:
            settings = self._settings()
        except mc.RangeError:
            self.status.setText(self.t("mt_err_range"))
            return False
        try:
            if self.controls.kind == mc.DATALOGGER:
                self._send(mc.datalogger_setup(self._datalogger_rows(settings)))
            elif len(settings) == 1:
                self._send(mc.multimeter_calls(self.controls, *settings[0]))
        except Exception as exc:  # the call error says what went wrong (CALL-xxx, TRN-xxx)
            self.status.setText(self.t("mt_err_call").format(error=exc))
            return False
        self._applied = True
        self.status.setText(self.t("mt_applied"))
        return True

    def read(self) -> bool:
        """Read every row (the settings are sent first if they changed)."""
        try:
            settings = self._settings()
        except mc.RangeError:
            self.status.setText(self.t("mt_err_range"))
            return False
        try:
            if self.controls.kind == mc.DATALOGGER:
                rows = self._datalogger_rows(settings)
                if not self._applied:
                    self._send(mc.datalogger_setup(rows))
                    self._applied = True
                readings = self.run("read_scan")
                for index, value in enumerate(mc.datalogger_values(rows, readings or [])):
                    self._show(index, value, settings[index][0])
            else:
                for index, (function, range_) in enumerate(settings):
                    if len(settings) > 1 or not self._applied:  # one meter, several functions
                        self._send(mc.multimeter_calls(self.controls, function, range_))
                    self._show(index, self.run("read_measurement"), function)
                self._applied = len(settings) == 1
        except Exception as exc:
            self.status.setText(self.t("mt_err_call").format(error=exc))
            return False
        self.status.setText("")
        return True

    def set_continuous(self, on: bool):
        """Read again every few seconds (the interval of the box) while checked."""
        if on:
            self.timer.start(self.interval.value() * 1000)
            self.read()
        else:
            self.timer.stop()

    def _tick(self):
        if not self.read():  # an error stops the continuous reading: it is shown, not repeated
            self.continuous.setChecked(False)

    def stop_reading(self):
        """Stop the continuous reading (when the panel is removed or the tab closes)."""
        self.timer.stop()
        if self.rows:
            self.continuous.setChecked(False)
