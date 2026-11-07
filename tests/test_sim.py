# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The simulated transport behaves like a real one for the operations the contract lists."""

import pytest

from ola.errors import TransportClosed, TransportTimeout
from ola.sim import SimTransport


def sim(*messages):
    t = SimTransport()
    t._inbox.extend(m if isinstance(m, bytes) else m.encode() for m in messages)
    return t


def test_read_until_consumes_up_to_the_terminator_and_keeps_the_rest():
    t = sim("ab>>cd", "ef\n")
    assert t.read_until(b">>") == b"ab"
    assert t.read_line() == "cdef"


def test_read_until_without_terminator_times_out_and_consumes_nothing():
    t = sim("abc")
    with pytest.raises(TransportTimeout):
        t.read_until(b">>")
    assert t.read_until(b"c") == b"ab"


def test_read_exact():
    t = sim("abc", "def")
    assert t.read_exact(4) == b"abcd"
    assert t.read_exact(2) == b"ef"
    with pytest.raises(TransportTimeout):
        t.read_exact(1)


def test_read_exact_with_too_little_data_consumes_nothing():
    t = sim("ab")
    with pytest.raises(TransportTimeout):
        t.read_exact(3)
    assert t.read_exact(2) == b"ab"


def test_set_terminators_validates_and_remembers():
    t = SimTransport()
    t.set_terminators(b"\r", b"\n")
    assert t.terminators == (b"\r", b"\n")
    with pytest.raises(ValueError):
        t.set_terminators(b"\r", b"")


def test_closed_simulator_refuses_reads():
    t = sim("x\n")
    t.close()
    for op in (t.read_line, t.read_block, lambda: t.read_exact(1), lambda: t.read_until(b"\n")):
        with pytest.raises(TransportClosed):
            op()
