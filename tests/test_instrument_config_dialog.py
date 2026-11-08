# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The editor of the instrument file (.inst) on the real library (no screen needed)."""

import glob
import json
import os
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QLineEdit, QMessageBox  # noqa: E402

from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from frontend.ui.InstrumentConfigDialog import InstrumentConfigDialog  # noqa: E402
from frontend.ui.InstrumentPanels import (  # noqa: E402
    NetworkAnalyzerPanel,
    SerialPanel,
    SwitchUnitPanel,
)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
pytestmark = pytest.mark.skipif(
    LIB is None or "network_analyzers_series" not in (open(LIB).read() if LIB else ""),
    reason="library with the VNA models not available",
)

VNA = {
    "instrument_type": "network_analyzer",
    "instance_name": "VNA",
    "series": "Zenko_LiteVNA_Series",
    "model": "LiteVNA 62",
    "model_id": "VNA_Zenko_LiteVNA62",
    "visa_address": "ASRL/dev/ttyACM0::INSTR",
}
PSU = {
    "instrument_type": "power_supply",
    "instance_name": "PSU",
    "series": "Keysight_E36300_Series",
    "model": "Keysight E36312A",
    "model_id": "PSU_Keysight_E36312A",
    "visa_address": "TCPIP0::192.168.1.201::inst0::INSTR",
    "channels": [{"enabled": True, "name": "CH1", "max_current": 5.0, "max_voltage": 6.0}],
}
LOAD = {
    "instrument_type": "electronic_load",
    "instance_name": "LOAD",
    "is_manual": True,
    "num_channels": 1,
    "channels": [{"enabled": True, "name": "CH1", "max_current": 10.0, "max_voltage": 60.0}],
}
SWITCH = {
    "instrument_type": "switch_unit",
    "instance_name": "SW",
    "series": "Agilent_3499A_Series",
    "model": "DL_Agilent_3499A",
    "model_id": "DL_Agilent_3499A",
    "visa_address": "GPIB0::9::INSTR",
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_real_dialogs(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected message box: {args[1:3]}")

    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


def make(tmp_path, entries, extra=None):
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({**(extra or {}), "instruments": entries}), encoding="utf-8")
    library = LoadInstruments()
    assert library.load_instruments(LIB)
    return InstrumentConfigDialog(str(path), library), path


def saved(path):
    return json.loads(path.read_text(encoding="utf-8"))


def select(dialog, name):
    row = [e.get("instance_name") for e in dialog.instruments].index(name)
    dialog.list_widget.setCurrentRow(row)


def panel(dialog, kind):
    return dialog.editor_widget.findChild(kind)


def test_other_keys_of_the_file_survive_an_edit(app, tmp_path):
    dialog, path = make(tmp_path, [PSU, LOAD], extra={"format": 7})
    select(dialog, "PSU")
    dialog.name_edit.setText("SUPPLY")
    dialog.name_edit.editingFinished.emit()
    assert saved(path)["format"] == 7
    assert saved(path)["instruments"][0]["instance_name"] == "SUPPLY"


def test_a_broken_file_is_not_overwritten(app, tmp_path, monkeypatch):
    path = tmp_path / "lab.inst"
    path.write_text("{ this is not json", encoding="utf-8")
    library = LoadInstruments()
    library.load_instruments(LIB)
    dialog = InstrumentConfigDialog(str(path), library)
    dialog.instruments.append(dict(LOAD))
    dialog.save_instruments()
    assert path.read_text(encoding="utf-8") == "{ this is not json"


def test_the_list_marks_the_entries_with_problems(app, tmp_path):
    broken = {**PSU, "instance_name": "BAD", "visa_address": "", "channels": []}
    dialog, _ = make(tmp_path, [PSU, broken])
    assert dialog.list_widget.item(0).text() == "PSU"
    assert dialog.list_widget.item(1).text().startswith("⚠")
    assert dialog.list_widget.item(1).toolTip()
    select(dialog, "BAD")
    text = dialog.problems_label.text()
    assert "address" in text.lower() and "channel" in text.lower()
    select(dialog, "PSU")
    assert "✓" in dialog.problems_label.text()


def test_names_must_be_unique_and_not_empty(app, tmp_path):
    dialog, path = make(tmp_path, [PSU, LOAD])
    select(dialog, "PSU")
    dialog.name_edit.setText("LOAD")  # typing only shows the problem, nothing is changed yet
    assert not dialog.name_error.isHidden()
    dialog.name_edit.editingFinished.emit()  # finished: refused, the old name comes back
    assert dialog.name_edit.text() == "PSU"
    assert saved(path)["instruments"][0]["instance_name"] == "PSU"
    dialog.name_edit.setText("  ")
    dialog.name_edit.editingFinished.emit()
    assert saved(path)["instruments"][0]["instance_name"] == "PSU"
    dialog.name_edit.setText("PSU2")
    assert dialog.name_error.isHidden()
    assert saved(path)["instruments"][0]["instance_name"] == "PSU"  # not before it is finished
    dialog.name_edit.editingFinished.emit()
    assert saved(path)["instruments"][0]["instance_name"] == "PSU2"


def project_using(tmp_path, instrument):
    """A project next to the instrument file with one measurement that names ``instrument``."""
    from ola.project import MeasurementRef, Project

    project = Project.new("P", tmp_path, inst_file="lab.inst")
    (tmp_path / "m.meas").write_text(
        json.dumps({"type": "x", "role_bindings": {"psu": [instrument]}}), encoding="utf-8"
    )
    project.measurements.append(MeasurementRef("m1", "x", "my measurement", "m.meas"))
    project.save()


def bound(tmp_path):
    return json.loads((tmp_path / "m.meas").read_text(encoding="utf-8"))["role_bindings"]["psu"]


def test_renaming_updates_the_measurements_after_asking(app, tmp_path, monkeypatch):
    dialog, path = make(tmp_path, [PSU, LOAD])
    project_using(tmp_path, "PSU")
    asked = []

    def yes(parent, title, text, *args):
        asked.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(yes))
    select(dialog, "PSU")
    dialog.name_edit.setText("SUPPLY")
    dialog.name_edit.editingFinished.emit()
    assert len(asked) == 1 and "my measurement" in asked[0] and "PSU" in asked[0]
    assert bound(tmp_path) == ["SUPPLY"]
    assert saved(path)["instruments"][0]["instance_name"] == "SUPPLY"
    assert dialog.list_widget.item(0).text() == "SUPPLY"


