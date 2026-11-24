# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The GW Instek GDS-1000B memory answer: the ``until`` field of a step, the waveform parser and
the three calls of the library that read the same message."""

import struct

import pytest

from ola.call_errors import ResponseNotRecognisedError
from ola.call_planner import plan_call
from ola.instrument import Instrument
from ola.parsers import get_parser, gwinstek_waveform
from ola.sim import SimTransport
from ola.steps import Step

SETTINGS = (
    "Format,1.0B;Memory Length,10000;IntpDistance,0;Trigger Address,2;Trigger Level,1.160E+01;"
    "Source,CH1;Vertical Units,V;Probe Ratio,1.000e+01;Vertical Scale,5.000e-01;"
    "Vertical Position,-1.100e+01;Horizontal Units,S;Horizontal Scale,5.000E-04;"
    "Horizontal Position,1.000E-03;Sampling Period,5.000e-07;Firmware,V0.99b8;Waveform Data;"
)
CODES = [28, 25, -25, 0, 50]
SAMPLES = struct.pack(">5h", *CODES)  # as read_block returns it: no #<n><len> header


def test_until_is_only_for_a_string_query_or_read():
    assert Step("query", text="Q?", until=";").until == ";"
    assert Step("read", until=";").until == ";"
    for bad in (
        {"op": "write", "text": "W", "until": ";"},
        {"op": "query", "text": "Q?", "returns": "binary", "until": ";"},
        {"op": "query", "text": "Q?", "until": ""},
    ):
        with pytest.raises(ValueError):
            Step.from_dict(bad)


def test_a_step_reads_up_to_the_marker_then_the_block():
    sim = SimTransport(lambda c: [SETTINGS.encode(), SAMPLES] if c == "MEM?" else None)
    steps = [
        {"op": "query", "text": "MEM?", "until": "Waveform Data;"},
        {"op": "read", "returns": "binary"},
    ]
    got = Instrument("gds", sim).run({"call": "t", "access": "scpi", "steps": steps})
    assert got[0].startswith("Format,1.0B;") and got[0].endswith(";")
    assert got[1] == SAMPLES


def test_the_parser_gives_volts_and_times_from_the_trigger():
    wave = gwinstek_waveform(SETTINGS, SAMPLES)
    assert list(wave["voltage"]) == pytest.approx([c / 25 * 0.5 for c in CODES])
    assert list(wave["time"]) == pytest.approx([(i - 2) * 5e-7 for i in range(5)])
    assert wave["points"] == 5 and wave["sample_interval"] == 5e-7
    assert wave["vertical_gain"] == 0.5 and wave["timebase"] == 5e-4
    assert wave["trigger_delay"] == 1e-3
    assert get_parser("gwinstek_waveform") is gwinstek_waveform


@pytest.mark.parametrize(
    "settings, data",
    [
        (SETTINGS.replace("Vertical Scale", "Other"), SAMPLES),
        (SETTINGS.replace("Sampling Period,5.000e-07", "Sampling Period,abc"), SAMPLES),
        (SETTINGS, b""),
    ],
)
def test_the_parser_refuses_settings_it_cannot_read_and_empty_data(settings, data):
    with pytest.raises(ResponseNotRecognisedError):
        gwinstek_waveform(settings, data)


# ---- the library entry ------------------------------------------------------------------------
MODEL = "OSC_GWInstek_GDS1054B"


def _need(library):
    if library.find_model(MODEL) is None:
        pytest.skip("the library has no GW Instek GDS-1000B yet")


def answer_from(plan, library_answer):
    """Run a plan against a simulated GDS that answers the memory query."""
    sim = SimTransport(lambda c: library_answer if c.endswith(":MEMory?") else None)
    return plan.interpret(Instrument("gds", sim).run(plan))


def test_the_three_calls_read_the_same_message(library):
    _need(library)
    message = [SETTINGS.encode(), SAMPLES]
    pre = plan_call(library, MODEL, "query_waveform_preamble", {"channel_number": 1})
    assert [s.get("text") for s in pre.steps if s["op"] != "read"][-1] == ":ACQuire1:MEMory?"
    assert answer_from(pre, message).startswith("Format,1.0B;")
    data = plan_call(library, MODEL, "query_waveform_data", {"channel_number": 2})
    assert answer_from(data, message) == SAMPLES
    full = plan_call(library, MODEL, "read_waveform", {"channel_number": 1})
    wave = answer_from(full, message)
    assert wave["points"] == 5
