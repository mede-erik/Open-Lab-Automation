# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The Rigol DHO800/DHO900 and MSO5000 oscilloscopes of the instrument library: the commands of
the logical calls and the differences of their programming guides."""

import pytest

from ola.call_planner import plan_call
from ola.call_errors import ValueNotHandledError

DHO = "OSC_Rigol_DHO814"
MSO = "OSC_Rigol_MSO5354"


def _need(library, model_id):
    if library.find_model(model_id) is None:
        pytest.skip("the library has no such Rigol oscilloscope yet")


def _texts(library, model_id, call, args=None):
    return [s.get("text") for s in plan_call(library, model_id, call, args or {}).steps]


@pytest.mark.parametrize("model_id", [DHO, MSO])
@pytest.mark.parametrize(
    "call, args, texts",
    [
        ("identification_query", {}, ["*IDN?"]),
        ("run_acquisition", {}, [":RUN"]),
        ("stop_acquisition", {}, [":STOP"]),
        ("acquire_single", {}, [":SINGle"]),
        ("set_channel_scale", {"channel_number": 2, "value": 0.5}, [":CHANnel2:SCALe 0.5"]),
        ("set_channel_state", {"channel_number": 1, "state": True}, [":CHANnel1:DISPlay ON"]),
        ("set_timebase_scale", {"value": 1e-6}, [":TIMebase:SCALe 1e-06"]),
        ("set_timebase_delay", {"value": 0.001}, [":TIMebase:MAIN:OFFSet 0.001"]),
        ("set_trigger_mode", {"mode": "SINGLE"}, [":TRIGger:SWEep SINGle"]),
        ("set_trigger_slope", {"slope": "EITHER"}, [":TRIGger:EDGe:SLOPe RFALl"]),
        ("set_waveform_format", {"format_type": "WORD"}, [":WAVeform:FORMat WORD"]),
        ("query_waveform_data", {}, [":WAVeform:DATA?"]),
        ("error_query", {}, [":SYSTem:ERRor?"]),
    ],
)
def test_the_rigol_command_family(library, model_id, call, args, texts):
    _need(library, model_id)
    assert _texts(library, model_id, call, args) == texts


def test_the_dho_has_autoset_and_no_high_resolution_mode(library):
    _need(library, DHO)
    assert _texts(library, DHO, "auto_setup") == [":AUToset"]
    with pytest.raises(ValueNotHandledError):
        plan_call(library, DHO, "set_acquisition_type", {"acquisition_type": "HIRES"})
    assert _texts(library, DHO, "set_acquisition_type", {"acquisition_type": "AVERAGE"}) == [
        ":ACQuire:TYPE AVERages"
    ]


def test_the_mso5000_has_autoscale_and_a_high_resolution_mode(library):
    _need(library, MSO)
    assert _texts(library, MSO, "auto_setup") == [":AUToscale"]
    assert _texts(library, MSO, "set_acquisition_type", {"acquisition_type": "HIRES"}) == [
        ":ACQuire:TYPE HRESolution"
    ]
    assert _texts(library, MSO, "set_acquisition_depth", {"depth": 1000000}) == [
        ":ACQuire:MDEPth 1M"
    ]


@pytest.mark.parametrize(
    "model_id, accepted, refused",
    [
        ("OSC_Rigol_MSO5074", [20e6], [100e6, 200e6]),
        ("OSC_Rigol_MSO5204", [20e6, 100e6], [200e6]),
        ("OSC_Rigol_MSO5354", [20e6, 100e6, 200e6], []),
    ],
)
def test_the_mso5000_bandwidth_limits_depend_on_the_model(library, model_id, accepted, refused):
    _need(library, model_id)
    for hz in accepted:
        _texts(library, model_id, "set_channel_bandwidth_limit",
               {"channel_number": 1, "bandwidth": hz})
    for hz in refused:
        with pytest.raises(ValueNotHandledError):
            plan_call(library, model_id, "set_channel_bandwidth_limit",
                      {"channel_number": 1, "bandwidth": hz})


def test_the_trigger_status_answers_become_logical_values(library):
    _need(library, DHO)
    plan = plan_call(library, DHO, "query_trigger_status")
    assert [plan.interpret([a]) for a in ("TD", "WAIT", "RUN", "AUTO", "STOP")] == [
        "TRIGGERED", "READY", "ARMED", "AUTO", "STOPPED",
    ]  # fmt: skip
