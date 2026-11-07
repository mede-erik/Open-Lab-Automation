# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Datalogger calls: readings as list of numbers, scan setup (needs the real library)."""

import os

import pytest

from ola.call_planner import plan_call
from ola.library import Library

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
pytestmark = pytest.mark.skipif(LIB is None, reason="library not available")

MODELS = ["DL_Agilent_34970A", "DL_Keysight_DAQ970A", "DL_Keysight_DAQ973A"]


@pytest.mark.parametrize("model", MODELS)
def test_read_scan_is_a_list_of_numbers(model):
    plan = plan_call(Library.load(LIB), model, "read_scan")
    assert [s["text"] for s in plan.steps] == ["READ?"]
    assert plan.interpret(["+1.50E+00,-2.0E-01,+3.0E+00"]) == [1.5, -0.2, 3.0]


@pytest.mark.parametrize("model", MODELS)
def test_scan_setup_calls(model):
    lib = Library.load(LIB)
    assert plan_call(lib, model, "select_channels", {"channels": "101:103"}).steps[0]["text"] == (
        "ROUT:SCAN (@101:103)"
    )
    assert plan_call(lib, model, "read_and_remove", {"max_count": 5}).steps[0]["text"] == "R? 5"
    text = plan_call(
        lib,
        model,
        "configure_dc_voltage",
        {"range": "AUTO", "resolution": 0.001, "channels": "101"},
    ).steps[0]["text"]
    assert text == "CONF:VOLT:DC AUTO,0.001,(@101)"
