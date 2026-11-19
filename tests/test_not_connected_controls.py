# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Every command of the Remote control tab says when its instrument is not connected: a box with
the code (INST-006, VISA-002...) instead of nothing. The buttons of a supply, the output switch,
the readings and the panels of the generators (RF, function generator, load, analyzer) are all
covered. Before, a supply that was not there gave no message at all, and a generator gave a
line of text only."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton  # noqa: E402

from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from ola import rf_controls as rc  # noqa: E402
from ola.call_errors import CallNotSupportedError, InstrumentNotConnectedError  # noqa: E402
from tests.conftest import LIBRARY_PATH  # noqa: E402

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")

PSU = {
    "instrument_type": "power_supply",
    "instance_name": "PSU",
    "model": "Keysight E36311A",
    "model_id": "PSU_Keysight_E36311A",
    "series": "Keysight_E36300_Series",
    "visa_address": "TCPIP0::10.255.255.1::inst0::INSTR",
    "channels": [{"enabled": True, "name": "CH1", "channel_id": "1",
                  "max_voltage": 6.0, "max_current": 5.0}],
}
CH = PSU["channels"][0]


class Refused:
    """A VISA resource manager for which nothing is on the network."""

    def open_resource(self, address):
        raise OSError("VI_ERROR_RSRC_NFOUND (-1073807343)")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def library():
    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    return li


@pytest.fixture
def popups(monkeypatch):
    """Every box of the Remote control tab and of the panels, as (title, text, exception)."""
    import frontend.ui.ElectronicLoadPanel as el_panel
    import frontend.ui.FunctionGeneratorPanel as fg_panel
    import frontend.ui.RemoteControlTab as tab_module
    import frontend.ui.RfGeneratorPanel as rf_panel
    import frontend.ui.VnaPanel as vna_panel

    seen = []

    def record(parent, title, text, code=None, exception=None, level="warning"):
        seen.append((title, text, exception))

    for module in (tab_module, rf_panel, el_panel, fg_panel, vna_panel):
        monkeypatch.setattr(module, "show_problem", record)
    return seen


@pytest.fixture
def tab(app, library, monkeypatch):
    from frontend.ui.RemoteControlTab import RemoteControlTab

    tab = RemoteControlTab(library)
    tab._ensure_visa_initialized = lambda: True
    tab.rm = Refused()
    yield tab
    tab.close()


def edit_with(text):
    field = QLineEdit()
    field.setText(text)
    return field


@needs_library
def test_a_command_to_a_supply_that_is_not_there_is_reported(tab, popups):
    tab.set_voltage(PSU, CH, edit_with("5"))
    assert len(popups) == 1
    title, text, exc = popups[0]
    assert isinstance(exc, InstrumentNotConnectedError)
    assert exc.code == "VISA-002"  # the address does not answer: why, in the box
    assert "PSU" in text and "TCPIP0::10.255.255.1" in text


@needs_library
def test_the_current_of_a_supply_that_is_not_there_is_reported(tab, popups):
    tab.set_current(PSU, CH, edit_with("1"))
    assert len(popups) == 1 and isinstance(popups[0][2], InstrumentNotConnectedError)


@needs_library
def test_the_output_switch_says_it_and_goes_back(tab, popups):
    button = QPushButton()
    button.setCheckable(True)
    button.setChecked(True)  # the user switched the output on
    tab.toggle_output(PSU, CH, button, True)
    assert len(popups) == 1 and popups[0][2].code == "VISA-002"
    assert button.isChecked() is False  # back to off, nothing was switched


@needs_library
def test_a_reading_of_a_supply_that_is_not_there_is_reported(tab, popups):
    label = QLabel()
    tab.read_actual(PSU, CH, label)
    assert len(popups) == 1 and isinstance(popups[0][2], InstrumentNotConnectedError)


@needs_library
def test_no_address_says_to_set_it(tab, popups):
    entry = {**PSU, "visa_address": ""}
    tab.set_voltage(entry, CH, edit_with("5"))
    assert popups[0][2].code == "INST-005"


@needs_library
def test_no_visa_says_so(tab, popups, monkeypatch):
    monkeypatch.setattr(tab, "_ensure_visa_initialized", lambda: False)
    tab.set_voltage(PSU, CH, edit_with("5"))
    assert popups[0][2].code == "VISA-005"


@needs_library
def test_a_missing_connection_is_not_a_model_limit(tab):
    """The command is refused as "not connected", never as "not supported by the model"."""
    with pytest.raises(InstrumentNotConnectedError) as info:
        tab.run_call(PSU, CH, "set_voltage", value=5.0)
    assert not isinstance(info.value, CallNotSupportedError)


@needs_library
def test_the_manual_refresh_names_the_instruments_not_connected(tab, popups):
    tab.meas_vars = [(PSU, {**CH, "measured_variable": "VOUT"})]
    tab.meas_labels = {("PSU", "VOUT"): QLabel()}
    tab.refresh_measurements_auto(manual=True)
    assert len(popups) == 1 and "PSU" in popups[0][1]


@needs_library
def test_the_automatic_refresh_does_not_open_boxes(tab, popups):
    tab.meas_vars = [(PSU, {**CH, "measured_variable": "VOUT"})]
    tab.meas_labels = {("PSU", "VOUT"): QLabel()}
    tab.refresh_measurements_auto()
    assert popups == []


def test_the_rf_panel_reports_a_generator_that_is_not_there(app, popups):
    from frontend.ui.RfGeneratorPanel import RfGeneratorPanel

    def run(call, **args):
        raise InstrumentNotConnectedError("RF is not connected", call=call, code="VISA-002")

    controls = rc.RfControls(calls=["set_frequency", "set_power_level", "set_output_state"])
    from frontend.core.Translator import Translator

    panel = RfGeneratorPanel(controls, run, Translator(default_lang="en").t)
    panel.frequency.setText("1G")
    assert panel.apply_carrier() is False
    assert len(popups) == 1 and popups[0][2].code == "VISA-002"
    assert panel.status.text() == "Error: [VISA-002] RF is not connected"
