# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The spectrum analyzer type in the instrument lists, the commands of its logical calls on the
Rigol DSA800 and RSA3000 and the Siglent SSA3000X Plus, and the parser of the trace."""

import glob
import json
import os

import pytest

from frontend.core.LoadInstruments import LoadInstruments
from ola.call_errors import ResponseNotRecognisedError, ValueNotHandledError
from ola.call_planner import plan_call
from ola.parsers import get_parser, spectrum_trace_ascii

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(HERE, "frontend", "lang")
DSA, RSA, SSA = "SA_Rigol_DSA815", "SA_Rigol_RSA3045", "SA_Siglent_SSA3000X_Plus"


def _need(library, model_id):
    if library.find_model(model_id) is None:
        pytest.skip("the library has no such spectrum analyzer yet")


def test_the_type_is_in_the_lists(tmp_path):
    path = tmp_path / "lib.json"
    series = {"series_id": "S", "series_name": "S", "models": [{"id": "SA_X", "name": "X"}]}
    path.write_text(json.dumps({"spectrum_analyzers_series": [series]}), encoding="utf-8")
    library = LoadInstruments()
    library.load_instruments(str(path))
    assert LoadInstruments.get_series_key("spectrum_analyzer") == "spectrum_analyzers_series"
    assert "spectrum_analyzer" in library.get_all_types()
    assert [s["series_id"] for s in library.get_series("spectrum_analyzer")] == ["S"]


def test_the_type_has_a_name_in_every_language():
    paths = glob.glob(os.path.join(LANG, "*.json"))
    assert len(paths) == 5
    for path in paths:
        assert json.load(open(path, encoding="utf-8")).get("spectrum_analyzer"), path


def texts(library, model_id, call, args=None):
    return [s.get("text") for s in plan_call(library, model_id, call, args or {}).steps]


@pytest.mark.parametrize("model_id", [DSA, RSA, SSA])
@pytest.mark.parametrize(
    "call, args, expected",
    [
        ("identification_query", {}, ["*IDN?"]),
        ("set_center_frequency", {"value": 100e6}, [":SENSe:FREQuency:CENTer 100000000"]),
        ("set_span", {"value": 20e6}, [":SENSe:FREQuency:SPAN 20000000"]),
        ("set_start_frequency", {"value": 1e6}, [":SENSe:FREQuency:STARt 1000000"]),
        ("set_stop_frequency", {"value": 2e6}, [":SENSe:FREQuency:STOP 2000000"]),
        ("query_center_frequency", {}, [":SENSe:FREQuency:CENTer?"]),
        ("set_video_bandwidth_auto", {"state": True}, None),
        ("set_reference_level", {"value": -10}, [":DISPlay:WINDow:TRACe:Y:SCALe:RLEVel -10"]),
        ("set_input_attenuation", {"value": 20}, [":SENSe:POWer:RF:ATTenuation 20"]),
        ("set_sweep_time", {"value": 0.1}, [":SENSe:SWEep:TIME 0.1"]),
        ("set_sweep_continuous", {"state": False}, [":INITiate:CONTinuous OFF"]),
        ("initiate_sweep", {}, [":INITiate:IMMediate"]),
        ("set_marker_state", {"marker_number": 2, "state": True}, [":CALCulate:MARKer2:STATe ON"]),
        ("set_marker_frequency", {"value": 5e6}, [":CALCulate:MARKer1:X 5000000"]),
        ("query_marker_frequency", {"marker_number": 3}, [":CALCulate:MARKer3:X?"]),
        ("query_marker_amplitude", {}, [":CALCulate:MARKer1:Y?"]),
        ("set_power_unit", {"unit": "DBMV"}, [":UNIT:POWer DBMV"]),
    ],
)
def test_the_common_calls(library, model_id, call, args, expected):
    _need(library, model_id)
    got = texts(library, model_id, call, args)
    if expected is None:
        assert len(got) == 1 and got[0].endswith(" ON")
    else:
        assert got == expected


def test_the_bandwidth_commands_follow_the_manual_of_each_series(library):
    for model, head in ((DSA, "BANDwidth"), (RSA, "BANDwidth"), (SSA, "BWIDth")):
        _need(library, model)
        assert texts(library, model, "set_resolution_bandwidth", {"value": 1000}) == [
            f":SENSe:{head}:RESolution 1000"
        ]
        assert texts(library, model, "set_video_bandwidth", {"value": 300}) == [
            f":SENSe:{head}:VIDeo 300"
        ]


def test_the_peak_search_and_the_trace_calls_differ_by_series(library):
    for model in (DSA, RSA, SSA):
        _need(library, model)
    assert texts(library, DSA, "marker_peak_search", {"marker_number": 2}) == [
        ":CALCulate:MARKer2:MAXimum:MAX"
    ]
    assert texts(library, SSA, "marker_peak_search") == [":CALCulate:MARKer1:MAXimum"]
    assert texts(library, DSA, "set_trace_mode", {"trace_number": 1, "mode": "AVERAGE"}) == [
        ":TRACe1:MODE VIDeoavg"
    ]
    assert texts(library, RSA, "set_trace_mode", {"trace_number": 5, "mode": "MAX_HOLD"}) == [
        ":TRACe5:MODE MAXHold"
    ]
    with pytest.raises(ValueNotHandledError):  # the RSA3000 has no VIEW mode
        plan_call(library, RSA, "set_trace_mode", {"trace_number": 1, "mode": "VIEW"})
    assert texts(library, SSA, "set_detector", {"trace_number": 2, "detector": "POSITIVE"}) == [
        ":SENSe:DETector:TRACe2:FUNCtion POSitive"
    ]
    assert texts(library, RSA, "set_detector", {"trace_number": 2, "detector": "RMS"}) == [
        ":SENSe:DETector:TRACe2 RAVerage"
    ]
    assert texts(library, DSA, "set_detector", {"detector": "QUASI_PEAK"}) == [
        ":SENSe:DETector:FUNCtion QPEak"
    ]


def test_reading_a_trace_sets_ascii_then_asks_for_the_trace(library):
    _need(library, DSA)
    assert texts(library, DSA, "read_trace", {"trace_number": 2}) == [
        ":FORMat:TRACe:DATA ASCii",
        ":TRACe:DATA? TRACE2",
    ]
    assert texts(library, SSA, "read_trace") == [":FORMat:TRACe:DATA ASCii", ":TRACe:DATA? 1"]
    plan = plan_call(library, DSA, "read_trace", {"trace_number": 1})
    answer = "#9000000030 -1.5e+01, -7.1e+01, -7.0e+01"
    assert plan.interpret([None, answer]) == [-15.0, -71.0, -70.0]


# ---- the parser of the trace ------------------------------------------------------------------
def test_the_trace_parser_reads_the_rigol_block_header_and_the_plain_siglent_answer():
    assert spectrum_trace_ascii("#9000000030 -1.5e+01, -7.1e+01, -7.0e+01") == [-15.0, -71.0, -70.0]
    assert spectrum_trace_ascii("-1.5e+01,-7.1e+01,\n") == [-15.0, -71.0]
    assert get_parser("spectrum_trace_ascii") is spectrum_trace_ascii


@pytest.mark.parametrize("answer", ["", "#9000000000", "-1.5e+01, abc"])
def test_the_trace_parser_refuses_an_empty_answer_and_a_point_that_is_not_a_number(answer):
    with pytest.raises(ResponseNotRecognisedError):
        spectrum_trace_ascii(answer)
