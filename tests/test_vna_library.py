"""The SCPI network analyzers of the library: the commands of the manuals and their data."""

import os

import pytest

from ola.call_errors import CallNotSupportedError, InvalidArgumentError
from ola.call_planner import plan_call
from ola.library import Library
from ola.sim import SimTransport
from ola.tester import make_handle

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
pytestmark = pytest.mark.skipif(
    LIB is None or "Siglent_SNA_Series" not in (open(LIB).read() if LIB else ""),
    reason="library with the SCPI network analyzers not available",
)
SIGLENT, RS = "VNA_Siglent_SNA5002A", "VNA_RS_ZNB8"


@pytest.fixture(scope="module")
def library():
    return Library.load(LIB)


def commands(library, model, call, args):
    return [s["text"] for s in plan_call(library, model, call, args).steps]


def test_all_models_are_experimental(library):
    ids = [m["id"] for s in library.categories["network_analyzers_series"] for m in s["models"]]
    assert len(ids) == 3 + 19 + 16
    for model_id in ids:
        assert library.find_model(model_id).model["experimental"] is True


def test_siglent_commands(library):
    sweep = {"start_frequency": 1e6, "stop_frequency": 2e9, "points": 201}
    assert commands(library, SIGLENT, "set_frequency_sweep", sweep) == [
        ":SENSe1:SWEep:TYPE LINear",
        ":SENSe1:FREQuency:STARt 1000000",
        ":SENSe1:FREQuency:STOP 2000000000",
        ":SENSe1:SWEep:POINts 201",
    ]
    assert commands(library, SIGLENT, "run_sweep", {}) == [
        ":INITiate1:CONTinuous OFF",
        ":INITiate1:IMMediate",
        "*OPC?",
    ]
    assert commands(library, SIGLENT, "read_sparameters", {"sparameters": ["S11", "S21"]}) == [
        ":SENSe1:CORRection:STATe?",
        ":FORMat:DATA ASCii",
        ":SENSe1:FREQuency:DATA?",
        ":SENSe1:DATA:CORRdata? S11",
        ":SENSe1:DATA:CORRdata? S21",
    ]
    begin = {"kind": "TRANSMISSION_RESPONSE", "port": 1, "port2": 2}
    assert commands(library, SIGLENT, "calibration_begin", begin) == [
        ":SENSe1:CORRection:COLLect:METHod:THRU 2,1"
    ]
    assert commands(library, SIGLENT, "calibration_begin", {"kind": "ONE_PORT", "port": 2}) == [
        ":SENSe1:CORRection:COLLect:METHod:SOLT1 2"
    ]
    assert commands(library, SIGLENT, "calibration_measure", {"standard": "LOAD", "port": 1}) == [
        ":SENSe1:CORRection:COLLect:ACQuire:LOAD 1",
        "*OPC?",
    ]
    assert (
        commands(library, SIGLENT, "calibration_apply", {})[0] == ":SENSe1:CORRection:COLLect:SAVE"
    )
    assert commands(library, SIGLENT, "set_correction_state", {"state": False}) == [
        ":SENSe1:CORRection:STATe OFF"
    ]


def test_rohde_schwarz_commands(library):
    assert commands(library, RS, "read_sparameters", {"sparameters": ["S21", "S11"]}) == [
        "FORMat ASCii",
        "CALCulate1:PARameter:SDEFine 'OLA1','S21'",
        "CALCulate1:PARameter:SDEFine 'OLA2','S11'",
        "INITiate1:CONTinuous OFF",
        "INITiate1:IMMediate",
        "*OPC?",
        "SENSe1:CORRection:STATe?",
        "CALCulate1:PARameter:SELect 'OLA1'",
        "CALCulate1:DATA:STIMulus?",
        "CALCulate1:PARameter:SELect 'OLA1'",
        "CALCulate1:DATA? SDATa",
        "CALCulate1:PARameter:SELect 'OLA2'",
        "CALCulate1:DATA? SDATa",
    ]
    begin = {"kind": "TWO_PORT", "port": 1, "port2": 2}
    assert commands(library, RS, "calibration_begin", begin) == [
        "SENSe1:CORRection:COLLect:METHod:DEFine 'OLA', TOSM, 1,2"
    ]
    assert commands(library, RS, "calibration_measure", {"standard": "LOAD", "port": 2})[0] == (
        "SENSe1:CORRection:COLLect:ACQuire:SELected MATCh,2"
    )
    thru = {"standard": "THRU", "port": 1, "port2": 2}
    assert commands(library, RS, "calibration_measure", thru)[0] == (
        "SENSe1:CORRection:COLLect:ACQuire:SELected THRough,1,2"
    )
    assert commands(library, RS, "calibration_clear", {}) == [
        "SENSe1:CORRection:COLLect:DELete 'OLA'"
    ]


@pytest.mark.parametrize("model", [SIGLENT, RS])
def test_the_data_come_back_as_complex_arrays(library, model):
    answers = {
        "*OPC?": "1",
        ":SENSe1:CORRection:STATe?": "1",
        "SENSe1:CORRection:STATe?": "1",
        ":SENSe1:FREQuency:DATA?": "1e6,2e6",
        "CALCulate1:DATA:STIMulus?": "1e6,2e6",
        ":SENSe1:DATA:CORRdata? S11": "0.1,-0.2,0.3,0.4",
        "CALCulate1:DATA? SDATa": "0.1,-0.2,0.3,0.4",
        ":SENSe1:DATA:CORRdata? S11": "0.1,-0.2,0.3,0.4",
    }
    sim = SimTransport(lambda cmd: answers.get(cmd))  # a write gets no answer
    handle = make_handle(library, model, sim, "vna")
    result = handle.call("read_sparameters", sparameters=["S11"])
    assert list(result["frequency"]) == [1e6, 2e6] and result["calibrated"] is True
    assert list(result["parameters"]["S11"]["real"]) == [0.1, 0.3]
    assert list(result["parameters"]["S11"]["imaginary"]) == [-0.2, 0.4]


def test_the_scpi_models_have_no_driver_and_the_instrument_decides_unsupported_calls(library):
    assert make_handle(library, SIGLENT, SimTransport(lambda c: "1"), "v").supports("run_sweep")
    with pytest.raises(CallNotSupportedError):
        plan_call(library, SIGLENT, "select_sparameters", {})
    with pytest.raises(InvalidArgumentError):
        plan_call(library, SIGLENT, "calibration_begin", {"kind": "THREE", "port": 1})
