# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The multimeter / datalogger panel of the Remote control tab.

One row per enabled channel with function, range and value; only the functions the model
defines in the library are offered (``ola.meter_controls``), and only logical calls are sent.
"""

import json
import os

import pytest

from ola import meter_controls as mc
from tests.conftest import LIBRARY_PATH

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")


def library():
    from ola.library import Library

    return Library.load(LIBRARY_PATH)


DL_CHANNELS = [
    {"enabled": True, "name": "VOUT", "slot_number": 1, "channel_id": "103",
     "meas_type": "VOLT:DC"},
    {"enabled": True, "name": "R1", "slot_number": 1, "channel_id": "101", "meas_type": "RES",
     "attenuation": 2.0},
]


# ----- what the panel shows and sends (no Qt) ---------------------------------------------------
@needs_library
def test_multimeter_functions_are_the_ones_the_model_translates():
    hp = mc.meter_controls(library(), "MTR_HP_3478A", "multimeter")
    assert hp.kind == mc.MULTIMETER
    assert "DC_VOLTAGE" in hp.functions and "FREQUENCY" not in hp.functions  # the 3478A has none
    agilent = mc.meter_controls(library(), "MTR_Agilent_34401A", "multimeter")
    assert "FREQUENCY" in agilent.functions and "EXTENDED_RESISTANCE" not in agilent.functions


@needs_library
def test_datalogger_types_follow_the_configure_calls():
    c = mc.meter_controls(library(), "DL_Agilent_34970A", "datalogger")
    assert c.kind == mc.DATALOGGER
    assert {"VOLT:DC", "RES", "TEMP"} <= set(c.functions)


@needs_library
def test_every_call_the_panel_sends_is_accepted_by_the_planner():
    from ola.call_planner import plan_call

    lib = library()
    for model in ("MTR_HP_3478A", "MTR_Agilent_34401A"):
        c = mc.meter_controls(lib, model, "multimeter")
        for function in c.functions:
            for range_ in ("AUTO", 10.0):
                for name, args in mc.multimeter_calls(c, function, range_):
                    plan_call(lib, model, name, args)
        plan_call(lib, model, "read_measurement", {})
    dl = mc.meter_controls(lib, "DL_Agilent_34970A", "datalogger")
    rows = mc.datalogger_rows(DL_CHANNELS, {0: ("VOLT:AC", 10.0)})
    for name, args in mc.datalogger_setup(rows):
        plan_call(lib, "DL_Agilent_34970A", name, args)
    plan_call(lib, "DL_Agilent_34970A", "read_scan", {})
    assert dl.has("read_scan")


def test_an_unknown_or_incomplete_model_has_no_control():
    class Lib:
        def commands(self, model_id):
            return {"read_measurement": {}}

    assert mc.meter_controls(Lib(), "x", "multimeter").kind == ""
    assert mc.meter_controls(Lib(), "x", "datalogger").kind == ""


def test_ranges_and_defaults():
    assert mc.parse_range("") == "AUTO" and mc.parse_range("auto") == "AUTO"
    assert mc.parse_range("0,1") == 0.1
    for bad in ("abc", "-1", "0"):
        with pytest.raises(mc.RangeError):
            mc.parse_range(bad)
    c = mc.MeterControls(mc.MULTIMETER, [], ["DC_VOLTAGE", "AC_CURRENT"])
    assert mc.default_function(c, {"meas_type": "CURR:AC"}) == "AC_CURRENT"
    assert mc.default_function(c, {"meas_type": "FREQ"}) == "DC_VOLTAGE"  # not on this model
    assert mc.multimeter_calls(
        mc.MeterControls(mc.MULTIMETER, ["set_function", "set_range"], ["DC_VOLTAGE"],
                         range_functions=["DC_VOLTAGE"]), "DC_VOLTAGE", 10.0
    ) == [("set_function", {"function": "DC_VOLTAGE"}),
          ("set_range", {"function": "DC_VOLTAGE", "range": 10.0})]


def test_scan_readings_go_back_to_their_rows():
    rows = [dict(c) for c in DL_CHANNELS]  # 103 first in the file, 101 first in the scan
    assert mc.datalogger_values(rows, [5.0, 3.3]) == [3.3, 5.0]
    assert mc.datalogger_values(rows, [5.0]) == [None, 5.0]
    assert mc.scaled(10.0, {"attenuation": 2}) == 5.0 and mc.scaled("x", {}) is None


# ----- the panel ---------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make(controls, channels, answers=None, fail=None):
    from frontend.core.Translator import Translator
    from frontend.ui.MeterPanel import MeterPanel

    sent = []

    def run(call, **args):
        if fail and call == fail:
            raise RuntimeError("TRN-002 timeout")
        sent.append((call, args))
        return (answers or {}).get(call)

    return MeterPanel("METER", controls, channels, run, Translator().t), sent


DMM = mc.MeterControls(
    mc.MULTIMETER,
    ["set_function", "set_auto_range", "set_range", "read_measurement"],
    ["DC_VOLTAGE", "AC_VOLTAGE"],
    range_functions=["DC_VOLTAGE", "AC_VOLTAGE"],
    auto_range_functions=["DC_VOLTAGE", "AC_VOLTAGE"],
)
DL = mc.MeterControls(mc.DATALOGGER, ["select_channels", "read_scan", "configure_dc_voltage",
                                      "configure_resistance"], ["VOLT:DC", "RES"])


@pytest.mark.gui
def test_a_multimeter_is_set_then_read(app):
    panel, sent = make(DMM, [{"name": "VIN", "meas_type": "VOLT:AC"}], {"read_measurement": 1.25})
    row = panel.rows[0]
    assert row["function"].currentData() == "AC_VOLTAGE"  # from the .inst file
    assert panel.read()
    assert sent == [("set_function", {"function": "AC_VOLTAGE"}),
                    ("set_auto_range", {"function": "AC_VOLTAGE", "state": True}),
                    ("read_measurement", {})]
    assert row["value"].text() == "1.2500 V"
    sent.clear()
    assert panel.read()
    assert sent == [("read_measurement", {})]  # settings unchanged: not sent again
    row["range"].setText("10")
    assert panel.read()
    assert ("set_range", {"function": "AC_VOLTAGE", "range": 10.0}) in sent


@pytest.mark.gui
def test_a_datalogger_is_configured_and_each_value_goes_to_its_row(app):
    panel, sent = make(DL, DL_CHANNELS, {"read_scan": [8.0, 3.3]})
    assert panel.read()
    names = [c for c, _ in sent]
    assert names[-2:] == ["select_channels", "read_scan"] and "configure_dc_voltage" in names
    assert panel.rows[0]["value"].text() == "3.3000 V"  # channel 103
    assert panel.rows[1]["value"].text() == "4.0000 Ω"  # channel 101, attenuation 2


@pytest.mark.gui
def test_a_bad_range_and_a_failing_call_are_shown(app):
    panel, sent = make(DMM, [{"name": "VIN"}])
    panel.rows[0]["range"].setText("abc")
    assert not panel.read() and sent == []
    assert "positive number" in panel.status.text()
    panel, _ = make(DMM, [{"name": "VIN"}], fail="read_measurement")
    assert not panel.read() and "TRN-002" in panel.status.text()


@pytest.mark.gui
def test_continuous_reading_stops_on_error(app):
    panel, sent = make(DMM, [{"name": "VIN"}], {"read_measurement": 1.0})
    panel.continuous.setChecked(True)
    assert panel.timer.isActive()
    panel.run = lambda call, **a: (_ for _ in ()).throw(RuntimeError("lost"))
    panel._tick()
    assert not panel.continuous.isChecked() and not panel.timer.isActive()
    panel.continuous.setChecked(True)
    panel.stop_reading()
    assert not panel.timer.isActive()


@pytest.mark.gui
def test_no_control_without_library_model_or_channels(app):
    panel, _ = make(mc.MeterControls(), [{"name": "X"}])
    assert panel.rows == []
    panel, _ = make(DMM, [])
    assert panel.rows == []


@pytest.mark.gui
@needs_library
def test_the_remote_control_tab_uses_the_meter_panel(app, tmp_path, monkeypatch):
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.MeterPanel import MeterPanel
    from frontend.ui.RemoteControlTab import RemoteControlTab

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    dmm = {"instrument_type": "multimeter", "instance_name": "DMM", "model": "34401A",
           "model_id": "MTR_Agilent_34401A", "visa_address": "GPIB0::22::INSTR",
           "channels": [{"enabled": True, "name": "VIN", "meas_type": "VOLT:DC"}]}
    unknown = {"instrument_type": "multimeter", "instance_name": "OLD", "model": "nope",
               "model_id": "nope", "channels": [{"enabled": True, "name": "X"}]}
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": [dmm, unknown]}), encoding="utf-8")
    tab = RemoteControlTab(li)
    calls = []
    monkeypatch.setattr(tab, "run_call", lambda inst, ch, call, **args: calls.append(
        (inst["instance_name"], ch, call)) or 2.0)
    tab.load_instruments(str(path))
    panels = tab.findChildren(MeterPanel)
    assert len(panels) == 1 and panels[0].read()
    assert ("DMM", None, "set_function") in calls
    assert [inst["instance_name"] for inst, _ in tab.meas_vars] == ["OLD"]  # plain readings
    tab.load_instruments(str(path))  # reloading stops the old panels
    timer = getattr(tab, "measurement_timer", None)
    if timer is not None:
        timer.stop()
