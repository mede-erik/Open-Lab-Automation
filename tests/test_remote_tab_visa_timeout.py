# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A VISA resource whose timeout is infinite (pyvisa-py, USB instrument, @py backend) must get a
finite timeout before it is used: otherwise the remote tab fails with VISA-003."""

import types

import pytest

pytest.importorskip("PyQt6")

from frontend.ui.RemoteControlTab import RemoteControlTab  # noqa: E402


class FakeResource:
    def __init__(self, timeout):
        self.timeout = timeout
        self.write_termination = "\n"
        self.read_termination = "\n"


def fake_tab():
    # _configure_serial only uses its arguments for ASRL resources; the USB path returns early
    return types.SimpleNamespace(instruments_manager=None)


def test_infinite_timeout_is_replaced_before_use():
    res = FakeResource(float("inf"))
    RemoteControlTab._configure_serial(fake_tab(), res, "USB0::0xF4EC::0x1017::SERIAL::INSTR", {})
    assert res.timeout == 5000


def test_missing_timeout_is_replaced_before_use():
    res = FakeResource(None)
    RemoteControlTab._configure_serial(fake_tab(), res, "USB0::0x0957::0x0718::SERIAL::INSTR", {})
    assert res.timeout == 5000


def test_finite_timeout_is_left_alone():
    res = FakeResource(2000)
    RemoteControlTab._configure_serial(fake_tab(), res, "USB0::0x0957::0x0718::SERIAL::INSTR", {})
    assert res.timeout == 2000