def test_saying_no_leaves_the_name_and_the_measurements_as_they_were(app, tmp_path, monkeypatch):
    dialog, path = make(tmp_path, [PSU, LOAD])
    project_using(tmp_path, "PSU")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    select(dialog, "PSU")
    dialog.name_edit.setText("SUPPLY")
    dialog.name_edit.editingFinished.emit()
    assert dialog.name_edit.text() == "PSU" and bound(tmp_path) == ["PSU"]
    assert saved(path)["instruments"][0]["instance_name"] == "PSU"


def test_an_instrument_no_measurement_names_is_renamed_without_asking(app, tmp_path):
    dialog, path = make(tmp_path, [PSU, LOAD])
    project_using(tmp_path, "PSU")
    select(dialog, "LOAD")
    dialog.name_edit.setText("DUMMY")
    dialog.name_edit.editingFinished.emit()  # a question would fail the test (no_real_dialogs)
    assert saved(path)["instruments"][1]["instance_name"] == "DUMMY"
    assert bound(tmp_path) == ["PSU"]


def test_a_failed_update_does_not_rename(app, tmp_path, monkeypatch):
    dialog, path = make(tmp_path, [PSU, LOAD])
    project_using(tmp_path, "PSU")
    from ola import project_rename

    def boom(*args, **kwargs):
        raise project_rename.RenameError("disk full")

    warned = []
    monkeypatch.setattr(project_rename, "rename_references", boom)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    select(dialog, "PSU")
    dialog.name_edit.setText("SUPPLY")
    dialog.name_edit.editingFinished.emit()
    assert warned and "disk full" in warned[0]
    assert saved(path)["instruments"][0]["instance_name"] == "PSU" and bound(tmp_path) == ["PSU"]


def test_duplicate_gives_a_unique_instance_name_and_no_stray_key(app, tmp_path):
    dialog, path = make(tmp_path, [PSU])
    dialog.list_widget.setCurrentRow(0)
    dialog.duplicate_instrument()
    dialog.list_widget.setCurrentRow(0)
    dialog.duplicate_instrument()
    names = [e["instance_name"] for e in saved(path)["instruments"]]
    assert names == ["PSU", "PSU_copy", "PSU_copy1"]
    assert all("name" not in e for e in saved(path)["instruments"])
    assert [dialog.list_widget.item(i).text() for i in range(3)] == names


