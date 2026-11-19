# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A multimeter is set by its .inst entry, as a datalogger is, and the Remote control tab only
shows its value: function and range of its (one) channel, sent once and again only when the file
changes."""

import json
import os

import pytest

from ola import multimeter_setup as ms
from tests.conftest import LIBRARY_PATH

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")
EDITOR_TYPES = ["DC_V", "DC_A", "AC_V", "AC_A", "RES", "FREQ"]  # what the instrument editor offers


def test_function_and_automatic_range_from_the_channel():
    assert ms.multimeter_calls({"meas_type": "AC_A"}) == [
        ("set_function", {"function": "AC_CURRENT"}),
        ("set_auto_range", {"function": "AC_CURRENT", "state": True}),
    ]
    assert ms.multimeter_calls({"meas_type": "DC_V", "range": "10"}) == [
        ("set_function", {"function": "DC_VOLTAGE"}),
        ("set_range", {"function": "DC_VOLTAGE", "range": 10.0}),
    ]
    assert ms.multimeter_calls({})[0] == ("set_function", {"function": "DC_VOLTAGE"})


def test_range_calls_only_if_the_model_has_them():
    assert ms.multimeter_calls({"meas_type": "RES"}, lambda call, function: False) == [
        ("set_function", {"function": "RESISTANCE_2W"})
    ]
    commands = {
        "set_auto_range": {"parameters": {"function": {"map": {"DC_VOLTAGE": "VOLT"}}}},
        "set_range": {"parameters": {}},
    }
    accepts = ms.accepts_from(commands)
    assert accepts("set_auto_range", "DC_VOLTAGE") and not accepts("set_auto_range", "FREQUENCY")
    assert accepts("set_range", "FREQUENCY") and not accepts("set_function", "DC_VOLTAGE")
    assert ms.multimeter_calls({"meas_type": "FREQ"}, accepts) == [
        ("set_function", {"function": "FREQUENCY"})
    ]


def test_bad_entries_say_which_channel():
    with pytest.raises(ms.MultimeterSetupError, match="VIN"):
        ms.multimeter_calls({"name": "VIN", "meas_type": "TEMP"})
    with pytest.raises(ms.MultimeterSetupError, match="not a number"):
        ms.multimeter_calls({"name": "VIN", "range": "big"})


def test_one_input_the_first_enabled_channel():
    channels = [{"name": "A", "enabled": False}, {"name": "B"}, {"name": "C"}]
    assert ms.measured_channel(channels)["name"] == "B"
    assert ms.measured_channel([{"name": "A", "enabled": False}]) is None


def test_the_signature_follows_the_file():
    assert ms.signature({"meas_type": "DC_V"}) == ms.signature({"meas_type": "dc_v", "range": ""})
    assert ms.signature({"meas_type": "DC_V"}) != ms.signature({"meas_type": "DC_V", "range": 10})


@needs_library
def test_the_calls_are_accepted_by_the_library_models():
    from ola.call_errors import CallError
    from ola.call_planner import plan_call
    from ola.library import Library

    lib = Library.load(LIBRARY_PATH)
    for model, missing in (("MTR_Agilent_34401A", set()), ("MTR_HP_3478A", {"FREQ"})):
        commands = lib.commands(model)
        for meas in EDITOR_TYPES:
            for channel in ({"meas_type": meas}, {"meas_type": meas, "range": 10}):
                calls = ms.multimeter_calls(channel, ms.accepts_from(commands))
                if meas in missing:  # the HP 3478A cannot measure frequency
                    with pytest.raises(CallError):
                        plan_call(lib, model, *calls[0])
                    continue
                for name, args in calls:
                    plan_call(lib, model, name, args)


# ----- the Remote control tab ---------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.gui
@needs_library
def test_the_tab_sets_the_meter_once_and_shows_its_value(app, tmp_path, monkeypatch):
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.RemoteControlTab import RemoteControlTab

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    dmm = {"instrument_type": "multimeter", "instance_name": "DMM", "model": "34401A",
           "model_id": "MTR_Agilent_34401A", "visa_address": "GPIB0::22::INSTR",
           "channels": [{"enabled": True, "name": "VIN", "meas_type": "AC_V", "unit": "V",
                         "attenuation": 2.0},
                        {"enabled": True, "name": "EXTRA", "meas_type": "DC_A"}]}
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": [dmm]}), encoding="utf-8")
    tab = RemoteControlTab(li)
    calls = []

    def run_call(inst, ch, call, **args):
        calls.append((ch, call, args))
        return 3.0 if call == "read_measurement" else None

    monkeypatch.setattr(tab, "run_call", run_call)
    monkeypatch.setattr(tab, "get_visa_instrument", lambda inst: object())
    tab.load_instruments(str(path))
    if getattr(tab, "measurement_timer", None) is not None:
        tab.measurement_timer.stop()
    assert [ch["name"] for _, ch in tab.meas_vars] == ["VIN"]  # one input
    tab.refresh_measurements_auto()
    assert calls == [
        (None, "set_function", {"function": "AC_VOLTAGE"}),
        (None, "set_auto_range", {"function": "AC_VOLTAGE", "state": True}),
        (None, "read_measurement", {}),
    ]
    assert tab.meas_labels[("DMM", "VIN")].text() == "VIN = 1.500 V"
    calls.clear()
    tab.refresh_measurements_auto()
    assert calls == [(None, "read_measurement", {})]  # the file did not change: only read
    dmm["channels"][0]["range"] = 100
    path.write_text(json.dumps({"instruments": [dmm]}), encoding="utf-8")
    tab.load_instruments(str(path))
    if getattr(tab, "measurement_timer", None) is not None:
        tab.measurement_timer.stop()
    calls.clear()
    tab.refresh_measurements_auto()
    assert calls[1] == (None, "set_range", {"function": "AC_VOLTAGE", "range": 100.0})
