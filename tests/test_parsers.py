"""Named parsers and read_waveform (descriptor built from the Siglent programming guide)."""

import os
import struct

import pytest

from ola.call_errors import ResponseNotRecognisedError
from ola.call_planner import plan_call
from ola.instrument import Instrument
from ola.library import Library
from ola.parsers import siglent_waveform
from ola.sim import SimTransport

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)


def descriptor(
    count, gain=10.0, offset=14.5, code_per_div=30.0, interval=2e-10, delay=1.72e-8, comm_type=0
):
    """A 346-byte WAVEDESC with the fields of Table 1 of the programming guide."""
    d = bytearray(346)
    d[0:8] = b"WAVEDESC"
    d[16:23] = b"WAVEACE"
    struct.pack_into("<h", d, 32, comm_type)
    struct.pack_into("<h", d, 34, 0)
    struct.pack_into("<i", d, 36, 346)
    struct.pack_into("<i", d, 60, count)
    struct.pack_into("<i", d, 116, count)
    struct.pack_into("<f", d, 156, gain)
    struct.pack_into("<f", d, 160, offset)
    struct.pack_into("<f", d, 164, code_per_div)
    struct.pack_into("<f", d, 176, interval)
    struct.pack_into("<d", d, 180, delay)
    return bytes(d)


def test_values_of_the_guide_example():
    # guide: first point -11 -> -11*(10/30)-14.5 = -18.167 V; time = 1.72e-8 - 2e-8*10/2 = -82.8 ns
    data = bytes([(-11) & 0xFF, 0, 30, 100])
    wave = siglent_waveform(descriptor(4), data, 2e-8)
    assert wave["points"] == 4
    assert wave["voltage"][0] == pytest.approx(-18.1667, abs=1e-3)
    assert wave["voltage"][1] == pytest.approx(-14.5)
    assert wave["voltage"][2] == pytest.approx(30 * 10 / 30 - 14.5)
    assert wave["time"][0] == pytest.approx(-82.8e-9, rel=1e-4)
    assert wave["time"][1] - wave["time"][0] == pytest.approx(2e-10, rel=1e-4)
    assert wave["sample_interval"] == pytest.approx(2e-10, rel=1e-5)


def test_descriptor_with_16_bit_scale_and_byte_data():
    # SDS824X HD, 0.5 V/div, offset -1.4833 V, 7680 codes/div in the descriptor, byte data:
    # codes -89 and +89 are 0 V and 2.97 V (3 V probe-compensation square wave)
    desc = descriptor(2, gain=0.5, offset=-1.4833333, code_per_div=7680.0)
    wave = siglent_waveform(desc, bytes([(-89) & 0xFF, 89]), 5e-4)
    assert wave["voltage"][0] == pytest.approx(0.0, abs=0.01)
    assert wave["voltage"][1] == pytest.approx(2.967, abs=0.01)


def test_extra_bytes_after_the_samples_are_ignored():
    wave = siglent_waveform(descriptor(2), bytes([1, 2, 10, 10]), 1e-3)
    assert wave["points"] == 2 and len(wave["voltage"]) == 2


def test_not_a_descriptor_and_unsupported_format():
    with pytest.raises(ResponseNotRecognisedError):
        siglent_waveform(b"short", b"", 1e-3)
    with pytest.raises(ResponseNotRecognisedError):
        siglent_waveform(descriptor(2, comm_type=1), bytes(4), 1e-3)


@pytest.mark.skipif(LIB is None, reason="library not available")
def test_read_waveform_call_on_the_sds():
    library = Library.load(LIB)
    desc = descriptor(3)
    answers = {
        ":TIMebase:SCALe?": "2.0E-08",
        ":WAVeform:PREamble?": desc,
        ":WAVeform:DATA?": bytes([(-11) & 0xFF, 0, 30]),
    }
    sim = SimTransport(lambda cmd: answers.get(cmd))
    plan = plan_call(library, "OSC_Siglent_SDS824X_HD", "read_waveform", {"channel_number": 2})
    assert [s["text"] for s in plan.steps] == [
        ":WAVeform:SOURce C2",
        ":WAVeform:WIDTh BYTE",
        ":TIMebase:SCALe?",
        ":WAVeform:PREamble?",
        ":WAVeform:DATA?",
    ]
    wave = plan.interpret(Instrument("osc", sim).run(plan))
    assert wave["points"] == 3 and wave["voltage"][0] == pytest.approx(-18.1667, abs=1e-3)
    assert sim.log[0] == ":WAVeform:SOURce C2"


@pytest.mark.skipif(LIB is None, reason="library not available")
def test_trigger_mode_after_a_forced_trigger_is_forced():
    library = Library.load(LIB)
    plan = plan_call(library, "OSC_Siglent_SDS824X_HD", "query_trigger_mode")
    assert plan.interpret(["FTRIG"]) == "FORCED" and plan.interpret(["NORMal"]) == "NORMAL"
