# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The settings of a datalogger channel in the editor: range, integration time, zero, input
impedance (``ola.channel_setup``), as four cells of the channel table.

``SettingsCells(channel, options, t)`` makes the four widgets for one channel (a dictionary of the
``.inst`` file) and keeps the dictionary up to date: a setting that is the default is **taken out**
of the dictionary, so a file that does not use them stays as it was. What each cell offers comes
from ``options`` (what the model lists, ``ModelOptions``): a model without integration time has
that cell disabled, one without the zero calls has no zero, and so on; a function that has none of
them (AC voltage, frequency, temperature) has all four disabled and its settings cleared.
``model_options`` reads the options of the model of an instrument from the library.
"""

from typing import Any, Callable, Dict, Optional

from PyQt6.QtWidgets import QCheckBox, QComboBox

from frontend.ui.connector_setup import default_library_path, load_library
from ola.channel_setup import FUNCTIONS, ModelOptions, function_of, options_of

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
            for key in ("range", "nplc", "zero", "impedance"):
                ch.pop(key, None)
        self._fill_range(name, unit, ch.get("range"))
        self._fill_nplc(ch.get("nplc") if function else None, bool(function and self.options.nplc))
        self.zero_box.setChecked(bool(ch.get("zero")) and bool(function and self.options.zero))
        self.zero_box.setEnabled(bool(function and self.options.zero))
        self.zero_box.setToolTip(self._tip("channel_zero_tip", function and self.options.zero))
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

    def _fill_nplc(self, current: Any, available: bool) -> None:
        box = self.nplc_box
        box.clear()
        box.addItem(self.t("nplc_default"), "")
        for value in self.options.nplc if available else []:
            box.addItem(value, value)
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
