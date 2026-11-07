# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The GPIB adapters window, the bus picker and the GPIB part of the address editor (no screen
needed, see conftest.py). The VISA library is the fake one of test_gpib_adapter.py."""

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("pyvisa")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.core import gpib_settings  # noqa: E402
from frontend.ui import GpibAdapterDialog as dialog_module  # noqa: E402
from frontend.ui.GpibAdapterDialog import GpibAdapterDialog  # noqa: E402
from frontend.ui.GpibDevicePickerDialog import GpibDevicePickerDialog  # noqa: E402
from frontend.ui.module_translator import CatalogTranslator  # noqa: E402
from ola.gpib_adapter import BusDevice, GpibAdapterConfig  # noqa: E402
from tests.test_gpib_adapter import FakeBus, FakeRM, answers  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(tmp_path):
    gpib_settings.forget_scans()
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def errors(monkeypatch):
    seen = []
    monkeypatch.setattr(dialog_module, "handle_error", lambda exc, msg: seen.append(msg))
    return seen


@pytest.fixture
def bus():
    return FakeBus({7: answers({"*IDN?": "KEYSIGHT,34461A,MY1,A.02"})})


def make(app, settings, bus):
    d = GpibAdapterDialog(
        settings=settings, rm_factory=lambda backend="": FakeRM(bus), asynchronous=False
    )
    d.scan_timeout_spin.setValue(20)
    return d


def test_starts_with_a_keysight_82357b(app, settings, bus):
    d = make(app, settings, bus)
    assert d.adapter_list.count() == 1
    cfg = d.form_config()
    assert cfg.profile == "keysight_82357b" and cfg.board == 0
    assert d.board_spin.isVisibleTo(d) and not d.port_combo.isVisibleTo(d)


def test_prologix_shows_the_port(app, settings, bus):
    d = make(app, settings, bus)
    d.model_combo.setCurrentIndex(d.model_combo.findData("prologix_usb"))
    assert d.port_combo.isVisibleTo(d) and not d.board_spin.isVisibleTo(d)
    assert not d.local_button.isEnabled()  # no REN control on a Prologix


def test_save_and_reload(app, settings, bus, errors):
    d = make(app, settings, bus)
    d.name_edit.setText("Bench")
    d.board_spin.setValue(1)
    d.idn_edit.setText("ID?, *IDN?")
    assert d.save()
    d.add_adapter()
    d.model_combo.setCurrentIndex(d.model_combo.findData("prologix_ethernet"))
    d.port_combo.setEditText("10.0.0.9")
    assert d.save()
    saved = gpib_settings.load_adapters(settings)
    assert [(c.name, c.profile, c.board, c.port) for c in saved] == [
        ("Bench", "keysight_82357b", 1, ""),
        ("GPIB0", "prologix_ethernet", 0, "10.0.0.9"),
    ]
    assert saved[0].idn_commands == ["ID?", "*IDN?"]
    again = make(app, settings, bus)
    assert again.adapter_list.count() == 2
    assert errors == []


def test_invalid_form_is_not_saved(app, settings, bus, errors):
    d = make(app, settings, bus)
    d.name_edit.setText("")
    assert not d.save()
    assert errors and "GPIB-006" in errors[0]
    assert gpib_settings.load_adapters(settings) == []


def test_duplicate_names_are_refused(app, settings, bus, errors):
    d = make(app, settings, bus)
    d.add_adapter()
    d.name_edit.setText("GPIB0")
    assert not d.save()
    assert errors


def test_scan_fills_the_table_and_is_remembered(app, settings, bus, errors):
    d = make(app, settings, bus)
    d.scan()
    assert errors == []
    assert d.bus_table.rowCount() == 1
    assert d.bus_table.item(0, 1).text() == "GPIB0::7::INSTR"
    assert d.bus_table.item(0, 2).text().startswith("KEYSIGHT")
    assert [x.address for x in gpib_settings.last_scan("GPIB0")] == [7]
    d.bus_table.selectRow(0)
    assert d.console_addr.value() == 7
    d.copy_address()
    assert QApplication.clipboard().text() == "GPIB0::7::INSTR"


def test_scan_without_the_board(app, settings, bus, errors):
    d = make(app, settings, bus)
    d.board_spin.setValue(5)
    d.scan()
    assert errors and "GPIB-001" in errors[0]
    assert d.scan_button.isEnabled()


def test_check_shows_the_results(app, settings, bus, errors):
    d = make(app, settings, bus)
    d.check()
    texts = [d.check_table.item(r, 1).text() for r in range(d.check_table.rowCount())]
    assert any("GPIB0" in t for t in texts)
    assert errors == []


def test_bus_operations(app, settings, bus, errors):
    d = make(app, settings, bus)
    d.interface_clear()
    d.remote_enable(False)
    assert bus.ifc == 1 and len(bus.ren) == 1
    assert errors == []


def test_console(app, settings, bus):
    d = make(app, settings, bus)
    d.console_addr.setValue(7)
    d.command_edit.setText("*IDN?")
    d.console_query()
    log = d.console_log.toPlainText()
    assert "→ *IDN?" in log and "← KEYSIGHT,34461A" in log
    d.console_addr.setValue(9)  # nothing there
    d.console_query()
    assert "✖" in d.console_log.toPlainText()
    d.close()


def test_detect_adds_the_boards(app, settings, bus, monkeypatch):
    from ola import gpib_adapter

    monkeypatch.setattr(gpib_adapter, "list_serial_ports", lambda: [])
    bus.board = 2
    d = make(app, settings, bus)
    d.detect()
    assert [c.board for c in d.adapters] == [0, 2]


def test_closing_saves_a_valid_form(app, settings, bus):
    d = make(app, settings, bus)
    d.name_edit.setText("Kept")
    d.close()
    assert [c.name for c in gpib_settings.load_adapters(settings)] == ["Kept"]


# ----- the bus picker ------------------------------------------------------------------------
def test_picker_scans_and_returns_the_device(app, settings, bus):
    cfg = GpibAdapterConfig(scan_timeout_ms=20)
    tr = CatalogTranslator("gpib", lang="it")
    p = GpibDevicePickerDialog(
        cfg, tr, rm_factory=lambda backend="": FakeRM(bus), asynchronous=False
    )
    assert p.table.rowCount() == 0 and not p.use_button.isEnabled()
    p.scan()
    assert p.table.rowCount() == 1
    p.accept()
    assert p.chosen.address == 7


def test_picker_shows_the_last_scan(app, settings):
    gpib_settings.remember_scan("GPIB0", [BusDevice(4, "GPIB0::4::INSTR", "X")])
    p = GpibDevicePickerDialog(GpibAdapterConfig(), CatalogTranslator("gpib", lang="en"))
    assert p.table.item(0, 1).text() == "GPIB0::4::INSTR"


# ----- the address editor ----------------------------------------------------------------------
class NoLibrary:
    def find_instrument(self, **kw):
        return None


@pytest.fixture
def app_settings(tmp_path, monkeypatch):
    """The application settings (QSettings('LabAutomation', 'App')) in a temporary folder."""
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(tmp_path / "app"))
    s = QSettings("LabAutomation", "App")
    s.clear()
    gpib_settings.save_adapters(
        [
            GpibAdapterConfig(name="Main", board=0),
            GpibAdapterConfig(name="Second", board=1),
            GpibAdapterConfig(name="Prologix", profile="prologix_usb", port="COM5"),
        ],
        s,
    )
    yield s
    s.clear()


def editor(address):
    from frontend.ui.AddressEditorDialog import AddressEditorDialog

    return AddressEditorDialog({"address": address, "instrument_type": "x"}, NoLibrary())


def test_address_editor_uses_the_configured_adapters(app, app_settings):
    e = editor("")
    e.conn_combo.setCurrentText("GPIB")
    assert e.adapter_combo.count() == 3
    e.adapter_combo.setCurrentIndex(1)
    e.fields["gpib_addr"].setText("7")
    assert e.get_address() == "GPIB1::7::INSTR"
    e.adapter_combo.setCurrentIndex(2)
    assert e.get_address() == "PROLOGIX::COM5::7::INSTR"


@pytest.mark.parametrize(
    "address, adapter, pad",
    [
        ("GPIB1::12::INSTR", 1, "12"),
        ("PROLOGIX::COM5::3::INSTR", 2, "3"),
        ("GPIB::4::INSTR", 0, "4"),
    ],
)
def test_address_editor_reads_an_existing_address(app, app_settings, address, adapter, pad):
    e = editor(address)
    assert e.conn_combo.currentText() == "GPIB"
    assert e.adapter_combo.currentIndex() == adapter
    assert e.fields["gpib_addr"].text() == pad
    assert e.get_address() == address.replace("GPIB::", "GPIB0::")


def test_address_editor_without_configured_adapters(app, tmp_path):
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(tmp_path / "empty"))
    QSettings("LabAutomation", "App").clear()
    e = editor("")
    e.conn_combo.setCurrentText("GPIB")
    e.fields["gpib_addr"].setText("9")
    assert e.get_address() == "GPIB0::9::INSTR"


# ----- Linux set-up tab --------------------------------------------------------------------------
def linux_dialog(app, settings, bus, platform="linux", runner=None, confirm=lambda text: True):
    from tests.test_gpib_linux import FakeProbe

    d = GpibAdapterDialog(
        settings=settings,
        rm_factory=lambda backend="": FakeRM(bus),
        asynchronous=False,
        platform=platform,
        probe=FakeProbe(),
        runner=runner or (lambda argv, out: 0),
        confirm=confirm,
    )
    return d


def test_linux_tab_only_on_linux_for_linux_gpib_adapters(app, settings, bus):
    d = linux_dialog(app, settings, bus)
    assert d.tabs.isTabVisible(d.linux_tab_index)
    d.model_combo.setCurrentIndex(d.model_combo.findData("prologix_usb"))
    assert not d.tabs.isTabVisible(d.linux_tab_index)
    w = linux_dialog(app, settings, bus, platform="win32")
    assert not w.tabs.isTabVisible(w.linux_tab_index)


def test_linux_check_and_script(app, settings, bus):
    d = linux_dialog(app, settings, bus)
    assert not d.linux_install_button.isEnabled()
    d.linux_check()
    rows = [d.linux_table.item(r, 1).text() for r in range(d.linux_table.rowCount())]
    assert any("measat_releaseX1.8.hex" in t for t in rows)
    assert d.linux_install_button.isEnabled() and d.linux_python_button.isEnabled()
    d.show_linux_script()
    assert "agilent_82357a" in d.linux_log.toPlainText()


def test_linux_install_runs_pkexec(app, settings, bus, errors, monkeypatch):
    from ola import gpib_linux

    monkeypatch.setattr(gpib_linux.shutil, "which", lambda c: "/usr/bin/pkexec")
    calls, asked = [], []

    def runner(argv, out):
        calls.append(list(argv))
        out("==> Packages")
        return 0

    d = linux_dialog(
        app, settings, bus, runner=runner, confirm=lambda text: asked.append(text) or True
    )
    d.linux_check()
    d.linux_install()
    assert calls[0][0] == "/usr/bin/pkexec"
    assert "/etc/gpib.conf" in asked[0]
    assert "==> Packages" in d.linux_log.toPlainText()
    assert errors == []


def test_linux_install_cancelled(app, settings, bus):
    calls = []
    d = linux_dialog(
        app,
        settings,
        bus,
        runner=lambda argv, out: calls.append(argv) or 0,
        confirm=lambda text: False,
    )
    d.linux_check()
    d.linux_install()
    assert calls == []


def test_linux_install_failure(app, settings, bus, errors, monkeypatch):
    from ola import gpib_linux

    monkeypatch.setattr(gpib_linux.shutil, "which", lambda c: "/usr/bin/pkexec")
    d = linux_dialog(app, settings, bus, runner=lambda argv, out: 2)
    d.linux_check()
    d.linux_install()
    assert errors and "GPIB-008" in errors[0]


def test_linux_python_bindings(app, settings, bus):
    calls = []
    d = linux_dialog(app, settings, bus, runner=lambda argv, out: calls.append(argv) or 0)
    d.linux_check()
    d.linux_python()
    assert calls[0][1:] == ["-m", "pip", "install", "gpib-ctypes"]
