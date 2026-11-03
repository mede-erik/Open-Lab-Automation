"""read_waveform_full: blocks of a long memory joined into one waveform."""

from array import array

import pytest

from ola.call_errors import CallError
from ola.waveform import parse_points, read_waveform_full


class FakeHandle:
    """A scope with ``total`` points of memory that sends at most ``block`` points per read."""

    def __init__(self, total, block, depth="10M", supported=None):
        self.total, self.block, self.depth = total, block, depth
        self.calls = []
        default = {"stop_acquisition", "query_waveform_max_points", "set_acquisition_depth"}
        self.supported = default if supported is None else supported

    def supports(self, name):
        return name in self.supported

    def readback(self, name, **args):
        self.calls.append((name, args))
        if self.depth is None:
            raise CallError("not supported", call=name)
        return self.depth

    def call(self, name, **args):
        self.calls.append((name, args))
        if name == "query_waveform_max_points":
            return self.block
        if name == "read_waveform":
            start = args["start"]
            n = max(0, min(args["points"] or self.block, self.total - start))
            return {
                "time": array("d", (i * 1e-9 for i in range(start, start + n))),
                "voltage": array("d", (float(i) for i in range(start, start + n))),
                "points": n,
                "sample_interval": 1e-9,
            }
        return None


def test_parse_points():
    assert parse_points("10M") == 10_000_000 and parse_points("500k") == 500_000
    assert parse_points(1000) == 1000 and parse_points("AUTO") is None


def test_blocks_are_joined_and_the_acquisition_is_stopped_first():
    handle = FakeHandle(total=25, block=10, depth="25")
    wave = read_waveform_full(handle, 1, bits=16)
    assert wave["points"] == 25 and wave["blocks"] == 3
    assert list(wave["voltage"]) == [float(i) for i in range(25)]
    assert wave["time"][24] == pytest.approx(24e-9)
    assert handle.calls[0][0] == "stop_acquisition"
    starts = [a["start"] for n, a in handle.calls if n == "read_waveform"]
    assert starts == [0, 10, 20]
    assert all(a["bits"] == 16 for n, a in handle.calls if n == "read_waveform")


def test_depth_equal_to_a_multiple_of_the_block_does_not_read_past_the_end():
    handle = FakeHandle(total=20, block=10, depth="20")
    wave = read_waveform_full(handle, 1)
    assert wave["points"] == 20 and wave["blocks"] == 2


def test_without_a_depth_the_blocks_end_with_a_short_one():
    handle = FakeHandle(total=25, block=10, depth=None)
    assert read_waveform_full(handle, 1)["points"] == 25


def test_stop_can_be_skipped_and_a_model_without_block_limit_reads_once():
    handle = FakeHandle(total=7, block=10, supported=set())
    wave = read_waveform_full(handle, 2, stop=False)
    assert wave["points"] == 7 and wave["blocks"] == 1
    assert [n for n, _ in handle.calls] == ["read_waveform"]


def test_no_points_is_an_error():
    with pytest.raises(CallError):
        read_waveform_full(FakeHandle(total=0, block=10), 1)
