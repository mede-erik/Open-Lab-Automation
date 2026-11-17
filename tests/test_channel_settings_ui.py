# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The four channel-setting cells of the datalogger editor (no screen needed)."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.channel_settings import SettingsCells  # noqa: E402
from ola.channel_setup import ModelOptions  # noqa: E402

pytestmark = pytest.mark.gui

FULL = ModelOptions(
    ranges={"VOLT:DC": [0.1, 1, 10]}, nplc=["0.02", "1", "20", "100"], zero=True, impedance=True
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def cells(app, channel, options=FULL):
    return SettingsCells(channel, options, lambda key: key)


def test_defaults_leave_the_channel_untouched(app):
    channel = {"meas_type": "VOLT:DC"}
    c = cells(app, channel)
    c.nplc_box.setCurrentIndex(0)
    assert channel == {"meas_type": "VOLT:DC"}


def test_choices_are_written_and_cleared(app):
    channel = {"meas_type": "VOLT:DC"}
    c = cells(app, channel)
    c.nplc_box.setCurrentIndex(c.nplc_box.findData("20"))
    c.zero_box.setChecked(True)
    c.impedance_box.setCurrentIndex(c.impedance_box.findData("auto"))
    c.range_box.setCurrentIndex(c.range_box.findData(10))
    assert channel["nplc"] == 20.0 and channel["zero"] is True
    assert channel["impedance"] == "auto" and channel["range"] == 10.0
    c.zero_box.setChecked(False)
    assert "zero" not in channel


def test_existing_values_are_shown(app):
    c = cells(app, {"meas_type": "VOLT:DC", "nplc": 100, "zero": True, "range": 1})
    assert c.nplc_box.currentData() == "100"
    assert c.zero_box.isChecked()
    assert c.range_box.currentData() == 1


def test_unsupported_model_disables_the_cells(app):
    c = cells(app, {"meas_type": "VOLT:DC"}, ModelOptions())
    assert not c.nplc_box.isEnabled() and not c.zero_box.isEnabled()
    assert not c.impedance_box.isEnabled()


def test_a_function_without_settings_clears_them(app):
    channel = {"meas_type": "VOLT:DC", "nplc": 20, "zero": True}
    c = cells(app, channel)
    c.fill_function("VOLT:AC")
    assert "nplc" not in channel and "zero" not in channel
    assert not c.zero_box.isEnabled()


TEMP_OPTIONS = ModelOptions(
    nplc=["1", "20"],
    temp_nplc=["0.2", "1", "20"],
    zero=True,
    impedance=True,
    probes={"TCouple": ["J", "K"], "RTD": ["85"]},
)


def test_a_temperature_channel_chooses_its_probe_and_sensor_in_one_cell(app):
    channel = {"meas_type": "TEMP"}
    c = cells(app, channel, TEMP_OPTIONS)
    assert c.range_box.isEnabled() and c.range_box.count() == 3
    c.range_box.setCurrentIndex(c.range_box.findData("RTD|85"))
    assert channel["probe_type"] == "RTD" and channel["sensor_type"] == "85"
    assert "range" not in channel


def test_a_temperature_channel_shows_the_sensor_the_file_has(app):
    c = cells(app, {"meas_type": "TEMP", "probe_type": "TCouple", "sensor_type": "J"}, TEMP_OPTIONS)
    assert c.range_box.currentData() == "TCouple|J"


def test_a_temperature_channel_takes_the_temperature_integration_times_and_no_zero(app):
    channel = {"meas_type": "TEMP"}
    c = cells(app, channel, TEMP_OPTIONS)
    assert c.nplc_box.isEnabled() and c.nplc_box.count() == 1 + len(TEMP_OPTIONS.temp_nplc)
    c.nplc_box.setCurrentIndex(c.nplc_box.findData("0.2"))
    assert channel["nplc"] == 0.2
    assert not c.zero_box.isEnabled() and not c.impedance_box.isEnabled()


def test_changing_to_another_function_takes_the_sensor_out(app):
    channel = {"meas_type": "TEMP", "probe_type": "RTD", "sensor_type": "85"}
    c = cells(app, channel, TEMP_OPTIONS)
    c.fill_function("VOLT:DC")
    assert "probe_type" not in channel and "sensor_type" not in channel


def test_a_model_without_probes_disables_the_sensor_cell(app):
    c = cells(app, {"meas_type": "TEMP"}, ModelOptions())
    assert not c.range_box.isEnabled()


RTD_OPTIONS = ModelOptions(
    temp_nplc=["1"],
    probes={"RTD": ["85", "91"], "TCouple": ["K"]},
    rtd_ohms={"RTD": [100.0, 1000.0]},
)


def test_an_rtd_is_offered_as_pt100_and_pt1000(app):
    channel = {"meas_type": "TEMP"}
    c = cells(app, channel, RTD_OPTIONS)
    labels = [c.range_box.itemText(i) for i in range(c.range_box.count())]
    assert "probe_rtd2 PT100" in labels and "probe_rtd2 PT1000" in labels
    assert "probe_rtd2 PT1000 (α 0.00391)" in labels  # the other alpha is spelled out
    c.range_box.setCurrentIndex(c.range_box.findData("RTD|85|1000"))
    assert channel["probe_type"] == "RTD" and channel["sensor_type"] == "85"
    assert channel["rtd_ohms"] == 1000.0


def test_the_rtd_resistance_of_the_file_is_shown_and_a_thermocouple_takes_it_out(app):
    channel = {"meas_type": "TEMP", "probe_type": "RTD", "sensor_type": "85", "rtd_ohms": 1000}
    c = cells(app, channel, RTD_OPTIONS)
    assert c.range_box.currentData() == "RTD|85|1000"
    c.range_box.setCurrentIndex(c.range_box.findData("TCouple|K"))
    assert channel["probe_type"] == "TCouple" and "rtd_ohms" not in channel


def test_a_model_without_the_resistance_call_offers_the_alpha_only(app):
    options = ModelOptions(temp_nplc=["1"], probes={"RTD": ["85"]})
    channel = {"meas_type": "TEMP"}
    c = cells(app, channel, options)
    assert c.range_box.itemText(0) == "probe_rtd2 α 0.00385"
    c.range_box.setCurrentIndex(0)
    assert "rtd_ohms" not in channel
