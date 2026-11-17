# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Remote-control panel of an RF signal generator: the carrier (frequency, power, RF output) and
one box for each modulation the model has (AM, FM, PM, pulse).

Layout and signal wiring only: what is shown, the checks and the calls sent come from
``ola.rf_controls`` (what the model defines in the library); every command goes through
``run(call, **args)`` (the logical calls of the Remote control tab). No SCPI is written here.
"""

from typing import Any, Callable, Dict, Optional

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
    QVBoxLayout,
    QWidget,
)

from ola import rf_controls as rc
from ola.vna_controls import parse_frequency

TOGGLE_STYLE = """
    QPushButton { padding: 6px; font-weight: bold; background-color: #d32f2f; color: white; }
    QPushButton:checked { background-color: #2e7d32; }
"""


class RfGeneratorPanel(QWidget):
    """The carrier and the modulations of one RF signal generator."""

    def __init__(
        self,
        controls: rc.RfControls,
        run: Callable[..., Any],
        t: Callable[[str], str],
        parent=None,
    ):
        super().__init__(parent)
        self.controls, self.run, self.t = controls, run, t
        self.kinds: Dict[str, Dict[str, Any]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        if not controls.usable:
            layout.addWidget(QLabel(t("rf_not_supported")))
            return

        # carrier
        form = QFormLayout()
        c = controls
        hint = ""
        if c.frequency_min is not None and c.frequency_max is not None:
            hint = f" ({c.frequency_min:g} – {c.frequency_max:g} Hz)"
        self.frequency = QLineEdit()
        self.frequency.setPlaceholderText("1G, 433.92M, 100k")
        form.addRow(t("rf_frequency") + hint, self.frequency)
        power_hint = ""
        if c.power_min is not None and c.power_max is not None:
            power_hint = f" ({c.power_min:g} … {c.power_max:g} dBm)"
        self.power = QLineEdit()
        self.power.setValidator(QDoubleValidator())
        self.power.setPlaceholderText("-10")
        form.addRow(t("rf_power") + power_hint, self.power)
        row = QHBoxLayout()
        self.apply_button = QPushButton(t("rf_apply"))
        self.apply_button.clicked.connect(self.apply_carrier)
        self.output_button = QPushButton(t("rf_output_off"))
        self.output_button.setCheckable(True)
        self.output_button.setStyleSheet(TOGGLE_STYLE)
        self.output_button.clicked.connect(self.set_output)
        row.addWidget(self.apply_button)
        row.addWidget(self.output_button)
        form.addRow(row)
        layout.addLayout(form)

        # modulation
        self.master_button: Optional[QPushButton] = None
        if c.kinds:
            if c.has("set_modulation_output_state"):
                self.master_button = QPushButton(t("rf_modulation_off"))
                self.master_button.setCheckable(True)
                self.master_button.setStyleSheet(TOGGLE_STYLE)
                self.master_button.setToolTip(t("rf_modulation_tip"))
                self.master_button.clicked.connect(self.set_master)
                layout.addWidget(self.master_button)
            for info in c.kinds:
                layout.addWidget(self._kind_box(info))
        layout.addWidget(self.status)

    # ----- layout ---------------------------------------------------------------------------
    def _kind_box(self, info: rc.ModulationKind) -> QGroupBox:
        t = self.t
        box = QGroupBox(t(f"rf_kind_{info.kind.lower()}"))
        form = QFormLayout(box)
        w: Dict[str, Any] = {"info": info}
        w["enabled"] = QCheckBox(t("rf_kind_enable"))
        outer = form
        outer.addRow(w["enabled"])
        # the settings of the modulation are shown only when it is enabled: less room is used
        details = QWidget()
        details.setVisible(False)
        w["enabled"].toggled.connect(details.setVisible)
        outer.addRow(details)
        form = QFormLayout(details)  # every setting below goes into the part that shows
        form.setContentsMargins(0, 0, 0, 0)
        if info.sources:
            w["source"] = QComboBox()
            for name in info.sources:
                w["source"].addItem(t(f"rf_source_{name.lower()}"), name)
            w["source"].currentIndexChanged.connect(lambda _i, k=info.kind: self._source_changed(k))
            form.addRow(t("rf_source"), w["source"])
        if info.rate_sources:
            w["rate"] = QLineEdit()
            w["rate"].setPlaceholderText("1k")
            form.addRow(t("rf_rate"), w["rate"])
        if info.depth_call:
            w["depth"] = QLineEdit()
            w["depth"].setValidator(QDoubleValidator())
            label = t("rf_depth") if info.kind == "AM" else t("rf_deviation")
            form.addRow(f"{label} ({info.depth_unit})", w["depth"])
        if info.shapes:
            w["shape"] = QComboBox()
            for name in info.shapes:
                w["shape"].addItem(t(f"rf_shape_{name.lower()}"), name)
            form.addRow(t("rf_shape"), w["shape"])
        if info.couplings:
            w["coupling"] = QComboBox()
            for name in info.couplings:
                w["coupling"].addItem(name, name)
            form.addRow(t("rf_coupling"), w["coupling"])
        w["apply"] = QPushButton(t("rf_apply"))
        w["apply"].clicked.connect(lambda _=False, k=info.kind: self.apply_modulation(k))
        form.addRow(w["apply"])
        self.kinds[info.kind] = w
        self._source_changed(info.kind)
        return box

    def _source_changed(self, kind: str):
        """Only the fields that the chosen source makes useful can be edited."""
        w = self.kinds[kind]
        info = w["info"]
        source = w["source"].currentData() if "source" in w else None
        if "rate" in w:
            w["rate"].setEnabled(source in rc.INTERNAL_SOURCES if source else True)
        if "shape" in w:
            w["shape"].setEnabled(rc.shape_applies(info, source))
        if "coupling" in w:
            w["coupling"].setEnabled(source == "EXTERNAL")

    # ----- helpers --------------------------------------------------------------------------
    def _send(self, calls) -> bool:
        try:
            for call, args in calls:
                self.run(call, **args)
        except Exception as exc:  # the call error says what went wrong (CALL-xxx, TRN-xxx)
            self.status.setText(self.t("rf_err_call").format(error=exc))
            return False
        return True

    @staticmethod
    def _text(edit: Optional[QLineEdit]) -> str:
        return edit.text().strip() if edit is not None else ""

    # ----- actions --------------------------------------------------------------------------
    def apply_carrier(self) -> bool:
        """Send the frequency and the power that are filled in (checked first)."""
        try:
            text = self._text(self.frequency)
            frequency = parse_frequency(text) if text else None
            text = self._text(self.power).replace(",", ".")
            power = float(text) if text else None
        except ValueError:
            self.status.setText(self.t("rf_err_number"))
            return False
        problems = rc.check_carrier(self.controls, frequency, power)
        if problems:
            self.status.setText("\n".join(self.t(p) for p in problems))
            return False
        if self._send(rc.carrier_calls(self.controls, frequency, power)):
            self.status.setText(self.t("rf_applied"))
            return True
        return False

    def set_output(self, on: bool) -> bool:
        """Switch the RF output; the button goes back if the call fails."""
        if self._send(rc.output_calls(bool(on))):
            self.output_button.setText(self.t("rf_output_on") if on else self.t("rf_output_off"))
            self.status.setText("")
            return True
        self.output_button.setChecked(not on)
        return False

    def set_master(self, on: bool) -> bool:
        """Switch all the modulation of the output; the button goes back if the call fails."""
        if self._send(rc.master_calls(self.controls, bool(on))):
            self.master_button.setText(
                self.t("rf_modulation_on") if on else self.t("rf_modulation_off")
            )
            self.status.setText("")
            return True
        self.master_button.setChecked(not on)
        return False

    def apply_modulation(self, kind: str) -> bool:
        """Send the settings of one modulation and its on or off state (checked first)."""
        w = self.kinds[kind]
        try:
            rate_text = self._text(w.get("rate"))
            rate = parse_frequency(rate_text) if rate_text else None
            depth_text = self._text(w.get("depth")).replace(",", ".")
            depth = float(depth_text) if depth_text else None
        except ValueError:
            self.status.setText(self.t("rf_err_number"))
            return False
        problems = rc.check_modulation(rate, depth)
        if problems:
            self.status.setText("\n".join(self.t(p) for p in problems))
            return False
        calls = rc.modulation_calls(
            self.controls,
            kind,
            w["enabled"].isChecked(),
            w["source"].currentData() if "source" in w else None,
            rate,
            depth,
            w["shape"].currentData() if "shape" in w else None,
            w["coupling"].currentData() if "coupling" in w else None,
        )
        if self._send(calls):
            self.status.setText(self.t("rf_applied"))
            return True
        return False
