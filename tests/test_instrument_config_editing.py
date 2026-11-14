# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The instrument file editor (``InstrumentConfigDialog``): the parts the other test file does
not reach, on the real library and without a screen.

Channel tables of every instrument kind, the oscilloscope and datalogger-slot buttons, deleting
an instrument, the list menu, the "Add instrument" dialog, the address editor, the VISA scan, and
what happens when the library or the file cannot be read. Pop-ups and nested dialogs are replaced
by recorders: nothing blocks, and every change is checked in the saved file.
"""

import json
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
)

from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from frontend.ui import InstrumentConfigDialog as module  # noqa: E402
from frontend.ui.InstrumentConfigDialog import InstrumentConfigDialog  # noqa: E402
from tests.conftest import LIBRARY_PATH  # noqa: E402

pytestmark = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")

PSU = {
    "instrument_type": "power_supply",
    "instance_name": "PSU",
    "series": "Keysight_E36300_Series",
    "model": "Keysight E36312A",
    "model_id": "PSU_Keysight_E36312A",
    "num_channels": 3,
    "visa_address": "TCPIP0::192.168.1.201::inst0::INSTR",
    "channels": [],
}
LOAD = {
    "instrument_type": "electronic_load",
    "instance_name": "LOAD",
    "is_manual": True,
    "num_channels": 1,
    "channels": [{"enabled": True, "name": "CH1", "max_current": 10.0, "max_voltage": 60.0}],
}
DMM = {
    "instrument_type": "multimeter",
    "instance_name": "DMM",
    "model_id": "MTR_Agilent_34401A",
    "num_channels": 2,
    "visa_address": "GPIB0::22::INSTR",
}
LOGGER_NO_SLOTS = {
    "instrument_type": "datalogger",
    "instance_name": "LOG",
    "series": "No_Such_Series",
    "model_id": "NO_SUCH_MODEL",
    "num_channels": 3,
    "visa_address": "TCPIP0::192.168.1.210::inst0::INSTR",
}
LOGGER_SLOTS = {
    "instrument_type": "datalogger",
    "instance_name": "DAQ",
    "series": "Keysight_3497X_Series",
    "model_id": "DL_Agilent_34970A",
    "visa_address": "TCPIP0::192.168.1.211::inst0::INSTR",
    "slots": [
        {
            "slot_number": 1,
            "module_id": "34901A",
            "channels": [{"enabled": True, "name": "VOUT"}, {"enabled": False, "name": "VIN"}],
        },
        {"slot_number": 2, "module_id": None, "channels": []},
    ],
}
SCOPE = {
    "instrument_type": "oscilloscope",
    "instance_name": "OSC",
    "series": "Siglent_SDS_HD_Series",
    "model_id": "OSC_Siglent_SDS824X_HD",
    "visa_address": "TCPIP0::192.168.1.125::inst0::INSTR",
    "channels": [
        {"enabled": True, "channel_id": "1", "name": "VOUT"},
        {"enabled": True, "channel_id": "2", "name": "IL"},
        {"enabled": False, "channel_id": "3", "name": "x"},
        {"enabled": False, "channel_id": "4", "name": "y"},
    ],
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Settings in a temporary folder (the Add dialog reads one), and every pop-up recorded:
    ``shown`` lists ``(kind, title)``; nothing blocks."""
    QSettings.setPath(
        QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp_path / "settings")
    )
    QSettings("LabAutomation", "App").clear()
    shown = []
    for kind in ("critical", "warning", "information", "question"):

        def record(parent, title, *args, _kind=kind, **kwargs):
            shown.append((_kind, title))
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, kind, staticmethod(record))
    return shown


@pytest.fixture
def library():
    loader = LoadInstruments()
    assert loader.load_instruments(LIBRARY_PATH)
    return loader


def make(tmp_path, library, entries):
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": entries}), encoding="utf-8")
    return InstrumentConfigDialog(str(path), library), path


