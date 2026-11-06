"""Parts of the instrument file editor for the settings of one instrument entry.

``InstrumentConfigDialog`` shows one of these panels below the common fields of an entry. Each
panel edits the entry (a dict of the ``.inst`` file, see ``ola.inst_file``) in place and calls
``on_change()`` after every valid change, so the dialog saves the file and shows the problems
again. A value that cannot be read is not stored: the field turns red and the problems list
of the dialog says why.

* ``NetworkAnalyzerPanel``: ports (number, enabled, name) and the usual sweep of a VNA.
* ``SerialPanel``: RS-232 settings that differ from the ones of the library.
* ``SwitchUnitPanel``: the module in each slot of a switch unit.
"""

from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ola import inst_file as inst
from ola.vna_calibration_flow import parse_frequency

BAD_STYLE = "border: 1px solid #b00020;"
HINT_STYLE = "color: #555;"


def _mark(field: QLineEdit, ok: bool) -> None:
    """Red border while the text of ``field`` cannot be used."""
    field.setStyleSheet("" if ok else BAD_STYLE)


class NetworkAnalyzerPanel(QWidget):
    """Ports and sweep of a network analyzer (``num_ports``, ``ports``, ``sweep``)."""

    def __init__(
        self,
        entry: Dict[str, Any],
        caps: Optional[Dict[str, Any]],
        translator: Any,
        on_change: Callable[[], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.entry, self.caps, self.on_change = entry, caps or {}, on_change
        self.t = translator.t
        options = inst.port_options(self.caps)
        if not entry.get("ports"):
            inst.resize_ports(entry, options[0])
        if not entry.get("sweep"):
            entry["sweep"] = inst.default_sweep(self.caps)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._ports_group(options))
        layout.addWidget(self._sweep_group())

    # ---- ports -----------------------------------------------------------------------------
    def _ports_group(self, options: List[int]) -> QGroupBox:
        group = QGroupBox(self.t("inst_ports"))
        layout = QVBoxLayout(group)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.t("inst_num_ports")))
        self.count = QComboBox()
        current = int(self.entry.get("num_ports") or options[0])
        for n in sorted(set(options) | {current}):
            self.count.addItem(str(n), n)
        self.count.setCurrentIndex(self.count.findData(current))
        self.count.setEnabled(len(options) > 1)
        self.count.currentIndexChanged.connect(self._count_changed)
        row.addWidget(self.count)
        row.addStretch(1)
        layout.addLayout(row)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self.t("inst_col_port"), self.t("inst_col_enabled"), self.t("inst_col_name")]
        )
        layout.addWidget(self.table)
        self._fill_ports()
        return group

    def _fill_ports(self) -> None:
        ports = self.entry["ports"]
        self.table.setRowCount(len(ports))
        for row, port in enumerate(ports):
            self.table.setCellWidget(row, 0, QLabel(f" {port['port']} "))
            check = QCheckBox()
            check.setChecked(bool(port.get("enabled")))
            check.toggled.connect(lambda on, p=port: self._set_port(p, "enabled", bool(on)))
            self.table.setCellWidget(row, 1, check)
            name = QLineEdit(str(port.get("name", "")))
            name.textChanged.connect(lambda text, p=port: self._set_port(p, "name", text))
            self.table.setCellWidget(row, 2, name)
        self.table.resizeColumnsToContents()
        self.table.setMaximumHeight(34 + 30 * max(len(ports), 1))

    def _set_port(self, port: Dict[str, Any], key: str, value: Any) -> None:
        port[key] = value
        self.on_change()

    def _count_changed(self) -> None:
        inst.resize_ports(self.entry, int(self.count.currentData()))
        self._fill_ports()
        self.on_change()

    # ---- sweep -----------------------------------------------------------------------------
    def _sweep_group(self) -> QGroupBox:
        group = QGroupBox(self.t("inst_sweep"))
        layout = QVBoxLayout(group)
        hint = QLabel(self._range_hint())
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_STYLE)
        layout.addWidget(hint)
        form = QFormLayout()
        sweep = self.entry["sweep"]
        self.start = QLineEdit(inst.format_frequency(sweep["start_hz"]))
        self.stop = QLineEdit(inst.format_frequency(sweep["stop_hz"]))
        self.points = QSpinBox()
        self.points.setRange(2, int(self.caps.get("max_sweep_points") or 1_000_000))
        self.points.setValue(int(sweep.get("points", inst.DEFAULT_SWEEP_POINTS)))
        self.if_bandwidth = QLineEdit(self._optional(sweep.get("if_bandwidth_hz"), True))
        self.if_bandwidth.setPlaceholderText(self.t("inst_not_set"))
        self.power = QLineEdit(self._optional(sweep.get("power_dbm"), False))
        self.power.setPlaceholderText(self.t("inst_not_set"))
        form.addRow(self.t("inst_sweep_start"), self.start)
        form.addRow(self.t("inst_sweep_stop"), self.stop)
        form.addRow(self.t("inst_sweep_points"), self.points)
        form.addRow(self.t("inst_sweep_if"), self.if_bandwidth)
        form.addRow(self.t("inst_sweep_power"), self.power)
        layout.addLayout(form)
        self.start.textChanged.connect(lambda text: self._frequency("start_hz", self.start, text))
        self.stop.textChanged.connect(lambda text: self._frequency("stop_hz", self.stop, text))
        self.points.valueChanged.connect(lambda value: self._store("points", int(value)))
        self.if_bandwidth.textChanged.connect(
            lambda text: self._optional_number("if_bandwidth_hz", self.if_bandwidth, text, True)
        )
        self.power.textChanged.connect(
            lambda text: self._optional_number("power_dbm", self.power, text, False)
        )
        return group

    def _range_hint(self) -> str:
        low, high = self.caps.get("frequency_min_hz"), self.caps.get("frequency_max_hz")
        if not (low and high):
            return self.t("inst_sweep_hint")
        text = self.t("inst_sweep_model_range").format(
            low=inst.format_frequency(low), high=inst.format_frequency(high)
        )
        if self.caps.get("max_sweep_points"):
            text += " " + self.t("inst_sweep_model_points").format(n=self.caps["max_sweep_points"])
        return text + " " + self.t("inst_sweep_hint")

    @staticmethod
    def _optional(value: Any, frequency: bool) -> str:
        if value is None:
            return ""
        return inst.format_frequency(float(value)) if frequency else f"{value:g}"

    def _store(self, key: str, value: Any) -> None:
        if value is None:
            self.entry["sweep"].pop(key, None)
        else:
            self.entry["sweep"][key] = value
        self.on_change()

    def _frequency(self, key: str, field: QLineEdit, text: str) -> None:
        try:
            value = parse_frequency(text)
        except ValueError:
            _mark(field, False)
            return
        _mark(field, True)
        self._store(key, value)

    def _optional_number(self, key: str, field: QLineEdit, text: str, frequency: bool) -> None:
        if not text.strip():
            _mark(field, True)
            self._store(key, None)
            return
        try:
            value = parse_frequency(text) if frequency else float(text.replace(",", "."))
        except ValueError:
            _mark(field, False)
            return
        _mark(field, True)
        self._store(key, value)


