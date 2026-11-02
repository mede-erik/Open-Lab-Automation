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


# ---- wrapping a resource that other code keeps using ---------------------------------------------


def _shared_resource(inst, timeout_ms=7000):
    import pyvisa

    rm = pyvisa.ResourceManager("@py")
    res = rm.open_resource(f"TCPIP0::127.0.0.1::{inst.port}::SOCKET")
    res.read_termination = "\n"
    res.write_termination = "\n"
    res.timeout = timeout_ms
    return res, pyvisa


def _settings(res):
    return (res.read_termination, res.write_termination, res.timeout)


def test_wrapping_does_not_change_the_shared_resource():
    """The app keeps using its pyvisa resource after the adapter wrapped it."""
    payload = bytes(range(64))

    def h(conn):
        while True:
            data = conn.recv(256)
            if not data:
                return
            if data.startswith(b"CURV"):
                conn.sendall(b"#2%02d" % len(payload) + payload + b"\n")
            else:
                conn.sendall(b"1.5\n")

    inst = FakeTcpInstrument(h)
    res, pyvisa = _shared_resource(inst)
    before = _settings(res)
    c = VisaConnection(res, "visa://shared", 1000, pyvisa)
    assert _settings(res) == before  # constructing it changes nothing

    assert c.query("X?") == "1.5"
    c.send("CURV?")
    assert c.read_block() == payload
    c.set_terminators(b"\r", b"\n")
    c.timeout_ms = 2000
    c.flush_input()
    c.send("X?")
    assert c.read_exact(4) == b"1.5\n"
    c.send("X?")
    with pytest.raises(TransportTimeout):
        c.read_until(b">>", timeout_ms=100)  # multi-byte terminator never arrives
    assert _settings(res) == before  # nothing left modified by any operation

    res.timeout = 1000
    res.write("X?")
    assert res.read() == "1.5"  # the application's own pyvisa call still works


def test_adopts_the_terminators_of_the_resource():
    inst = FakeTcpInstrument(line_server(lambda c: b"ok\n"))
    res, pyvisa = _shared_resource(inst)
    res.write_termination = "\r\n"
    c = VisaConnection(res, "visa://shared", 1000, pyvisa)
    assert c._wterm == b"\r\n" and c._rterm == b"\n"


# ---- RS-232 (ASRL) resource, as used for bench instruments without a network port ----------


def test_asrl_resource_with_default_pyvisa_settings():
    """A plain rm.open_resource("ASRL...") has read_termination None and write_termination CRLF.
    The adapter must still read lines (fallback terminator LF), strip a CRLF reply and leave the
    resource exactly as the application configured it."""
    pytest.importorskip("serial")
    import pyvisa

    from tests.fake_instrument import FakePtyInstrument

    inst = FakePtyInstrument(
        lambda cmd: b"HEWLETT-PACKARD,E3631A\r\n" if cmd == b"*IDN?" else None, eol=b"\n"
    )
    try:
        res = pyvisa.ResourceManager("@py").open_resource(f"ASRL{inst.slave_path}::INSTR")
        assert res.read_termination is None
        before = (res.read_termination, res.write_termination, res.timeout, res.baud_rate)
        c = VisaConnection(res, "visa://asrl", 1000, pyvisa)
        c.set_terminators(b"\n", b"\n")  # explicit terminators, as the library will provide
        assert c.query("*IDN?") == "HEWLETT-PACKARD,E3631A"
        assert (res.read_termination, res.write_termination, res.timeout, res.baud_rate) == before
        c.close()
    finally:
        inst.close()