def saved(path):
    return json.loads(path.read_text(encoding="utf-8"))["instruments"]


def select(dialog, name):
    row = [e.get("instance_name") for e in dialog.instruments].index(name)
    dialog.list_widget.setCurrentRow(row)


def texts(widget, kind=QLabel):
    return [w.text() for w in widget.findChildren(kind)]


def force_exec(monkeypatch, action, result=QDialog.DialogCode.Accepted):
    """``QDialog.exec`` runs ``action(dialog)`` instead of showing the dialog."""

    def fake(self):
        action(self)
        return result

    monkeypatch.setattr(QDialog, "exec", fake)


# ---------------------------------------------------------------- channel tables
def test_the_power_table_fills_the_channels_the_model_has(app, tmp_path, library):
    """A supply entered without channels gets the three outputs of its model, with the limits of
    the library, and every edit of the table is written to the file."""
    dialog, path = make(tmp_path, library, [PSU])
    select(dialog, "PSU")
    table = dialog.channel_table
    assert table.rowCount() == 3 and table.columnCount() == 5
    channels = dialog.instruments[0]["channels"]
    assert len(channels) == 3 and all(not c["enabled"] for c in channels)
    assert channels[0]["max_current"] > 0 and channels[0]["max_voltage"] > 0
    table.cellWidget(1, 0).setChecked(True)
    table.cellWidget(1, 1).setText("VIN")
    table.cellWidget(1, 2).setText("2,5")  # a comma is accepted
    table.cellWidget(1, 3).setText("12")
    table.cellWidget(1, 4).setText("30")
    row = saved(path)[0]["channels"][1]
    assert row["enabled"] is True and row["name"] == "VIN"
    assert row["max_current"] == 2.5 and row["max_voltage"] == 12.0 and row["max_power"] == 30.0
    table.cellWidget(1, 2).setText("lots")  # not a number: "limit not set"
    assert saved(path)[0]["channels"][1]["max_current"] == 0.0
    table.cellWidget(1, 4).setText("-5")  # a power limit must be positive
    assert "max_power" not in saved(path)[0]["channels"][1]
    table.cellWidget(1, 0).setChecked(False)
    assert saved(path)[0]["channels"][1]["enabled"] is False


def test_extra_channels_of_the_file_are_cut_to_the_number_of_the_instrument(app, tmp_path, library):
    entry = dict(LOAD, channels=[{"name": f"CH{i}", "enabled": True} for i in range(4)])
    dialog, _ = make(tmp_path, library, [entry])
    select(dialog, "LOAD")
    assert dialog.channel_table.rowCount() == 1 and len(dialog.instruments[0]["channels"]) == 1


def test_a_multimeter_table_has_type_attenuation_unit_and_integration(app, tmp_path, library):
    dialog, path = make(tmp_path, library, [DMM])
    select(dialog, "DMM")
    table = dialog.channel_table
    assert table.rowCount() == 2 and table.columnCount() == 6
    assert [table.cellWidget(0, 2).itemText(i) for i in range(6)] == [
        "DC_V",
        "DC_A",
        "AC_V",
        "AC_A",
        "RES",
        "FREQ",
    ]
    created = dialog.instruments[0]["channels"][0]
    assert created["meas_type"] == "DC_V" and created["attenuation"] == 1.0
    assert created["unit"] == "V" and created["integration_time"] == 0.0
    table.cellWidget(0, 0).setChecked(True)
    table.cellWidget(0, 1).setText("VIN")
    table.cellWidget(0, 2).setCurrentText("RES")
    table.cellWidget(0, 3).setText("0,5")
    table.cellWidget(0, 4).setText("ohm")
    table.cellWidget(0, 5).setText("10")
    channel = saved(path)[0]["channels"][0]
    assert channel == {
        "enabled": True,
        "name": "VIN",
        "meas_type": "RES",
        "attenuation": 0.5,
        "unit": "ohm",
        "integration_time": 10.0,
    }
    table.cellWidget(0, 3).setText("")  # not a number: no attenuation (x1)
    assert saved(path)[0]["channels"][0]["attenuation"] == 1.0


