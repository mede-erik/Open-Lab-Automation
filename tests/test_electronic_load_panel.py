# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The electronic-load panel of the Remote control tab.

It shows the modes, readings and protections the model defines in the library
(``ola.load_controls``), checks a setpoint against the channel limits, never passes a channel
argument to the load calls (they have none: ``select_channel`` comes first when the model has
it), and sends logical calls only.
"""

import json
import os

import pytest

from ola import load_controls as lc
from tests.conftest import LIBRARY_PATH

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")


def library():
    from ola.library import Library

    return Library.load(LIBRARY_PATH)


# ----- what the panel shows and sends (no Qt) ---------------------------------------------------
@needs_library
def test_the_controls_follow_the_model():
    keysight = lc.load_controls(library(), "EL_Keysight_EL4913A")
    assert keysight.modes == ["CC", "CV", "CR", "CP"]
    assert keysight.protections == ["ovp", "ocp", "opp"]
    assert [c for c, _ in keysight.readings] == ["read_voltage", "read_current", "read_power"]
    siglent = lc.load_controls(library(), "EL_Siglent_SDL1030X_E")
    assert siglent.protections == ["ocp", "opp"]  # no over-voltage protection on this model
    chroma = lc.load_controls(library(), "EL_Chroma_6330A")
    assert chroma.has("select_channel") and chroma.protections == []


@needs_library
def test_every_call_the_panel_sends_is_accepted_by_the_planner():
    """The planner refuses unknown arguments (CALL-003): no channel_number on load calls."""
    from ola.call_planner import plan_call

    lib = library()
    for model in ("EL_Keysight_EL4913A", "EL_Siglent_SDL1030X_E", "EL_Chroma_6330A"):
        c = lc.load_controls(lib, model)
        calls = []
        for mode in c.modes:
            calls += lc.setpoint_calls(c, mode, 1.0, 2)
        calls += lc.input_calls(c, True, 2) + lc.input_calls(c, False, 2)
        for kind in c.protections:
            calls += lc.protection_calls(c, kind, True, 5.0, 2)
            calls += lc.protection_calls(c, kind, False, None, 2)
        calls += [(name, {}) for name, _ in c.readings]
        for name, args in calls:
            plan_call(lib, model, name, args)  # raises if the model does not accept it


def test_a_channel_is_selected_first_only_when_the_model_can():
    with_select = lc.LoadControls(calls=["select_channel", "set_mode", "set_current_level"],
                                  modes=["CC"])
    assert lc.setpoint_calls(with_select, "CC", 2, 3) == [
        ("select_channel", {"channel_number": 3}),
        ("set_mode", {"mode": "CC"}),
        ("set_current_level", {"value": 2.0}),
    ]
    without = lc.LoadControls(calls=["set_current_level", "load_on"], modes=["CC"])
    assert lc.setpoint_calls(without, "CC", 2, 3) == [("set_current_level", {"value": 2.0})]
    assert lc.input_calls(without, True, 3) == [("load_on", {})]


def test_setpoints_are_checked_against_the_channel_limits():
    ch = {"max_current": 10.0, "max_voltage": 60.0}
    assert lc.check_setpoint("CC", 5, ch) == []
    assert lc.check_setpoint("CC", 12, ch) == ["el_err_limit"]
    assert lc.check_setpoint("CV", -1, ch) == ["el_err_negative"]
    assert lc.check_setpoint("CP", 1e6, ch) == []  # no power limit given
    assert lc.check_setpoint("CR", 1e6, ch) == []  # resistance has no limit


def test_protections_set_the_level_then_enable_or_disable():
    c = lc.LoadControls(calls=["set_ovp_level", "enable_ovp", "disable_ovp", "enable_ocp"])
    assert lc.protection_calls(c, "ovp", True, 30, None) == [
        ("set_ovp_level", {"value": 30.0}),
        ("enable_ovp", {}),
    ]
    assert lc.protection_calls(c, "ovp", False, 30, None) == [("disable_ovp", {})]
    assert lc.protection_calls(c, "ocp", False, None, None) == []  # cannot be switched off


def test_channel_numbers_come_from_the_channel_id():
    assert lc.channel_number({"channel_id": "CH2"}) == 2
    assert lc.channel_number({"channel_id": 3}) == 3
    assert lc.channel_number({}) is None


# ----- the panel ---------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FULL = lc.LoadControls(
    calls=["set_mode", "set_current_level", "set_voltage_level", "load_on", "load_off",
           "read_voltage", "read_current", "set_ovp_level", "enable_ovp", "disable_ovp"],
    modes=["CC", "CV"],
    readings=[("read_voltage", "V"), ("read_current", "A")],
    protections=["ovp"],
)
CHANNEL = {"name": "CH1", "max_current": 10.0, "max_voltage": 60.0}


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make(controls=FULL, channel=CHANNEL, fail=None):
    from frontend.core.Translator import Translator
    from frontend.ui.ElectronicLoadPanel import ElectronicLoadPanel

    sent = []

    def run(call, **args):
        if fail and call == fail:
            raise RuntimeError("TRN-002 timeout")
        sent.append((call, args))
        return {"read_voltage": 12.0, "read_current": 1.5}.get(call)

    return ElectronicLoadPanel("LOAD - CH1", controls, channel, run, Translator().t), sent


@pytest.mark.gui
def test_the_setpoint_goes_with_the_mode(app):
    panel, sent = make()
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("CV"))
    assert panel.unit.text() == "V"
    panel.setpoint.setText("24")
    assert panel.apply_setpoint()
    assert sent == [("set_mode", {"mode": "CV"}), ("set_voltage_level", {"value": 24.0})]


@pytest.mark.gui
def test_a_setpoint_above_the_limit_is_not_sent(app):
    panel, sent = make()
    panel.setpoint.setText("11")  # CC, limit 10 A
    assert not panel.apply_setpoint()
    assert sent == [] and "limit" in panel.status.text()


@pytest.mark.gui
def test_input_readings_and_protection(app):
    panel, sent = make()
    panel.input_button.click()
    assert sent[-1] == ("load_on", {}) and panel.input_button.isChecked()
    assert panel.read()
    assert panel.readings_label.text() == "12 V   1.5 A"
    w = panel.protection_widgets["ovp"]
    w["level"].setText("30")
    assert panel.apply_protection("ovp")
    assert sent[-2:] == [("set_ovp_level", {"value": 30.0}), ("enable_ovp", {})]
    panel, _ = make(fail="load_on")
    panel.input_button.click()
    assert not panel.input_button.isChecked() and "TRN-002" in panel.status.text()


@pytest.mark.gui
def test_a_model_not_in_the_library_has_no_control(app):
    panel, _ = make(controls=lc.LoadControls())
    assert panel.mode_combo is None


@pytest.mark.gui
@needs_library
def test_the_remote_control_tab_uses_the_load_panel(app, tmp_path, monkeypatch):
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.ElectronicLoadPanel import ElectronicLoadPanel
    from frontend.ui.RemoteControlTab import RemoteControlTab

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    load = {
        "instrument_type": "electronic_load",
        "instance_name": "LOAD",
        "model": "EL4913A",
        "model_id": "EL_Keysight_EL4913A",
        "visa_address": "TCPIP0::127.0.0.1::inst0::INSTR",
        "num_channels": 1,
        "channels": [{"enabled": True, "name": "CH1", "channel_id": "CH1",
                      "max_current": 10.0, "max_voltage": 60.0}],
    }
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": [load]}), encoding="utf-8")
    tab = RemoteControlTab(li)
    calls = []
    monkeypatch.setattr(tab, "run_call", lambda inst, ch, call, **args: calls.append(
        (inst["instance_name"], ch, call, args)))
    tab.load_instruments(str(path))
    panels = tab.findChildren(ElectronicLoadPanel)
    assert len(panels) == 1
    panels[0].setpoint.setText("2")
    assert panels[0].apply_setpoint()
    assert ("LOAD", None, "set_current_level", {"value": 2.0}) in calls  # no channel argument
    timer = getattr(tab, "measurement_timer", None)
    if timer is not None:
        timer.stop()
