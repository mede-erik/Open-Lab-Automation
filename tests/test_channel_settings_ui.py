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