def test_an_attenuation_of_a_file_is_shown_with_a_dot_and_no_exponent(app, tmp_path, library):
    entry = dict(
        DMM,
        channels=[
            {
                "enabled": True,
                "name": "A",
                "attenuation": 0.0000001,
                "unit": "V",
                "meas_type": "DC_V",
            },
            {"enabled": True, "name": "B", "attenuation": "10,5", "unit": "V", "meas_type": "DC_V"},
        ],
    )
    dialog, _ = make(tmp_path, library, [entry])
    select(dialog, "DMM")
    table = dialog.channel_table
    assert table.cellWidget(0, 3).text() == "0.0000001"
    assert table.cellWidget(1, 3).text() == "10.5"


def test_a_datalogger_without_slots_gets_the_generic_table(app, tmp_path, library):
    dialog, path = make(tmp_path, library, [LOGGER_NO_SLOTS])
    select(dialog, "LOG")
    table = dialog.channel_table
    assert table.rowCount() == 3 and table.columnCount() == 5
    combo = table.cellWidget(2, 2)
    assert "TEMP" in [combo.itemText(i) for i in range(combo.count())]
    combo.setCurrentText("TEMP")
    table.cellWidget(2, 3).setText("10")
    table.cellWidget(2, 4).setText("degC")
    table.cellWidget(2, 0).setChecked(True)
    table.cellWidget(2, 1).setText("T1")
    channel = saved(path)[0]["channels"][2]
    assert channel["meas_type"] == "TEMP" and channel["attenuation"] == 10.0
    assert channel["unit"] == "degC" and channel["enabled"] is True and channel["name"] == "T1"


def test_an_instrument_without_channels_says_so(app, tmp_path, library):
    entry = dict(LOAD, num_channels=0, channels=[])
    dialog, _ = make(tmp_path, library, [entry])
    select(dialog, "LOAD")
    assert not hasattr(dialog, "channel_table")
    assert any("No channels" in text for text in texts(dialog.editor_widget))


def test_a_library_that_fails_does_not_break_the_tables(app, tmp_path, library, monkeypatch):
    """If the library cannot say what the model has, the entry's own channel count is used,
    for a supply and for a datalogger."""
    dialog, _ = make(tmp_path, library, [PSU, LOGGER_SLOTS])

    def boom(*args, **kwargs):
        raise RuntimeError("library gone")

    monkeypatch.setattr(dialog.load_instruments, "get_model_capabilities", boom)
    select(dialog, "PSU")
    assert dialog.channel_table.rowCount() == 3
    select(dialog, "DAQ")  # the slots cannot be read: the generic table is the fallback
    assert hasattr(dialog, "channel_table")
    assert dialog.entry_caps(PSU) is None


def test_the_problems_of_an_entry_survive_a_failing_library(app, tmp_path, library, monkeypatch):
    dialog, _ = make(tmp_path, library, [PSU])

    def boom(*args, **kwargs):
        raise RuntimeError("library gone")

    monkeypatch.setattr(dialog.load_instruments, "get_library", boom)
    assert isinstance(dialog.entry_problems(PSU), list)  # the model counts as found


def test_a_problem_text_with_a_wrong_placeholder_is_shown_as_it_is(app, tmp_path, library):
    dialog, _ = make(tmp_path, library, [])
    dialog.translator = SimpleNamespace(t=lambda key: "needs {missing}")
    assert dialog.problem_text("any", {"other": 1}) == "needs {missing}"


# ---------------------------------------------------------------- oscilloscope and slots
def test_the_oscilloscope_summary_lists_the_enabled_channels(app, tmp_path, library):
    dialog, _ = make(tmp_path, library, [SCOPE])
    select(dialog, "OSC")
    labels = texts(dialog.editor_widget)
    assert any("4 in total, 2 enabled" in t for t in labels)
    assert any("1 (VOUT), 2 (IL)" in t for t in labels)
    assert not any("3 (x)" in t for t in labels)


