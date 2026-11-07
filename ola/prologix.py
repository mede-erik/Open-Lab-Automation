# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Transport through a Prologix-compatible GPIB adapter (Prologix GPIB-USB, GPIB-ETHERNET, AR488).

These adapters are not VISA interfaces: the computer talks to the adapter over a serial port
(USB) or a TCP socket (port 1234) and the adapter is driven with ``++`` commands (``++addr 7``,
``++read eoi``...). ``PrologixConnection`` hides that and behaves like every other connection
(the contract is ``ola.transport.Transport``), so a project can use an instrument behind such an
adapter with the address::

    PROLOGIX::/dev/ttyUSB0::7::INSTR        serial port (Linux / macOS)
    PROLOGIX::COM5::7::INSTR                serial port (Windows)
    PROLOGIX::192.168.1.20::7::INSTR        GPIB-ETHERNET (port 1234)
    PROLOGIX::192.168.1.20:1234::7::INSTR   explicit port

Several instruments on the same bus share one *link* to the adapter (a serial port can be opened
only once): every connection sends ``++addr`` again when the adapter is talking to another
instrument. How the adapter is set up when the link opens: controller mode, no automatic read
after write (``++auto 0``), EOI asserted on the last byte, nothing appended by the adapter
(``++eos 3``: the connection sends its own terminator, escaped), configuration not saved to the
adapter's EEPROM.

