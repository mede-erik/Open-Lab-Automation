"""Call planner: arguments, translation, steps, errors, interpretation (no hardware)."""

import os

import pytest

from ola.call_errors import (
    CallNotSupportedError,
    InvalidArgumentError,
    ResponseNotRecognisedError,
    ValueNotHandledError,
)
from ola.call_planner import plan_call
from ola.library import Library

SCHEMA = {
    "schema_version": 1,
    "category": "oscilloscopes_series",
    "types": {
        "slope": {"kind": "enum", "values": ["RISE", "FALL", "EITHER"]},
        "status": {"kind": "enum", "values": ["ARMED", "TRIGGERED"]},
        "bool": {"kind": "bool"},
    },
    "calls": {
        "reset": {"requirement": "mandatory", "kind": "action"},
        "set_scale": {
            "requirement": "mandatory",
            "kind": "set",
            "args": {
                "channel_number": {"type": "int", "min": 1, "max": 4},
                "value": {"type": "float"},
            },
        },
        "set_slope": {
            "requirement": "mandatory",
            "kind": "set",
            "args": {"slope": {"type": "slope"}},
        },
        "set_state": {
            "requirement": "mandatory",
            "kind": "set",
            "args": {"channel_number": {"type": "int"}, "state": {"type": "bool"}},
        },
        "set_level": {
            "requirement": "mandatory",
            "kind": "set",
            "args": {
                "value": {"type": "float"},
                "channel_number": {"type": "int", "required": False},
            },
        },
        "acquire_single": {"requirement": "mandatory", "kind": "action"},
        "query_status": {"requirement": "mandatory", "kind": "query", "result": {"type": "status"}},
        "query_two": {"requirement": "optional", "kind": "query", "result": {"type": "float"}},
        "query_on": {"requirement": "optional", "kind": "query", "result": {"type": "int"}},
    },
}

SERIES = {
    "series_id": "S",
    "common_scpi_commands": {
        "reset": {"set": {"syntax": "*RST"}},
        "set_scale": {
            "set": {"syntax": "CH{channel_number}:SCAL {value}"},
            "parameters": {"channel_number": {"type": "int"}, "value": {"type": "float"}},
        },
        "set_slope": {
            "set": {"syntax": "SLOP {slope}"},
            "parameters": {"slope": {"type": "string", "map": {"RISE": "POS", "FALL": "NEG"}}},
        },
        "set_state": {
            "set": {"syntax": "CH{channel_number}:DISP {state}"},
            "parameters": {"channel_number": {"type": "int"}, "state": {"type": "string"}},
        },
        "set_level": {"set": {"syntax": "LEV {value}"}, "parameters": {"value": {"type": "float"}}},
        "acquire_single": {
            "set": {
                "steps": [
                    {"op": "write", "text": "ACQ:STOPAFTER SEQ"},
                    {"op": "write", "text": "ACQ:STATE RUN"},
                ]
            }
        },
        "query_status": {
            "query": {
                "syntax": "TRIG:STATE?",
                "return_type": "string",
                "response_map": {"ARM": "ARMED", "TRIG'D": "TRIGGERED"},
            }
        },
        "query_two": {
            "query": {"syntax": "READ?", "return_type": "float", "split": ",", "index": 1}
        },
        "query_on": {
            "query": {
                "syntax": "ON?",
                "return_type": "int",
                "bool": {"true": ["1"], "false": ["0"]},
            }
        },
    },
    "models": [
        {"id": "M1"},
        {"id": "M2", "scpi_commands": {"reset": None}},
        {
            "id": "M3",
            "access": "driver",
            "scpi_commands": {"reset": {"driver": {"function": "do_reset"}}},
        },
    ],
}


@pytest.fixture
def lib():
    return Library({"oscilloscopes_series": [SERIES]}, {"oscilloscopes_series": SCHEMA})


def test_single_syntax_write(lib):
    p = plan_call(lib, "M1", "set_scale", {"channel_number": 2, "value": 0.5})
    assert p.steps == [{"op": "write", "text": "CH2:SCAL 0.5"}]
    assert p.result == {"from_step": None} and p.access == "scpi"


def test_steps_form(lib):
    p = plan_call(lib, "M1", "acquire_single")
    assert [s["text"] for s in p.steps] == ["ACQ:STOPAFTER SEQ", "ACQ:STATE RUN"]


def test_map_and_unmapped_value(lib):
    assert plan_call(lib, "M1", "set_slope", {"slope": "rise"}).steps[0]["text"] == "SLOP POS"
    with pytest.raises(ValueNotHandledError) as e:
        plan_call(lib, "M1", "set_slope", {"slope": "EITHER"})
    assert e.value.code == "CALL-002"


def test_bool_default_on_off(lib):
    assert (
        plan_call(lib, "M1", "set_state", {"channel_number": 1, "state": True}).steps[0]["text"]
        == "CH1:DISP ON"
    )
    assert (
        plan_call(lib, "M1", "set_state", {"channel_number": 1, "state": "off"}).steps[0]["text"]
        == "CH1:DISP OFF"
    )


