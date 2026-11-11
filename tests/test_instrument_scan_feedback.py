# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The window "Instruments found (VISA)" of the instrument editor never stays silent.

Pressing *Set on the selected instrument* used to do nothing, without a word, when no
instrument was selected in the list of the editor, when the file had none, or when the instrument
was a manual one; and when it worked the window stayed open and nothing showed that the address
had been set. Now the window says what the button will do (or why it cannot), and closes after
setting the address.
"""

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from frontend.ui import InstrumentConfigDialog as module  # noqa: E402
from frontend.ui.InstrumentConfigDialog import InstrumentConfigDialog  # noqa: E402
from tests.conftest import LIBRARY_PATH  # noqa: E402

pytestmark = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")

FOUND = "TCPIP0::192.168.1.77::inst0::INSTR"
PSU = {
    "instrument_type": "power_supply",
    "instance_name": "PSU",
    "model_id": "PSU_Keysight_E36312A",
    "num_channels": 3,
    "visa_address": "TCPIP0::1.1.1.1::inst0::INSTR",
    "channels": [],
}
LOAD = {
    "instrument_type": "electronic_load",
    "instance_name": "LOAD",
    "is_manual": True,
    "num_channels": 1,
    "channels": [{"enabled": True, "name": "CH1", "max_current": 10.0, "max_voltage": 60.0}],
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    """Settings in a temporary folder and no blocking message box."""
    QSettings.setPath(
        QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "settings")
    )
    QSettings("LabAutomation", "App").clear()
    for kind in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(
            QMessageBox, kind, staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        )


class FakeResource:
    def query(self, command):
        return "ACME,SCOPE,1,1"

    def close(self):
        pass


def fake_visa(addresses):
    class Manager:
        def __init__(self, *args):
            pass

        def list_resources(self):
            return tuple(addresses)

        def open_resource(self, address):
            return FakeResource()

    return SimpleNamespace(ResourceManager=Manager)


def open_scan(monkeypatch, tmp_path, entries, row, found=(FOUND,), act=None):
    """Open the editor on a file with ``entries``, select ``row`` in its list (None: nothing),
    open the scan window and run ``act(window)`` in it. Returns (editor, file path, window)."""
    library = LoadInstruments()
    assert library.load_instruments(LIBRARY_PATH)
    monkeypatch.setattr(module, "pyvisa", fake_visa(found))
    monkeypatch.setattr(module, "PYVISA_AVAILABLE", True)
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": entries}), encoding="utf-8")
    editor = InstrumentConfigDialog(str(path), library)
    editor.list_widget.setCurrentRow(-1 if row is None else row)
    seen = {}

    def fake_exec(self):
        seen["window"] = self
        if act is not None:
            act(self)
        return self.result() or QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    editor.open_network_scan_dialog()
    return editor, path, seen["window"]


def parts(window):
    buttons = {b.text(): b for b in window.findChildren(QPushButton)}
    status = [w.text() for w in window.findChildren(QLabel) if w.text()]
    return buttons["Set on the selected instrument"], status, window.findChild(QTableWidget)


def saved(path):
    return json.loads(path.read_text(encoding="utf-8"))["instruments"]


def test_setting_the_address_closes_the_window_and_the_editor_shows_it(
    app, tmp_path, monkeypatch
):
    def act(window):
        button, status, table = parts(window)
        assert not button.isEnabled()  # no row selected yet
        assert "PSU" in status[-1] and "Select an instrument" in status[-1]
        table.setCurrentCell(0, 0)
        button, status, _ = parts(window)
        assert button.isEnabled() and FOUND in status[-1] and "PSU" in status[-1]
        button.click()

    editor, path, window = open_scan(monkeypatch, tmp_path, [PSU], 0, act=act)
    assert window.result() == QDialog.DialogCode.Accepted  # it closed
    assert saved(path)[0]["visa_address"] == FOUND
    assert editor.addr_label.text() == FOUND  # what the editor behind now shows


def test_a_double_click_on_the_row_sets_the_address_too(app, tmp_path, monkeypatch):
    def act(window):
        table = window.findChild(QTableWidget)
        table.setCurrentCell(0, 0)
        table.cellDoubleClicked.emit(0, 0)

    _, path, window = open_scan(monkeypatch, tmp_path, [PSU], 0, act=act)
    assert window.result() == QDialog.DialogCode.Accepted
    assert saved(path)[0]["visa_address"] == FOUND


def test_with_no_instrument_selected_the_window_says_so_and_sets_nothing(
    app, tmp_path, monkeypatch
):
    def act(window):
        button, status, table = parts(window)
        table.setCurrentCell(0, 0)
        button, status, _ = parts(window)
        assert not button.isEnabled()
        assert "No instrument is selected" in status[-1]
        button.click()

    _, path, window = open_scan(monkeypatch, tmp_path, [PSU], None, act=act)
    assert window.result() != QDialog.DialogCode.Accepted
    assert saved(path)[0]["visa_address"] == PSU["visa_address"]


def test_with_an_empty_file_the_window_says_there_is_no_instrument(app, tmp_path, monkeypatch):
    def act(window):
        window.findChild(QTableWidget).setCurrentCell(0, 0)
        button, status, _ = parts(window)
        assert not button.isEnabled() and "No instrument is selected" in status[-1]

    _, path, _ = open_scan(monkeypatch, tmp_path, [], None, act=act)
    assert saved(path) == []


def test_a_manual_instrument_has_no_address_and_the_window_says_so(app, tmp_path, monkeypatch):
    def act(window):
        window.findChild(QTableWidget).setCurrentCell(0, 0)
        button, status, _ = parts(window)
        assert not button.isEnabled()
        assert "LOAD" in status[-1] and "manual instrument" in status[-1]

    _, path, _ = open_scan(monkeypatch, tmp_path, [LOAD], 0, act=act)
    assert "visa_address" not in saved(path)[0]


def test_when_nothing_is_found_the_window_says_so(app, tmp_path, monkeypatch):
    def act(window):
        button, status, table = parts(window)
        assert table.rowCount() == 0 and not button.isEnabled()
        assert "No instrument found" in status[-1]

    open_scan(monkeypatch, tmp_path, [PSU], 0, found=(), act=act)


def test_the_message_follows_the_usb_filter(app, tmp_path, monkeypatch):
    """Filtering the table drops the selected row: the button must follow, not stay enabled."""
    found = (FOUND, "USB0::0x2A8D::0x0001::SN1::INSTR")

    def act(window):
        table = window.findChild(QTableWidget)
        table.setCurrentCell(0, 0)
        button, _, _ = parts(window)
        assert button.isEnabled()
        from PyQt6.QtWidgets import QCheckBox

        window.findChild(QCheckBox).setChecked(True)  # USB only: row 0 is now the USB one
        button, status, table = parts(window)
        assert table.rowCount() == 1
        if table.currentRow() < 0:
            assert not button.isEnabled()
        else:
            assert button.isEnabled() and "USB0" in status[-1]

    open_scan(monkeypatch, tmp_path, [PSU], 0, found=found, act=act)
