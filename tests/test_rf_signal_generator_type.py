# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The RF signal generator type in the instrument lists, and the calls of its schema."""

import glob
import json
import os

import pytest

from frontend.core.LoadInstruments import LoadInstruments
from ola.call_planner import plan_call

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(HERE, "frontend", "lang")

SERIES = {
    "series_id": "Keysight_EXG_Series",
    "series_name": "Keysight EXG",
    "models": [{"id": "RFGEN_Keysight_N5172B", "name": "Keysight N5172B"}],
}


def test_the_type_is_in_the_lists(tmp_path):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps({"rf_signal_generators_series": [SERIES]}), encoding="utf-8")
    library = LoadInstruments()
    library.load_instruments(str(path))
    assert LoadInstruments.get_series_key("rf_signal_generator") == "rf_signal_generators_series"
    assert "rf_signal_generator" in library.get_all_types()
    assert [s["series_id"] for s in library.get_series("rf_signal_generator")] == [
        "Keysight_EXG_Series"
    ]


def test_the_type_has_a_name_in_every_language():
    paths = glob.glob(os.path.join(LANG, "*.json"))
    assert len(paths) == 5
    for path in paths:
        catalog = json.load(open(path, encoding="utf-8"))
        assert catalog.get("rf_signal_generator"), os.path.basename(path)


MODELS = [
    "RFGEN_Keysight_N5171B",
    "RFGEN_Keysight_N5172B",
    "RFGEN_Keysight_N5181B",
    "RFGEN_Keysight_N5182B",
]


@pytest.mark.parametrize("model_id", MODELS)
@pytest.mark.parametrize(
    "call, args, texts",
    [
        ("identification_query", {}, ["*IDN?"]),
        ("reset", {}, ["*RST"]),
        ("clear_status", {}, ["*CLS"]),
        ("error_query", {}, ["SYSTem:ERRor?"]),
        ("set_frequency", {"value": 2.4e9}, ["FREQuency:CW 2400000000 Hz"]),
        ("query_frequency", {}, ["FREQuency:CW?"]),
        ("set_power_level", {"value": -10.5}, ["POWer:AMPLitude -10.5 dBm"]),
        ("query_power_level", {}, ["POWer:AMPLitude?"]),
        ("set_output_state", {"state": True}, ["OUTPut:STATe ON"]),
        ("set_output_state", {"state": False}, ["OUTPut:STATe OFF"]),
        ("query_output_state", {}, ["OUTPut:STATe?"]),
    ],
)
def test_logical_calls_plan_the_commands_of_the_family(library, model_id, call, args, texts):
    if library.find_model(model_id) is None:
        pytest.skip("the library has no RF signal generator yet")
    plan = plan_call(library, model_id, call, args)
    assert [s.get("text") for s in plan.steps] == texts


def test_the_output_state_answer_becomes_a_boolean(library):
    if library.find_model("RFGEN_Keysight_N5172B") is None:
        pytest.skip("the library has no RF signal generator yet")
    plan = plan_call(library, "RFGEN_Keysight_N5172B", "query_output_state")
    assert plan.interpret(["1"]) is True and plan.interpret(["0"]) is False


def test_a_value_the_family_cannot_give_is_not_a_crash(library):
    if library.find_model("RFGEN_Keysight_N5172B") is None:
        pytest.skip("the library has no RF signal generator yet")
    with pytest.raises(Exception, match="CALL-003|needs argument"):
        plan_call(library, "RFGEN_Keysight_N5172B", "set_frequency", {})
