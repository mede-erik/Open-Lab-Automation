# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A tiny scriptable fake instrument for transport tests (TCP and pty-serial)."""

from __future__ import annotations

import os
import socket
import threading
from typing import Callable


class FakeTcpInstrument:
    """Accepts one connection and hands the raw socket to ``handler``."""

    def __init__(self, handler: Callable[[socket.socket], None]):
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.port = self._srv.getsockname()[1]
        self._handler = handler
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            self._handler(conn)
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        # shutdown() wakes a thread blocked in accept(); close() alone does not on Linux
        try:
            self._srv.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._srv.close()


def line_server(reply: Callable[[bytes], bytes | None]) -> Callable[[socket.socket], None]:
    """Handler: for every newline-terminated command call ``reply(cmd)``; send what it returns."""

    def handler(conn: socket.socket) -> None:
        acc = b""
        while True:
            data = conn.recv(4096)
            if not data:
                return
            acc += data
            while b"\n" in acc:
                line, acc = acc.split(b"\n", 1)
                out = reply(line)
                if out is not None:
                    conn.sendall(out)

    return handler


class FakePtyInstrument:
    """Serial-port stand-in: a pseudo-terminal pair. Open ``slave_path`` as the port."""

    def __init__(self, reply: Callable[[bytes], bytes | None], eol: bytes = b"\r"):
        import pty
        import tty

        self._master, slave = pty.openpty()
        tty.setraw(self._master)
        tty.setraw(slave)
        self.slave_path = os.ttyname(slave)
        self._slave = slave  # keep open so the pty does not hang up
        self._reply = reply
        self._eol = eol
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        acc = b""
        while not self._stop:
            try:
                data = os.read(self._master, 4096)
            except OSError:
                return
            acc += data
            while self._eol in acc:
                line, acc = acc.split(self._eol, 1)
                out = self._reply(line)
                if out is not None:
                    os.write(self._master, out)

    def close(self):
        self._stop = True
        for fd in (self._master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass
