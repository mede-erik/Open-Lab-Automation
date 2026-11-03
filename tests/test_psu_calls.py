"""Power-supply calls: the same logical call for every brand (needs the real library)."""

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


def texts(model, call, args=None):
    return [s["text"] for s in plan_call(Library.load(LIB), model, call, args or {}).steps]


@pytest.mark.parametrize(
    "model,expected",
    [
        ("PSU_OWON_ODP3033", ["INST:NSEL 2", "VOLT 5"]),
        ("PSU_Keysight_E36311A", ["INST:SEL CH2", "VOLT 5"]),
        ("PSU_Rohde_Schwarz_HMP4040", ["INST:SEL OUT2", "VOLT 5"]),
        ("PSU_HP_E3631A", ["INSTrument:NSELect 2", "VOLTage 5"]),
        ("PSU_TDK_GEN80_19", ["VOLT 5"]),
    ],
)
def test_set_voltage_selects_the_channel(model, expected):
    assert texts(model, "set_voltage", {"channel_number": 2, "value": 5}) == expected


@pytest.mark.parametrize(
    "model,expected",
    [
        ("PSU_OWON_ODP3033", ["INST:NSEL 3", "MEAS:CURR?"]),
        ("PSU_Keysight_E36311A", ["MEAS:CURR? CH3"]),
        ("PSU_Rohde_Schwarz_HMP4040", ["INST:SEL OUT3", "MEAS:CURR?"]),
        ("PSU_HP_E3631A", ["MEASure:CURRent? N25V"]),
        ("PSU_TDK_GEN80_19", ["MEAS:CURR?"]),
    ],
)
def test_read_current(model, expected):
    assert texts(model, "read_current", {"channel_number": 3}) == expected


@pytest.mark.parametrize(
    "model",
    [
        "PSU_OWON_ODP3033",
        "PSU_Keysight_E36311A",
        "PSU_Rohde_Schwarz_HMP4040",
        "PSU_HP_E3631A",
        "PSU_TDK_GEN80_19",
    ],
)
def test_output_state_is_boolean(model):
    plan = plan_call(Library.load(LIB), model, "output_state_query")
    assert plan.interpret(["1"]) is True and plan.interpret(["0"]) is False
    assert plan.interpret(["ON"]) is True and plan.interpret(["OFF"]) is False