def test_the_oscilloscope_button_saves_and_reloads_after_ok(app, tmp_path, library, monkeypatch):
    dialog, path = make(tmp_path, library, [SCOPE])
    select(dialog, "OSC")
    opened = []

    class FakeDialog:
        def __init__(self, entry, translator, parent, load_instruments):
            opened.append(entry["instance_name"])
            self.entry = entry

        def exec(self):
            self.entry["channels"][2]["enabled"] = True
            return 1

    monkeypatch.setattr(module, "OscilloscopeConfigDialog", FakeDialog)
    button = next(b for b in dialog.editor_widget.findChildren(QPushButton) if "⚙" in b.text())
    button.click()
    assert opened == ["OSC"]
    assert saved(path)[0]["channels"][2]["enabled"] is True
    assert any("3 enabled" in t for t in texts(dialog.editor_widget))  # the summary is reloaded


def test_cancelling_the_oscilloscope_dialog_saves_nothing(app, tmp_path, library, monkeypatch):
    dialog, path = make(tmp_path, library, [SCOPE])
    select(dialog, "OSC")
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        module,
        "OscilloscopeConfigDialog",
        lambda *a, **k: SimpleNamespace(exec=lambda: 0),
    )
    next(b for b in dialog.editor_widget.findChildren(QPushButton) if "⚙" in b.text()).click()
    assert path.read_text(encoding="utf-8") == before


def test_a_datalogger_with_slots_shows_its_modules_and_opens_the_slot_dialog(
    app, tmp_path, library, monkeypatch
):
    dialog, path = make(tmp_path, library, [LOGGER_SLOTS])
    select(dialog, "DAQ")
    assert not hasattr(dialog, "channel_table")  # slots, not a channel table
    summary = " ".join(texts(dialog.editor_widget))
    assert "1/2" in summary and "34901A" in summary and "2 ch" in summary
    opened = []

    class FakeSlots:
        def __init__(self, entry, load_instruments, translator, parent):
            opened.append(entry["instance_name"])
            self.entry = entry

        def exec(self):
            self.entry["slots"][1]["module_id"] = "34902A"
            return 1

    monkeypatch.setattr(module, "DataloggerSlotConfigDialog", FakeSlots)
    next(b for b in dialog.editor_widget.findChildren(QPushButton) if "⚙" in b.text()).click()
    assert opened == ["DAQ"] and saved(path)[0]["slots"][1]["module_id"] == "34902A"
    assert "2/2" in " ".join(texts(dialog.editor_widget))


# ---------------------------------------------------------------- delete and menu
def test_deleting_asks_first_and_only_yes_deletes(app, tmp_path, library, monkeypatch):
    dialog, path = make(tmp_path, library, [PSU, LOAD])
    select(dialog, "PSU")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    dialog.delete_instrument()
    assert len(saved(path)) == 2 and dialog.list_widget.count() == 2
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    dialog.delete_instrument()
    assert [e["instance_name"] for e in saved(path)] == ["LOAD"]
    assert dialog.list_widget.count() == 1 and dialog.list_widget.item(0).text() == "LOAD"


def test_after_deleting_the_first_instrument_the_next_one_is_shown(
    app, tmp_path, library, monkeypatch
):
    dialog, _ = make(tmp_path, library, [PSU, LOAD])
    select(dialog, "PSU")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    dialog.delete_instrument()
    assert dialog.current_instrument is not None
    assert dialog.current_instrument["instance_name"] == "LOAD"
    assert dialog.name_edit.text() == "LOAD"


def test_deleting_the_last_row_selects_the_one_before(app, tmp_path, library, monkeypatch):
    dialog, path = make(tmp_path, library, [PSU, LOAD])
    select(dialog, "LOAD")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    dialog.delete_instrument()
    assert dialog.list_widget.currentRow() == 0
    assert dialog.current_instrument["instance_name"] == "PSU"


def test_deleting_the_only_instrument_leaves_an_empty_editor(app, tmp_path, library, monkeypatch):
    dialog, path = make(tmp_path, library, [LOAD])
    select(dialog, "LOAD")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    dialog.delete_instrument()
    assert saved(path) == [] and dialog.current_instrument is None
    assert any("no instruments" in t for t in texts(dialog.editor_widget))
    dialog.delete_instrument()  # nothing selected: nothing happens
    dialog.refresh_problems()  # and there is nothing to check


def test_the_list_menu_offers_duplicate_and_delete_only_on_an_instrument(
    app, tmp_path, library, monkeypatch
):
    dialog, _ = make(tmp_path, library, [PSU, LOAD])
    dialog.show()
    app.processEvents()
    menus = []
    monkeypatch.setattr(
        QMenu, "exec", lambda self, *a: menus.append([a.text() for a in self.actions()])
    )
    item = dialog.list_widget.item(0)
    dialog.list_widget.setCurrentRow(0)
    dialog.show_context_menu(dialog.list_widget.visualItemRect(item).center())
    assert menus == [["Duplicate", "Delete"]] or len(menus[0]) == 2
    dialog.show_context_menu(dialog.list_widget.viewport().rect().bottomRight())  # empty area
    assert len(menus) == 1
    dialog.close()


def test_the_warning_marks_follow_the_entries_of_the_list(app, tmp_path, library):
    dialog, _ = make(tmp_path, library, [PSU])
    dialog.instruments.append(dict(LOAD, instance_name="NEW"))  # not in the list widget yet
    dialog.refresh_list_marks()  # must not fail for the entry that has no row
    assert dialog.list_widget.count() == 1


# ---------------------------------------------------------------- add instrument
def add_dialog_values(dialog, monkeypatch, type_name, series, model, name):
    """Run ``add_instrument_dialog`` choosing a type, a series, a model and a name."""

    def fill(pop):
        combos = pop.findChildren(QComboBox)
        type_combo, series_combo, model_combo = combos[0], combos[1], combos[2]
        type_combo.setCurrentIndex(type_combo.findData(type_name))
        series_combo.setCurrentIndex(series_combo.findData(series))
        model_combo.setCurrentIndex(model_combo.findText(model))
        pop.findChildren(QLineEdit)[0].setText(name)

    force_exec(monkeypatch, fill)
    dialog.add_instrument_dialog()


def show_experimental(on=True):
    QSettings("LabAutomation", "App").setValue("show_experimental_instruments", on)


def test_adding_an_instrument_from_the_library(app, tmp_path, library, monkeypatch):
    show_experimental()
    dialog, path = make(tmp_path, library, [])
    add_dialog_values(
        dialog, monkeypatch, "power_supply", "Keysight_E36300_Series", "Keysight E36311A", "BENCH"
    )
    entry = saved(path)[0]
    assert entry["instrument_type"] == "power_supply" and entry["instance_name"] == "BENCH"
    assert entry["model"] == "Keysight E36311A" and entry["model_id"] == "PSU_Keysight_E36311A"
    assert entry["series"] == "Keysight_E36300_Series" and entry["channels"] == []
    assert entry["num_channels"] == 3
    assert dialog.list_widget.count() == 1 and dialog.list_widget.currentRow() == 0
    assert dialog.channel_table.rowCount() == 3  # the new entry is selected and shown


def test_an_empty_name_is_the_type_and_a_used_name_gets_a_suffix(
    app, tmp_path, library, monkeypatch
):
    show_experimental()
    dialog, path = make(tmp_path, library, [])
    for name in ("", "oscilloscope", "oscilloscope"):
        add_dialog_values(
            dialog, monkeypatch, "oscilloscope", "Siglent_SDS_HD_Series", "Siglent SDS824X HD", name
        )
    names = [e["instance_name"] for e in saved(path)]
    assert names == ["oscilloscope", "oscilloscope_", "oscilloscope_1"]
    assert saved(path)[0]["num_channels"] == 4


def test_experimental_models_are_offered_only_when_asked(app, tmp_path, library, monkeypatch):
    seen = {}

    def look(pop):
        combos = pop.findChildren(QComboBox)
        combos[0].setCurrentIndex(combos[0].findData("power_supply"))
        combos[1].setCurrentIndex(combos[1].findData("Keysight_E36300_Series"))
        seen["models"] = [combos[2].itemText(i) for i in range(combos[2].count())]
        seen["types"] = [combos[0].itemData(i) for i in range(combos[0].count())]

    dialog, _ = make(tmp_path, library, [])
    show_experimental(False)
    force_exec(monkeypatch, look, QDialog.DialogCode.Rejected)
    dialog.add_instrument_dialog()
    hidden = list(seen["models"])
    show_experimental(True)
    dialog.add_instrument_dialog()
    assert "power_supply" in seen["types"] and "function_generator" in seen["types"]
    assert "Keysight E36311A" not in hidden  # experimental: hidden by default
    assert "Keysight E36311A" in seen["models"] and set(hidden) <= set(seen["models"])


def test_cancelling_the_add_dialog_adds_nothing(app, tmp_path, library, monkeypatch):
    dialog, path = make(tmp_path, library, [LOAD])
    before = path.read_text(encoding="utf-8")
    force_exec(monkeypatch, lambda pop: None, QDialog.DialogCode.Rejected)
    dialog.add_instrument_dialog()
    assert path.read_text(encoding="utf-8") == before and dialog.list_widget.count() == 1


# ---------------------------------------------------------------- address and scan
def test_the_address_editor_changes_the_address_only_when_it_gives_one(
    app, tmp_path, library, monkeypatch
):
    dialog, path = make(tmp_path, library, [PSU])
    answers = iter(["TCPIP0::10.0.0.9::inst0::INSTR", None])

    class FakeEditor:
        def __init__(self, entry, load_instruments, parent):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def get_address(self):
            return next(answers)

    monkeypatch.setattr(module, "AddressEditorDialog", FakeEditor)
    dialog.current_instrument = None
    dialog.open_address_editor()  # nothing is selected: the editor is not even opened
    assert saved(path)[0]["visa_address"] == PSU["visa_address"]
    dialog.current_instrument = dialog.instruments[0]
    dialog.open_address_editor()
    assert saved(path)[0]["visa_address"] == "TCPIP0::10.0.0.9::inst0::INSTR"
    assert dialog.addr_label.text() == "TCPIP0::10.0.0.9::inst0::INSTR"
    dialog.open_address_editor()  # the editor refused the address (it told the user)
    assert saved(path)[0]["visa_address"] == "TCPIP0::10.0.0.9::inst0::INSTR"


class FakeResource:
    def __init__(self, address):
        self.address = address
        self.closed = False

    def query(self, command):
        if "ASRL" in self.address:
            raise OSError("no answer")
        return f"ACME,{self.address[:4]},1,1"

    def close(self):
        self.closed = True


def fake_visa(addresses, fail_open=()):
    class Manager:
        def __init__(self, *args):
            pass

        def list_resources(self):
            return tuple(addresses)

        def open_resource(self, address):
            if address in fail_open:
                raise OSError("busy")
            return FakeResource(address)

    return SimpleNamespace(ResourceManager=Manager)


def scan_buttons(pop):
    return {b.text(): b for b in pop.findChildren(QPushButton)}