def test_max_power_of_a_supply_or_load_is_edited_and_can_be_removed(app, tmp_path):
    dialog, path = make(tmp_path, [PSU, LOAD])
    select(dialog, "LOAD")
    table = dialog.channel_table
    assert table.columnCount() == 5
    table.cellWidget(0, 4).setText("150")
    assert saved(path)["instruments"][1]["channels"][0]["max_power"] == 150.0
    table.cellWidget(0, 4).setText("")
    assert "max_power" not in saved(path)["instruments"][1]["channels"][0]
    table.cellWidget(0, 2).setText("0")  # a limit of zero is reported
    select(dialog, "LOAD")
    assert "current" in dialog.problems_label.text().lower()


def test_the_timeout_is_stored_only_when_it_is_not_the_default(app, tmp_path):
    dialog, path = make(tmp_path, [PSU, LOAD])
    select(dialog, "PSU")
    dialog.timeout_spin.setValue(20000)
    assert saved(path)["instruments"][0]["timeout_ms"] == 20000
    dialog.timeout_spin.setValue(5000)
    assert "timeout_ms" not in saved(path)["instruments"][0]


def test_a_manual_instrument_has_no_address_and_no_timeout(app, tmp_path):
    dialog, _ = make(tmp_path, [LOAD])
    select(dialog, "LOAD")
    assert dialog.addr_btn.isHidden() and dialog.addr_label.isHidden()
    assert panel(dialog, SerialPanel) is None


def test_serial_settings_are_stored_when_they_differ_from_the_library(app, tmp_path):
    entry = {**PSU, "visa_address": "ASRL3::INSTR"}
    dialog, path = make(tmp_path, [entry])
    select(dialog, "PSU")
    serial = panel(dialog, SerialPanel)
    assert serial is not None and not serial.isChecked()
    serial.setChecked(True)
    assert "serial" not in saved(path)["instruments"][0]  # same as the library: nothing to store
    serial.fields["baud"].setCurrentIndex(serial.fields["baud"].findData(19200))
    assert saved(path)["instruments"][0]["serial"] == {"baud": 19200}
    serial.setChecked(False)
    assert "serial" not in saved(path)["instruments"][0]


def test_serial_settings_are_not_offered_for_a_lan_instrument(app, tmp_path):
    dialog, _ = make(tmp_path, [PSU])
    select(dialog, "PSU")
    assert panel(dialog, SerialPanel) is None


def test_network_analyzer_ports_and_sweep(app, tmp_path):
    dialog, path = make(tmp_path, [VNA])
    select(dialog, "VNA")
    editor = panel(dialog, NetworkAnalyzerPanel)
    assert editor is not None
    entry = saved(path)["instruments"][0]
    assert "sweep" not in entry  # nothing is written just by looking at it
    editor.start.setText("1M")
    editor.stop.setText("100M")
    editor.points.setValue(401)
    entry = saved(path)["instruments"][0]
    assert entry["sweep"] == {"start_hz": 1e6, "stop_hz": 1e8, "points": 401}
    assert [p["port"] for p in entry["ports"]] == [1, 2] and entry["num_ports"] == 2
    editor.table.cellWidget(1, 2).setText("DUT")
    assert saved(path)["instruments"][0]["ports"][1]["name"] == "DUT"
    assert "✓" in dialog.problems_label.text()


def test_a_sweep_that_cannot_be_used_is_not_stored_and_a_wrong_one_is_reported(app, tmp_path):
    dialog, path = make(tmp_path, [VNA])
    select(dialog, "VNA")
    editor = panel(dialog, NetworkAnalyzerPanel)
    editor.start.setText("1M")
    editor.stop.setText("fast")  # not a frequency: kept out of the file, field turns red
    assert saved(path)["instruments"][0]["sweep"]["stop_hz"] != 0
    assert "border" in editor.stop.styleSheet()
    editor.stop.setText("500k")  # a number, but below the start frequency
    assert "higher" in dialog.problems_label.text()
    editor.stop.setText("10G")  # above what the model does
    assert "range" in dialog.problems_label.text().lower()
    editor.if_bandwidth.setText("1k")
    assert saved(path)["instruments"][0]["sweep"]["if_bandwidth_hz"] == 1000.0
    editor.if_bandwidth.setText("")
    assert "if_bandwidth_hz" not in saved(path)["instruments"][0]["sweep"]


def test_a_switch_unit_gets_a_module_for_each_slot(app, tmp_path):
    dialog, path = make(tmp_path, [SWITCH])
    select(dialog, "SW")
    editor = panel(dialog, SwitchUnitPanel)
    assert editor is not None
    from PyQt6.QtWidgets import QComboBox

    combos = editor.findChildren(QComboBox)
    assert len(combos) == 5
    combos[1].setCurrentIndex(1)
    slots = saved(path)["instruments"][0]["slots"]
    assert slots[1]["slot_number"] == 2 and slots[1]["module_id"]
    assert slots[0]["module_id"] == ""


def test_every_text_of_the_editor_is_translated_in_all_languages(app):
    """Each ``inst_*`` key the editor can show, and a problem text for every problem code."""
    from ola import inst_file

    sources = [
        os.path.join(HERE, "frontend", "ui", name)
        for name in ("InstrumentConfigDialog.py", "InstrumentPanels.py")
    ]
    wanted = set()
    for source in sources:
        text = open(source, encoding="utf-8").read()
        wanted |= set(re.findall(r"""t\(\s*["'](inst_[a-z_]+)["']""", text))
        wanted |= set(re.findall(r"""["'](inst_[a-z_]+)["']""", text))
    code_text = open(os.path.join(HERE, "ola", "inst_file.py"), encoding="utf-8").read()
    wanted |= {f"inst_problem_{c}" for c in re.findall(r'\(\s*"([a-z_]+)",\s*\{', code_text)}
    wanted |= {"inst_limit_max_voltage", "inst_limit_max_current", "manual_field_max_power"}
    wanted = {k for k in wanted if not k.endswith("_") and k != "inst_file"}  # prefixes, module
    assert inst_file.check_entry({"instrument_type": "power_supply"})  # sanity
    langs = glob.glob(os.path.join(HERE, "frontend", "lang", "*.json"))
    assert len(langs) == 5
    for path in langs:
        catalog = json.load(open(path, encoding="utf-8"))
        missing = sorted(k for k in wanted if k not in catalog)
        assert not missing, f"{os.path.basename(path)} lacks {missing}"


def test_the_manual_instrument_dialog_takes_a_power_limit(app, tmp_path, monkeypatch):
    """The data a manual instrument is saved with (the pop-up itself is a plain form)."""
    dialog, path = make(tmp_path, [])
    from PyQt6.QtWidgets import QDialog, QDoubleSpinBox

    def fake_exec(self):
        spins = self.findChildren(QDoubleSpinBox)
        spins[0].setValue(30.0)
        spins[1].setValue(5.0)
        spins[2].setValue(100.0)
        self.findChildren(QLineEdit)[0].setText("HAND")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    dialog.add_manual_instrument_dialog()
    channel = saved(path)["instruments"][0]["channels"][0]
    assert channel == {
        "enabled": True,
        "name": "CH1",
        "max_current": 5.0,
        "max_voltage": 30.0,
        "max_power": 100.0,
    }


def test_changing_instrument_leaves_no_widget_of_the_previous_one(app, tmp_path):
    """The editor of a network analyzer must not stay on screen under the editor of a supply."""
    dialog, _ = make(tmp_path, [VNA, PSU])
    select(dialog, "VNA")
    select(dialog, "PSU")
    assert panel(dialog, NetworkAnalyzerPanel) is None
    names = [w for w in dialog.editor_widget.findChildren(QLineEdit) if w.text() == "VNA"]
    assert names == []


def _delete(dialog, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    dialog.delete_instrument()


def test_after_deleting_the_first_instrument_the_next_one_is_shown(app, tmp_path, monkeypatch):
    """takeItem() made the list emit the old row number; the editor used to stay empty."""
    dialog, path = make(tmp_path, [PSU, LOAD])
    select(dialog, "PSU")
    _delete(dialog, monkeypatch)
    assert [e["instance_name"] for e in saved(path)["instruments"]] == ["LOAD"]
    assert dialog.list_widget.currentRow() == 0
    assert dialog.current_instrument is dialog.instruments[0]
    assert dialog.current_instrument["instance_name"] == "LOAD"


def test_after_deleting_the_last_instrument_the_previous_one_is_shown(app, tmp_path, monkeypatch):
    dialog, path = make(tmp_path, [PSU, LOAD])
    select(dialog, "LOAD")
    _delete(dialog, monkeypatch)
    assert dialog.list_widget.currentRow() == 0
    assert dialog.current_instrument["instance_name"] == "PSU"


def test_deleting_the_only_instrument_leaves_an_empty_editor(app, tmp_path, monkeypatch):
    dialog, path = make(tmp_path, [LOAD])
    select(dialog, "LOAD")
    _delete(dialog, monkeypatch)
    assert dialog.current_instrument is None
    assert saved(path)["instruments"] == []
