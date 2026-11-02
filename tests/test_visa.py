"""The pyvisa adapter against a fake raw-socket instrument, through the pure-Python
pyvisa-py backend (no VISA library or hardware needed)."""

import time

import pytest

pytest.importorskip("pyvisa")
pytest.importorskip("pyvisa_py")

from ola._visa import VisaConnection  # noqa: E402
from ola.errors import TransportClosed, TransportError, TransportTimeout  # noqa: E402
from tests.fake_instrument import FakeTcpInstrument, line_server  # noqa: E402


def open_visa(inst, timeout_ms=1000):
    return VisaConnection.open(f"TCPIP0::127.0.0.1::{inst.port}::SOCKET", timeout_ms, backend="@py")


def test_query():
    inst = FakeTcpInstrument(line_server(lambda c: b"1.234567\n"))
    c = open_visa(inst)
    assert c.query("MEAS:VOLT?") == "1.234567"
    assert c.query(b"MEAS:CURR?") == "1.234567"
    c.close()
    assert not c.is_open


def test_crlf_and_two_answers_in_one_segment():
    def h(conn):
        conn.recv(64)
        conn.sendall(b"one\r\ntwo\n")
        time.sleep(0.3)

    c = open_visa(FakeTcpInstrument(h))
    c.send("X?")
    assert c.read_line() == "one"
    assert c.read_line() == "two"


def test_timeout():
    c = open_visa(FakeTcpInstrument(lambda conn: time.sleep(2)), timeout_ms=200)
    t = time.perf_counter()
    with pytest.raises(TransportTimeout):
        c.query("X?", timeout_ms=150)
    assert time.perf_counter() - t < 1.0


def test_ieee_block_and_following_line():
    payload = bytes(range(256)) * 8

    def h(conn):
        conn.recv(64)
        conn.sendall(b"#4%04d" % len(payload) + payload + b"\n" + b"next\n")
        time.sleep(0.5)

    c = open_visa(FakeTcpInstrument(h))
    c.send("CURV?")
    assert c.read_block() == payload
    assert c.read_line() == "next"


def test_block_bad_header():
    def h(conn):
        conn.recv(64)
        conn.sendall(b"oops\n")
        time.sleep(0.3)

    c = open_visa(FakeTcpInstrument(h))
    c.send("CURV?")
    with pytest.raises(TransportError, match="TRN-005"):
        c.read_block()


def test_custom_terminators_multibyte():
    def h(conn):
        conn.recv(64)
        conn.sendall(b"ab>>cd")
        time.sleep(0.3)

    c = open_visa(FakeTcpInstrument(h))
    c.set_terminators(b"\r", b">>")
    c.send("X")
    assert c.read_line() == "ab"


def test_refused_connection_is_trn_001():
    inst = FakeTcpInstrument(lambda conn: None)
    port = inst.port
    inst.close()
    # pyvisa-py connects SOCKET resources lazily: the error appears at the first I/O
    with pytest.raises(TransportError, match="TRN-001"):
        c = VisaConnection.open(f"TCPIP0::127.0.0.1::{port}::SOCKET", 300, backend="@py")
        c.send("X?")


def test_unknown_resource_fails_at_open():
    with pytest.raises(TransportError, match="TRN-001"):
        VisaConnection.open("NOT-A-RESOURCE", 300, backend="@py")


def test_closed():
    c = open_visa(FakeTcpInstrument(line_server(lambda c: b"1\n")))
    c.close()
    with pytest.raises(TransportClosed):
        c.send("X?")