class SerialPanel(QGroupBox):
    """RS-232 settings of an ``ASRL`` instrument: the ones of the library unless changed here.

    Only the values that differ from the library are stored (``serial`` in the entry)."""

    def __init__(
        self,
        entry: Dict[str, Any],
        library_defaults: Dict[str, Any],
        translator: Any,
        on_change: Callable[[], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(translator.t("inst_serial_title"), parent)
        self.entry, self.on_change = entry, on_change
        self.defaults = {**inst.SERIAL_FALLBACK, **library_defaults}
        self.t = translator.t
        self.setCheckable(True)
        self.setChecked(bool(entry.get("serial")))
        layout = QVBoxLayout(self)
        hint = QLabel(self.t("inst_serial_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(HINT_STYLE)
        layout.addWidget(hint)
        form = QFormLayout()
        values = {**self.defaults, **(entry.get("serial") or {})}
        self.fields: Dict[str, QComboBox] = {}
        for key, label in (
            ("baud", "inst_serial_baud"),
            ("data_bits", "inst_serial_data_bits"),
            ("parity", "inst_serial_parity"),
            ("stop_bits", "inst_serial_stop_bits"),
            ("flow_control", "inst_serial_flow"),
        ):
            combo = QComboBox()
            choices = inst.SERIAL_BAUDS if key == "baud" else inst.SERIAL_CHOICES[key]
            for choice in choices:
                combo.addItem(str(choice), choice)
            shown = values.get(key, combo.itemData(0))
            index = combo.findData(shown)
            if index < 0:  # a value the lists do not have (kept as it is)
                combo.addItem(str(shown), shown)
                index = combo.count() - 1
            combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(self._changed)
            self.fields[key] = combo
            form.addRow(self.t(label), combo)
        layout.addLayout(form)
        self.toggled.connect(self._changed)

    def values(self) -> Dict[str, Any]:
        """The settings shown now."""
        return {key: combo.currentData() for key, combo in self.fields.items()}

    def _changed(self, *_args: Any) -> None:
        if self.isChecked():
            changes = inst.serial_changes(self.values(), self.defaults)
            if changes:
                self.entry["serial"] = changes
            else:
                self.entry.pop("serial", None)
        else:
            self.entry.pop("serial", None)
            for key, combo in self.fields.items():  # show the library settings again
                if key in self.defaults:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(max(combo.findData(self.defaults[key]), 0))
                    combo.blockSignals(False)
        self.on_change()


class SwitchUnitPanel(QWidget):
    """The module in every slot of a switch unit (``slots``: ``slot_number``, ``module_id``)."""

    def __init__(
        self,
        entry: Dict[str, Any],
        caps: Optional[Dict[str, Any]],
        translator: Any,
        on_change: Callable[[], None],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.entry, self.on_change = entry, on_change
        self.t = translator.t
        caps = caps or {}
        count = caps.get("number_of_slots")
        count = count if isinstance(count, int) and count > 0 else 0
        modules = [m for m in caps.get("compatible_modules") or [] if isinstance(m, str)]
        known = {s.get("slot_number"): s for s in entry.get("slots") or [] if isinstance(s, dict)}
        entry["slots"] = [
            known.get(n) or {"slot_number": n, "module_id": ""} for n in range(1, count + 1)
        ]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(self.t("inst_switch_slots"))
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        if not count:
            layout.addWidget(QLabel(self.t("inst_switch_no_slots")))
            return
        form = QFormLayout()
        for slot in entry["slots"]:
            combo = QComboBox()
            combo.addItem(self.t("inst_switch_empty"), "")
            for module in modules:
                combo.addItem(module, module)
            current = slot.get("module_id", "")
            if current and combo.findData(current) < 0:
                combo.addItem(current, current)
            combo.setCurrentIndex(max(combo.findData(current), 0))
            combo.currentIndexChanged.connect(lambda _i, s=slot, c=combo: self._set(s, c))
            form.addRow(f"{self.t('slot')} {slot['slot_number']}", combo)
        layout.addLayout(form)

    def _set(self, slot: Dict[str, Any], combo: QComboBox) -> None:
        slot["module_id"] = combo.currentData() or ""
        self.on_change()