def test_the_scan_lists_resources_filters_by_kind_and_applies_the_address(
    app, tmp_path, library, monkeypatch
):
    addresses = [
        "TCPIP0::10.0.0.5::inst0::INSTR",
        "USB0::0x2A8D::0x0001::SN1::INSTR",
        "ASRL3::INSTR",
        "GPIB0::7::INSTR",
    ]
    monkeypatch.setattr(module, "pyvisa", fake_visa(addresses, fail_open=("GPIB0::7::INSTR",)))
    monkeypatch.setattr(module, "PYVISA_AVAILABLE", True)
    dialog, path = make(tmp_path, library, [PSU])
    select(dialog, "PSU")
    seen = {}

    def interact(pop):
        table = pop.findChild(QTableWidget)
        seen["rows"] = [
            (table.item(r, 1).text(), table.item(r, 2).text(), table.item(r, 3).text())
            for r in range(table.rowCount())
        ]
        boxes = {c.text(): c for c in pop.findChildren(QCheckBox)}
        for name in ("LAN", "RS232", "GPIB"):  # keep only the USB ones
            boxes[name].setChecked(False)
        seen["usb_rows"] = table.rowCount()
        for name in ("LAN", "RS232", "GPIB"):
            boxes[name].setChecked(True)
        buttons = scan_buttons(pop)
        buttons["Copy address"].click()  # nothing selected: nothing is copied
        table.setCurrentCell(1, 0)
        buttons["Copy address"].click()
        seen["clipboard"] = QApplication.clipboard().text()
        buttons["Set on the selected instrument"].click()

    force_exec(monkeypatch, interact)
    dialog.open_network_scan_dialog()
    assert [r[0] for r in seen["rows"]] == addresses
    assert seen["rows"][0][1].startswith("ACME,TCPI") and seen["rows"][2][1] == ""  # no answer
    assert seen["rows"][3][1] == ""  # could not be opened
    assert seen["usb_rows"] == 1
    assert seen["clipboard"] == "USB0::0x2A8D::0x0001::SN1::INSTR"
    assert saved(path)[0]["visa_address"] == "USB0::0x2A8D::0x0001::SN1::INSTR"


def test_the_scan_never_sets_an_address_on_a_manual_instrument(app, tmp_path, library, monkeypatch):
    monkeypatch.setattr(module, "pyvisa", fake_visa(["TCPIP0::10.0.0.5::inst0::INSTR"]))
    monkeypatch.setattr(module, "PYVISA_AVAILABLE", True)
    dialog, path = make(tmp_path, library, [LOAD])
    select(dialog, "LOAD")

    def interact(pop):
        pop.findChild(QTableWidget).setCurrentCell(0, 0)
        scan_buttons(pop)["Set on the selected instrument"].click()

    force_exec(monkeypatch, interact)
    dialog.open_network_scan_dialog()
    assert "visa_address" not in saved(path)[0]


def test_the_scan_says_when_pyvisa_is_missing(app, tmp_path, library, monkeypatch, isolated):
    monkeypatch.setattr(module, "PYVISA_AVAILABLE", False)
    dialog, _ = make(tmp_path, library, [PSU])
    dialog.open_network_scan_dialog()
    assert isolated == [("information", "Scan not available")]


def test_a_scan_that_fails_is_reported(app, tmp_path, library, monkeypatch, isolated):
    class Broken:
        @staticmethod
        def ResourceManager(*args):
            raise OSError("no VISA backend")

    monkeypatch.setattr(module, "pyvisa", Broken)
    monkeypatch.setattr(module, "PYVISA_AVAILABLE", True)
    dialog, _ = make(tmp_path, library, [PSU])
    force_exec(monkeypatch, lambda pop: None, QDialog.DialogCode.Rejected)
    dialog.open_network_scan_dialog()
    assert ("warning", "Scan error") in isolated


# ---------------------------------------------------------------- saving
def test_a_file_that_cannot_be_written_is_reported_and_the_editor_goes_on(
    app, tmp_path, library, monkeypatch, isolated
):
    dialog, _ = make(tmp_path, library, [LOAD])

    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(module.inst, "save_inst", refuse)
    dialog.save_instruments()
    assert ("warning", "Save error") in isolated
    assert dialog.instruments_modified is False


