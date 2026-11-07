# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""GPIB adapters: profiles, configuration, driver check, bus scan and bus operations.

The engine behind the tool *Tools > GPIB adapters* (``frontend/ui/GpibAdapterDialog.py``); no Qt
here, pyvisa and pyserial are imported only when needed.

Two families of adapters are supported:

* **VISA** adapters, which the VISA library shows as a board ``GPIBn`` (Keysight 82357B / 82357A,
  NI GPIB-USB-HS / HS+, Measurement Computing USB-488, any other GPIB board). On Windows the
  vendor's VISA (Keysight IO Libraries Suite or NI-VISA + NI-488.2) drives them; on Linux the
  ``linux-gpib`` kernel driver plus ``pyvisa-py`` (``gpib-ctypes``). An instrument has the address
  ``GPIB<board>::<address>::INSTR``.
* **Prologix-compatible** adapters (Prologix GPIB-USB, GPIB-ETHERNET, AR488), driven with ``++``
  commands over a serial port or TCP; an instrument has the address
  ``PROLOGIX::<port>::<address>::INSTR`` and is opened by ``ola.prologix.PrologixConnection``.

Every adapter is described by a ``GpibAdapterConfig`` (a name, the model from ``PROFILES``, the
board number or the port, the scan settings). Main functions::

    check_environment(cfg)            # driver installed? adapter present? (list of DiagItem)
    scan_bus(cfg, progress, cancel)   # which addresses answer, and with which identification
    open_device(cfg, 7)               # a connection (ola.transport.Transport) to address 7
    interface_clear(cfg)              # IFC on the bus
    detect_adapters()                 # adapters that look present, as ready-made configurations

