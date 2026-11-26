# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Editor of a pulse-on-an-electronic-load file (``.pls``): the form of the module, with the shape
of the pulse drawn above it and the power of the load watched while the values are typed.

The fields, their checks and the file are those of ``FormEditorDialog`` (the ``form.json`` of the
module); this window adds what only a window can do:

* the **preview**, the trapezoid of the pulse (``ola.pulse_load.pulse_profile``), redrawn at every
  change; it is a view of the same data, the edges are for the drawing only;
* the **limits of the load** chosen in the file (``limits(name)``, the numbers the library gives for
  its model): a current above the maximum is brought back to it, and a pulse whose peak or average
  power (current x working voltage) exceeds the power limit has the parameter changed last
  corrected to the largest value that keeps it within the limit, with a message that says so.
"""

from typing import Any, Callable, Mapping, Optional, Sequence

from PyQt6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from frontend.core.errorhandler import show_problem
from frontend.core.Translator import Translator
from frontend.ui.FormEditorDialog import FormEditorDialog
from frontend.ui.trace_plot import TracePlot
from ola.compat import CURRENT, POWER
from ola.pulse_load import power_of, pulse_profile
from ola.pulse_power import corrected_parameter

# the parameters the power depends on: the name used by the correction -> the field of the file
FIELDS = {
    "amplitude": "amplitude_a",
    "base_level": "base_level_a",
    "width": "width_us",
    "frequency": "frequency_hz",
}
LABELS = {  # the key of the name of each one in the messages
    "amplitude": "pulse_amplitude",
    "base_level": "pulse_base_level",
    "width": "pulse_width",
    "frequency": "pulse_frequency",
}
UNITS = {"amplitude": "A", "base_level": "A", "width": "us", "frequency": "Hz"}
CURRENT_FIELDS = (
    ("amplitude", "pulse_amplitude_exceeded"),
    ("base_level", "pulse_base_level_exceeded"),
)


class PulseLoadEditorDialog(FormEditorDialog):
    """The form of the pulse file, with the preview and the checks of the limits of the load."""

    _limits: Optional[Callable[[str], Mapping[str, float]]] = None
    _changed_last = ""
    _correcting = False

    def __init__(
        self,
        file_path: str,
        registry: Any,
        type_id: str,
        translator: Any = None,
        instruments: Sequence[str] = (),
        role_instruments: Optional[Mapping[str, Sequence[str]]] = None,
        assets: Any = None,
        parent: Optional[QWidget] = None,
        duts: Any = None,
        limits: Optional[Callable[[str], Mapping[str, float]]] = None,
    ):
        """``limits(name)``: what the library gives for the model of the instrument ``name`` of the
        project (``max_current``, ``max_power`` in A and W; empty if it gives none)."""
        self._app_t = (translator or Translator()).t
        super().__init__(
            file_path, registry, type_id, translator, instruments,
            role_instruments=role_instruments, assets=assets, parent=parent, duts=duts,
        )  # fmt: skip
        self._limits = limits
        self._draw_preview()

    # ================================================================ window
    def _build_ui(self, module_name: str) -> None:
        super()._build_ui(module_name)
        box = QGroupBox(self._app_t("pulse_waveform_preview"))
        layout = QVBoxLayout(box)
        self.preview = TracePlot()
        self.preview.empty_text = self._app_t("plot_no_data")
        self.preview.setMinimumHeight(220)
        layout.addWidget(self.preview)
        self.layout().insertWidget(1, box)  # under the summary line, above the fields

    def _refresh_state(self) -> None:
        super()._refresh_state()
        self._draw_preview()

    def _draw_preview(self) -> None:
        """The pulse of the file as it is now; nothing is drawn while a value is not valid."""
        preview = getattr(self, "preview", None)
        if preview is None:
            return
        p = self.model.params
        try:
            times, currents = pulse_profile(
                float(p["amplitude_a"]), float(p["base_level_a"]), float(p["width_us"]),
                float(p["frequency_hz"]), float(p.get("rise_time_us", 10.0)),
                float(p.get("fall_time_us", 10.0)),
            )  # fmt: skip
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            preview.set_curves([])
            return
        preview.set_curves(
            [(self._app_t("pulse_peak"), [t * 1e6 for t in times], currents)],
            xlabel=self._app_t("pulse_time_us"),
            ylabel=self._app_t("pulse_current_a"),
        )

    # ================================================================ limits of the load
    def _edited(self, field: Any) -> None:
        # the parameter changed last is the one corrected; any other field (the voltage comes from
        # the circuit) leaves it empty, and the correction then lowers the amplitude
        self._changed_last = next((n for n, path in FIELDS.items() if path == field.path), "")
        super()._edited(field)
        if not self._loading and not self._correcting:
            self._keep_within_the_load()

    def _load_limits(self) -> Mapping[str, float]:
        name = self.model.instrument("load")
        return (self._limits(name) if (self._limits and name) else None) or {}

    def _set_field(self, name: str, value: float) -> None:
        """Put a corrected value in the field and in the file data."""
        path = FIELDS[name]
        self.model.set(path, value)
        self._loading = True
        try:
            self._show_value(self.rows[path])
        finally:
            self._loading = False

    def _keep_within_the_load(self) -> None:
        """A current above the maximum of the load, then a power above its limit: correct them."""
        limits = self._load_limits()
        if not limits:
            return
        self._correcting = True
        try:
            self._limit_currents(limits.get(CURRENT))
            self._limit_power(limits.get(POWER))
        finally:
            self._correcting = False
        self._refresh_state()

    def _limit_currents(self, max_current: Optional[float]) -> None:
        if not max_current:
            return
        for name, key in CURRENT_FIELDS:
            value = self.model.get(FIELDS[name])
            if isinstance(value, (int, float)) and value > max_current:
                self._set_field(name, max_current)
                show_problem(
                    self, self._app_t("error"),
                    self._app_t(key).format(value=value, max=max_current) + "\n[TOOL-004]",
                    code="TOOL-004",
                )  # fmt: skip

    def _limit_power(self, max_power: Optional[float]) -> None:
        p = self.model.params
        voltage = p.get("voltage_v")
        if not max_power or not isinstance(voltage, (int, float)) or voltage <= 0:
            return  # without a power limit or a voltage there is nothing to check yet
        try:
            result = power_of(p, float(voltage), max_power)
        except (KeyError, TypeError, ZeroDivisionError):
            return
        if not result.exceeded:
            return
        name, value = corrected_parameter(
            self._changed_last, p["amplitude_a"], p["base_level_a"], p["width_us"],
            p["frequency_hz"], float(voltage), max_power,
        )  # fmt: skip
        self._set_field(name, value)
        t = self._app_t
        message = (
            t("pulse_power_exceeded").format(power=round(result.worst, 3), max=max_power)
            + "\n"
            + t("pulse_power_summary").format(
                peak=round(result.peak, 3), average=round(result.average, 3), max=max_power
            )
            + "\n"
            + t("pulse_power_corrected").format(
                parameter=t(LABELS[name]), value=f"{value} {UNITS[name]}"
            )
            + "\n[TOOL-008]"
        )
        show_problem(self, t("error"), message, code="TOOL-008")
