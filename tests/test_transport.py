"""Transport tests. The same suite runs against the native (Rust) and pure-Python
implementations, so the fallback cannot drift from the real thing."""

import statistics
import threading
import time

import pytest

from ola import _pyconn
from ola.errors import TransportClosed, TransportError, TransportTimeout
from tests.fake_instrument import FakePtyInstrument, FakeTcpInstrument, line_server

try:
    import ola_native
except ImportError:  # pragma: no cover
    ola_native = None

IMPLS = [pytest.param(_pyconn.PyConnection, id="python")]
if ola_native is not None:
    IMPLS.append(pytest.param(ola_native.Connection, id="native"))


@pytest.fixture(params=IMPLS)
def Conn(request):
    return request.param


def serve(handler):
    inst = FakeTcpInstrument(handler)
    return inst


def connect(Conn, inst, timeout_ms=500):
    return Conn.open_tcp("127.0.0.1", inst.port, timeout_ms)


def test_query_roundtrip(Conn):
    inst = serve(line_server(lambda cmd: b"1.234567\n"))
    c = connect(Conn, inst)
    assert c.query("MEAS:VOLT?") == "1.234567"
    assert c.query(b"MEAS:CURR?") == "1.234567"
    c.close()


def test_crlf_stripped(Conn):
    inst = serve(line_server(lambda cmd: b"ABC\r\n"))
    c = connect(Conn, inst)
    assert c.query("*IDN?") == "ABC"


def test_latency_regression_no_nagle_delay(Conn):
    """PLAN.md section 4.1: the old backend needed ~44 ms per query."""
    inst = serve(line_server(lambda cmd: b"1.0\n"))
    c = connect(Conn, inst)
    times = []
    for _ in range(100):
        t = time.perf_counter()
        c.query("MEAS:VOLT?")
        times.append(time.perf_counter() - t)
    assert statistics.median(times) < 0.005


def test_timeout(Conn):
    inst = serve(lambda conn: time.sleep(2))
    c = connect(Conn, inst)
    t = time.perf_counter()
    with pytest.raises(TransportTimeout):
        c.query("MEAS:VOLT?", timeout_ms=100)
    assert time.perf_counter() - t < 0.4


def test_timeout_is_a_transport_error(Conn):
    assert issubclass(TransportTimeout, TransportError)
    assert issubclass(TransportClosed, TransportError)


def test_answer_split_across_segments(Conn):
    def h(conn):
        conn.recv(64)
        for part in (b"1.2", b"34", b"5\n"):
            conn.sendall(part)
            time.sleep(0.02)

    c = connect(Conn, serve(h))
    assert c.query("X?") == "1.2345"


def test_two_answers_in_one_segment(Conn):
    def h(conn):
        conn.recv(64)
        conn.sendall(b"one\ntwo\n")
        time.sleep(0.2)

    c = connect(Conn, serve(h))
    c.send("X?")
    assert c.read_line() == "one"
    assert c.read_line() == "two"


def test_ieee_block_split_and_terminator_dropped(Conn):
    payload = bytes(range(256)) * 20  # 5120 bytes

    def h(conn):
        conn.recv(64)
        msg = b"#4%04d" % len(payload) + payload + b"\n" + b"next\n"
        for i in range(0, len(msg), 777):
            conn.sendall(msg[i : i + 777])
            time.sleep(0.002)
        time.sleep(0.3)

    c = connect(Conn, serve(h))
    c.send("CURV?")
    assert c.read_block() == payload
    assert c.read_line() == "next"  # the block's trailing newline must not leak


def test_block_bad_header(Conn):
    def h(conn):
        conn.recv(64)
        conn.sendall(b"oops\n")
        time.sleep(0.2)

    c = connect(Conn, serve(h))
    c.send("CURV?")
    with pytest.raises(TransportError, match="TRN-005"):
        c.read_block()


def test_read_exact_and_custom_terminators(Conn):
    def h(conn):
        conn.recv(64)
        conn.sendall(b"ab>>cd")
        time.sleep(0.2)

    c = connect(Conn, serve(h))
    c.set_terminators(b"\r", b">>")
    c.send("X")
    assert c.read_line() == "ab"
    assert c.read_exact(2) == b"cd"


def test_peer_close(Conn):
    c = connect(Conn, serve(lambda conn: None))
    time.sleep(0.05)
    with pytest.raises(TransportClosed):
        c.read_line(timeout_ms=300)
    assert not c.is_open


def test_flush_input(Conn):
    def h(conn):
        conn.sendall(b"stale\n")
        conn.recv(64)
        conn.sendall(b"fresh\n")
        time.sleep(0.2)

    c = connect(Conn, serve(h))
    time.sleep(0.05)
    c.flush_input()
    assert c.query("X?") == "fresh"


def test_connect_refused(Conn):
    inst = FakeTcpInstrument(lambda conn: None)
    port = inst.port
    inst.close()
    with pytest.raises(TransportError, match="TRN-001"):
        Conn.open_tcp("127.0.0.1", port, 100, 500)


def test_after_close(Conn):
    c = connect(Conn, serve(line_server(lambda cmd: b"1\n")))
    c.close()
    with pytest.raises(TransportClosed):
        c.send("X?")


def test_context_manager(Conn):
    with connect(Conn, serve(line_server(lambda cmd: b"1\n"))) as c:
        assert c.query("X?") == "1"
    assert not c.is_open


def test_shared_connection_between_threads(Conn):
    """query() is atomic: each thread must get the answer to its own command."""
    c = connect(Conn, serve(line_server(lambda cmd: cmd + b"\n")), timeout_ms=2000)
    errors = []

    def worker(tag):
        for i in range(50):
            cmd = f"{tag}{i}?"
            if c.query(cmd) != cmd:
                errors.append(cmd)

    threads = [threading.Thread(target=worker, args=(t,)) for t in "ab"]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors


def test_blocking_read_does_not_hold_the_gil(Conn):
    """A long wait for an instrument must not freeze other Python threads (the GUI)."""
    c = connect(Conn, serve(lambda conn: time.sleep(1)))
    ticks = []

    def waiter():
        try:
            c.read_line(timeout_ms=400)
        except TransportTimeout:
            pass

    t = threading.Thread(target=waiter)
    t.start()
    end = time.perf_counter() + 0.3
    while time.perf_counter() < end:
        ticks.append(1)
        time.sleep(0.001)
    t.join()
    assert len(ticks) > 100


# ---- serial (pseudo-terminal) ------------------------------------------------------------


@pytest.mark.skipif(not hasattr(__import__("os"), "ttyname"), reason="needs a POSIX pty")
def test_serial_query_over_pty():
    if ola_native is None:
        pytest.skip("native module not built")
    inst = FakePtyInstrument(lambda cmd: b"LITE-VNA\r\n" if cmd == b"version" else None)
    try:
        c = ola_native.Connection.open_serial(inst.slave_path, 115200, 1000)
        c.set_terminators(b"\r", b"\n")
        assert c.query("version") == "LITE-VNA"
        c.close()
    finally:
        inst.close()


def test_serial_open_missing_port(Conn):
    with pytest.raises(TransportError, match="TRN-001"):
        Conn.open_serial("/dev/does-not-exist", 115200, 100)