Messages are given as a key plus values (``DiagItem.key`` / ``values``) so the user interface can
translate them; ``DiagItem.text`` is the English text (``MESSAGES``). Errors are ``GpibError`` with
a ``[GPIB-xxx]`` code (see ERROR_CODES.md).
"""

from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import sys
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .errors import TransportError, TransportTimeout
from .prologix import PrologixConnection, adapter_version, make_address

FAMILY_VISA = "visa"
FAMILY_PROLOGIX = "prologix"

MIN_ADDRESS, MAX_ADDRESS = 0, 30
DEFAULT_IDN_COMMANDS = ("*IDN?", "ID?")  # ID? : older HP instruments (3478A, 3457A...)
BACKENDS = ("", "@py", "@ivi")  # default VISA library, pyvisa-py, IVI (Keysight / NI)

_CODE = re.compile(r"\[([A-Z]+-\d{3})\]")


class GpibError(Exception):
    """A problem with a GPIB adapter; the message starts with its ``[GPIB-xxx]`` code."""

    @property
    def code(self) -> str:
        """The code of the message, e.g. ``"GPIB-001"`` ("" if it has none)."""
        m = _CODE.search(str(self))
        return m.group(1) if m else ""


# ----- adapter profiles -----------------------------------------------------------------------
@dataclass(frozen=True)
class AdapterProfile:
    """A model of GPIB adapter: how it is reached and how to recognise it on the USB bus."""

    id: str
    name: str
    family: str
    usb_ids: Tuple[Tuple[int, int], ...] = ()
    """(vendor, product) of the adapter ready to work (firmware loaded)."""
    no_firmware_ids: Tuple[Tuple[int, int], ...] = ()
    """(vendor, product) of the adapter whose firmware has not been loaded yet (Linux)."""
    linux_driver: str = ""
    """The ``linux-gpib`` driver (``board_type`` in ``/etc/gpib.conf``)."""
    hint_windows: str = "hint_windows_generic"
    hint_linux: str = "hint_linux_generic"
    """Keys of ``MESSAGES``: what to install on each system."""


PROFILES: Dict[str, AdapterProfile] = {
    p.id: p
    for p in (
        AdapterProfile(
            "keysight_82357b",
            "Keysight 82357B USB/GPIB",
            FAMILY_VISA,
            usb_ids=((0x0957, 0x0718),),
            no_firmware_ids=((0x0957, 0x0518),),
            linux_driver="agilent_82357a",
            hint_windows="hint_windows_keysight",
            hint_linux="hint_linux_keysight",
        ),
        AdapterProfile(
            "keysight_82357a",
            "Agilent/Keysight 82357A USB/GPIB",
            FAMILY_VISA,
            usb_ids=((0x0957, 0x0107),),
            no_firmware_ids=((0x0957, 0x0007),),
            linux_driver="agilent_82357a",
            hint_windows="hint_windows_keysight",
            hint_linux="hint_linux_keysight",
        ),
        AdapterProfile(
            "ni_gpib_usb_hs",
            "NI GPIB-USB-HS / GPIB-USB-HS+",
            FAMILY_VISA,
            usb_ids=((0x3923, 0x709B), (0x3923, 0x7618)),
            linux_driver="ni_usb_b",
            hint_windows="hint_windows_ni",
            hint_linux="hint_linux_ni",
        ),
        AdapterProfile(
            "mcc_usb_488",
            "Measurement Computing USB-488",
            FAMILY_VISA,
            hint_windows="hint_windows_ni",
        ),
        AdapterProfile("generic_visa", "Generic VISA GPIB board", FAMILY_VISA),
        AdapterProfile(
            "prologix_usb",
            "Prologix GPIB-USB",
            FAMILY_PROLOGIX,
            usb_ids=((0x0403, 0x6001),),  # FTDI FT232R: also used by other USB-serial cables
            hint_windows="hint_prologix_serial",
            hint_linux="hint_prologix_serial",
        ),
        AdapterProfile(
            "prologix_ethernet",
            "Prologix GPIB-ETHERNET",
            FAMILY_PROLOGIX,
            hint_windows="hint_prologix_ethernet",
            hint_linux="hint_prologix_ethernet",
        ),
        AdapterProfile(
            "ar488",
            "AR488 (Arduino, Prologix-compatible)",
            FAMILY_PROLOGIX,
            hint_windows="hint_prologix_serial",
            hint_linux="hint_prologix_serial",
        ),
    )
}
DEFAULT_PROFILE = "keysight_82357b"


def profile(profile_id: str) -> AdapterProfile:
    """The profile ``profile_id``; ``GpibError`` [GPIB-006] if unknown."""
    try:
        return PROFILES[profile_id]
    except KeyError:
        raise GpibError(f"[GPIB-006] invalid configuration: unknown adapter model '{profile_id}'")


# ----- configuration ---------------------------------------------------------------------------
@dataclass
class GpibAdapterConfig:
    """One adapter as the user configured it."""

    name: str = "GPIB0"
    profile: str = DEFAULT_PROFILE
    board: int = 0
    """VISA family: the interface number, ``GPIB<board>`` (Keysight Connection Expert / NI MAX)."""
    port: str = ""
    """Prologix family: serial port (``COM5``, ``/dev/ttyUSB0``) or host[:port] of a
    GPIB-ETHERNET."""
    backend: str = ""
    """VISA library used by the tool: "" default, "@py" pyvisa-py, "@ivi" IVI."""
    timeout_ms: int = 5000
    scan_timeout_ms: int = 400
    scan_first: int = 1
    scan_last: int = 30
    idn_commands: List[str] = field(default_factory=lambda: list(DEFAULT_IDN_COMMANDS))

    @property
    def family(self) -> str:
        """``FAMILY_VISA`` or ``FAMILY_PROLOGIX``, from the model."""
        return profile(self.profile).family

    def validate(self) -> "GpibAdapterConfig":
        """Raise ``GpibError`` [GPIB-006] if a value is not usable; returns self."""

        def bad(why: str):
            raise GpibError(f"[GPIB-006] invalid configuration of '{self.name}': {why}")

        if not str(self.name).strip():
            bad("the name is empty")
        family = profile(self.profile).family
        if family == FAMILY_VISA and not (isinstance(self.board, int) and 0 <= self.board <= 31):
            bad("the board number must be between 0 and 31")
        if family == FAMILY_PROLOGIX and not str(self.port).strip():
            bad("the serial port or network address of the adapter is empty")
        if self.backend not in BACKENDS:
            bad(f"unknown VISA backend '{self.backend}'")
        if not 1 <= int(self.timeout_ms) <= 600000:
            bad("the timeout must be between 1 ms and 600 s")
        if not 10 <= int(self.scan_timeout_ms) <= 60000:
            bad("the scan timeout must be between 10 ms and 60 s")
        if not MIN_ADDRESS <= self.scan_first <= self.scan_last <= MAX_ADDRESS:
            bad(f"the scan range must be within {MIN_ADDRESS}-{MAX_ADDRESS}, first <= last")
        if not [c for c in self.idn_commands if str(c).strip()]:
            bad("at least one identification command is needed")
        return self

    def address(self, pad: int, sad: Optional[int] = None) -> str:
        """The project address of the instrument at GPIB address ``pad`` behind this adapter."""
        if not MIN_ADDRESS <= int(pad) <= MAX_ADDRESS:
            raise GpibError(f"[GPIB-006] invalid configuration: GPIB address {pad} not in 0-30")
        if self.family == FAMILY_PROLOGIX:
            return make_address(self.port.strip(), int(pad), sad)
        tail = f"::{sad}" if sad is not None else ""
        return f"GPIB{self.board}::{int(pad)}{tail}::INSTR"

    def to_dict(self) -> Dict[str, Any]:
        """The configuration as a JSON-ready dictionary (see ``from_dict``)."""
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "GpibAdapterConfig":
        """Build from a saved dictionary (unknown keys ignored, missing keys get the default),
        then ``validate()``."""
        if not isinstance(data, dict):
            raise GpibError("[GPIB-006] invalid configuration: not a JSON object")
        known = GpibAdapterConfig.__dataclass_fields__
        values = {k: v for k, v in data.items() if k in known}
        try:
            cfg = GpibAdapterConfig(**values)
            for key in ("board", "timeout_ms", "scan_timeout_ms", "scan_first", "scan_last"):
                setattr(cfg, key, int(getattr(cfg, key)))
            cfg.name, cfg.port = str(cfg.name), str(cfg.port)
            cfg.idn_commands = [str(c) for c in (cfg.idn_commands or []) if str(c).strip()]
        except (TypeError, ValueError) as exc:
            raise GpibError(f"[GPIB-006] invalid configuration: {exc}") from exc
        return cfg.validate()


def configs_to_json(configs: Sequence[GpibAdapterConfig]) -> str:
    """The list of adapters as JSON text (what the application saves)."""
    return json.dumps([c.to_dict() for c in configs], indent=1)


def configs_from_json(text: str) -> List[GpibAdapterConfig]:
    """The list saved by ``configs_to_json``; ``GpibError`` [GPIB-006] if it is not valid or two
    adapters have the same name."""
    if not text or not text.strip():
        return []
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise GpibError(f"[GPIB-006] invalid configuration: {exc}") from exc
    if isinstance(data, dict):  # a single adapter
        data = [data]
    if not isinstance(data, list):
        raise GpibError("[GPIB-006] invalid configuration: a list of adapters is expected")
    configs = [GpibAdapterConfig.from_dict(d) for d in data]
    check_unique_names(configs)
    return configs


def check_unique_names(configs: Sequence[GpibAdapterConfig]) -> None:
    """``GpibError`` [GPIB-006] if two adapters have the same name."""
    seen: Set[str] = set()
    for c in configs:
        key = c.name.strip().lower()
        if key in seen:
            raise GpibError(f"[GPIB-006] invalid configuration: two adapters are called '{c.name}'")
        seen.add(key)


def unique_name(base: str, configs: Sequence[GpibAdapterConfig]) -> str:
    """``base`` or ``base (2)``, ``base (3)``... not used by any of ``configs``."""
    names = {c.name.strip().lower() for c in configs}
    if base.lower() not in names:
        return base
    n = 2
    while f"{base} ({n})".lower() in names:
        n += 1
    return f"{base} ({n})"


# ----- messages ------------------------------------------------------------------------------
MESSAGES: Dict[str, str] = {
    "diag_pyvisa_ok": "pyvisa {version} is installed",
    "diag_no_pyvisa": "[GPIB-002] pyvisa is not installed (pip install pyvisa pyvisa-py)",
    "diag_pyserial_ok": "pyserial is installed",
    "diag_no_pyserial": "[GPIB-002] pyserial is not installed (pip install pyserial)",
    "diag_usb_found": "{adapter} found on the USB bus ({ids})",
    "diag_usb_missing": "{adapter} not found on the USB bus: check the cable",
    "diag_usb_unknown": "USB devices cannot be listed on this system: check skipped",
    "diag_no_firmware": "[GPIB-003] {adapter} is connected but its firmware is not loaded ({ids})",
    "diag_backend_ok": "VISA library '{backend}' opened: {library}",
    "diag_backend_vendor": "VISA library in use: {vendor}",
    "diag_backend_failed": "VISA library '{backend}' not available: {error}",
    "diag_board_found": "Board GPIB{board} found with the VISA library '{backend}'",
    "diag_board_missing": "Board GPIB{board} not found with the VISA library '{backend}' "
    "(boards seen: {boards})",
    "diag_board_not_found": "[GPIB-001] the adapter is not seen as GPIB{board} by any VISA library",
    "diag_py_no_gpib": "pyvisa-py cannot use GPIB: install linux-gpib and its Python bindings "
    "or gpib-ctypes (pip install gpib-ctypes)",
    "diag_no_dev_gpib": "{device} does not exist: the linux-gpib driver is not loaded/configured",
    "diag_dev_gpib_ok": "{device} is present (linux-gpib)",
    "diag_no_port": "[GPIB-006] no serial port or network address is set for the adapter",
    "diag_port_missing": "Serial port {port} not found (ports present: {ports})",
    "diag_prologix_ok": "Adapter on {port} answers: {version}",
    "diag_prologix_failed": "[GPIB-001] no Prologix-compatible adapter answers on {port}: {error}",
    "hint_windows_keysight": "Windows: install the Keysight IO Libraries Suite, plug the adapter "
    "in and check in Keysight Connection Expert which interface it is (GPIB0, GPIB1...). With "
    "NI-VISA installed too, enable 'VISA coexistence' or set the IVI backend.",
    "hint_linux_keysight": 'Linux: install linux-gpib, set board_type = "agilent_82357a" in '
    "/etc/gpib.conf, load the firmware (gpib_config / fxload with the linux-gpib firmware "
    "package), then pip install gpib-ctypes and use the pyvisa-py backend (@py).",
    "hint_windows_ni": "Windows: install NI-VISA and NI-488.2, plug the adapter in and check its "
    "interface number (GPIB0...) in NI MAX.",
    "hint_linux_ni": 'Linux: install linux-gpib, set board_type = "ni_usb_b" in /etc/gpib.conf, '
    "run gpib_config, then pip install gpib-ctypes and use the pyvisa-py backend (@py).",
    "hint_windows_generic": "Windows: install the VISA library of the adapter's maker and check "
    "the interface number (GPIB0...) in its configuration utility.",
    "hint_linux_generic": "Linux: configure the adapter in linux-gpib (/etc/gpib.conf, "
    "gpib_config) and use the pyvisa-py backend (@py) with gpib-ctypes.",
    "hint_prologix_serial": "The adapter appears as a serial port (COMx on Windows, /dev/ttyUSBx "
    "or /dev/ttyACMx on Linux). On Linux add your user to the 'dialout' group.",
    "hint_prologix_ethernet": "Set the IP address of the adapter (Prologix NetFinder); the tool "
    "connects to TCP port 1234.",
}


@dataclass
class DiagItem:
    """One line of the driver check: ``level`` is "ok", "info", "warn" or "error"."""

    level: str
    key: str
    values: Dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """The message in English, with its values."""
        return MESSAGES.get(self.key, self.key).format(**self.values)


def worst_level(items: Iterable[DiagItem]) -> str:
    """ "error" if any item is an error, then "warn", else "ok"."""
    levels = {i.level for i in items}
    return "error" if "error" in levels else "warn" if "warn" in levels else "ok"


# ----- system probing (replaceable in tests) -----------------------------------------------------
def list_usb_devices() -> Optional[List[Tuple[int, int]]]:
    """(vendor, product) of the USB devices present, or None if they cannot be listed."""
    if sys.platform.startswith("linux") and os.path.isdir("/sys/bus/usb/devices"):
        found = []
        for vid_file in glob.glob("/sys/bus/usb/devices/*/idVendor"):
            try:
                with open(vid_file) as f:
                    vid = int(f.read().strip(), 16)
                with open(os.path.join(os.path.dirname(vid_file), "idProduct")) as f:
                    pid = int(f.read().strip(), 16)
            except (OSError, ValueError):
                continue
            found.append((vid, pid))
        return found
    try:
        import usb.core  # pyusb (optional)

        return [(d.idVendor, d.idProduct) for d in usb.core.find(find_all=True)]
    except Exception:  # pyusb missing or no libusb backend
        return None


def list_serial_ports() -> List[Tuple[str, Optional[int], Optional[int], str]]:
    """(device, vendor, product, description) of the serial ports present ([] without pyserial)."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.vid, p.pid, p.description or "") for p in list_ports.comports()]


def _resource_manager(backend: str = ""):
    import pyvisa

    return pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()


def _ids_text(ids: Iterable[Tuple[int, int]]) -> str:
    return ", ".join(f"{v:04x}:{p:04x}" for v, p in ids)


def _is_pyvisa_py(library: str) -> bool:
    """True for pyvisa-py ("Visa Library at py")."""
    low = library.lower().strip()
    return "pyvisa-py" in low or low.endswith(" py") or low in ("py", "@py")


def _vendor_of(library: str) -> str:
    low = library.lower()
    if "ktvisa" in low or "agvisa" in low or "keysight" in low or "agilent" in low:
        return "Keysight VISA"
    if "ni-visa" in low or "nivisa" in low or "national instruments" in low:
        return "NI-VISA"
    if _is_pyvisa_py(library):
        return "pyvisa-py"
    return library


def _boards(rm) -> List[str]:
    """The GPIB interfaces a resource manager sees (``GPIB0::INTFC``...)."""
    try:
        return [r for r in rm.list_resources("GPIB?*::INTFC")]
    except Exception:  # no GPIB support in this backend / nothing found
        return []


def check_environment(
    config: GpibAdapterConfig,
    rm_factory: Callable[[str], Any] = _resource_manager,
    usb_devices: Optional[Callable[[], Optional[List[Tuple[int, int]]]]] = None,
    serial_ports: Callable[[], List[Tuple[str, Optional[int], Optional[int], str]]] = None,
    platform: str = sys.platform,
    path_exists: Callable[[str], bool] = os.path.exists,
    find_spec: Callable[[str], Any] = importlib.util.find_spec,
    prologix_opener=None,
) -> List[DiagItem]:
    """Check what the adapter of ``config`` needs, step by step (see ``MESSAGES``); the last item
    is the installation hint for this system. The arguments after ``config`` replace the probing
    of the real system (tests)."""
    prof = profile(config.profile)
    items: List[DiagItem] = []
    usb = (usb_devices or list_usb_devices)()
    if prof.usb_ids or prof.no_firmware_ids:
        name = prof.name
        if usb is None:
            items.append(DiagItem("info", "diag_usb_unknown"))
        else:
            ready = [i for i in prof.usb_ids if i in usb]
            raw = [i for i in prof.no_firmware_ids if i in usb]
            if ready:
                items.append(
                    DiagItem("ok", "diag_usb_found", {"adapter": name, "ids": _ids_text(ready)})
                )
            elif raw:
                items.append(
                    DiagItem("error", "diag_no_firmware", {"adapter": name, "ids": _ids_text(raw)})
                )
            else:
                items.append(DiagItem("warn", "diag_usb_missing", {"adapter": name}))

    if prof.family == FAMILY_VISA:
        items += _check_visa(config, rm_factory, platform, path_exists, find_spec)
    else:
        items += _check_prologix(
            config, serial_ports or list_serial_ports, find_spec, prologix_opener
        )
    hint = prof.hint_windows if platform.startswith("win") else prof.hint_linux
    items.append(DiagItem("info", hint))
    return items


