# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""GPIB adapters engine (``ola.gpib_adapter``): configuration, driver check, bus scan and bus
operations, against a fake VISA resource manager and a fake Prologix adapter."""

import json
import os
import re
import threading

import pytest

pytest.importorskip("pyvisa")

from ola import gpib_adapter as ga  # noqa: E402
from ola.errors import TransportTimeout  # noqa: E402
from ola.gpib_adapter import GpibAdapterConfig, GpibError  # noqa: E402
from tests.fake_instrument import FakePrologix  # noqa: E402

LANG_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "lang", "modules", "gpib")


# ----- a fake VISA library with a GPIB bus -------------------------------------------------------
class FakeBus:
    """Board ``GPIB<board>`` with instruments: address -> reply(command) -> bytes or None."""

    def __init__(self, devices, board=0, listed=(), library="Visa Library at ktvisa32.dll"):
        self.devices, self.board, self.listed = dict(devices), board, list(listed)
        self.library = library
        self.ifc = 0
        self.ren = []
        self.opened = []


class FakeResource:
    def __init__(self, bus, name):
        self.bus, self.name = bus, name
        self.timeout = 1000
        self.read_termination = None
        self.write_termination = None
        m = re.match(r"GPIB\d+::(\d+)::INSTR", name)
        self.addr = int(m.group(1)) if m else None
        self._out = b""

    def write_raw(self, data):
        reply = self.bus.devices.get(self.addr)
        answer = reply(bytes(data).rstrip(b"\n")) if reply else None
        if answer:
            self._out += answer

    def read_raw(self):
        if not self._out:
            raise TransportTimeout("[TRN-003] timeout waiting for the instrument")
        term = (self.read_termination or "\n").encode()
        i = self._out.find(term)
        end = len(self._out) if i < 0 else i + len(term)
        data, self._out = self._out[:end], self._out[end:]
        return data

    def read_bytes(self, n, break_on_termchar=False):
        if len(self._out) < n:
            raise TransportTimeout("[TRN-003] timeout waiting for the instrument")
        data, self._out = self._out[:n], self._out[n:]
        return data

    def send_ifc(self):
        self.bus.ifc += 1

    def control_ren(self, mode):
        self.bus.ren.append(mode)

    def close(self):
        pass


class FakeRM:
    def __init__(self, bus):
        self.bus = bus
        self.visalib = bus.library

    def list_resources(self, query="?*::INSTR"):
        b = self.bus.board
        if query == "GPIB?*::INTFC":
            return (f"GPIB{b}::INTFC",)
        if query == f"GPIB{b}::?*::INSTR":
            return tuple(f"GPIB{b}::{a}::INSTR" for a in self.bus.listed)
        return ()

    def open_resource(self, name):
        if not name.upper().startswith(f"GPIB{self.bus.board}::"):
            raise ValueError(f"VI_ERROR_RSRC_NFOUND: {name}")
        self.bus.opened.append(name)
        return FakeResource(self.bus, name)


def answers(table):
    """reply() of an instrument that answers ``table[command]``."""

    def reply(cmd):
        text = table.get(cmd.decode())
        return (text + "\n").encode() if text else None

    return reply


@pytest.fixture
def bus():
    return FakeBus(
        {
            5: answers({"*IDN?": "KEYSIGHT,34461A,MY1,A.02"}),
            22: answers({"ID?": "HP3478A"}),  # an old instrument: no *IDN?
        }
    )


def rm_of(bus):
    return lambda backend="": FakeRM(bus)


def fast(**kw):
    values = dict(scan_timeout_ms=50, timeout_ms=200)
    values.update(kw)
    return GpibAdapterConfig(**values)


# ----- configuration -------------------------------------------------------------------------
def test_default_config_is_a_keysight_82357b_on_gpib0():
    cfg = GpibAdapterConfig().validate()
    assert cfg.profile == "keysight_82357b"
    assert ga.profile(cfg.profile).name.startswith("Keysight 82357B")
    assert cfg.family == ga.FAMILY_VISA
    assert cfg.address(7) == "GPIB0::7::INSTR"
    assert GpibAdapterConfig(board=2).address(7, 3) == "GPIB2::7::3::INSTR"


def test_every_family_has_profiles():
    families = {p.family for p in ga.PROFILES.values()}
    assert families == {ga.FAMILY_VISA, ga.FAMILY_PROLOGIX}
    assert {"keysight_82357b", "ni_gpib_usb_hs", "prologix_usb", "ar488"} <= set(ga.PROFILES)
    for p in ga.PROFILES.values():
        assert p.hint_windows in ga.MESSAGES and p.hint_linux in ga.MESSAGES


def test_prologix_address():
    cfg = GpibAdapterConfig(name="P", profile="prologix_usb", port="COM5")
    assert cfg.address(9) == "PROLOGIX::COM5::9::INSTR"


@pytest.mark.parametrize(
    "change",
    [
        {"name": " "},
        {"profile": "nope"},
        {"board": 40},
        {"profile": "prologix_usb", "port": ""},
        {"backend": "@xx"},
        {"scan_first": 20, "scan_last": 3},
        {"scan_last": 31},
        {"scan_timeout_ms": 1},
        {"idn_commands": [" "]},
    ],
)
def test_invalid_config(change):
    with pytest.raises(GpibError) as exc:
        GpibAdapterConfig(**change).validate()
    assert exc.value.code == "GPIB-006"


def test_address_out_of_range():
    with pytest.raises(GpibError):
        GpibAdapterConfig().address(31)


def test_json_round_trip():
    configs = [
        GpibAdapterConfig(name="Bench", board=1, idn_commands=["ID?"]),
        GpibAdapterConfig(name="Prologix", profile="prologix_ethernet", port="10.0.0.9"),
    ]
    again = ga.configs_from_json(ga.configs_to_json(configs))
    assert again == configs
    assert ga.configs_from_json("") == []
    # a single object, unknown keys ignored, numbers given as text
    one = ga.configs_from_json(json.dumps({"name": "X", "board": "3", "colour": "red"}))
    assert one[0].board == 3 and one[0].name == "X"


def test_json_errors():
    for text in ("{", "[1]", "5", json.dumps([{"name": "A"}, {"name": "a"}])):
        with pytest.raises(GpibError):
            ga.configs_from_json(text)


def test_unique_name():
    configs = [GpibAdapterConfig(name="GPIB0"), GpibAdapterConfig(name="GPIB0 (2)")]
    assert ga.unique_name("GPIB0", configs) == "GPIB0 (3)"
    assert ga.unique_name("GPIB1", configs) == "GPIB1"


# ----- scan ----------------------------------------------------------------------------------
def test_scan_finds_instruments_and_uses_the_fallback_command(bus):
    calls = []
    devices = ga.scan_bus(
        fast(scan_first=1, scan_last=30),
        progress=lambda a, done, total: calls.append((a, done, total)),
        rm_factory=rm_of(bus),
    )
    assert [(d.address, d.idn, d.command) for d in devices] == [
        (5, "KEYSIGHT,34461A,MY1,A.02", "*IDN?"),
        (22, "HP3478A", "ID?"),
    ]
    assert devices[0].resource == "GPIB0::5::INSTR"
    assert calls[0] == (1, 0, 30) and calls[-1] == (-1, 30, 30)


def test_scan_range(bus):
    devices = ga.scan_bus(fast(scan_first=10, scan_last=30), rm_factory=rm_of(bus))
    assert [d.address for d in devices] == [22]


def test_scan_tries_only_the_listed_addresses(bus):
    bus.listed = [5, 9]  # 9 is a listener that does not answer to identification
    devices = ga.scan_bus(fast(), rm_factory=rm_of(bus))
    assert [(d.address, d.idn, d.listed) for d in devices] == [
        (5, "KEYSIGHT,34461A,MY1,A.02", True),
        (9, "", True),
    ]
    assert bus.opened == ["GPIB0::5::INSTR", "GPIB0::9::INSTR"]


def test_scan_can_be_cancelled(bus):
    cancel = threading.Event()

    def progress(address, done, total):
        if address == 3:
            cancel.set()

    devices = ga.scan_bus(fast(), progress=progress, cancel=cancel, rm_factory=rm_of(bus))
    assert devices == []
    assert bus.opened[-1] == "GPIB0::3::INSTR"


def test_scan_without_the_board(bus):
    with pytest.raises(GpibError) as exc:
        ga.scan_bus(fast(board=3), rm_factory=rm_of(bus))
    assert exc.value.code == "GPIB-001"


def test_scan_prologix():
    fake = FakePrologix({4: answers({"*IDN?": "TEKTRONIX,TDS 210,0,CF:91.1CT"})})
    try:
        cfg = fast(name="P", profile="prologix_ethernet", port=fake.port, scan_last=6)
        devices = ga.scan_bus(cfg)
        assert [(d.address, d.resource) for d in devices] == [
            (4, f"PROLOGIX::{fake.port}::4::INSTR")
        ]
        assert fake.commands.count("++ver") == 1  # the link is set up once for the whole scan
    finally:
        fake.close()


def test_scan_prologix_without_adapter():
    cfg = fast(name="P", profile="prologix_ethernet", port="127.0.0.1:9")
    with pytest.raises(GpibError) as exc:
        ga.scan_bus(cfg)
    assert exc.value.code == "GPIB-001"


def test_open_device_and_query(bus):
    c = ga.open_device(fast(), 5, rm_factory=rm_of(bus))
    assert c.query("*IDN?").startswith("KEYSIGHT")
    c.close()


# ----- bus operations ---------------------------------------------------------------------------
def test_interface_clear_and_ren(bus):
    ga.interface_clear(fast(), rm_factory=rm_of(bus))
    assert bus.ifc == 1
    ga.remote_enable(fast(), False, rm_factory=rm_of(bus))
    import pyvisa

    assert bus.ren == [pyvisa.constants.RENLineOperation.deassert]
    with pytest.raises(GpibError) as exc:
        ga.interface_clear(fast(board=4), rm_factory=rm_of(bus))
    assert exc.value.code == "GPIB-001"


def test_ren_not_on_prologix():
    cfg = GpibAdapterConfig(name="P", profile="ar488", port="/dev/ttyACM0")
    assert not ga.supports_ren(cfg)
    with pytest.raises(GpibError) as exc:
        ga.remote_enable(cfg, True)
    assert exc.value.code == "GPIB-007"


def test_interface_clear_prologix():
    fake = FakePrologix({})
    try:
        ga.interface_clear(GpibAdapterConfig(name="P", profile="prologix_ethernet", port=fake.port))
        deadline = __import__("time").monotonic() + 2
        while "++ifc" not in fake.commands and __import__("time").monotonic() < deadline:
            pass
        assert "++ifc" in fake.commands
    finally:
        fake.close()


# ----- driver check ------------------------------------------------------------------------------
def keys(items):
    return [i.key for i in items]


def test_check_ready_keysight_on_windows(bus):
    items = ga.check_environment(
        GpibAdapterConfig(),
        rm_factory=rm_of(bus),
        usb_devices=lambda: [(0x0957, 0x0718)],
        platform="win32",
    )
    assert "diag_usb_found" in keys(items)
    assert "diag_board_found" in keys(items)
    assert any(
        i.key == "diag_backend_vendor" and i.values["vendor"] == "Keysight VISA" for i in items
    )
    assert items[-1].key == "hint_windows_keysight"
    assert ga.worst_level(items) == "ok"
    for item in items:
        assert item.text  # every message formats with its values


def test_check_firmware_not_loaded_on_linux(bus):
    bus.library = "Visa Library at py"
    items = ga.check_environment(
        GpibAdapterConfig(),
        rm_factory=rm_of(bus),
        usb_devices=lambda: [(0x0957, 0x0518)],
        platform="linux",
        path_exists=lambda p: False,
        find_spec=lambda name: None,
    )
    k = keys(items)
    assert "diag_no_firmware" in k
    assert "diag_py_no_gpib" in k and "diag_no_dev_gpib" in k
    assert k.count("diag_backend_ok") == 1  # the default already is pyvisa-py
    assert items[-1].key == "hint_linux_keysight"
    assert ga.worst_level(items) == "error"
    assert "GPIB-003" in next(i.text for i in items if i.key == "diag_no_firmware")


def test_check_board_missing(bus):
    items = ga.check_environment(
        GpibAdapterConfig(board=1),
        rm_factory=rm_of(bus),
        usb_devices=lambda: None,
        platform="win32",
    )
    k = keys(items)
    assert "diag_usb_unknown" in k and "diag_board_missing" in k and "diag_board_not_found" in k


def test_check_without_visa_library(bus):
    def rm_factory(backend=""):
        if backend == "":
            raise OSError("Could not locate a VISA implementation")
        return FakeRM(bus)

    items = ga.check_environment(
        GpibAdapterConfig(), rm_factory=rm_factory, usb_devices=lambda: [], platform="win32"
    )
    k = keys(items)
    assert "diag_backend_failed" in k and "diag_usb_missing" in k and "diag_board_found" in k


def test_check_prologix():
    fake = FakePrologix({})
    try:
        cfg = GpibAdapterConfig(name="P", profile="prologix_ethernet", port=fake.port)
        items = ga.check_environment(cfg, usb_devices=lambda: [], platform="linux")
        ok = next(i for i in items if i.key == "diag_prologix_ok")
        assert "Prologix GPIB-ETHERNET" in ok.text
        assert items[-1].key == "hint_prologix_ethernet"
    finally:
        fake.close()
    items = ga.check_environment(
        GpibAdapterConfig(name="P", profile="prologix_ethernet", port="127.0.0.1:9"),
        usb_devices=lambda: [],
    )
    assert "diag_prologix_failed" in keys(items)


def test_check_prologix_missing_serial_port():
    cfg = GpibAdapterConfig(name="P", profile="prologix_usb", port="COM9")
    items = ga.check_environment(
        cfg,
        usb_devices=lambda: [],
        serial_ports=lambda: [("COM3", None, None, "")],
        prologix_opener=None,
    )
    assert "diag_port_missing" in keys(items)
    assert "diag_prologix_failed" in keys(items)


# ----- detection ---------------------------------------------------------------------------------
def test_detect_adapters(bus):
    found = ga.detect_adapters(
        existing=[],
        rm_factory=rm_of(bus),
        usb_devices=lambda: [(0x0957, 0x0718)],
        serial_ports=lambda: [
            ("/dev/ttyUSB0", 0x0403, 0x6001, "FT232R USB UART"),
            ("/dev/ttyACM0", 0x2341, 0x0043, "AR488 GPIB"),
            ("/dev/ttyS0", None, None, "n/a"),
        ],
    )
    assert [(c.profile, c.board, c.port) for c in found] == [
        ("keysight_82357b", 0, ""),
        ("prologix_usb", 0, "/dev/ttyUSB0"),
        ("ar488", 0, "/dev/ttyACM0"),
    ]
    assert len({c.name for c in found}) == 3
    # already configured: nothing new
    assert (
        ga.detect_adapters(
            existing=found, rm_factory=rm_of(bus), usb_devices=lambda: [], serial_ports=lambda: []
        )
        == []
    )


# ----- translations ------------------------------------------------------------------------------
@pytest.mark.parametrize("lang", ["it", "en", "fr", "es", "de"])
def test_every_message_is_translated(lang):
    with open(os.path.join(LANG_DIR, f"{lang}.json"), encoding="utf-8") as f:
        catalog = json.load(f)
    missing = [k for k in ga.MESSAGES if k not in catalog]
    assert missing == []
    placeholder = re.compile(r"\{(\w+)\}")
    for key, text in ga.MESSAGES.items():
        assert set(placeholder.findall(catalog[key])) == set(placeholder.findall(text)), key
