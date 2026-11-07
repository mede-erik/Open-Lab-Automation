"""pyvisa adapter: same interface as ``ola.transport.Connection`` for USB-TMC, GPIB, VXI-11
and anything else a VISA backend can open (``pyvisa-py`` or a vendor VISA library).

    c = VisaConnection.open("USB0::0x1AB1::0x04CE::DS1ZA0000::INSTR")
    c = VisaConnection.open("TCPIP0::192.168.1.50::inst0::INSTR")     # VXI-11
    c = VisaConnection.open("GPIB0::7::INSTR")

pyvisa is imported lazily, so ``ola`` works without it.

Note: with the pure-Python ``pyvisa-py`` backend a raw-socket resource is connected lazily, so
a refused connection is reported (as TRN-001) by the first read/write, not by ``open``.
"""

from __future__ import annotations

import contextlib
import threading
import time
from typing import Optional

from .errors import TransportClosed, TransportError, TransportTimeout

MAX_RESPONSE = 256 * 1024 * 1024


def _term_bytes(value) -> bytes:
    return value.encode("latin-1") if isinstance(value, str) else b""


def _b(x) -> bytes:
    return x.encode("utf-8") if isinstance(x, str) else bytes(x)


class VisaConnection:
    """Transport over a pyvisa resource (USB-TMC, GPIB, VXI-11, ASRL); the method contract is
    ``ola.transport.Transport``. A resource shared with other code is never left modified."""

    def __init__(self, resource, peer: str, timeout_ms: int, pyvisa_module):
        self._res = resource
        self._peer = peer
        self._pv = pyvisa_module
        self._timeout_ms = timeout_ms
        # Adopt the terminators already set on the resource (it may be shared with other code);
        # the resource itself is never left modified, see _applied().
        self._wterm = _term_bytes(getattr(resource, "write_termination", None)) or b"\n"
        self._rterm = _term_bytes(getattr(resource, "read_termination", None)) or b"\n"
        self._lock = threading.RLock()

    # ----- construction -----------------------------------------------------------------
    @staticmethod
    def open(resource_name: str, timeout_ms: int = 5000, backend: str = ""):
        """Open a VISA resource. ``backend``: "" = default VISA library, "@py" = pyvisa-py."""
        try:
            import pyvisa
        except ImportError as e:
            raise TransportError("[TRN-001] connection failed: pyvisa is not installed") from e
        try:
            rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
            res = rm.open_resource(resource_name)
            res.timeout = timeout_ms
        except Exception as e:  # pyvisa raises VisaIOError, ValueError, OSError...
            raise TransportError(f"[TRN-001] connection failed: {resource_name}: {e}") from e
        return VisaConnection(res, f"visa://{resource_name}", timeout_ms, pyvisa)

    # ----- properties / settings ---------------------------------------------------------
    @property
    def peer(self) -> str:
        """Address of the instrument as text (see ``ola.transport.Transport``)."""
        return self._peer

    @property
    def is_open(self) -> bool:
        """True until ``close()`` is called or the instrument closes the connection."""
        return self._res is not None

    @property
    def timeout_ms(self) -> int:
        """Default timeout of every read, in milliseconds."""
        return self._timeout_ms

    @timeout_ms.setter
    def timeout_ms(self, value: int) -> None:
        self._timeout_ms = value  # applied per operation, the resource is left untouched

    def set_terminators(self, write_term, read_term) -> None:
        """Set the terminator appended by ``send`` and the one ``read_line`` waits for."""
        if not _b(read_term):
            raise TransportError("[TRN-006] invalid argument: read terminator must not be empty")
        self._wterm, self._rterm = _b(write_term), _b(read_term)

    @contextlib.contextmanager
    def _applied(self, res, timeout_ms=None, read_termination=None):
        """Temporarily set the timeout (and, optionally, the read termination character) on the
        resource and restore its previous settings afterwards, so a resource shared with other
        code is never left changed. Writes use write_raw and read_bytes ignores the termchar, so
        the resource's own write/read termination never interferes."""
        old_timeout, old_term = res.timeout, res.read_termination
        try:
            res.timeout = max(1, int(self._timeout_ms if timeout_ms is None else timeout_ms))
            if read_termination is not None:
                res.read_termination = read_termination
            yield res
        finally:
            if self._res is not None:
                res.read_termination = old_term
                res.timeout = old_timeout

    def close(self) -> None:
        """Close the connection; later calls raise ``TransportClosed``."""
        with self._lock:
            res, self._res = self._res, None
        if res is not None:
            try:
                res.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        return f"<ola.VisaConnection {self._peer} open={self.is_open}>"

    # ----- writing ------------------------------------------------------------------------
    def write(self, data) -> None:
        """Send ``data`` exactly as given (no terminator), in a single write."""
        with self._lock:
            res = self._need()
            try:
                res.write_raw(_b(data))
            except Exception as e:
                self._fail(e)

    def send(self, cmd) -> None:
        """Send ``cmd`` followed by the write terminator, in a single write."""
        self.write(_b(cmd) + self._wterm)

    # ----- reading ------------------------------------------------------------------------
    def flush_input(self) -> None:
        """Throw away everything received and not yet read (stale answers)."""
        with self._lock:
            res = self._need()
            with self._applied(res, timeout_ms=1):
                while True:
                    try:
                        if not res.read_bytes(1):
                            break
                    except Exception:
                        break

    def read_until(self, term, timeout_ms: Optional[int] = None) -> bytes:
        """Read up to and consuming ``term`` (the terminator is not returned)."""
        term = _b(term)
        if not term:
            raise TransportError("[TRN-006] invalid argument: terminator must not be empty")
        total_ms = self._timeout_ms if timeout_ms is None else timeout_ms
        with self._lock:
            res = self._need()
            if len(term) == 1:
                return self._read_until_char(res, term, total_ms)
            deadline = time.monotonic() + total_ms / 1000.0
            buf = bytearray()
            while not buf.endswith(term):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportTimeout("[TRN-003] timeout waiting for the instrument")
                if len(buf) >= MAX_RESPONSE:
                    raise TransportError("[TRN-005] protocol error: response exceeds the limit")
                with self._applied(res, timeout_ms=remaining * 1000):
                    try:
                        buf += res.read_bytes(1)  # multi-byte terminator: exact but slow path
                    except Exception as e:
                        self._fail(e)
            return bytes(buf[: -len(term)])

    def _read_until_char(self, res, term: bytes, total_ms: int) -> bytes:
        with self._applied(res, timeout_ms=total_ms, read_termination=term.decode("latin-1")):
            try:
                data = res.read_raw()
            except Exception as e:
                self._fail(e)
        return bytes(data[:-1]) if data.endswith(term) else bytes(data)

    def read_line(self, timeout_ms: Optional[int] = None) -> str:
        """Read one answer line, terminator removed (``TransportTimeout`` if none comes)."""
        line = self.read_until(self._rterm, timeout_ms)
        if self._rterm == b"\n" and line.endswith(b"\r"):
            line = line[:-1]
        return line.decode("utf-8", errors="replace")

    def query(self, cmd, timeout_ms: Optional[int] = None) -> str:
        """``send(cmd)`` followed by ``read_line()``."""
        with self._lock:
            self.send(cmd)
            return self.read_line(timeout_ms)

    def read_exact(self, n: int, timeout_ms: Optional[int] = None) -> bytes:
        """Read exactly ``n`` bytes."""
        if n > MAX_RESPONSE:
            raise TransportError(f"[TRN-006] invalid argument: {n} bytes exceeds the limit")
        with self._lock:
            return self._read_bytes(n, timeout_ms)

    def read_block(self, timeout_ms: Optional[int] = None) -> bytes:
        """IEEE 488.2 definite-length block; the trailing terminator is consumed if present."""
        with self._lock:
            head = self._read_bytes(2, timeout_ms)
            if head[:1] != b"#":
                raise TransportError(
                    f"[TRN-005] protocol error: block header must start with '#', "
                    f"got 0x{head[0]:02x}"
                )
            if head[1:2] == b"0":
                raise TransportError(
                    "[TRN-005] protocol error: indefinite-length blocks (#0) are not supported"
                )
            if not (b"1" <= head[1:2] <= b"9"):
                raise TransportError(
                    f"[TRN-005] protocol error: bad block length digit count 0x{head[1]:02x}"
                )
            digits = int(head[1:2])
            try:
                length = int(self._read_bytes(digits, timeout_ms))
            except ValueError as e:
                raise TransportError("[TRN-005] protocol error: non-numeric block length") from e
            if length > MAX_RESPONSE:
                raise TransportError(
                    f"[TRN-005] protocol error: block of {length} bytes exceeds the limit"
                )
            data = self._read_bytes(length, timeout_ms)
            self._drop_terminator()
            return data

    # ----- internals ----------------------------------------------------------------------
    def _need(self):
        if self._res is None:
            raise TransportClosed("[TRN-004] connection closed")
        return self._res

    def _read_bytes(self, n: int, timeout_ms: Optional[int]) -> bytes:
        res = self._need()
        if n == 0:
            return b""
        with self._applied(res, timeout_ms=timeout_ms):
            try:
                return bytes(res.read_bytes(n, break_on_termchar=False))
            except Exception as e:
                self._fail(e)

    def _drop_terminator(self) -> None:
        """Consume the terminator an instrument appends after a block (short wait)."""
        res = self._need()
        with self._applied(res, timeout_ms=20):
            try:
                res.read_bytes(len(self._rterm), break_on_termchar=False)
            except Exception:
                pass

    def _fail(self, e: Exception):
        VisaIOError = getattr(self._pv.errors, "VisaIOError", None)
        if VisaIOError is not None and isinstance(e, VisaIOError):
            if e.error_code == self._pv.constants.StatusCode.error_timeout:
                raise TransportTimeout("[TRN-003] timeout waiting for the instrument") from e
            if e.error_code in (
                self._pv.constants.StatusCode.error_connection_lost,
                self._pv.constants.StatusCode.error_invalid_object,
            ):
                self._res = None
                raise TransportClosed("[TRN-004] connection closed") from e
        if isinstance(e, TransportError):
            raise e
        if isinstance(e, ConnectionRefusedError):
            # pyvisa-py connects SOCKET resources lazily, so a refused connection shows up
            # at the first I/O instead of at open()
            raise TransportError(f"[TRN-001] connection failed: {self._peer}: {e}") from e
        raise TransportError(f"[TRN-002] I/O error: {e}") from e