def _check_visa(config, rm_factory, platform, path_exists, find_spec) -> List[DiagItem]:
    items: List[DiagItem] = []
    try:
        import pyvisa
    except ImportError:
        return [DiagItem("error", "diag_no_pyvisa")]
    items.append(DiagItem("ok", "diag_pyvisa_ok", {"version": getattr(pyvisa, "__version__", "?")}))
    wanted = f"GPIB{config.board}::INTFC"
    found_anywhere = False
    seen_py = False
    for backend in [config.backend] if config.backend else ["", "@py"]:
        label = backend or "default"
        if backend == "@py" and (seen_py or found_anywhere):
            continue  # the default library already is pyvisa-py, or it already sees the board
        try:
            rm = rm_factory(backend)
        except Exception as exc:  # no VISA library of this kind installed
            items.append(
                DiagItem("warn", "diag_backend_failed", {"backend": label, "error": str(exc)})
            )
            continue
        library = str(getattr(rm, "visalib", label))
        items.append(DiagItem("ok", "diag_backend_ok", {"backend": label, "library": library}))
        if backend == "":
            items.append(DiagItem("info", "diag_backend_vendor", {"vendor": _vendor_of(library)}))
        if _is_pyvisa_py(library) or backend == "@py":
            seen_py = True
            if find_spec("gpib_ctypes") is None and find_spec("gpib") is None:
                items.append(DiagItem("warn", "diag_py_no_gpib"))
            if platform.startswith("linux"):
                device = f"/dev/gpib{config.board}"
                if path_exists(device):
                    items.append(DiagItem("ok", "diag_dev_gpib_ok", {"device": device}))
                else:
                    items.append(DiagItem("warn", "diag_no_dev_gpib", {"device": device}))
        boards = _boards(rm)
        if any(b.upper() == wanted.upper() for b in boards):
            found_anywhere = True
            items.append(
                DiagItem("ok", "diag_board_found", {"board": config.board, "backend": label})
            )
        else:
            items.append(
                DiagItem(
                    "warn",
                    "diag_board_missing",
                    {"board": config.board, "backend": label, "boards": ", ".join(boards) or "-"},
                )
            )
    if not found_anywhere:
        items.append(DiagItem("error", "diag_board_not_found", {"board": config.board}))
    return items