def test_saving_rounds_an_attenuation_to_ten_decimals(app, tmp_path, library):
    entry = dict(
        DMM,
        channels=[
            {
                "enabled": True,
                "name": "A",
                "attenuation": 0.1 + 0.2,
                "unit": "V",
                "meas_type": "DC_V",
            },
        ],
    )
    dialog, path = make(tmp_path, library, [entry])
    dialog.save_instruments()
    assert saved(path)[0]["channels"][0]["attenuation"] == 0.3
    assert os.path.getsize(path) > 0


# ---------------------------------------------------------------- small branches
def test_a_new_load_channel_takes_the_power_limit_of_its_model(app, tmp_path, library):
    entry = {
        "instrument_type": "electronic_load",
        "instance_name": "EL",
        "series": "Siglent_SDL1000X_E_Series",
        "model_id": "EL_Siglent_SDL1030X_E",
        "num_channels": 1,
        "visa_address": "TCPIP0::192.168.1.50::inst0::INSTR",
        "channels": [],
    }
    dialog, path = make(tmp_path, library, [entry])
    select(dialog, "EL")
    channel = dialog.instruments[0]["channels"][0]
    assert channel["max_power"] == 300 and channel["max_current"] == 30
    assert dialog.channel_table.cellWidget(0, 4).text() == "300"


def test_the_serial_defaults_are_empty_when_the_library_fails(app, tmp_path, library, monkeypatch):
    dialog, _ = make(tmp_path, library, [PSU])

    def boom(*args, **kwargs):
        raise RuntimeError("library gone")

    monkeypatch.setattr(dialog.load_instruments, "get_library", boom)
    assert dialog.serial_defaults(PSU) == {}


def test_edits_with_nothing_selected_change_nothing(app, tmp_path, library):
    dialog, path = make(tmp_path, library, [PSU])
    before = path.read_text(encoding="utf-8")
    dialog.current_instrument = None
    dialog.on_timeout_changed(9000)
    dialog.on_channel_power_changed(0, "50")
    dialog.on_channel_current_changed(0, "1")
    dialog.check_name("whatever")
    dialog.commit_name()
    assert path.read_text(encoding="utf-8") == before


def test_committing_the_same_name_changes_nothing(app, tmp_path, library):
    dialog, path = make(tmp_path, library, [PSU, LOAD])
    select(dialog, "PSU")
    before = path.read_text(encoding="utf-8")
    dialog.name_edit.setText("  PSU ")  # the same name with spaces around
    dialog.name_edit.editingFinished.emit()
    assert path.read_text(encoding="utf-8") == before and dialog.name_error.isHidden()


def test_a_resource_that_answers_with_write_and_read_still_gets_its_idn(
    app, tmp_path, library, monkeypatch
):
    """An old VISA resource without ``query`` is asked with write + read."""

    class OldResource:
        def __init__(self):
            self.sent = []

        def write(self, text):
            self.sent.append(text)

        def read(self):
            return "OLD,INSTRUMENT,1,0"

        def close(self):
            pass

    class Manager:
        def __init__(self, *args):
            pass

        def list_resources(self):
            return ("GPIB0::3::INSTR",)

        def open_resource(self, address):
            return OldResource()

    monkeypatch.setattr(module, "pyvisa", SimpleNamespace(ResourceManager=Manager))
    monkeypatch.setattr(module, "PYVISA_AVAILABLE", True)
    dialog, _ = make(tmp_path, library, [PSU])
    seen = {}

    def look(pop):
        table = pop.findChild(QTableWidget)
        seen["idn"] = table.item(0, 2).text()

    force_exec(monkeypatch, look, QDialog.DialogCode.Rejected)
    dialog.open_network_scan_dialog()
    assert seen["idn"] == "OLD,INSTRUMENT,1,0"
