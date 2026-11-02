"""Pure-Python transport with the same behaviour as the Rust ``ola_native.Connection``.

Used when the native module is not built (e.g. a plain ``git clone`` without a Rust
toolchain). Same rules: TCP_NODELAY, one write per command, deadline-bounded reads,
IEEE 488.2 blocks. Serial needs the optional ``pyserial`` package.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Optional, Union

from .errors import TransportClosed, TransportError, TransportTimeout

MAX_RESPONSE = 256 * 1024 * 1024
_CHUNK = 16 * 1024
BytesLike = Union[bytes, bytearray, str]


def _b(x: BytesLike) -> bytes:
    return x.encode("utf-8") if isinstance(x, str) else bytes(x)


class PyConnection:
    def __init__(self, link, kind: str, peer: str, timeout_ms: int):
        self._link = link
        self._kind = kind  # "tcp" | "serial"
        self._peer = peer
        self._timeout = timeout_ms / 1000.0
        self._rbuf = bytearray()
        self._wterm = b"\n"
        self._rterm = b"\n"
        self._pending_term = False
        self._lock = threading.RLock()

    # ----- construction ---------------------------------------------------------------
    @staticmethod
    def open_tcp(
        host: str, port: int = 5025, timeout_ms: int = 5000, connect_timeout_ms: int = 3000
    ):
        try:
            sock = socket.create_connection((host, port), timeout=connect_timeout_ms / 1000.0)
        except OSError as e:
            raise TransportError(f"[TRN-001] connection failed: {host}:{port}: {e}") from e
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(timeout_ms / 1000.0)
        return PyConnection(sock, "tcp", f"tcp://{host}:{port}", timeout_ms)

    @staticmethod
    def open_serial(
        path: str,
        baud: int = 115200,
        timeout_ms: int = 5000,
        data_bits: int = 8,
        parity: str = "N",
        stop_bits: int = 1,
    ):
        try:
            import serial  # pyserial
        except ImportError as e:
            raise TransportError(
                "[TRN-001] serial support needs the native module or 'pyserial'"
            ) from e
        try:
            ser = serial.Serial(
                path,
                baudrate=baud,
                bytesize=data_bits,
                parity=parity.upper(),
                stopbits=stop_bits,
                timeout=timeout_ms / 1000.0,
            )
        except (OSError, ValueError, serial.SerialException) as e:
            raise TransportError(f"[TRN-001] connection failed: {path}: {e}") from e
        return PyConnection(ser, "serial", f"serial://{path}", timeout_ms)

    # ----- properties / settings --------------------------------------------------------
    @property
    def peer(self) -> str:
        return self._peer

    @property
    def is_open(self) -> bool:
        return self._link is not None

    @property
    def timeout_ms(self) -> int:
        return int(self._timeout * 1000)

    @timeout_ms.setter
    def timeout_ms(self, value: int) -> None:
        self._timeout = value / 1000.0

    def set_terminators(self, write_term: BytesLike, read_term: BytesLike) -> None:
        if not _b(read_term):
            raise TransportError("[TRN-006] invalid argument: read terminator must not be empty")
        self._wterm, self._rterm = _b(write_term), _b(read_term)

    def close(self) -> None:
        with self._lock:
            link, self._link = self._link, None
            self._rbuf.clear()
            self._pending_term = False
        if link is not None:
            try:
                link.close()
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        return f"<ola.PyConnection {self._peer} open={self.is_open}>"

    # ----- writing ----------------------------------------------------------------------
    def write(self, data: BytesLike) -> None:
        with self._lock:
            link = self._need_link()
            try:
                if self._kind == "tcp":
                    link.sendall(_b(data))
                else:
                    link.write(_b(data))
                    link.flush()
            except socket.timeout as e:
                raise TransportTimeout("[TRN-003] timeout waiting for the instrument") from e
            except OSError as e:
                self._fail(e)

    def send(self, cmd: BytesLike) -> None:
        self.write(_b(cmd) + self._wterm)  # one write

    # ----- reading ----------------------------------------------------------------------
    def flush_input(self) -> None:
        with self._lock:
            self._rbuf.clear()
            self._pending_term = False
            link = self._need_link()
            try:
                if self._kind == "tcp":
                    link.settimeout(0.001)
                    while link.recv(4096):
                        pass
                else:
                    link.reset_input_buffer()
            except (OSError, socket.timeout):
                pass
            finally:
                if self._kind == "tcp" and self._link is not None:
                    link.settimeout(self._timeout)

    def read_until(self, term: BytesLike, timeout_ms: Optional[int] = None) -> bytes:
        term = _b(term)
        if not term:
            raise TransportError("[TRN-006] invalid argument: terminator must not be empty")
        with self._lock:
            deadline = self._deadline(timeout_ms)
            self._strip_pending()
            scanned = 0
            while True:
                pos = self._rbuf.find(term, scanned)
                if pos >= 0:
                    line = bytes(self._rbuf[:pos])
                    del self._rbuf[: pos + len(term)]
                    return line
                scanned = max(0, len(self._rbuf) - (len(term) - 1))
                self._fill(deadline)
                self._strip_pending()

    def read_line(self, timeout_ms: Optional[int] = None) -> str:
        return self._read_line_bytes(timeout_ms).decode("utf-8", errors="replace")

    def _read_line_bytes(self, timeout_ms: Optional[int]) -> bytes:
        line = self.read_until(self._rterm, timeout_ms)
        if self._rterm == b"\n" and line.endswith(b"\r"):
            line = line[:-1]
        return line

    def query(self, cmd: BytesLike, timeout_ms: Optional[int] = None) -> str:
        with self._lock:
            self.send(cmd)
            return self.read_line(timeout_ms)

    def read_exact(self, n: int, timeout_ms: Optional[int] = None) -> bytes:
        if n > MAX_RESPONSE:
            raise TransportError(f"[TRN-006] invalid argument: {n} bytes exceeds the limit")
        with self._lock:
            deadline = self._deadline(timeout_ms)
            self._strip_pending()
            self._ensure(n, deadline)
            out = bytes(self._rbuf[:n])
            del self._rbuf[:n]
            return out

    def read_block(self, timeout_ms: Optional[int] = None) -> bytes:
        with self._lock:
            deadline = self._deadline(timeout_ms)
            self._strip_pending()
            self._ensure(2, deadline)
            if self._rbuf[0:1] != b"#":
                raise TransportError(
                    f"[TRN-005] protocol error: block header must start with '#', got 0x{self._rbuf[0]:02x}"
                )
            c = self._rbuf[1:2]
            if c == b"0":
                raise TransportError(
                    "[TRN-005] protocol error: indefinite-length blocks (#0) are not supported"
                )
            if not (b"1" <= c <= b"9"):
                raise TransportError(
                    f"[TRN-005] protocol error: bad block length digit count 0x{c[0]:02x}"
                )
            digits = int(c)
            self._ensure(2 + digits, deadline)
            try:
                length = int(bytes(self._rbuf[2 : 2 + digits]))
            except ValueError as e:
                raise TransportError("[TRN-005] protocol error: non-numeric block length") from e
            if length > MAX_RESPONSE:
                raise TransportError(
                    f"[TRN-005] protocol error: block of {length} bytes exceeds the limit"
                )
            self._ensure(2 + digits + length, deadline)
            data = bytes(self._rbuf[2 + digits : 2 + digits + length])
            del self._rbuf[: 2 + digits + length]
            self._pending_term = True
            self._strip_pending()
            return data

    # ----- internals --------------------------------------------------------------------
    def _need_link(self):
        if self._link is None:
            raise TransportClosed("[TRN-004] connection closed")
        return self._link

    def _deadline(self, timeout_ms: Optional[int]) -> float:
        t = self._timeout if timeout_ms is None else timeout_ms / 1000.0
        return time.monotonic() + t

    def _ensure(self, n: int, deadline: float) -> None:
        while len(self._rbuf) < n:
            self._fill(deadline)
            self._strip_pending()

    def _strip_pending(self) -> None:
        if not self._pending_term:
            return
        if self._rbuf.startswith(self._rterm):
            del self._rbuf[: len(self._rterm)]
            self._pending_term = False
        elif self._rbuf and not self._rterm.startswith(bytes(self._rbuf)):
            self._pending_term = False

    def _fill(self, deadline: float) -> None:
        if len(self._rbuf) >= MAX_RESPONSE:
            raise TransportError("[TRN-005] protocol error: response exceeds the size limit")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportTimeout("[TRN-003] timeout waiting for the instrument")
            link = self._need_link()
            try:
                if self._kind == "tcp":
                    link.settimeout(max(remaining, 0.001))
                    data = link.recv(_CHUNK)
                    if not data:
                        self._link = None
                        raise TransportClosed("[TRN-004] connection closed")
                else:
                    link.timeout = max(remaining, 0.001)
                    data = link.read(1)
                    if data:
                        data += link.read(link.in_waiting)
                    else:
                        continue
            except socket.timeout as e:
                raise TransportTimeout("[TRN-003] timeout waiting for the instrument") from e
            except InterruptedError:
                continue
            except OSError as e:
                self._fail(e)
            self._rbuf += data
            return

    def _fail(self, e: OSError):
        if isinstance(e, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            self._link = None
            raise TransportClosed("[TRN-004] connection closed") from e
        raise TransportError(f"[TRN-002] I/O error: {e}") from e
