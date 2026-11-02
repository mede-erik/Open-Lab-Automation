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
    def __init__(self, responder: Optional[Callable[[str], Reply]] = None, timeout_ms: int = 1000):
        self._responder = responder or (lambda cmd: None)
        self._inbox: deque = deque()
        self._open = True
        self._lock = threading.Lock()
        self.log: List[str] = []
        self.timeout_ms = timeout_ms
        self.peer = "sim://"
        self.flush_count = 0

    @property
    def is_open(self) -> bool:
        return self._open

    def close(self) -> None:
        self._open = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _need_open(self):
        if not self._open:
            raise TransportClosed("[TRN-004] connection closed")

    def send(self, cmd) -> None:
        self._need_open()
        text = cmd.decode() if isinstance(cmd, (bytes, bytearray)) else cmd
        with self._lock:
            self.log.append(text)
            reply = self._responder(text)
            if reply is None:
                return
            for item in reply if isinstance(reply, list) else [reply]:
                self._inbox.append(item.encode() if isinstance(item, str) else item)

    write = send

    def _pop(self) -> bytes:
        with self._lock:
            if not self._inbox:
                raise TransportTimeout("[TRN-003] timeout waiting for the instrument")
            return self._inbox.popleft()

    def read_line(self, timeout_ms: Optional[int] = None) -> str:
        self._need_open()
        return self._pop().decode().rstrip("\r\n")

    def read_block(self, timeout_ms: Optional[int] = None) -> bytes:
        self._need_open()
        return self._pop()

    def query(self, cmd, timeout_ms: Optional[int] = None) -> str:
        self.send(cmd)
        return self.read_line(timeout_ms)

    def flush_input(self) -> None:
        self._need_open()
        with self._lock:
            self._inbox.clear()
            self.flush_count += 1
