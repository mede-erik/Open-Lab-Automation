# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The settings of a datalogger channel in the editor: range, integration time, zero, input
impedance (``ola.channel_setup``), as four cells of the channel table.

``SettingsCells(channel, options, t)`` makes the four widgets for one channel (a dictionary of the
``.inst`` file) and keeps the dictionary up to date: a setting that is the default is **taken out**
of the dictionary, so a file that does not use them stays as it was. What each cell offers comes
from ``options`` (what the model lists, ``ModelOptions``): a model without integration time has
that cell disabled, one without the zero calls has no zero, and so on. A temperature channel has
its probe and sensor in the range cell (one choice: probe and sensor together), its integration
time from ``set_temperature_nplc``, and no zero and no input impedance. A function that has none of
them (AC voltage, frequency) has its cells disabled and its settings cleared.
"""

from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtWidgets import QCheckBox, QComboBox

from frontend.ui.connector_setup import default_library_path, load_library
from ola.channel_setup import (
    FUNCTIONS,
    TEMPERATURE,
    ModelOptions,
    canonical_probe,
    function_of,
    options_of,
)

UNITS = {"VOLT:DC": "V", "CURR:DC": "A", "RES": "Ω", "FRES": "Ω"}
AUTO = "AUTO"


def model_options(instrument: Dict[str, Any], library_path: Optional[str] = None) -> ModelOptions:
    """What the model of the instrument (a dictionary of the ``.inst`` file) lets you choose for a
    channel. Empty options if the model or the library cannot be found."""
    try:
        library = load_library(library_path or default_library_path())
        identifier = instrument.get("model_id") or instrument.get("model") or ""
        model_id = library.resolve_model_id(identifier)
        return options_of(library.commands(model_id)) if model_id else ModelOptions()
    except Exception:  # an editor must open with a library that cannot be read
        return ModelOptions()


class SettingsCells:
    """The four cells of a channel: ``range_box``, ``nplc_box``, ``zero_box``, ``impedance_box``."""

    def __init__(
        self,
        channel: Dict[str, Any],
        options: ModelOptions,
        t: Callable[[str], str],
        changed: Optional[Callable[[], None]] = None,
    ):
        self.channel, self.options, self.t, self.changed = channel, options, t, changed
        self.range_box, self.nplc_box = QComboBox(), QComboBox()
        self.impedance_box, self.zero_box = QComboBox(), QCheckBox()
        self._loading = True
        self.fill_function(channel.get("meas_type"), keep=True)
        self.nplc_box.currentIndexChanged.connect(self._write)
        self.range_box.currentIndexChanged.connect(self._write)
        self.impedance_box.currentIndexChanged.connect(self._write)
        self.zero_box.stateChanged.connect(self._write)
        self._loading = False

    @property
    def widgets(self):
        """The four widgets in the order of the columns."""
        return (self.range_box, self.nplc_box, self.zero_box, self.impedance_box)

    # ----- filling the cells ------------------------------------------------------------------
    def fill_function(self, meas_type: Any, keep: bool = False) -> None:
        """Fill the cells for the function of the channel. ``keep``: show what the file already has
        (at the start); otherwise the settings are put back to the defaults."""
        was, self._loading = self._loading, True
        function = function_of(meas_type or "VOLT:DC")
        name = function.name if function else ""
        unit = UNITS.get(name, "")
        ch = self.channel
        if not keep:
            for key in ("range", "nplc", "zero", "impedance", "probe_type", "sensor_type",
                        "rtd_ohms"):  # fmt: skip
                ch.pop(key, None)
        temperature = name == TEMPERATURE
        if temperature:
            self._fill_sensor(ch.get("probe_type"), ch.get("sensor_type"), ch.get("rtd_ohms"))
        else:
            self._fill_range(name, unit, ch.get("range"))
        integration = self.options.temp_nplc if temperature else self.options.nplc
        self._fill_nplc(ch.get("nplc") if function else None, integration if function else [])
        zero = bool(function and function.zero and self.options.zero)
        self.zero_box.setChecked(bool(ch.get("zero")) and zero)
        self.zero_box.setEnabled(zero)
        self.zero_box.setToolTip(self._tip("channel_zero_tip", zero))
        self._fill_impedance(function, ch.get("impedance"))
        self._loading = was

    def _tip(self, key: str, available: Any) -> str:
        return self.t(key) if available else self.t("channel_setting_unavailable")

    def _fill_range(self, name: str, unit: str, current: Any) -> None:
        box = self.range_box
        box.clear()
        box.addItem(self.t("range_auto"), AUTO)
        listed = self.options.ranges.get(name, [])
        for value in listed:
            box.addItem(f"{value} {unit}".strip(), value)
        if current not in (None, "", AUTO) and not self._select(box, current):
            box.addItem(f"{current} {unit}".strip(), str(current))  # a value the file has
            self._select(box, current)
        box.setEnabled(bool(name))
        box.setToolTip(self._tip("channel_range_tip", name))

    def _fill_sensor(self, probe: Any, sensor: Any, ohms: Any = None) -> None:
        """The cell of a temperature channel: the probe and the sensor in one choice
        (``TCouple|K``, ``RTD|85|1000``...), as the model lists them. An RTD is offered as a PT100
        and as a PT1000 when the model can set the nominal resistance."""
        box = self.range_box
        box.clear()
        for name, sensors in self.options.probes.items():
            resistances = self.options.rtd_ohms.get(name, [])
            for kind in sensors:
                for value in resistances or [None]:
                    key = f"{name}|{kind}" + (f"|{value:g}" if value else "")
                    box.addItem(
                        f"{self._probe_text(name)} {self._sensor_text(name, kind, value)}", key
                    )
        current = f"{probe}|{sensor}" + (f"|{float(ohms):g}" if ohms not in (None, "") else "")
        if probe and sensor and not self._select(box, current):
            box.addItem(f"{probe} {sensor}", current)  # a value the file has
            self._select(box, current)
        box.setEnabled(bool(self.options.probes))
        box.setToolTip(self._tip("channel_sensor_tip", self.options.probes))

    def _probe_text(self, probe: str) -> str:
        key = {
            "TCouple": "probe_thermocouple",
            "RTD": "probe_rtd2",
            "FRTD": "probe_rtd4",
            "THERmistor": "probe_thermistor",
        }.get(canonical_probe(probe) or "", "")
        return self.t(key) if key else probe

    @staticmethod
    def _split_sensor(data: Any) -> tuple:
        """``"RTD|85|1000"`` -> ``("RTD", "85", "1000")``; the nominal resistance is empty when
        the choice has none (a thermocouple, a thermistor, an RTD of a model without it)."""
        parts = str(data or "").split("|")
        parts += [""] * (3 - len(parts))
        return parts[0], parts[1], parts[2]

    @staticmethod
    def _sensor_text(probe: str, sensor: str, ohms: Optional[float] = None) -> str:
        """The sensor as a person names it: a thermocouple letter, an RTD as ``PT100`` or
        ``PT1000`` (its nominal resistance; the alpha 0.00385 is the usual one, 0.00391 is added),
        a thermistor's resistance at 25 degrees."""
        kind = canonical_probe(probe)
        if kind == "THERmistor":
            return f"{sensor} Ω"
        if kind in ("RTD", "FRTD"):
            alpha = {"85": "α 0.00385", "91": "α 0.00391"}.get(sensor, sensor)
            if not ohms:
                return alpha
            name = f"PT{ohms:g}"
            return name if sensor == "85" else f"{name} ({alpha})"
        return sensor

    def _fill_nplc(self, current: Any, integration: List[str]) -> None:
        box = self.nplc_box
        box.clear()
        box.addItem(self.t("nplc_default"), "")
        for value in integration:
            box.addItem(value, value)
        available = bool(integration)
        if current not in (None, "") and available and not self._select(box, current):
            box.addItem(f"{current:g}" if isinstance(current, (int, float)) else str(current),
                        str(current))  # fmt: skip
            self._select(box, current)
        box.setEnabled(available)
        box.setToolTip(self._tip("channel_nplc_tip", available))

    def _fill_impedance(self, function: Any, current: Any) -> None:
        box = self.impedance_box
        box.clear()
        box.addItem(self.t("impedance_default"), "")
        available = bool(function and function.impedance and self.options.impedance)
        if available:
            box.addItem(self.t("impedance_auto_option"), "auto")
            box.addItem(self.t("impedance_fixed_option"), "10M")
            for index in range(box.count()):
                if box.itemData(index) == current:
                    box.setCurrentIndex(index)
        box.setEnabled(available)
        box.setToolTip(self._tip("channel_impedance_tip", available))

    @staticmethod
    def _select(box: QComboBox, value: Any) -> bool:
        """Select the item whose value is ``value`` (a number or its text); False if none."""
        for index in range(box.count()):
            data = box.itemData(index)
            try:
                same = float(data) == float(value)
            except (TypeError, ValueError):
                same = str(data).upper() == str(value).upper()
            if same:
                box.setCurrentIndex(index)
                return True
        return False

    # ----- writing back -----------------------------------------------------------------------
    def _write(self, *_args: Any) -> None:
        if self._loading:
            return
        ch = self.channel
        function = function_of(ch.get("meas_type", "VOLT:DC"))
        if function is not None and function.name == TEMPERATURE:
            probe, sensor, ohms = self._split_sensor(self.range_box.currentData())
            self._set(ch, "probe_type", probe or None)
            self._set(ch, "sensor_type", sensor or None)
            self._set(ch, "rtd_ohms", float(ohms) if ohms else None)
            self._set(ch, "range", None)
        else:
            rng = self.range_box.currentData()
            self._set(ch, "range", None if rng in (None, AUTO) else float(rng))
        nplc = self.nplc_box.currentData()
        self._set(ch, "nplc", float(nplc) if nplc else None)
        self._set(ch, "zero", True if self.zero_box.isChecked() else None)
        self._set(ch, "impedance", self.impedance_box.currentData() or None)
        if self.changed:
            self.changed()

    @staticmethod
    def _set(channel: Dict[str, Any], key: str, value: Any) -> None:
        if value is None:
            channel.pop(key, None)
        else:
            channel[key] = value


__all__ = ["FUNCTIONS", "SettingsCells", "model_options"]