def _check_prologix(config, serial_ports, find_spec, opener) -> List[DiagItem]:
    from .prologix import is_network_port

    items: List[DiagItem] = []
    port = config.port.strip()
    if not port:
        return [DiagItem("error", "diag_no_port")]
    if not is_network_port(port):
        if find_spec("serial") is None:
            return [DiagItem("error", "diag_no_pyserial")]
        items.append(DiagItem("ok", "diag_pyserial_ok"))
        ports = [p[0] for p in serial_ports()]
        if opener is None and ports and port not in ports:
            items.append(
                DiagItem("warn", "diag_port_missing", {"port": port, "ports": ", ".join(ports)})
            )
    try:
        version = adapter_version(port, max(config.timeout_ms, 1000), opener)
        items.append(DiagItem("ok", "diag_prologix_ok", {"port": port, "version": version}))
    except TransportError as exc:
        items.append(DiagItem("error", "diag_prologix_failed", {"port": port, "error": str(exc)}))
    return items


# ----- detection -------------------------------------------------------------------------------
def detect_adapters(
    existing: Sequence[GpibAdapterConfig] = (),
    rm_factory: Callable[[str], Any] = _resource_manager,
    usb_devices: Optional[Callable[[], Optional[List[Tuple[int, int]]]]] = None,
    serial_ports: Optional[
        Callable[[], List[Tuple[str, Optional[int], Optional[int], str]]]
    ] = None,
) -> List[GpibAdapterConfig]:
    """Adapters that look present and are not in ``existing`` yet, as configurations to add:
    every GPIB board a VISA library sees (model guessed from the USB bus) and every serial port
    that looks like a Prologix (FTDI chip or 'Prologix'/'AR488' in its description)."""
    taken = list(existing)
    have_boards = {c.board for c in existing if c.family == FAMILY_VISA}
    have_ports = {c.port.strip().lower() for c in existing if c.family == FAMILY_PROLOGIX}
    usb = (usb_devices or list_usb_devices)() or []
    visa_model = next(
        (
            p.id
            for p in PROFILES.values()
            if p.family == FAMILY_VISA and any(i in usb for i in p.usb_ids)
        ),
        "generic_visa",
    )
    out: List[GpibAdapterConfig] = []
    boards: Set[int] = set()
    for backend in ("", "@py"):
        try:
            rm = rm_factory(backend)
        except Exception:  # this VISA library is not installed
            continue
        for res in _boards(rm):
            m = re.match(r"GPIB(\d+)::INTFC", res, re.I)
            if m:
                boards.add(int(m.group(1)))
    for board in sorted(boards - have_boards):
        cfg = GpibAdapterConfig(
            name=unique_name(f"GPIB{board}", taken + out), profile=visa_model, board=board
        )
        out.append(cfg)
    for device, vid, pid, desc in (serial_ports or list_serial_ports)():
        low = desc.lower()
        if device.lower() in have_ports:
            continue
        if "ar488" in low:
            model = "ar488"
        elif "prologix" in low or (vid, pid) == (0x0403, 0x6001):
            model = "prologix_usb"
        else:
            continue
        name = unique_name(f"{PROFILES[model].name.split(' (')[0]} {device}", taken + out)
        out.append(GpibAdapterConfig(name=name, profile=model, port=device))
    return out


