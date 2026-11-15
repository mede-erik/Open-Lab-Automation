# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Remote-control panel of one channel of an electronic load.

Layout and signal wiring only: what is shown and which calls are sent come from
``ola.load_controls`` (the calls the model defines in the library), every command goes through
``run(call, **args)`` (the logical calls of the Remote control tab). No SCPI is written here.
"""

from typing import Any, Callable, Dict, Mapping, Optional

from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from ola import load_controls as lc

INPUT_STYLE = """
    QPushButton { padding: 6px; font-weight: bold; background-color: #d32f2f; color: white; }
    QPushButton:checked { background-color: #2e7d32; }
"""


class ElectronicLoadPanel(QGroupBox):
    """Mode and setpoint, input on/off, readings and protections of one load channel."""

    def __init__(
        self,
        title: str,
        controls: lc.LoadControls,
        channel: Mapping[str, Any],
        run: Callable[..., Any],
        t: Callable[[str], str],
        parent=None,
    ):
        super().__init__(title, parent)
        self.controls = controls
        self.channel = channel
        self.number: Optional[int] = lc.channel_number(channel)
        self.run = run
        self.t = t
        self.protection_widgets: Dict[str, Dict[str, Any]] = {}
        form = QFormLayout(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        if not controls.modes:
            form.addRow(QLabel(t("el_not_supported")))
            self.mode_combo = None
            return

        # mode and setpoint
        self.mode_combo = QComboBox()
        for mode in controls.modes:
            self.mode_combo.addItem(t(f"el_mode_{mode.lower()}"), mode)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        form.addRow(t("el_mode"), self.mode_combo)
        row = QHBoxLayout()
        self.setpoint = QLineEdit()
        self.setpoint.setValidator(QDoubleValidator())
        self.unit = QLabel("")
        self.set_button = QPushButton(t("el_set"))
        self.set_button.clicked.connect(self.apply_setpoint)
        row.addWidget(self.setpoint)
        row.addWidget(self.unit)
        row.addWidget(self.set_button)
        holder = QWidget()
        holder.setLayout(row)
        self.setpoint_label = QLabel(t("el_setpoint"))
        form.addRow(self.setpoint_label, holder)
        self._mode_changed()

        # input on/off and readings
        row = QHBoxLayout()
        self.input_button = QPushButton(t("el_input_off"))
        self.input_button.setCheckable(True)
        self.input_button.setStyleSheet(INPUT_STYLE)
        self.input_button.clicked.connect(self.set_input)
        row.addWidget(self.input_button)
        self.read_button = None
        if controls.readings:
            self.read_button = QPushButton(t("el_read"))
            self.read_button.clicked.connect(self.read)
            row.addWidget(self.read_button)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow(holder)
        self.readings_label = QLabel("")
        if controls.readings:
            form.addRow(self.readings_label)

        # protections the model can set
        for kind in controls.protections:
            row = QHBoxLayout()
            enabled = QCheckBox(t("el_enabled"))
            enabled.setChecked(True)
            level = QLineEdit()
            level.setValidator(QDoubleValidator())
            level.setEnabled(controls.has(f"set_{kind}_level"))
            button = QPushButton(t("el_set"))
            button.clicked.connect(lambda _=False, k=kind: self.apply_protection(k))
            row.addWidget(enabled)
            row.addWidget(level)
            row.addWidget(button)
            holder = QWidget()
            holder.setLayout(row)
            form.addRow(t(f"el_{kind}"), holder)
            self.protection_widgets[kind] = {"enabled": enabled, "level": level, "button": button}
        form.addRow(self.status)

    # ----- helpers --------------------------------------------------------------------------
    def _mode_changed(self, *_args):
        mode = self.mode
        self.unit.setText(lc.UNIT.get(mode, ""))
        limit = self.channel.get(lc.LIMIT_KEY.get(mode, ""), 0) or 0
        self.setpoint.setPlaceholderText(f"≤ {limit:g}" if limit else "")

    @property
    def mode(self) -> str:
        return self.mode_combo.currentData() if self.mode_combo is not None else ""

    def _send(self, calls) -> bool:
        try:
            for call, args in calls:
                self.run(call, **args)
        except Exception as exc:  # the call error says what went wrong (CALL-xxx, TRN-xxx)
            self.status.setText(self.t("el_err_call").format(error=exc))
            return False
        return True

    @staticmethod
    def _number(edit: QLineEdit) -> Optional[float]:
        text = edit.text().strip().replace(",", ".")
        return float(text) if text else None

    # ----- actions --------------------------------------------------------------------------
    def apply_setpoint(self) -> bool:
        """Put the channel in the chosen mode with the setpoint typed (checked first)."""
        try:
            value = self._number(self.setpoint)
        except ValueError:
            value = None
        if value is None:
            self.status.setText(self.t("el_err_number"))
            return False
        problems = lc.check_setpoint(self.mode, value, self.channel)
        if problems:
            self.status.setText("\n".join(self.t(p) for p in problems))
            return False
        if self._send(lc.setpoint_calls(self.controls, self.mode, value, self.number)):
            self.status.setText(self.t("el_applied"))
            return True
        return False

    def set_input(self, on: bool) -> bool:
        """Switch the input on or off; the button goes back if the call fails."""
        if self._send(lc.input_calls(self.controls, bool(on), self.number)):
            self.input_button.setText(self.t("el_input_on") if on else self.t("el_input_off"))
            self.status.setText("")
            return True
        self.input_button.setChecked(not on)
        return False

    def read(self) -> bool:
        """Read voltage, current and power (those the model has)."""
        values = []
        try:
            if lc.select_first(self.controls, self.number):
                self.run("select_channel", channel_number=self.number)
            for call, unit in self.controls.readings:
                values.append(f"{float(self.run(call)):.6g} {unit}")
        except Exception as exc:
            self.status.setText(self.t("el_err_call").format(error=exc))
            return False
        self.readings_label.setText("   ".join(values))
        return True

    def apply_protection(self, kind: str) -> bool:
        """Set a protection: its level and enabled, or disabled."""
        w = self.protection_widgets[kind]
        try:
            level = self._number(w["level"])
        except ValueError:
            self.status.setText(self.t("el_err_number"))
            return False
        calls = lc.protection_calls(self.controls, kind, w["enabled"].isChecked(), level, self.number)
        if len(calls) == len(lc.select_first(self.controls, self.number)):
            self.status.setText(self.t("el_err_cannot_disable"))
            return False
        if self._send(calls):
            self.status.setText(self.t("el_applied"))
            return True
        return False
