# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The function-generator panel of the Remote control tab.

It shows only the controls the model defines in the library (``ola.control_panels``), checks
the values before sending them, and sends logical calls (never SCPI).
"""

import json
import os

import pytest

from ola.control_panels import (
    FunctionGeneratorControls,
    accepted_values,
    check_function_generator,
    function_generator_controls,
)
from tests.conftest import LIBRARY_PATH

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")


# ----- what a panel shows (no Qt) ------------------------------------------------------------
def test_accepted_values_are_the_ones_the_command_translates():
    command = {
        "parameters": {
            "shape": {"values": ["SINE", "SQUARE", "RAMP"]},
            "shape_text": {"from": "shape", "map": {"SINE": "SIN", "SQUARE": "SQU"}},
        }
    }
    assert accepted_values(command, "shape", ["X"]) == ["SINE", "SQUARE"]
    assert accepted_values({"parameters": {}}, "shape", ["A", "B"]) == ["A", "B"]
    assert accepted_values(None, "shape", ["A"]) == ["A"]


@needs_library
def test_a_two_channel_generator_with_an_output_switch():
    from ola.library import Library

    lib = Library.load(LIBRARY_PATH)
    c = function_generator_controls(lib, "FGEN_Rigol_DG1022")
    assert c.channels == 2 and c.has("set_output_state")
    assert "SINE" in c.shapes and "RAMP" not in c.shapes  # the DG1022 command does not map it
    assert c.frequency_max == 20e6


@needs_library
def test_a_generator_without_output_switch_has_no_output_control():
    from ola.library import Library

    lib = Library.load(LIBRARY_PATH)
    c = function_generator_controls(lib, "FGEN_Agilent_33120A")
    assert c.channels == 1 and not c.has("set_output_state") and c.has("set_frequency")


def test_an_unknown_model_has_no_control():
    class Empty:
        def commands(self, model_id):
            return None

        def find_model(self, model_id):
            return None

    c = function_generator_controls(Empty(), "nope")
    assert c.calls == [] and c.channels == 1


def test_values_are_checked_against_the_limits():
    c = FunctionGeneratorControls(calls=["set_frequency"], frequency_min=1.0, frequency_max=1e6)
    assert check_function_generator(c, 1000, 1) == []
    assert check_function_generator(c, 0.5, None) == ["fg_err_frequency_low"]
    assert check_function_generator(c, 2e6, None) == ["fg_err_frequency_high"]
    assert check_function_generator(c, None, -1) == ["fg_err_amplitude"]


# ----- the panel ---------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ALL = FunctionGeneratorControls(
    calls=[
        "set_waveform_shape",
        "set_frequency",
        "set_amplitude",
        "set_offset",
        "set_output_state",
    ],
    shapes=["SINE", "SQUARE"],
    channels=2,
    frequency_max=20e6,
)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make(controls, fail=None):
    from frontend.core.Translator import Translator
    from frontend.ui.FunctionGeneratorPanel import FunctionGeneratorPanel

    sent = []

    def run(number, call, **args):
        if fail and call == fail:
            raise RuntimeError("CALL-002 not handled")
        sent.append((number, call, args))

    tr = Translator()
    return FunctionGeneratorPanel(controls, run, tr.t), sent


@pytest.mark.gui
def test_one_box_per_channel_and_apply_sends_logical_calls(app):
    panel, sent = make(ALL)
    assert sorted(panel.channels) == [1, 2]
    w = panel.channels[2]
    w["shape"].setCurrentIndex(w["shape"].findData("SQUARE"))
    w["frequency"].setText("1000")
    w["amplitude"].setText("2,5")  # a comma is accepted
    assert panel.apply(2)
    assert sent == [
        (2, "set_waveform_shape", {"shape": "SQUARE"}),
        (2, "set_frequency", {"value": 1000.0}),
        (2, "set_amplitude", {"value": 2.5}),  # the empty offset is not sent
    ]


@pytest.mark.gui
def test_a_value_out_of_the_limits_is_not_sent(app):
    panel, sent = make(ALL)
    panel.channels[1]["frequency"].setText("30000000")
    assert not panel.apply(1)
    assert sent == [] and "maximum" in panel.channels[1]["status"].text()


@pytest.mark.gui
def test_the_output_button_follows_the_instrument(app):
    panel, sent = make(ALL)
    out = panel.channels[1]["output"]
    out.click()
    assert sent == [(1, "set_output_state", {"state": True})] and out.isChecked()
    panel, _ = make(ALL, fail="set_output_state")
    out = panel.channels[1]["output"]
    out.click()
    assert not out.isChecked()  # the call failed: the button goes back
    assert "CALL-002" in panel.channels[1]["status"].text()


@pytest.mark.gui
def test_only_the_supported_controls_are_shown(app):
    panel, _ = make(FunctionGeneratorControls(calls=["set_frequency"], channels=1))
    assert set(panel.channels[1]) == {"frequency", "apply", "status"}
    panel, _ = make(FunctionGeneratorControls())
    assert panel.channels == {}  # not in the library: a message, no control


@pytest.mark.gui
@needs_library
def test_the_remote_control_tab_shows_a_panel_for_a_generator(app, tmp_path, monkeypatch):
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.FunctionGeneratorPanel import FunctionGeneratorPanel
    from frontend.ui.RemoteControlTab import RemoteControlTab

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    path = tmp_path / "lab.inst"
    gen = {
        "instrument_type": "function_generator",
        "instance_name": "GEN",
        "series": "Rigol_DG1000_Series",
        "model": "Rigol DG1022",
        "model_id": "FGEN_Rigol_DG1022",
        "visa_address": "TCPIP0::127.0.0.1::inst0::INSTR",
        "num_channels": 2,
        "channels": [],
    }
    path.write_text(json.dumps({"instruments": [gen]}), encoding="utf-8")
    tab = RemoteControlTab(li)
    calls = []
    monkeypatch.setattr(tab, "run_call", lambda inst, ch, call, **args: calls.append(
        (inst["instance_name"], call, args)))
    tab.load_instruments(str(path))
    panels = tab.findChildren(FunctionGeneratorPanel)
    assert len(panels) == 1 and sorted(panels[0].channels) == [1, 2]
    panels[0].channels[2]["frequency"].setText("50")
    assert panels[0].apply(2)
    assert ("GEN", "set_frequency", {"channel_number": 2, "value": 50.0}) in calls
    timer = getattr(tab, "measurement_timer", None)
    if timer is not None:
        timer.stop()
