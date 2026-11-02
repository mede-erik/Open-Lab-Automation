"""Instrument transport: the one entry point used by the rest of the software.

Uses the native Rust module (``ola_native``) when it is installed and falls back to a
pure-Python implementation with identical behaviour otherwise. Set the environment
variable ``OLA_TRANSPORT=python`` to force the fallback (e.g. for comparison tests).
"""

from __future__ import annotations

import os

from .errors import TransportClosed, TransportError, TransportTimeout

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
    "open_tcp",
    "open_serial",
    "Connection",
    "BACKEND",
    "TransportError",
    "TransportTimeout",
    "TransportClosed",
]
