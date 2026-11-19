# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The Rigol DG1000Z generators of the instrument library: the commands of the logical calls."""

import pytest

from ola.call_planner import plan_call

MODELS = ["FGEN_Rigol_DG1022Z", "FGEN_Rigol_DG1032Z", "FGEN_Rigol_DG1062Z"]


def _need(library, model_id):
    if library.find_model(model_id) is None:
        pytest.skip("the library has no Rigol DG1000Z yet")


@pytest.mark.parametrize("model_id", MODELS)
@pytest.mark.parametrize(
    "call, args, texts",
    [
        ("identification_query", {}, ["*IDN?"]),
        ("reset", {}, ["*RST"]),
        ("error_query", {}, [":SYSTem:ERRor?"]),
        ("set_frequency", {"value": 1000.0}, [":SOURce:FREQuency 1000"]),
        ("set_frequency", {"channel_number": 2, "value": 2.5e6}, [":SOURce2:FREQuency 2500000"]),
        (
            "set_amplitude",
            {"channel_number": 2, "value": 0.5},
            [":SOURce2:VOLTage:UNIT VPP", ":SOURce2:VOLTage 0.5"],
        ),
        ("set_offset", {"value": -1.0}, [":SOURce:VOLTage:OFFSet -1"]),
        ("set_waveform_shape", {"shape": "SINE"}, [":SOURce:FUNCtion SINusoid"]),
        (
            "set_waveform_shape",
            {"shape": "TRIANGLE"},
            [":SOURce:FUNCtion RAMP", ":SOURce:FUNCtion:RAMP:SYMMetry 50"],
        ),
        (
            "set_waveform_shape",
            {"channel_number": 2, "shape": "RAMP"},
            [":SOURce2:FUNCtion RAMP", ":SOURce2:FUNCtion:RAMP:SYMMetry 100"],
        ),
        ("set_waveform_shape", {"shape": "ARBITRARY"}, [":SOURce:FUNCtion USER"]),
        ("set_output_state", {"state": True}, [":OUTPut ON"]),
        ("set_output_state", {"channel_number": 2, "state": False}, [":OUTPut2 OFF"]),
    ],
)
def test_logical_calls_plan_the_commands_of_the_series(library, model_id, call, args, texts):
    _need(library, model_id)
    plan = plan_call(library, model_id, call, args)
    assert [s.get("text") for s in plan.steps] == texts


def test_the_channels_of_the_library(library):
    _need(library, "FGEN_Rigol_DG1032Z")
    caps = library.find_model("FGEN_Rigol_DG1032Z").model["capabilities"]
    assert caps["number_of_channels"] == 2 and caps["frequency_max_hz"] == 30e6
