"""The example project must stay consistent with the instrument library."""

import json
import os

import pytest

from ola.call_planner import plan_call
from ola.datalogger_setup import datalogger_calls
from ola.library import Library
from ola.manual_instrument import manual_handle_from_inst
from ola.was_calls import oscilloscope_calls_from_was

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.join(HERE, "examples", "test-dcdc-project")
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
pytestmark = pytest.mark.skipif(LIB is None, reason="library not available")


def load(name):
    with open(os.path.join(PROJECT, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def library():
    return Library.load(LIB)


@pytest.fixture(scope="module")
def instruments():
    return load("test_instruments.inst")["instruments"]


def test_library_instruments_exist_and_respect_their_limits(library, instruments):
    checked = 0
    for inst in instruments:
        if inst.get("is_manual"):
            assert "model_id" not in inst, "a manual instrument is not a library model"
            continue
        ref = library.find_model(inst["model_id"])
        assert ref is not None, inst["model_id"]
        caps = ref.model.get("capabilities", {})
        for ch, spec in zip(inst["channels"], caps.get("channels", [])):
            if "voltage_output" in spec:
                assert ch["max_voltage"] <= spec["voltage_output"]["max"], ch["name"]
                assert ch["max_current"] <= spec["current_output"]["max"], ch["name"]
        checked += 1
    assert checked == 3


def test_manual_instruments_make_a_handle(library, instruments):
    manual = [i for i in instruments if i.get("is_manual")]
    assert {i["instrument_type"] for i in manual} == {"power_supply", "electronic_load"}
    for inst in manual:
        assert inst["num_channels"] == 1 and len(inst["channels"]) == 1
        handle = manual_handle_from_inst(inst, library)
        on_call = "load_on" if inst["instrument_type"] == "electronic_load" else "output_on"
        assert handle.supports(on_call)


def test_datalogger_configuration_plans_for_its_model(library, instruments):
    logger = next(i for i in instruments if i["instrument_type"] == "datalogger")
    calls = datalogger_calls(logger["channels"])
    assert calls[-1] == ("select_channels", {"channels": "101,102,103"})
    for name, args in calls:
        assert plan_call(library, logger["model_id"], name, args).steps


def test_oscilloscope_settings_plan_for_its_model(library, instruments):
    scope = next(i for i in instruments if i["instrument_type"] == "oscilloscope")
    for name, args in oscilloscope_calls_from_was(load("osc1.was")):
        assert plan_call(library, scope["model_id"], name, args).steps, name


def test_project_variables_are_defined_by_the_instruments(instruments):
    project = load("Test DC-DC Converter.json")
    names = {c["name"] for i in instruments for c in i["channels"]}
    assert set(project["control_variables"]) <= names
    assert set(project["measure_variables"]) <= names
    assert project["inst_file"] == "test_instruments.inst"
    assert set(project["was_files"]) | set(project["eff_files"]) <= set(os.listdir(PROJECT))
    eff = load("eff.eff")
    assert {s["variable"] for s in eff["sweeps"]} <= names
    assert set(eff["measured_variables"]) <= names
