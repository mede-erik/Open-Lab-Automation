"""Instrument transport: the one entry point used by the rest of the software.

Uses the native Rust module (``ola_native``) when it is installed and falls back to a
pure-Python implementation with identical behaviour otherwise. Set the environment
variable ``OLA_TRANSPORT=python`` to force the fallback (e.g. for comparison tests).
"""

from __future__ import annotations

import os
from typing import Optional, Protocol, Union

from .errors import TransportClosed, TransportError, TransportTimeout

BytesLike = Union[bytes, bytearray, str]


class Transport(Protocol):
    """The contract every connection implements: the native Rust ``Connection``, the pure-Python
    ``PyConnection``, the pyvisa ``VisaConnection`` and the simulated ``SimTransport``.

    A connection is a byte stream to one instrument. It is thread-safe for whole operations
    (``query`` is atomic), but one *call* made of several operations must be protected by the
    caller, which is what ``ola.instrument.Instrument`` does. All methods raise
    ``TransportError`` (``TransportTimeout`` / ``TransportClosed`` are subclasses); the message
    starts with the ``[TRN-xxx]`` code of ``ERROR_CODES.md``.

    ``str`` arguments are sent as UTF-8; answers of ``read_line`` / ``query`` are ``str`` with the
    terminator removed (a ``\\r`` before ``\\n`` too), the other reads return ``bytes``.
    ``timeout_ms=None`` means the connection's default ``timeout_ms``.
    """

    peer: str
    """Address as text, e.g. ``tcp://192.168.1.50:5025`` or ``visa://USB0::...::INSTR``."""

    is_open: bool
    """True until ``close()`` is called or the instrument closes the connection."""

    timeout_ms: int
    """Default timeout of every read, in milliseconds (readable and writable)."""

    def set_terminators(self, write_term: BytesLike, read_term: BytesLike) -> None:
        """Terminator appended by ``send`` and terminator ``read_line`` waits for (not empty)."""

    def send(self, cmd: BytesLike) -> None:
        """Send ``cmd`` followed by the write terminator, in a single write."""

    def write(self, data: BytesLike) -> None:
        """Send ``data`` exactly as given (no terminator), in a single write."""

    def query(self, cmd: BytesLike, timeout_ms: Optional[int] = None) -> str:
        """``send(cmd)`` then ``read_line()``."""

    def read_line(self, timeout_ms: Optional[int] = None) -> str:
        """Read one answer line, terminator removed. ``TransportTimeout`` if it does not come."""

    def read_until(self, term: BytesLike, timeout_ms: Optional[int] = None) -> bytes:
        """Read up to and consuming ``term`` (not returned)."""

    def read_exact(self, n: int, timeout_ms: Optional[int] = None) -> bytes:
        """Read exactly ``n`` bytes."""

    def read_block(self, timeout_ms: Optional[int] = None) -> bytes:
        """Read an IEEE 488.2 definite-length block (``#<d><length><data>``), e.g. a waveform;
        the terminator that follows it is dropped. Indefinite blocks (``#0``) are refused."""

    def flush_input(self) -> None:
        """Throw away everything received and not yet read (stale answers)."""

    def close(self) -> None:
        """Close the connection. Later calls raise ``TransportClosed``."""

    def __enter__(self) -> "Transport":
        """Use as a context manager: ``with open_tcp(...) as c:`` closes at the end."""

    def __exit__(self, *exc) -> None:
        """Close the connection."""


try:
    if os.environ.get("OLA_TRANSPORT", "").lower() == "python":
        raise ImportError("native transport disabled by OLA_TRANSPORT=python")
    import ola_native as _native

    Connection = _native.Connection
    BACKEND = "native"
except ImportError:
    from ._pyconn import PyConnection as Connection

    BACKEND = "python"


def open_tcp(host: str, port: int = 5025, timeout_ms: int = 5000, connect_timeout_ms: int = 3000):
    """Open a LXI/raw-socket SCPI connection (default port 5025)."""
    return Connection.open_tcp(host, port, timeout_ms, connect_timeout_ms)


def open_serial(
    path: str,
    baud: int = 115200,
    timeout_ms: int = 5000,
    data_bits: int = 8,
    parity: str = "N",
    stop_bits: int = 1,
):
    """Open a serial / USB-CDC connection."""
    return Connection.open_serial(path, baud, timeout_ms, data_bits, parity, stop_bits)


__all__ = [
    "Transport",
    "open_tcp",
    "open_serial",
    "Connection",
    "BACKEND",
    "TransportError",
    "TransportTimeout",
    "TransportClosed",
]
