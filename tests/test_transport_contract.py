# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Every connection class must follow the ``ola.transport.Transport`` contract: same members, same
parameter names. The Protocol is the documentation; this test keeps the implementations equal to it.
"""

import inspect

import pytest

from ola import _pyconn
from ola.sim import SimTransport
from ola.transport import Transport
from tests.fake_instrument import FakeTcpInstrument, line_server

try:
    import ola_native
except ImportError:  # pragma: no cover
    ola_native = None

METHODS = [
    n
    for n, v in vars(Transport).items()
    if callable(v) and (not n.startswith("_") or n in ("__enter__", "__exit__"))
]
ATTRIBUTES = list(Transport.__annotations__)  # peer, is_open, timeout_ms


def make_python():
    inst = FakeTcpInstrument(line_server(lambda c: b"1\n"))
    return _pyconn.PyConnection.open_tcp("127.0.0.1", inst.port, 500)


def make_native():
    if ola_native is None:
        pytest.skip("native module not built")
    inst = FakeTcpInstrument(line_server(lambda c: b"1\n"))
    return ola_native.Connection.open_tcp("127.0.0.1", inst.port, 500)


def make_visa():
    pytest.importorskip("pyvisa_py")
    from ola._visa import VisaConnection

    inst = FakeTcpInstrument(line_server(lambda c: b"1\n"))
    return VisaConnection.open(f"TCPIP0::127.0.0.1::{inst.port}::SOCKET", 500, backend="@py")


def make_prologix():
    from ola.prologix import PrologixConnection
    from tests.fake_instrument import FakePrologix

    fake = FakePrologix({7: lambda cmd: b"1\n"})
    return PrologixConnection.open_device(fake.port, 7, timeout_ms=500)


FACTORIES = {
    "prologix": make_prologix,
    "python": make_python,
    "native": make_native,
    "visa": make_visa,
    "sim": lambda: SimTransport(),
}


@pytest.fixture(params=sorted(FACTORIES))
def connection(request):
    conn = FACTORIES[request.param]()
    yield conn
    conn.close()


def test_has_every_member_of_the_contract(connection):
    missing = [n for n in METHODS + ATTRIBUTES if not hasattr(connection, n)]
    assert missing == [], f"{type(connection).__name__} lacks {missing}"


def test_parameter_names_match_the_contract(connection):
    for name in METHODS:
        if name in ("__enter__", "__exit__"):
            continue
        try:
            actual = list(inspect.signature(getattr(connection, name)).parameters)
        except (TypeError, ValueError):  # builtin methods of the native module
            continue
        expected = list(inspect.signature(getattr(Transport, name)).parameters)[1:]  # without self
        assert actual == expected, f"{type(connection).__name__}.{name}{actual} != {expected}"


def test_context_manager_closes(connection):
    with connection as c:
        assert c.is_open
    assert not connection.is_open