# ----- talking to the bus ------------------------------------------------------------------------
def open_device(
    config: GpibAdapterConfig,
    pad: int,
    timeout_ms: Optional[int] = None,
    rm_factory: Callable[[str], Any] = _resource_manager,
    prologix_opener=None,
):
    """A connection (``ola.transport.Transport``) to the instrument at address ``pad``."""
    timeout = config.timeout_ms if timeout_ms is None else timeout_ms
    if config.family == FAMILY_PROLOGIX:
        return PrologixConnection.open(config.address(pad), timeout, prologix_opener)
    from ._visa import VisaConnection

    try:
        import pyvisa
    except ImportError as exc:
        raise GpibError(MESSAGES["diag_no_pyvisa"]) from exc
    address = config.address(pad)
    try:
        resource = rm_factory(config.backend).open_resource(address)
        resource.timeout = timeout
    except Exception as exc:  # VisaIOError, ValueError, OSError...
        raise TransportError(f"[TRN-001] connection failed: {address}: {exc}") from exc
    return VisaConnection(resource, address, timeout, pyvisa)


@dataclass
class BusDevice:
    """An address of the bus that answered."""

    address: int
    resource: str
    """The address to use in the project (``GPIB0::7::INSTR`` / ``PROLOGIX::COM5::7::INSTR``)."""
    idn: str = ""
    """The answer to the identification command ('' if none answered)."""
    command: str = ""
    """The identification command that answered."""
    listed: bool = False
    """True when the VISA library listed it as a listener on the bus."""


