# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The legacy C backend (backend/*.c through frontend.core.c_backend), against a fake LXI
instrument on localhost. The backend is not extended any more, but while it ships it must
build, load and talk SCPI correctly. Skipped when the shared library is not built
(``bash backend/build.sh``)."""

import socket
import threading

import pytest

from frontend.core import c_backend
from frontend.core.c_backend import CBackend, CBackendError
from tests.fake_instrument import FakeTcpInstrument, line_server

try:
    c_backend._find_library()
    BUILT = True
except FileNotFoundError:
    BUILT = False

pytestmark = pytest.mark.skipif(not BUILT, reason="C backend not built (backend/build.sh)")


class FakeSupply:
    """Answers like a single-channel power supply and records what it receives."""

    def __init__(self):
        self.received = []
        self.voltage = 0.0
        self.lock = threading.Lock()

    def reply(self, line: bytes):
        cmd = line.decode().strip()
        with self.lock:
            self.received.append(cmd)
        if cmd == "*IDN?":
            return b"FAKE,PSU,0,1.0\n"
        if cmd.startswith("VOLT "):
            self.voltage = float(cmd.split()[1])
            return None
        if cmd == "MEAS:VOLT?":
            return f"{self.voltage:.6f}\n".encode()
        if cmd == "MEAS:CURR?":
            return f"{self.voltage / 10:.6f}\n".encode()
        if cmd == "BAD?":
            return b"not-a-number\n"
        return None


@pytest.fixture
def backend():
    CBackend.load()
    yield CBackend
    CBackend.unload()


@pytest.fixture
def supply():
    fake = FakeSupply()
    server = FakeTcpInstrument(line_server(fake.reply))
    fake.port = server.port
    yield fake
    server.close()


def test_load_and_version(backend):
    assert backend.version() not in ("", "not loaded", "unknown")


def test_query_and_numbers(backend, supply):
    handle = backend.connect("127.0.0.1", supply.port, 2000)
    try:
        assert backend.query(handle, "*IDN?", 2000) == "FAKE,PSU,0,1.0"
        backend.send(handle, "VOLT 2.5")
        backend.send(handle, "MEAS:VOLT?")
        assert backend.receive_float(handle, 2000) == pytest.approx(2.5)
        backend.send(handle, "BAD?")
        with pytest.raises(CBackendError):
            backend.receive_float(handle, 2000)
    finally:
        backend.disconnect(handle)
    assert supply.received[:2] == ["*IDN?", "VOLT 2.5"]


def test_receive_timeout(backend, supply):
    handle = backend.connect("127.0.0.1", supply.port, 2000)
    try:
        backend.send(handle, "SILENT")
        with pytest.raises(CBackendError):
            backend.receive(handle, timeout_ms=200)
    finally:
        backend.disconnect(handle)


def test_connection_refused(backend):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(CBackendError):
        backend.connect("127.0.0.1", port, 500)


def test_invalid_handle(backend):
    with pytest.raises(CBackendError):
        backend.send(9999, "*IDN?")


def test_not_loaded_is_reported():
    CBackend.unload()
    assert CBackend.version() == "not loaded"
    with pytest.raises(CBackendError):
        CBackend.connect("127.0.0.1", 5025)


def test_sweep_sets_and_measures_every_point(backend, supply):
    handle = backend.connect("127.0.0.1", supply.port, 2000)
    progress = []
    try:
        volts, amps = backend.sweep_run(
            [handle],
            [1],
            [1.0, 2.0, 3.0],
            settling_time_s=0.0,
            progress_cb=lambda i, n: progress.append((i, n)),
        )
    finally:
        backend.disconnect(handle)
    assert volts == pytest.approx([1.0, 2.0, 3.0])
    assert amps == pytest.approx([0.1, 0.2, 0.3])
    assert "INST:NSEL 1" in supply.received
    assert [c for c in supply.received if c.startswith("VOLT ")] == [
        "VOLT 1.000000",
        "VOLT 2.000000",
        "VOLT 3.000000",
    ]
    assert progress and progress[-1][1] == 3


def test_sweep_argument_checks(backend):
    assert backend.sweep_run([1], [1], []) == ([], [])
    with pytest.raises(CBackendError):
        backend.sweep_run([], [], [1.0])
    with pytest.raises(CBackendError):
        backend.sweep_run([1], [1], [0.0] * 100001)
