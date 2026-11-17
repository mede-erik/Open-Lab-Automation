# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The RF signal generator panel of the Remote control tab.

The carrier (frequency, power, output) and one box per modulation the model has (AM, FM, PM,
pulse); only what the model defines in the library is offered, the values are checked before
they are sent, and only logical calls are sent.
"""

import json
import os

import pytest

from ola import rf_controls as rc
from tests.conftest import LIBRARY_PATH

needs_library = pytest.mark.skipif(
    LIBRARY_PATH is None or not os.path.exists(
        os.path.join(os.path.dirname(LIBRARY_PATH or ""), "schema", "rf_signal_generator.json")
    ),
    reason="the library has no RF signal generator yet",
)
MODELS = ("RFGEN_Keysight_N5171B", "RFGEN_Keysight_N5172B", "RFGEN_Keysight_N5181B",
          "RFGEN_Keysight_N5182B")


def library():
    from ola.library import Library

    return Library.load(LIBRARY_PATH)


# ----- what the panel shows and sends (no Qt) ----------------------------------------------------
@needs_library
def test_controls_of_the_keysight_generators():
    c = rc.rf_controls(library(), "RFGEN_Keysight_N5171B")
    assert c.usable and (c.frequency_min, c.frequency_max) == (9e3, 6e9)
    assert (c.power_min, c.power_max) == (-144.0, 19.0)
    assert [k.kind for k in c.kinds] == ["AM", "FM", "PM", "PULSE"]
    am, pulse = c.kind("AM"), c.kind("PULSE")
    assert am.sources == ["INTERNAL", "INTERNAL_2", "EXTERNAL"]
    assert am.depth_call == "set_am_depth" and am.depth_unit == "%"
    assert c.kind("FM").depth_call == "set_fm_deviation" and c.kind("PM").depth_unit == "rad"
    assert pulse.sources == [] and pulse.depth_call == ""  # on or off only
    assert c.has("set_modulation_output_state")


def test_an_unknown_model_has_no_control():
    class Empty:
        def commands(self, model_id):
            return None

        def find_model(self, model_id):
            return None

    c = rc.rf_controls(Empty(), "nope")
    assert not c.usable and c.kinds == []


def test_the_carrier_is_checked_against_the_model():
    c = rc.RfControls(frequency_min=9e3, frequency_max=6e9, power_min=-144.0, power_max=19.0)
    assert rc.check_carrier(c, 1e9, -10.0) == []
    assert rc.check_carrier(c, 1e3, None) == ["rf_err_frequency_low"]
    assert rc.check_carrier(c, 7e9, 25.0) == ["rf_err_frequency_high", "rf_err_power_high"]
    assert rc.check_carrier(c, None, -200.0) == ["rf_err_power_low"]
    assert rc.carrier_calls(c, 1e9, None) == [("set_frequency", {"value": 1e9})]
    assert rc.output_calls(True) == [("set_output_state", {"state": True})]


@needs_library
def test_am_with_an_internal_source_is_configured_then_switched_on():
    c = rc.rf_controls(library(), "RFGEN_Keysight_N5171B")
    assert rc.modulation_calls(c, "AM", True, "INTERNAL_2", 1000.0, 30.0, "TRIANGLE", "DC") == [
        ("set_modulation_source", {"kind": "AM", "source": "INTERNAL_2"}),
        ("set_modulation_rate", {"kind": "AM", "value": 1000.0, "source": "INTERNAL_2"}),
        ("set_am_depth", {"value": 30.0}),
        ("set_modulation_waveform", {"kind": "AM", "shape": "TRIANGLE"}),  # coupling: no
        ("set_modulation_state", {"kind": "AM", "state": True}),  # last
    ]


@needs_library
def test_the_external_source_has_a_coupling_and_no_rate():
    c = rc.rf_controls(library(), "RFGEN_Keysight_N5171B")
    assert rc.modulation_calls(c, "FM", True, "EXTERNAL", 1000.0, 5e3, "SINE", "AC") == [
        ("set_modulation_source", {"kind": "FM", "source": "EXTERNAL"}),
        ("set_fm_deviation", {"value": 5000.0}),
        ("set_modulation_external_coupling", {"kind": "FM", "coupling": "AC"}),
        ("set_modulation_state", {"kind": "FM", "state": True}),
    ]


@needs_library
def test_the_waveform_is_for_the_second_internal_generator_only():
    c = rc.rf_controls(library(), "RFGEN_Keysight_N5171B")
    first = [n for n, _ in rc.modulation_calls(c, "AM", True, "INTERNAL", 1e3, 30.0, "SQUARE")]
    assert "set_modulation_waveform" not in first  # the library documents it for generator 2
    assert not rc.shape_applies(c.kind("AM"), "EXTERNAL")


@needs_library
def test_disabling_and_pulse_send_only_the_state():
    c = rc.rf_controls(library(), "RFGEN_Keysight_N5171B")
    assert rc.modulation_calls(c, "AM", False, "INTERNAL", 1e3, 30.0) == [
        ("set_modulation_state", {"kind": "AM", "state": False})
    ]
    assert rc.modulation_calls(c, "PULSE", True, "INTERNAL", 1e3, 30.0) == [
        ("set_modulation_state", {"kind": "PULSE", "state": True})
    ]
    assert rc.modulation_calls(c, "XX", True) == []
    assert rc.master_calls(c, True) == [("set_modulation_output_state", {"state": True})]


@needs_library
def test_every_call_the_panel_can_send_is_accepted_by_the_planner():
    from ola.call_planner import plan_call

    lib = library()
    for model in MODELS:
        c = rc.rf_controls(lib, model)
        calls = rc.carrier_calls(c, 1e9, -10.0) + rc.output_calls(True) + rc.master_calls(c, True)
        for info in c.kinds:
            for source in info.sources or [None]:
                for shape in info.shapes or [None]:
                    for coupling in info.couplings or [None]:
                        calls += rc.modulation_calls(
                            c, info.kind, True, source, 1e3, 10.0, shape, coupling
                        )
            calls += rc.modulation_calls(c, info.kind, False)
        assert len(calls) > 10
        for name, args in calls:
            plan_call(lib, model, name, args)


# ----- the panel ---------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def keysight():
    mods = [
        rc.ModulationKind("AM", ["INTERNAL", "INTERNAL_2", "EXTERNAL"], ["INTERNAL", "INTERNAL_2"],
                          ["SINE", "SQUARE"], ["AC", "DC"], "set_am_depth", "%"),
        rc.ModulationKind("PULSE"),
    ]
    calls = ["set_frequency", "set_power_level", "set_output_state", "set_modulation_state",
             "set_modulation_output_state", "set_modulation_source", "set_modulation_rate",
             "set_modulation_waveform", "set_modulation_external_coupling", "set_am_depth"]
    return rc.RfControls(calls, mods, 9e3, 6e9, -144.0, 19.0)


def make(controls=None, fail=None):
    from frontend.core.Translator import Translator
    from frontend.ui.RfGeneratorPanel import RfGeneratorPanel

    sent = []

    def run(call, **args):
        if fail and call == fail:
            raise RuntimeError("CALL-002 not handled")
        sent.append((call, args))

    return RfGeneratorPanel(controls or keysight(), run, Translator().t), sent


@pytest.mark.gui
def test_the_carrier_is_sent_with_the_prefixes_of_the_frequency(app):
    panel, sent = make()
    panel.frequency.setText("433.92M")
    panel.power.setText("-10,5")
    assert panel.apply_carrier()
    assert sent == [("set_frequency", {"value": 433.92e6}), ("set_power_level", {"value": -10.5})]
    panel.output_button.click()
    assert sent[-1] == ("set_output_state", {"state": True}) and panel.output_button.isChecked()


@pytest.mark.gui
def test_a_carrier_out_of_the_range_is_not_sent(app):
    panel, sent = make()
    panel.frequency.setText("8G")
    assert not panel.apply_carrier()
    assert sent == [] and "maximum" in panel.status.text()
    panel.frequency.setText("abc")
    assert not panel.apply_carrier() and sent == []


@pytest.mark.gui
def test_a_box_per_modulation_and_the_fields_follow_the_source(app):
    panel, sent = make()
    assert list(panel.kinds) == ["AM", "PULSE"]
    am, pulse = panel.kinds["AM"], panel.kinds["PULSE"]
    assert set(pulse) == {"info", "enabled", "apply"}  # pulse: on or off only
    am["source"].setCurrentIndex(am["source"].findData("EXTERNAL"))
    assert am["coupling"].isEnabled() and not am["rate"].isEnabled()
    assert not am["shape"].isEnabled()
    am["source"].setCurrentIndex(am["source"].findData("INTERNAL_2"))
    assert not am["coupling"].isEnabled() and am["rate"].isEnabled() and am["shape"].isEnabled()


@pytest.mark.gui
def test_am_is_set_and_switched_on(app):
    panel, sent = make()
    am = panel.kinds["AM"]
    am["enabled"].setChecked(True)
    am["source"].setCurrentIndex(am["source"].findData("INTERNAL_2"))
    am["rate"].setText("1k")
    am["depth"].setText("30")
    assert panel.apply_modulation("AM")
    assert sent == [
        ("set_modulation_source", {"kind": "AM", "source": "INTERNAL_2"}),
        ("set_modulation_rate", {"kind": "AM", "value": 1000.0, "source": "INTERNAL_2"}),
        ("set_am_depth", {"value": 30.0}),
        ("set_modulation_waveform", {"kind": "AM", "shape": "SINE"}),
        ("set_modulation_state", {"kind": "AM", "state": True}),
    ]
    sent.clear()
    am["enabled"].setChecked(False)
    assert panel.apply_modulation("AM")
    assert sent == [("set_modulation_state", {"kind": "AM", "state": False})]


@pytest.mark.gui
def test_the_master_switch_and_errors(app):
    panel, sent = make()
    panel.master_button.click()
    assert sent == [("set_modulation_output_state", {"state": True})]
    panel, _ = make(fail="set_modulation_output_state")
    panel.master_button.click()
    assert not panel.master_button.isChecked() and "CALL-002" in panel.status.text()
    panel, _ = make(fail="set_am_depth")
    panel.kinds["AM"]["enabled"].setChecked(True)
    panel.kinds["AM"]["depth"].setText("30")
    assert not panel.apply_modulation("AM") and "CALL-002" in panel.status.text()
    panel.kinds["AM"]["depth"].setText("-1")
    assert not panel.apply_modulation("AM") and "negative" in panel.status.text()


@pytest.mark.gui
def test_a_model_without_the_calls_shows_a_message(app):
    panel, _ = make(rc.RfControls())
    assert panel.kinds == {} and not hasattr(panel, "frequency")


@pytest.mark.gui
@needs_library
def test_the_remote_control_tab_shows_the_panel_of_an_rf_generator(app, tmp_path, monkeypatch):
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.RemoteControlTab import RemoteControlTab
    from frontend.ui.RfGeneratorPanel import RfGeneratorPanel

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    gen = {"instrument_type": "rf_signal_generator", "instance_name": "RF", "model": "N5171B",
           "model_id": "RFGEN_Keysight_N5171B", "visa_address": "TCPIP0::127.0.0.1::inst0::INSTR",
           "channels": []}
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": [gen]}), encoding="utf-8")
    tab = RemoteControlTab(li)
    calls = []
    monkeypatch.setattr(tab, "run_call", lambda inst, ch, call, **args: calls.append(
        (inst["instance_name"], ch, call, args)))
    tab.load_instruments(str(path))
    panels = tab.findChildren(RfGeneratorPanel)
    assert len(panels) == 1 and list(panels[0].kinds) == ["AM", "FM", "PM", "PULSE"]
    panels[0].frequency.setText("1G")
    assert panels[0].apply_carrier()
    assert ("RF", None, "set_frequency", {"value": 1e9}) in calls  # no channel argument
    timer = getattr(tab, "measurement_timer", None)
    if timer is not None:
        timer.stop()


@pytest.mark.gui
def test_the_settings_of_a_modulation_show_only_when_it_is_enabled(app):
    """The fields of a modulation take room: they are shown when its tick is set, not before."""
    panel, _sent = make()
    panel.show()
    am = panel.kinds["AM"]
    assert not am["source"].isVisibleTo(panel) and not am["apply"].isVisibleTo(panel)
    am["enabled"].setChecked(True)
    assert am["source"].isVisibleTo(panel) and am["apply"].isVisibleTo(panel)
    am["enabled"].setChecked(False)
    assert not am["source"].isVisibleTo(panel)
