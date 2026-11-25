# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The terminators of the library's serial transport are applied to a connection, and an
instrument with a binary protocol (the LiteVNA: empty terminators) can be opened:
``set_terminators`` refuses an empty read terminator, so such an instrument is not given one."""

import types

import pytest

from ola.serial_config import apply_terminators
from ola.sim import SimTransport


def terminators(t):
    """The terminators of a SimTransport as bytes (it keeps what it was given: text or bytes)."""
    return tuple(x.encode() if isinstance(x, str) else x for x in t.terminators)


def test_a_binary_protocol_leaves_the_connection_as_it_is():
    t = SimTransport()
    before = t.terminators
    apply_terminators(t, {"write_termination": "", "read_termination": ""})
    assert t.terminators == before


def test_text_terminators_are_applied():
    t = SimTransport()
    apply_terminators(t, {"write_termination": "\r", "read_termination": "\r\n"})
    assert terminators(t) == (b"\r", b"\r\n")


def test_missing_keys_mean_a_newline():
    t = SimTransport()
    apply_terminators(t, {"baud": 9600})  # nothing about terminators: the usual newline
    assert terminators(t) == (b"\n", b"\n")


def test_an_empty_write_terminator_with_a_read_terminator_is_applied():
    t = SimTransport()
    apply_terminators(t, {"write_termination": "", "read_termination": "\n"})
    assert terminators(t) == (b"", b"\n")


def test_the_connection_itself_still_refuses_an_empty_read_terminator():
    # the contract of ola.transport.Transport does not change: only the caller skips the call
    with pytest.raises(ValueError):
        SimTransport().set_terminators(b"", b"")


def serial_models(library):
    for series_list in library.categories.values():
        for series in series_list:
            for model in series.get("models", []):
                settings = library.serial_settings(model["id"])
                if settings:
                    yield model["id"], settings


def test_the_library_terminators_of_every_serial_model_are_accepted(library):
    checked = 0
    for model_id, settings in serial_models(library):
        apply_terminators(SimTransport(), settings)  # must not raise for any model
        checked += 1
    assert checked > 0


def test_the_litevna_has_no_terminators_in_the_library(library):
    settings = library.serial_settings("VNA_Zenko_LiteVNA67")
    assert settings, "the LiteVNA67 has no serial transport in the library"
    assert settings.get("read_termination") == ""
    apply_terminators(SimTransport(), settings)


class FakeResource:
    def __init__(self):
        self.timeout = 2000
        self.write_termination = "\n"
        self.read_termination = "\n"


def test_the_remote_tab_opens_an_instrument_with_empty_terminators():
    pytest.importorskip("PyQt6")
    from frontend.ui.RemoteControlTab import RemoteControlTab

    tab = types.SimpleNamespace()
    tab.__dict__["_serial_cfg"] = {
        "ASRL/dev/ttyACM0::INSTR": {"write_termination": "", "read_termination": ""}
    }
    executor = RemoteControlTab._get_instrument_executor(
        tab, "ASRL/dev/ttyACM0::INSTR", FakeResource(), "VNA"
    )
    assert executor is not None
