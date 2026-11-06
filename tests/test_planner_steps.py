"""Steps that depend on an argument (when), steps repeated per list item (foreach) and the
parser of an SCPI network analyzer, with a small library written here."""

import pytest

from ola.call_errors import InvalidArgumentError, ResponseNotRecognisedError
from ola.call_planner import plan_call
from ola.library import Library
from ola.parsers import vna_sparameters

SCHEMA = {
    "schema_version": 1,
    "category": "vna_series",
    "types": {
        "sparameter": {"kind": "enum", "values": ["S11", "S21", "S12", "S22"]},
        "sparameter_list": {"kind": "list", "item": "sparameter"},
        "cal_kind": {"kind": "enum", "values": ["ONE_PORT", "TWO_PORT"]},
        "sparameters": {"kind": "mapping"},
    },
    "calls": {
        "read_sparameters": {
            "requirement": "mandatory",
            "kind": "query",
            "args": {"sparameters": {"type": "sparameter_list"}},
            "result": {"type": "sparameters"},
        },
        "calibration_begin": {
            "requirement": "optional",
            "kind": "action",
            "args": {
                "kind": {"type": "cal_kind"},
                "port": {"type": "int", "min": 1},
                "port2": {"type": "int", "min": 1, "required": False},
            },
        },
    },
}
LIBRARY = {
    "vna_series": [
        {
            "series_id": "Fake_VNA",
            "common_scpi_commands": {
                "read_sparameters": {
                    "query": {
                        "steps": [
                            {"op": "query", "text": ":CORR:STAT?"},
                            {"op": "query", "text": ":FREQ:DATA?"},
                            {"op": "write", "text": ":CALC:COUN {sparameters_count}"},
                            {
                                "foreach": "sparameters",
                                "steps": [
                                    {"op": "write", "text": ":SEL {n}"},
                                    {"op": "query", "text": ":DATA? {item}"},
                                ],
                            },
                        ],
                        "parse": {
                            "name": "vna_sparameters",
                            "from_steps": "queries",
                            "args": ["sparameters"],
                        },
                    },
                    "parameters": {"sparameters": {"type": "sparameter_list"}},
                },
                "calibration_begin": {
                    "set": {
                        "steps": [
                            {"op": "write", "when": {"kind": "ONE_PORT"}, "text": "CAL:ONE {port}"},
                            {
                                "op": "write",
                                "when": {"kind": ["TWO_PORT"]},
                                "text": "CAL:TWO {port},{port2}",
                            },
                        ]
                    },
                    "parameters": {
                        "kind": {"type": "string", "values": ["ONE_PORT", "TWO_PORT"]},
                        "port": {"type": "int"},
                        "port2": {"type": "int"},
                    },
                },
            },
            "models": [{"id": "VNA_Fake", "name": "Fake"}],
        }
    ]
}


@pytest.fixture(scope="module")
def library():
    return Library(LIBRARY, {"vna_series": SCHEMA})


def texts(plan):
    return [s["text"] for s in plan.steps]


def test_foreach_makes_one_step_per_list_item(library):
    plan = plan_call(library, "VNA_Fake", "read_sparameters", {"sparameters": ["S21", "S11"]})
    assert texts(plan) == [
        ":CORR:STAT?",
        ":FREQ:DATA?",
        ":CALC:COUN 2",
        ":SEL 1",
        ":DATA? S21",
        ":SEL 2",
        ":DATA? S11",
    ]
    # the list may also be given as comma-separated text
    again = plan_call(library, "VNA_Fake", "read_sparameters", {"sparameters": "s21, s11"})
    assert texts(again) == texts(plan)


def test_list_items_are_validated(library):
    with pytest.raises(InvalidArgumentError):
        plan_call(library, "VNA_Fake", "read_sparameters", {"sparameters": ["S11", "S99"]})
    with pytest.raises(InvalidArgumentError):
        plan_call(library, "VNA_Fake", "read_sparameters", {"sparameters": []})
    with pytest.raises(InvalidArgumentError):
        plan_call(library, "VNA_Fake", "read_sparameters", {})


def test_when_selects_the_steps_of_an_argument_value(library):
    one = plan_call(library, "VNA_Fake", "calibration_begin", {"kind": "one_port", "port": 1})
    two = plan_call(
        library, "VNA_Fake", "calibration_begin", {"kind": "TWO_PORT", "port": 1, "port2": 2}
    )
    assert texts(one) == ["CAL:ONE 1"] and texts(two) == ["CAL:TWO 1,2"]
    with pytest.raises(InvalidArgumentError):  # TWO_PORT needs port2
        plan_call(library, "VNA_Fake", "calibration_begin", {"kind": "TWO_PORT", "port": 1})


def test_the_answers_become_the_sparameters_dict(library):
    plan = plan_call(library, "VNA_Fake", "read_sparameters", {"sparameters": ["S11", "S21"]})
    raw = ["1", "1e6,2e6", None, None, "0.1,-0.2,0.3,0.4", None, "1,0,0.5,0.5"]
    result = plan.interpret(raw)
    assert list(result["frequency"]) == [1e6, 2e6] and result["calibrated"] is True
    assert list(result["parameters"]["S11"]["real"]) == [0.1, 0.3]
    assert list(result["parameters"]["S11"]["imaginary"]) == [-0.2, 0.4]
    assert list(result["parameters"]["S21"]["real"]) == [1.0, 0.5]


def test_parser_refuses_wrong_answers():
    with pytest.raises(ResponseNotRecognisedError):
        vna_sparameters("0", "1e6,2e6", "0.1,0.2,0.3", sparameters=["S11"])  # odd count
    with pytest.raises(ResponseNotRecognisedError):
        vna_sparameters("0", "1e6", "x,y", sparameters=["S11"])
    with pytest.raises(ResponseNotRecognisedError):
        vna_sparameters("0", "1e6", "0,0", "0,0", sparameters=["S11"])  # one answer too many
    assert vna_sparameters("OFF", "1e6", "0,0", sparameters=["S11"])["calibrated"] is False
