"""Simulated transport: lets the instrument layer be developed and tested without hardware
(and lets the app run a dry run that prints what would be sent).

``SimTransport(responder)`` implements the same interface as ``ola.transport.Connection``.
Every command sent is recorded in ``.log``; ``responder(cmd)`` returns the answer for it
(str / bytes, a list of those for several lines, or ``None`` for no answer).
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable, List, Optional, Union

from .errors import TransportClosed, TransportTimeout

Reply = Union[None, str, bytes, List[Union[str, bytes]]]


class SimTransport:
    """Fake instrument link: records what is sent and answers through ``responder``; same contract
    as ``ola.transport.Transport``."""

    def __init__(self, responder: Optional[Callable[[str], Reply]] = None, timeout_ms: int = 1000):
        self._responder = responder or (lambda cmd: None)
        self._inbox: deque = deque()
        self._open = True
        self._lock = threading.Lock()
        self.log: List[str] = []
        self.timeout_ms = timeout_ms
        self.peer = "sim://"
        self.flush_count = 0
        self.terminators = (b"\n", b"\n")

    @property
    def is_open(self) -> bool:
        """True until ``close()`` is called or the instrument closes the connection."""
        return self._open

    def close(self) -> None:
        """Close the connection; later calls raise ``TransportClosed``."""
        self._open = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _need_open(self):
        if not self._open:
            raise TransportClosed("[TRN-004] connection closed")

    def send(self, cmd) -> None:
        """Send ``cmd`` followed by the write terminator, in a single write."""
        self._need_open()
        text = cmd.decode() if isinstance(cmd, (bytes, bytearray)) else cmd
        with self._lock:
            self.log.append(text)
            reply = self._responder(text)
            if reply is None:
                return
            for item in reply if isinstance(reply, list) else [reply]:
                self._inbox.append(item.encode() if isinstance(item, str) else item)

    def write(self, data) -> None:
        """Send ``data`` exactly as given (the simulator records it like any command)."""
        self.send(data)

    def _pop(self) -> bytes:
        with self._lock:
            if not self._inbox:
                raise TransportTimeout("[TRN-003] timeout waiting for the instrument")
            return self._inbox.popleft()

    def read_line(self, timeout_ms: Optional[int] = None) -> str:
        """Read one answer line, terminator removed (``TransportTimeout`` if none comes)."""
        self._need_open()
        return self._pop().decode().rstrip("\r\n")

    def read_block(self, timeout_ms: Optional[int] = None) -> bytes:
        """Read an IEEE 488.2 definite-length block (waveform); drop the terminator after it."""
        self._need_open()
        return self._pop()

    def set_terminators(self, write_term, read_term) -> None:
        """Remember the terminators (the simulator works on whole messages and ignores them)."""
        if not (read_term.encode() if isinstance(read_term, str) else bytes(read_term)):
            raise ValueError("read terminator must not be empty")
        self.terminators = (write_term, read_term)

    def read_until(self, term, timeout_ms: Optional[int] = None) -> bytes:
        """Read up to and consuming ``term`` (the terminator is not returned)."""
        self._need_open()
        term = term.encode() if isinstance(term, str) else bytes(term)
        with self._lock:
            data = b"".join(self._inbox)
            pos = data.find(term) if term else -1
            if pos < 0:
                raise TransportTimeout("[TRN-003] timeout waiting for the instrument")
            self._inbox.clear()
            end = pos + len(term)
            rest = data[end:]
            if rest:
                self._inbox.append(rest)
            return data[:pos]

    def read_exact(self, n: int, timeout_ms: Optional[int] = None) -> bytes:
        """Read exactly ``n`` bytes (nothing is consumed if fewer are available)."""
        self._need_open()
        with self._lock:
            data = b"".join(self._inbox)
            if len(data) < n:
                raise TransportTimeout("[TRN-003] timeout waiting for the instrument")
            self._inbox.clear()
            if data[n:]:
                self._inbox.append(data[n:])
            return data[:n]

    def query(self, cmd, timeout_ms: Optional[int] = None) -> str:
        """``send(cmd)`` followed by ``read_line()``."""
        self.send(cmd)
        return self.read_line(timeout_ms)

    def flush_input(self) -> None:
        """Throw away everything received and not yet read (stale answers)."""
        self._need_open()
        with self._lock:
            self._inbox.clear()
            self.flush_count += 1
