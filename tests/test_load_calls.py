# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Electronic-load calls: same logical call for every brand (needs the real library)."""

import os

import pytest

from ola.call_errors import CallNotSupportedError
from ola.call_planner import plan_call
from ola.library import Library

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
pytestmark = pytest.mark.skipif(LIB is None, reason="library not available")

CHROMA, KEYSIGHT, SIGLENT = "EL_Chroma_6330A", "EL_Keysight_EL4913A", "EL_Siglent_SDL1030X_E"


def texts(model, call, args=None):
    return [s["text"] for s in plan_call(Library.load(LIB), model, call, args or {}).steps]


@pytest.mark.parametrize(
    "model,expected",
    [
        (CHROMA, "MODE CCL"),
        (KEYSIGHT, "FUNC CURRent"),
        (SIGLENT, "FUNC CURRent"),
    ],
)
def test_set_mode_cc(model, expected):
    assert texts(model, "set_mode", {"mode": "CC"}) == [expected]


@pytest.mark.parametrize(
    "model,expected",
    [
        (CHROMA, "LOAD ON"),
        (KEYSIGHT, "INP ON"),  # the manual's INPut|OUTPut is "either keyword", not text to send
        (SIGLENT, "INPut ON"),
    ],
)
def test_load_on(model, expected):
    assert texts(model, "load_on") == [expected]


def test_no_literal_alternatives_in_the_library():
    lib = Library.load(LIB)
    for series in lib.categories["electronic_loads_series"]:
        for name in series["common_scpi_commands"]:
            for model in series["models"]:
                for step in plan_call_safe(lib, model["id"], name):
                    assert "|" not in step


def plan_call_safe(lib, model_id, name):
    try:
        return [
            s["text"]
            for s in plan_call(lib, model_id, name, _sample_args(lib, model_id, name)).steps
        ]
    except Exception:
        return []


def _sample_args(lib, model_id, name):
    ref = lib.find_model(model_id)
    spec = lib.schema(ref.category)["calls"].get(name, {})
    out = {}
    for arg, a in spec.get("args", {}).items():
        out[arg] = {"int": 1, "float": 1.0, "string": "X"}.get(a["type"], "CC")
    return out


def test_dynamic_timing_from_frequency_and_duty():
    assert texts(CHROMA, "set_dynamic_timing", {"frequency": 1000, "duty": 25}) == [
        "CURR:DYN:T1 0.00025S",
        "CURR:DYN:T2 0.00075S",
    ]
    assert texts(SIGLENT, "set_dynamic_timing", {"frequency": 1000}) == [
        "CURR:TRAN:MODE CONT",
        "CURR:TRAN:AWID 0.0005",
        "CURR:TRAN:BWID 0.0005",
    ]  # duty default 50


def test_dynamic_mode_not_available_on_el4900():
    with pytest.raises(CallNotSupportedError):
        plan_call(Library.load(LIB), KEYSIGHT, "set_dynamic_timing", {"frequency": 1000})


def test_query_mode_and_state_are_logical():
    lib = Library.load(LIB)
    assert plan_call(lib, CHROMA, "query_mode").interpret(["CCDH"]) == "CC"
    assert plan_call(lib, KEYSIGHT, "query_mode").interpret(["VOLT"]) == "CV"
    assert plan_call(lib, SIGLENT, "query_input_state").interpret(["1"]) is True
