# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The Prologix-compatible GPIB adapter transport, against a fake GPIB-ETHERNET adapter."""

import time

import pytest

from ola import prologix
from ola.errors import TransportClosed, TransportError, TransportTimeout
from ola.prologix import PrologixConnection
from tests.fake_instrument import FakePrologix, FakeTcpInstrument


def wait_for(condition, timeout=2.0):
    """The fake adapter runs in its own thread: wait until it has seen what was sent."""
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def idn(name):
    return lambda cmd: (name + "\n").encode() if cmd == b"*IDN?" else None


@pytest.fixture
def adapter():
    fake = FakePrologix({7: idn("HP,34401A,0,1"), 22: idn("KEITHLEY,2000,1,A")})
    yield fake
    fake.close()


def test_address_parsing():
    assert prologix.parse_address("PROLOGIX::COM5::7::INSTR") == ("COM5", 7, None)
    assert prologix.parse_address("prologix::/dev/ttyUSB0::12::3::INSTR") == ("/dev/ttyUSB0", 12, 3)
    assert prologix.parse_address("PROLOGIX::10.0.0.5:1234::1") == ("10.0.0.5:1234", 1, None)
    for bad in ("GPIB0::7::INSTR", "PROLOGIX::COM5::31::INSTR", "PROLOGIX::COM5::x::INSTR"):
        with pytest.raises(TransportError):
            prologix.parse_address(bad)
    assert prologix.make_address("COM5", 7) == "PROLOGIX::COM5::7::INSTR"
    assert prologix.is_prologix_address("PROLOGIX::COM5::7::INSTR")
    assert not prologix.is_prologix_address("GPIB0::7::INSTR")


def test_network_port_detection():
    assert prologix.is_network_port("192.168.1.20")
    assert prologix.is_network_port("192.168.1.20:1234")
    assert prologix.is_network_port("localhost")
    for serial in ("COM5", "/dev/ttyUSB0", "/dev/tty.usbserial-PX1"):
        assert not prologix.is_network_port(serial)


def test_escape():
    assert prologix.escape(b"V+\r\n\x1b") == b"V\x1b+\x1b\r\x1b\n\x1b\x1b"


def test_setup_and_query(adapter):
    c = PrologixConnection.open(f"PROLOGIX::{adapter.port}::7::INSTR", 1000)
    assert c.query("*IDN?") == "HP,34401A,0,1"
    assert adapter.commands[0] == "++ver"
    for cmd in ("++savecfg 0", "++mode 1", "++auto 0", "++eoi 1", "++eos 3", "++addr 7"):
        assert cmd in adapter.commands
    assert adapter.data[7] == [b"*IDN?\n"]  # the terminator reaches the instrument
    assert "visa" not in c.peer and "PROLOGIX" in c.peer
    c.close()
    assert not c.is_open
    with pytest.raises(TransportClosed):
        c.query("*IDN?")


def test_two_instruments_share_the_adapter(adapter):
    a = PrologixConnection.open_device(adapter.port, 7, timeout_ms=1000)
    b = PrologixConnection.open_device(adapter.port, 22, timeout_ms=1000)
    assert a.query("*IDN?").startswith("HP")
    assert b.query("*IDN?").startswith("KEITHLEY")
    assert a.query("*IDN?").startswith("HP")
    assert adapter.commands.count("++ver") == 1  # one link, set up once
    assert [c for c in adapter.commands if c.startswith("++addr")] == [
        "++addr 7",
        "++addr 22",
        "++addr 7",
    ]
    a.close()
    assert b.query("*IDN?").startswith("KEITHLEY")  # the link stays open for b
    b.close()


def test_special_characters_are_escaped(adapter):
    adapter.devices[5] = lambda cmd: None
    c = PrologixConnection.open_device(adapter.port, 5, timeout_ms=500)
    c.send("VOLT +5")
    assert wait_for(lambda: 5 in adapter.data)
    c.close()
    assert adapter.data[5] == [b"VOLT +5\n"]


def test_timeout_when_nothing_answers(adapter):
    c = PrologixConnection.open_device(adapter.port, 9, timeout_ms=300)
    with pytest.raises(TransportTimeout):
        c.query("*IDN?")
    c.close()


def test_read_block(adapter):
    adapter.devices[3] = lambda cmd: b"#15hello\n" if cmd == b"CURV?" else None
    c = PrologixConnection.open_device(adapter.port, 3, timeout_ms=1000)
    c.send("CURV?")
    assert c.read_block() == b"hello"
    c.close()


def test_bus_commands(adapter):
    c = PrologixConnection.open_device(adapter.port, 7, timeout_ms=500)
    c.interface_clear()
    c.device_clear()
    c.go_to_local()
    assert wait_for(lambda: {"++ifc", "++clr", "++loc"} <= set(adapter.commands))
    c.close()


def test_adapter_version(adapter):
    assert prologix.adapter_version(adapter.port).startswith("Prologix")


def test_not_a_prologix():
    silent = FakeTcpInstrument(lambda conn: conn.recv(4096) and time.sleep(5))
    with pytest.raises(TransportError) as exc:
        PrologixConnection.open(f"PROLOGIX::127.0.0.1:{silent.port}::7::INSTR", 300)
    assert "TRN-001" in str(exc.value)
    silent.close()


def test_open_visa_dispatches_prologix_addresses(adapter):
    from ola.tester import open_visa

    c = open_visa(f"PROLOGIX::{adapter.port}::22::INSTR", None, "x", timeout_ms=1000)
    assert isinstance(c, PrologixConnection)
    assert c.query("*IDN?").startswith("KEITHLEY")
    c.close()