Reading: after a write, the first read asks the adapter to read from the instrument until EOI
(``++read eoi``); the answer then arrives as plain bytes. The adapter waits at most 3 s between
two characters (``++read_tmo_ms 3000``, the largest value).
"""

from __future__ import annotations

import re
import threading
from typing import Any, Callable, Dict, Optional, Tuple

from .errors import TransportClosed, TransportError

PROLOGIX_TCP_PORT = 1234
ESC = b"\x1b"
_SPECIAL = (b"\x1b", b"\r", b"\n", b"+")  # ESC first: it is the escape character itself

_ADDRESS = re.compile(
    r"^PROLOGIX::(?P<port>.+?)::(?P<pad>\d+)(?:::(?P<sad>\d+))?(?:::INSTR)?$", re.I
)

# opener(port) -> transport to the adapter itself (a serial port or a TCP socket)
LinkOpener = Callable[[str, int], Any]


def is_prologix_address(address: str) -> bool:
    """True for a ``PROLOGIX::...`` address."""
    return bool(address) and address.strip().upper().startswith("PROLOGIX::")


def parse_address(address: str) -> Tuple[str, int, Optional[int]]:
    """``'PROLOGIX::COM5::7::INSTR'`` -> ``('COM5', 7, None)``; the third value is the secondary
    address (96-126 on the bus, given here as 0-30), or None."""
    m = _ADDRESS.match(address.strip())
    if not m:
        raise TransportError(
            f"[TRN-006] invalid argument: '{address}' is not a Prologix address "
            "(PROLOGIX::<port>::<gpib address>::INSTR)"
        )
    pad = int(m.group("pad"))
    sad = int(m.group("sad")) if m.group("sad") is not None else None
    if not 0 <= pad <= 30 or (sad is not None and not 0 <= sad <= 30):
        raise TransportError(
            f"[TRN-006] invalid argument: GPIB address out of range (0-30) in '{address}'"
        )
    return m.group("port"), pad, sad


def make_address(port: str, pad: int, sad: Optional[int] = None) -> str:
    """The project address of instrument ``pad`` behind the adapter on ``port``."""
    tail = f"::{sad}" if sad is not None else ""
    return f"PROLOGIX::{port}::{pad}{tail}::INSTR"


def is_network_port(port: str) -> bool:
    """True when ``port`` names a GPIB-ETHERNET adapter (host or host:port), not a serial port."""
    p = port.strip()
    if p.startswith("/") or p.upper().startswith("COM") or p.startswith("\\\\"):
        return False
    host = p.rsplit(":", 1)[0] if p.count(":") == 1 else p
    return "." in host or host.lower() == "localhost"


def escape(data: bytes) -> bytes:
    """Escape the characters the adapter would take for itself (CR, LF, ESC, '+')."""
    out = bytearray()
    for byte in data:
        b = bytes([byte])
        if b in _SPECIAL:
            out += ESC
        out += b
    return bytes(out)


def _default_link_opener(port: str, timeout_ms: int):
    from .transport import open_serial, open_tcp

    if is_network_port(port):
        host, _, tcp = port.partition(":")
        return open_tcp(host, int(tcp) if tcp else PROLOGIX_TCP_PORT, timeout_ms)
    # USB adapters ignore the baud rate; AR488 (an Arduino) uses 115200
    return open_serial(port, 115200, timeout_ms)


def _b(x) -> bytes:
    return x.encode("utf-8") if isinstance(x, str) else bytes(x)


class PrologixLink:
    """The one connection to an adapter, shared by every instrument on its bus."""

    def __init__(self, port: str, transport: Any):
        self.port = port
        self.transport = transport
        self.lock = threading.RLock()
        self.users = 0
        self.current: Optional[Tuple[int, Optional[int]]] = None
        self.read_requested = False
        self.version = ""

    def command(self, text: str) -> None:
        """Send one ``++`` command to the adapter."""
        self.transport.write(text.encode("ascii") + b"\n")

    def ask(self, text: str, timeout_ms: int = 1000) -> str:
        """Send one ``++`` command that answers (``++ver``, ``++spoll``) and read the answer."""
        self.command(text)
        return self.transport.read_line(timeout_ms)

    def setup(self) -> None:
        """Put the adapter in the mode the connection expects (see the module docstring)."""
        try:
            self.transport.flush_input()
        except TransportError:
            pass
        self.version = ""
        # an AR488 (Arduino) resets when its serial port opens and needs ~2 s before answering
        for wait_ms in (1000, 2500):
            try:
                self.version = self.ask("++ver", wait_ms).strip()
                break
            except TransportError:
                continue
        if not self.version:
            raise TransportError(
                f"[TRN-001] connection failed: {self.port}: no Prologix-compatible adapter "
                "answers to ++ver"
            )
        for text in (
            "++savecfg 0",
            "++mode 1",
            "++auto 0",
            "++eoi 1",
            "++eos 3",
            "++read_tmo_ms 3000",
        ):
            self.command(text)
        self.current = None
        self.read_requested = False

    def select(self, pad: int, sad: Optional[int]) -> None:
        """Address instrument ``pad`` (and ``sad``) if the adapter is talking to another one."""
        if self.current == (pad, sad):
            return
        self.command(f"++addr {pad}" + (f" {96 + sad}" if sad is not None else ""))
        self.current = (pad, sad)
        self.read_requested = False


_LINKS: Dict[str, PrologixLink] = {}
_LINKS_LOCK = threading.Lock()


def _acquire_link(port: str, timeout_ms: int, opener: Optional[LinkOpener]) -> PrologixLink:
    key = port.strip().lower()
    with _LINKS_LOCK:
        link = _LINKS.get(key)
        if link is None or not link.transport.is_open:
            try:
                transport = (opener or _default_link_opener)(port, timeout_ms)
            except TransportError:
                raise
            except Exception as exc:  # pyserial / socket errors of the opener
                raise TransportError(f"[TRN-001] connection failed: {port}: {exc}") from exc
            link = PrologixLink(port, transport)
            try:
                link.setup()
            except Exception:
                transport.close()
                raise
            _LINKS[key] = link
        link.users += 1
        return link


def _release_link(link: PrologixLink) -> None:
    with _LINKS_LOCK:
        link.users -= 1
        if link.users <= 0:
            _LINKS.pop(link.port.strip().lower(), None)
            try:
                link.transport.close()
            except TransportError:
                pass


def adapter_version(port: str, timeout_ms: int = 2000, opener: Optional[LinkOpener] = None) -> str:
    """The answer of the adapter on ``port`` to ``++ver`` (``TransportError`` if none)."""
    link = _acquire_link(port, timeout_ms, opener)
    try:
        return link.version
    finally:
        _release_link(link)


class PrologixConnection:
    """One instrument behind a Prologix-compatible adapter; the method contract is
    ``ola.transport.Transport``."""

    def __init__(self, link: PrologixLink, pad: int, sad: Optional[int], timeout_ms: int):
        self._link: Optional[PrologixLink] = link
        self._pad, self._sad = pad, sad
        self._timeout_ms = timeout_ms
        self._wterm, self._rterm = b"\n", b"\n"
        self._peer = f"prologix://{link.port}/{make_address(link.port, pad, sad)}"

    # ----- construction -----------------------------------------------------------------
    @staticmethod
    def open(address: str, timeout_ms: int = 5000, opener: Optional[LinkOpener] = None):
        """Open the instrument at ``PROLOGIX::<port>::<address>::INSTR``."""
        port, pad, sad = parse_address(address)
        link = _acquire_link(port, timeout_ms, opener)
        return PrologixConnection(link, pad, sad, timeout_ms)

    @staticmethod
    def open_device(
        port: str,
        pad: int,
        sad: Optional[int] = None,
        timeout_ms: int = 5000,
        opener: Optional[LinkOpener] = None,
    ):
        """Same as ``open(make_address(port, pad, sad))``."""
        return PrologixConnection.open(make_address(port, pad, sad), timeout_ms, opener)

    # ----- properties / settings ---------------------------------------------------------
    @property
    def peer(self) -> str:
        """Address of the instrument as text (see ``ola.transport.Transport``)."""
        return self._peer

    @property
    def is_open(self) -> bool:
        """True until ``close()`` is called or the adapter link is lost."""
        return self._link is not None and self._link.transport.is_open

    @property
    def timeout_ms(self) -> int:
        """Default timeout of every read, in milliseconds."""
        return self._timeout_ms

    @timeout_ms.setter
    def timeout_ms(self, value: int) -> None:
        self._timeout_ms = value

    def set_terminators(self, write_term, read_term) -> None:
        """Set the terminator appended by ``send`` and the one ``read_line`` waits for."""
        if not _b(read_term):
            raise TransportError("[TRN-006] invalid argument: read terminator must not be empty")
        self._wterm, self._rterm = _b(write_term), _b(read_term)

    def close(self) -> None:
        """Close the connection (the adapter link closes with its last user)."""
        link, self._link = self._link, None
        if link is not None:
            _release_link(link)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        return f"<ola.PrologixConnection {self._peer} open={self.is_open}>"

    # ----- bus operations (used by the GPIB adapter tool) -----------------------------------
    def interface_clear(self) -> None:
        """Pulse IFC on the bus (every instrument stops talking/listening)."""
        with self._selected() as link:
            link.command("++ifc")
            link.current = None

    def device_clear(self) -> None:
        """Selected Device Clear of this instrument."""
        with self._selected() as link:
            link.command("++clr")

    def go_to_local(self) -> None:
        """Return this instrument to local (front-panel) control."""
        with self._selected() as link:
            link.command("++loc")

    # ----- writing ------------------------------------------------------------------------
    def write(self, data) -> None:
        """Send ``data`` exactly as given (no terminator), in a single write."""
        with self._selected() as link:
            link.transport.write(escape(_b(data)) + b"\n")
            link.read_requested = False

    def send(self, cmd) -> None:
        """Send ``cmd`` followed by the write terminator, in a single write."""
        self.write(_b(cmd) + self._wterm)

    # ----- reading ------------------------------------------------------------------------
    def flush_input(self) -> None:
        """Throw away everything received and not yet read (stale answers)."""
        with self._selected() as link:
            link.transport.flush_input()

    def read_until(self, term, timeout_ms: Optional[int] = None) -> bytes:
        """Read up to and consuming ``term`` (the terminator is not returned)."""
        with self._reading() as transport:
            return transport.read_until(term, self._t(timeout_ms))

    def read_line(self, timeout_ms: Optional[int] = None) -> str:
        """Read one answer line, terminator removed (``TransportTimeout`` if none comes)."""
        line = self.read_until(self._rterm, timeout_ms)
        if self._rterm == b"\n" and line.endswith(b"\r"):
            line = line[:-1]
        return line.decode("utf-8", errors="replace")

    def query(self, cmd, timeout_ms: Optional[int] = None) -> str:
        """``send(cmd)`` followed by ``read_line()``."""
        link = self._need()
        with link.lock:
            self.send(cmd)
            return self.read_line(timeout_ms)

    def read_exact(self, n: int, timeout_ms: Optional[int] = None) -> bytes:
        """Read exactly ``n`` bytes."""
        with self._reading() as transport:
            return transport.read_exact(n, self._t(timeout_ms))

    def read_block(self, timeout_ms: Optional[int] = None) -> bytes:
        """IEEE 488.2 definite-length block; the trailing terminator is consumed if present."""
        with self._reading() as transport:
            return transport.read_block(self._t(timeout_ms))

    # ----- internals ----------------------------------------------------------------------
    def _t(self, timeout_ms: Optional[int]) -> int:
        return self._timeout_ms if timeout_ms is None else timeout_ms

    def _need(self) -> PrologixLink:
        link = self._link
        if link is None or not link.transport.is_open:
            raise TransportClosed("[TRN-004] connection closed")
        return link

    class _Selected:
        def __init__(self, conn: "PrologixConnection", read: bool):
            self.conn, self.read = conn, read

        def __enter__(self):
            link = self.conn._need()
            link.lock.acquire()
            try:
                link.select(self.conn._pad, self.conn._sad)
                if self.read and not link.read_requested:
                    link.command("++read eoi")
                    link.read_requested = True
            except BaseException:
                link.lock.release()
                raise
            self.link = link
            return link.transport if self.read else link

        def __exit__(self, *_):
            self.link.lock.release()

    def _selected(self):
        return PrologixConnection._Selected(self, read=False)

    def _reading(self):
        return PrologixConnection._Selected(self, read=True)


__all__ = [
    "PrologixConnection",
    "PrologixLink",
    "PROLOGIX_TCP_PORT",
    "adapter_version",
    "escape",
    "is_network_port",
    "is_prologix_address",
    "make_address",
    "parse_address",
]