def test_optional_argument_ignored_when_unused(lib):
    p = plan_call(lib, "M1", "set_level", {"value": 1e-3, "channel_number": 3})
    assert p.steps[0]["text"] == "LEV 0.001"


def test_invalid_arguments(lib):
    for args in (
        {"channel_number": 9, "value": 1},
        {"channel_number": "x", "value": 1},
        {"value": 1},
        {"channel_number": 1, "value": 1, "bogus": 1},
    ):
        with pytest.raises(InvalidArgumentError) as e:
            plan_call(lib, "M1", "set_scale", args)
        assert e.value.code == "CALL-003"


def test_unsupported_call_and_model(lib):
    for model, call in (("M2", "reset"), ("M1", "nope"), ("ZZ", "reset")):
        with pytest.raises(CallNotSupportedError) as e:
            plan_call(lib, model, call)
        assert e.value.code == "CALL-001"


def test_driver_plan(lib):
    p = plan_call(lib, "M3", "reset")
    assert p.access == "driver" and p.driver == {"function": "do_reset", "args": {}}
    assert p.result == {"from_step": 0}


def test_interpret_response_map(lib):
    p = plan_call(lib, "M1", "query_status")
    assert p.steps == [{"op": "query", "text": "TRIG:STATE?", "returns": "string"}]
    assert p.interpret(["TRIG'D"]) == "TRIGGERED"
    assert p.interpret(["arm"]) == "ARMED"
    with pytest.raises(ResponseNotRecognisedError) as e:
        p.interpret(["???"])
    assert e.value.code == "CALL-005"


def test_interpret_split_and_bool(lib):
    p = plan_call(lib, "M1", "query_two")
    assert p.steps[0]["returns"] == "string"
    assert p.interpret(["1.5, 2.5, 3.5"]) == 2.5
    q = plan_call(lib, "M1", "query_on")
    assert q.interpret([1]) is True and q.interpret(["0"]) is False
    with pytest.raises(ResponseNotRecognisedError):
        q.interpret(["maybe"])


REAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Instruments_LIB",
    "instruments_lib.json",
)
REAL_ALT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Instruments_LIB",
    "instruments_lib.json",
)


@pytest.mark.skipif(
    not (os.path.isfile(REAL) or os.path.isfile(REAL_ALT)), reason="library not available"
)
def test_real_library_oscilloscopes():
    lib = Library.load(REAL if os.path.isfile(REAL) else REAL_ALT)
    assert (
        plan_call(
            lib, "OSC_Siglent_SDS824X_HD", "set_channel_scale", {"channel_number": 1, "value": 0.5}
        ).steps[0]["text"]
        == ":CHANnel1:SCALe 0.5"
    )
    assert (
        plan_call(lib, "OSC_Siglent_SDS824X_HD", "force_trigger").steps[0]["text"]
        == ":TRIGger:MODE FTRIG"
    )
    assert (
        plan_call(
            lib, "OSC_Tek_MSO54", "set_trigger_level", {"value": 0.1, "channel_number": 2}
        ).steps[0]["text"]
        == "TRIGger:A:LEVel:CH2 0.1"
    )
    with pytest.raises(CallNotSupportedError):
        plan_call(lib, "OSC_Siglent_SDS824X_HD", "query_waveform_all")


def _lib_with(commands):
    series = {"series_id": "S", "common_scpi_commands": commands, "models": [{"id": "M"}]}
    schema = {
        "schema_version": 1,
        "category": "c",
        "types": {
            "bool": {"kind": "bool"},
            "fmt": {"kind": "enum", "values": ["BYTE", "WORD", "ASCII"]},
        },
        "calls": {
            "set_bw": {
                "requirement": "optional",
                "kind": "set",
                "args": {"bandwidth": {"type": "float", "min": 0}},
            },
            "set_fmt": {
                "requirement": "optional",
                "kind": "set",
                "args": {"format_type": {"type": "fmt"}},
            },
            "set_depth": {
                "requirement": "optional",
                "kind": "set",
                "args": {"depth": {"type": "int"}},
            },
        },
    }
    return Library({"c": [series]}, {"c": schema})


def test_numeric_map_keys_and_map_default():
    lib = _lib_with(
        {
            "set_bw": {
                "set": {"syntax": "BW {bandwidth}"},
                "parameters": {
                    "bandwidth": {
                        "type": "string",
                        "map": {"0": "FULL", "20000000": "20M"},
                        "map_default": "pass",
                    }
                },
            },
            "set_depth": {
                "set": {"syntax": "DEPTH {depth}"},
                "parameters": {
                    "depth": {"type": "string", "map": {"10000": "10k", "1000000": "1M"}}
                },
            },
        }
    )
    assert plan_call(lib, "M", "set_bw", {"bandwidth": 0}).steps[0]["text"] == "BW FULL"
    assert plan_call(lib, "M", "set_bw", {"bandwidth": 2e7}).steps[0]["text"] == "BW 20M"
    assert plan_call(lib, "M", "set_bw", {"bandwidth": 5e6}).steps[0]["text"] == "BW 5000000"
    assert plan_call(lib, "M", "set_depth", {"depth": 1000000}).steps[0]["text"] == "DEPTH 1M"
    with pytest.raises(ValueNotHandledError):
        plan_call(lib, "M", "set_depth", {"depth": 123})


def test_derived_parameters():
    lib = _lib_with(
        {
            "set_fmt": {
                "set": {
                    "steps": [
                        {"op": "write", "text": "DAT:ENC {encoding}"},
                        {"op": "write", "text": "DAT:WID {width}"},
                    ]
                },
                "parameters": {
                    "format_type": {"type": "string"},
                    "encoding": {
                        "from": "format_type",
                        "map": {"BYTE": "RIB", "WORD": "RIB", "ASCII": "ASC"},
                    },
                    "width": {
                        "from": "format_type",
                        "map": {"BYTE": "1", "WORD": "2", "ASCII": "1"},
                    },
                },
            },
        }
    )
    p = plan_call(lib, "M", "set_fmt", {"format_type": "word"})
    assert [s["text"] for s in p.steps] == ["DAT:ENC RIB", "DAT:WID 2"]
    # without the argument, the error names it, not the derived placeholder
    with pytest.raises(InvalidArgumentError, match="needs argument 'format_type'"):
        plan_call(lib, "M", "set_fmt")


def test_missing_optional_source_of_a_derived_parameter_is_named():
    lib = _lib_with(
        {
            "set_bw": {
                "set": {"syntax": "BW {bw_text}"},
                "parameters": {"bw_text": {"from": "bandwidth", "map": {"0": "FULL"}}},
            },
        }
    )
    lib.schema("c")["calls"]["set_bw"]["args"]["bandwidth"]["required"] = False
    with pytest.raises(InvalidArgumentError, match="needs argument 'bandwidth'"):
        plan_call(lib, "M", "set_bw")


def test_expression_parameters_and_defaults():
    schema = {
        "schema_version": 1,
        "category": "c",
        "types": {},
        "calls": {
            "set_timing": {
                "requirement": "optional",
                "kind": "set",
                "args": {
                    "frequency": {"type": "float", "min": 0},
                    "duty": {"type": "float", "default": 25},
                },
            }
        },
    }
    series = {
        "series_id": "S",
        "common_scpi_commands": {
            "set_timing": {
                "set": {
                    "steps": [
                        {"op": "write", "text": "T1 {t_high}S"},
                        {"op": "write", "text": "T2 {t_low}S"},
                    ]
                },
                "parameters": {
                    "frequency": {"type": "float"},
                    "duty": {"type": "float"},
                    "t_high": {"from": ["frequency", "duty"], "expr": "duty / 100 / frequency"},
                    "t_low": {
                        "from": ["frequency", "duty"],
                        "expr": "(100 - duty) / 100 / frequency",
                    },
                },
            }
        },
        "models": [{"id": "M"}],
    }
    lib = Library({"c": [series]}, {"c": schema})
    texts = [s["text"] for s in plan_call(lib, "M", "set_timing", {"frequency": 1000}).steps]
    assert texts == ["T1 0.00025S", "T2 0.00075S"]
    texts = [
        s["text"] for s in plan_call(lib, "M", "set_timing", {"frequency": 100, "duty": 50}).steps
    ]
    assert texts == ["T1 0.005S", "T2 0.005S"]
    with pytest.raises(InvalidArgumentError):
        plan_call(lib, "M", "set_timing", {"frequency": 0})


def test_answer_as_list_of_numbers():
    series = {
        "series_id": "S",
        "common_scpi_commands": {
            "read_scan": {
                "query": {"syntax": "READ?", "return_type": "float", "split": ",", "as_list": True}
            }
        },
        "models": [{"id": "M"}],
    }
    lib = Library({"c": [series]}, {})
    plan = plan_call(lib, "M", "read_scan")
    assert plan.steps[0]["returns"] == "string"
    assert plan.interpret(["+1.5E+00, -2.0E-01,3"]) == [1.5, -0.2, 3.0]
    assert plan.interpret([""]) == []
    with pytest.raises(ResponseNotRecognisedError):
        plan.interpret(["1,abc"])


def test_number_or_keyword_argument():
    schema = {
        "schema_version": 1,
        "category": "c",
        "types": {},
        "calls": {
            "set_range": {
                "requirement": "optional",
                "kind": "set",
                "args": {
                    "range": {"type": "number_or_keyword", "keywords": ["AUTO", "MIN", "MAX"]}
                },
            }
        },
    }
    series = {
        "series_id": "S",
        "common_scpi_commands": {
            "set_range": {
                "set": {"syntax": "RANG {range}"},
                "parameters": {"range": {"type": "float", "values": ["AUTO", "MIN", "MAX"]}},
            }
        },
        "models": [{"id": "M"}],
    }
    lib = Library({"c": [series]}, {"c": schema})
    assert plan_call(lib, "M", "set_range", {"range": 10}).steps[0]["text"] == "RANG 10"
    assert plan_call(lib, "M", "set_range", {"range": "auto"}).steps[0]["text"] == "RANG AUTO"
    with pytest.raises(InvalidArgumentError):
        plan_call(lib, "M", "set_range", {"range": "huge"})
