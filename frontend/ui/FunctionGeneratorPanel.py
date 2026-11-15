# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Remote-control panel of a function generator: one box per output channel.

Layout and signal wiring only: what is shown comes from ``ola.control_panels`` (the calls the
model defines in the library), the values are checked there, and every command goes through
``run(channel_number, call, **args)`` (the logical calls of the Remote control tab). No SCPI is
written here.
"""

from typing import Any, Callable, Dict

from PyQt6.QtGui import QDoubleValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ola.control_panels import FunctionGeneratorControls, check_function_generator

OUTPUT_STYLE = """
    QPushButton { padding: 6px; font-weight: bold; background-color: #d32f2f; color: white; }
    QPushButton:checked { background-color: #2e7d32; }
"""


class FunctionGeneratorPanel(QWidget):
    """The channels of one function generator, with the controls its model supports."""

    def __init__(
        self,
        controls: FunctionGeneratorControls,
        run: Callable[..., Any],
        t: Callable[[str], str],
        parent=None,
    ):
        super().__init__(parent)
        self.controls = controls
        self.run = run
        self.t = t
        self.channels: Dict[int, Dict[str, Any]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if not controls.calls:
            layout.addWidget(QLabel(t("fg_not_supported")))
            return
        for number in range(1, controls.channels + 1):
            layout.addWidget(self._channel_box(number))

    # ----- layout ---------------------------------------------------------------------------
    def _number_edit(self, placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setValidator(QDoubleValidator())
        return edit

    def _channel_box(self, number: int) -> QGroupBox:
        t, c = self.t, self.controls
        box = QGroupBox(t("fg_channel").format(n=number))
        form = QFormLayout()
        widgets: Dict[str, Any] = {}
        if c.has("set_waveform_shape") and c.shapes:
            shape = QComboBox()
            for name in c.shapes:
                label = t(f"fg_shape_{name.lower()}")
                shape.addItem(label if not label.startswith("fg_shape_") else name, name)
            form.addRow(t("fg_waveform"), shape)
            widgets["shape"] = shape
        if c.has("set_frequency"):
            limit = f" (≤ {c.frequency_max:g} Hz)" if c.frequency_max else ""
            widgets["frequency"] = self._number_edit("1000")
            form.addRow(t("fg_frequency") + limit, widgets["frequency"])
        if c.has("set_amplitude"):
            widgets["amplitude"] = self._number_edit("1.0")
            form.addRow(t("fg_amplitude"), widgets["amplitude"])
        if c.has("set_offset"):
            widgets["offset"] = self._number_edit("0.0")
            form.addRow(t("fg_offset"), widgets["offset"])
        buttons = QHBoxLayout()
        apply_button = QPushButton(t("fg_apply"))
        apply_button.clicked.connect(lambda _=False, n=number: self.apply(n))
        buttons.addWidget(apply_button)
        widgets["apply"] = apply_button
        if c.has("set_output_state"):
            output = QPushButton(t("fg_output_off"))
            output.setCheckable(True)
            output.setStyleSheet(OUTPUT_STYLE)
            output.clicked.connect(lambda checked, n=number: self.set_output(n, checked))
            buttons.addWidget(output)
            widgets["output"] = output
        form.addRow(buttons)
        status = QLabel("")
        status.setWordWrap(True)
        form.addRow(status)
        widgets["status"] = status
        box.setLayout(form)
        self.channels[number] = widgets
        return box

    # ----- actions --------------------------------------------------------------------------
    @staticmethod
    def _value(widgets: Dict[str, Any], key: str):
        edit = widgets.get(key)
        text = edit.text().strip().replace(",", ".") if edit is not None else ""
        return float(text) if text else None

    def apply(self, number: int) -> bool:
        """Send the waveform and the values typed in the box of a channel (empty fields are
        left as they are on the instrument). True if everything was sent."""
        w = self.channels[number]
        try:
            frequency = self._value(w, "frequency")
            amplitude = self._value(w, "amplitude")
            offset = self._value(w, "offset")
        except ValueError:
            w["status"].setText(self.t("fg_err_number"))
            return False
        problems = check_function_generator(self.controls, frequency, amplitude)
        if problems:
            w["status"].setText("\n".join(self.t(p) for p in problems))
            return False
        calls = []
        if "shape" in w:
            calls.append(("set_waveform_shape", {"shape": w["shape"].currentData()}))
        for call, value in (
            ("set_frequency", frequency),
            ("set_amplitude", amplitude),
            ("set_offset", offset),
        ):
            if value is not None:
                calls.append((call, {"value": value}))
        try:
            for call, args in calls:
                self.run(number, call, **args)
        except Exception as exc:  # the call error says what went wrong (CALL-xxx, TRN-xxx)
            w["status"].setText(self.t("fg_err_call").format(error=exc))
            return False
        w["status"].setText(self.t("fg_applied"))
        return True

    def set_output(self, number: int, on: bool) -> bool:
        """Switch the output of a channel; the button goes back if the call fails."""
        w = self.channels[number]
        button = w["output"]
        try:
            self.run(number, "set_output_state", state=bool(on))
        except Exception as exc:
            button.setChecked(not on)
            w["status"].setText(self.t("fg_err_call").format(error=exc))
            return False
        button.setText(self.t("fg_output_on") if on else self.t("fg_output_off"))
        w["status"].setText("")
        return True
