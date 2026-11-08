# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The multimeter type in the instrument lists, and the calls of its schema."""

import glob
import json
import os

import pytest

from frontend.core.LoadInstruments import LoadInstruments
from ola.call_planner import plan_call

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(HERE, "frontend", "lang")

SERIES = {
    "series_id": "Agilent_34401A_Series",
    "series_name": "Agilent 34401A",
    "models": [{"id": "MTR_Agilent_34401A", "name": "Agilent 34401A"}],
}


def test_the_type_is_in_the_lists(tmp_path):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps({"multimeters_series": [SERIES]}), encoding="utf-8")
    library = LoadInstruments()
    library.load_instruments(str(path))
    assert LoadInstruments.get_series_key("multimeter") == "multimeters_series"
    assert "multimeter" in library.get_all_types()
    assert [s["series_id"] for s in library.get_series("multimeter")] == ["Agilent_34401A_Series"]


def test_the_type_has_a_name_in_every_language():
    paths = glob.glob(os.path.join(LANG, "*.json"))
    assert len(paths) == 5
    for path in paths:
        assert json.load(open(path, encoding="utf-8")).get("multimeter"), os.path.basename(path)


def _require(library, model_id):
    if library.find_model(model_id) is None or not library.schema("multimeters_series"):
        pytest.skip("the library has no multimeter schema yet")


@pytest.mark.parametrize(
    "model_id, call, args, texts",
    [
        ("MTR_Agilent_34401A", "set_function", {"function": "DC_VOLTAGE"},
         ['FUNCtion "VOLTage:DC"']),
        ("MTR_HP_3478A", "set_function", {"function": "RESISTANCE_4W"}, ["F4"]),
        ("MTR_Agilent_34401A", "set_range", {"function": "AC_CURRENT", "range": 1},
         ["CURRent:AC:RANGe 1"]),
        ("MTR_HP_3478A", "set_range", {"range": 1}, ["R0"]),  # 1 V: the 3 V range
        ("MTR_HP_3478A", "set_auto_range", {"state": True}, ["RA"]),
        ("MTR_HP_3478A", "set_trigger_source", {"source": "BUS"}, ["T4"]),
        ("MTR_Agilent_34401A", "measure_dc_voltage", {}, ["MEASure:VOLTage:DC? DEF,DEF"]),
    ],
)
def test_logical_calls_plan_the_commands_of_each_model(library, model_id, call, args, texts):
    _require(library, model_id)
    plan = plan_call(library, model_id, call, args)
    assert [s.get("text") for s in plan.steps] == texts


def test_the_3478a_reading_is_a_read_without_command(library):
    _require(library, "MTR_HP_3478A")
    plan = plan_call(library, "MTR_HP_3478A", "read_measurement")
    assert [s["op"] for s in plan.steps] == ["read"]
    assert plan.interpret([1.25]) == 1.25