def _listed_addresses(config: GpibAdapterConfig, rm_factory) -> List[int]:
    """Addresses the VISA library reports as listeners (Keysight / NI VISA search the bus)."""
    try:
        resources = rm_factory(config.backend).list_resources(f"GPIB{config.board}::?*::INSTR")
    except Exception:  # nothing found, or the backend cannot search the bus
        return []
    found = []
    for r in resources:
        m = re.match(rf"GPIB{config.board}::(\d+)::INSTR$", r, re.I)
        if m:
            found.append(int(m.group(1)))
    return sorted(set(found))


def identify(conn, commands: Sequence[str], timeout_ms: int) -> Tuple[str, str]:
    """(answer, command) of the first identification command that gets a non-empty answer."""
    for command in commands:
        try:
            conn.flush_input()
            answer = conn.query(command, timeout_ms).strip()
        except TransportTimeout:
            continue
        except TransportError:
            continue
        if answer:
            return answer, command
    return "", ""


def scan_bus(
    config: GpibAdapterConfig,
    progress: Callable[[int, int, int], None] = lambda address, done, total: None,
    cancel: Optional[threading.Event] = None,
    rm_factory: Callable[[str], Any] = _resource_manager,
    prologix_opener=None,
) -> List[BusDevice]:
    """The instruments on the bus of ``config``: every address of the scan range is sent the
    identification commands in turn. With a VISA adapter the addresses the VISA library lists as
    listeners are tried first; if it lists some, only those are tried. ``progress(address, done,
    total)`` is called before each address; ``cancel`` stops the scan (the devices found so far
    are returned). ``GpibError`` [GPIB-001] if the adapter cannot be opened."""
    config.validate()
    commands = [c for c in config.idn_commands if c.strip()]
    candidates = list(range(config.scan_first, config.scan_last + 1))
    listed: List[int] = []
    keeper = None
    if config.family == FAMILY_VISA:
        listed = [a for a in _listed_addresses(config, rm_factory) if a in candidates]
        if listed:
            candidates = listed
    else:  # keep the adapter link open for the whole scan (it is set up only once)
        try:
            keeper = open_device(
                config, candidates[0], config.scan_timeout_ms, rm_factory, prologix_opener
            )
        except TransportError as exc:
            raise GpibError(f"[GPIB-001] adapter not found: {config.port}: {exc}") from exc
    devices: List[BusDevice] = []
    try:
        for done, pad in enumerate(candidates):
            if cancel is not None and cancel.is_set():
                break
            progress(pad, done, len(candidates))
            try:
                conn = open_device(config, pad, config.scan_timeout_ms, rm_factory, prologix_opener)
            except TransportError as exc:
                raise GpibError(f"[GPIB-001] adapter not found: {config.name}: {exc}") from exc
            try:
                idn, command = identify(conn, commands, config.scan_timeout_ms)
            finally:
                conn.close()
            if idn or pad in listed:
                devices.append(
                    BusDevice(pad, config.address(pad), idn, command, listed=pad in listed)
                )
        progress(-1, len(candidates), len(candidates))
    finally:
        if keeper is not None:
            keeper.close()
    return devices


def _with_interface(config, rm_factory, action: Callable[[Any], None]) -> None:
    resource = None
    try:
        resource = rm_factory(config.backend).open_resource(f"GPIB{config.board}::INTFC")
        action(resource)
    except GpibError:
        raise
    except Exception as exc:  # VisaIOError, missing board...
        raise GpibError(f"[GPIB-001] board GPIB{config.board} not usable: {exc}") from exc
    finally:
        if resource is not None:
            try:
                resource.close()
            except Exception:  # already closed
                pass


def interface_clear(config: GpibAdapterConfig, rm_factory=_resource_manager, prologix_opener=None):
    """Send IFC (Interface Clear) on the bus: every instrument stops talking and listening."""
    if config.family == FAMILY_PROLOGIX:
        try:
            conn = open_device(config, config.scan_first, None, rm_factory, prologix_opener)
        except TransportError as exc:
            raise GpibError(f"[GPIB-001] adapter not found: {config.port}: {exc}") from exc
        try:
            conn.interface_clear()
        finally:
            conn.close()
        return
    _with_interface(config, rm_factory, lambda r: r.send_ifc())


def remote_enable(config: GpibAdapterConfig, on: bool, rm_factory=_resource_manager) -> None:
    """Assert (``on``) or release the REN line: released, every instrument goes back to local.
    VISA adapters only (``GpibError`` [GPIB-007] for the others)."""
    if config.family != FAMILY_VISA:
        raise GpibError(f"[GPIB-007] not supported by {profile(config.profile).name}: REN control")

    def action(resource):
        import pyvisa

        ops = pyvisa.constants.RENLineOperation
        resource.control_ren(ops.assert_ if on else ops.deassert)

    _with_interface(config, rm_factory, action)


def supports_ren(config: GpibAdapterConfig) -> bool:
    """True if ``remote_enable`` works with this adapter."""
    return config.family == FAMILY_VISA


__all__ = [
    "AdapterProfile",
    "BusDevice",
    "DEFAULT_PROFILE",
    "DiagItem",
    "FAMILY_PROLOGIX",
    "FAMILY_VISA",
    "GpibAdapterConfig",
    "GpibError",
    "MESSAGES",
    "PROFILES",
    "check_environment",
    "check_unique_names",
    "configs_from_json",
    "configs_to_json",
    "detect_adapters",
    "identify",
    "interface_clear",
    "open_device",
    "profile",
    "remote_enable",
    "scan_bus",
    "supports_ren",
    "unique_name",
    "worst_level",
]
