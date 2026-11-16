# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The editor of a time log: sources, readings from the library's calls, a datalogger scan, and
the file it writes (only when the time_log module accepts it)."""

import os

import pytest

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ola.project import MeasurementFile  # noqa: E402
from ola.readings import Readable  # noqa: E402
from ola.registry import default_registry  # noqa: E402

pytestmark = pytest.mark.gui

INSTRUMENTS = {
    "dmm1": {"instance_name": "dmm1", "model_id": "MTR_Agilent_34401A"},
    "daq": {"instance_name": "daq", "model_id": "DL_Agilent_34970A"},
    "psu": {"instance_name": "psu", "model_id": "PSU_OWON_ODP3033"},
    "load": {"instance_name": "load", "model_id": "EL_Keysight_EL4913A"},
}
CALLS = {
    "dmm1": [Readable("read_voltage", "V"), Readable("read_current", "A")],
    "daq": [Readable("measure_dc_voltage", "V")],
    "psu": [Readable("read_voltage", "V", True), Readable("read_current", "A", True)],
    "load": [Readable("read_voltage", "V"), Readable("read_power", "W")],
}


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def registry(tmp_path):
    return default_registry(user_dir=tmp_path / "none")


def make(tmp_path, registry, path_name="log.tlg", params=None):
    from frontend.core.Translator import Translator
    from frontend.ui.TimeLogEditorDialog import TimeLogEditorDialog

    path = tmp_path / path_name
    if params is not None:
        MeasurementFile("time_log", params=params).save(path)

    def calls_of(entry):
        return CALLS.get(entry["instance_name"], [])

    dialog = TimeLogEditorDialog(
        str(path),
        INSTRUMENTS,
        validate=lambda p: registry.create("time_log", p).validate(),
        calls=calls_of,
        translator=Translator(),
    )
    return dialog, path


def saved(path):
    return MeasurementFile.load(path).params


def test_a_new_file_gets_one_source_per_instrument(app, tmp_path, registry):
    dialog, path = make(tmp_path, registry)
    dialog._add_source()  # the first source
    dialog.name_edit.setText("dmm")
    dialog.instrument_combo.setCurrentIndex(dialog.instrument_combo.findData("dmm1"))
    dialog.interval_edit.setText("3600")
    dialog.samples_edit.setText("24")
    dialog._add_row(dialog.readings, ["vout", "read_voltage", "", ""])
    dialog.save()
    assert saved(path) == {"sources": [{
        "name": "dmm", "instrument": "dmm1", "interval_s": 3600.0, "samples": 24,
        "readings": [{"name": "vout", "call": "read_voltage"}],
    }]}


def test_the_calls_offered_are_those_of_the_chosen_instrument(app, tmp_path, registry):
    dialog, _ = make(tmp_path, registry)
    dialog._add_source()
    dialog.instrument_combo.setCurrentIndex(dialog.instrument_combo.findData("dmm1"))
    dialog._add_row(dialog.readings, ["i", "", "", ""])
    combo = dialog.readings.cellWidget(0, 1)
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "read_voltage (V)", "read_current (A)"]  # the readings with their unit, not every call
    assert [combo.itemData(i) for i in range(combo.count())] == ["read_voltage", "read_current"]


def test_a_datalogger_scan_saves_its_channels_and_no_readings(app, tmp_path, registry):
    dialog, path = make(tmp_path, registry)
    dialog._add_source()
    dialog.name_edit.setText("daq")
    dialog.instrument_combo.setCurrentIndex(dialog.instrument_combo.findData("daq"))
    dialog.interval_edit.setText("600")
    dialog.samples_edit.setText("3")
    dialog.scan_check.setChecked(True)
    dialog._add_row(dialog.channels, ["temp1", "101", "TEMP", "", "TCouple", "K"])
    dialog._add_row(dialog.channels, ["vout", "103", "VOLT:DC", "10", "", ""])
    assert dialog.save()
    source = saved(path)["sources"][0]
    assert source["scan"] is True and "readings" not in source
    assert source["channels"][0] == {"name": "temp1", "channel_id": "101", "meas_type": "TEMP",
                                     "probe_type": "TCouple", "sensor_type": "K"}
    assert source["channels"][1] == {"name": "vout", "channel_id": "103", "meas_type": "VOLT:DC",
                                     "range": "10"}


def test_an_invalid_source_is_not_saved_and_the_problems_are_shown(app, tmp_path, registry):
    dialog, path = make(tmp_path, registry)
    dialog._add_source()
    dialog.name_edit.setText("dmm")
    dialog.instrument_combo.setCurrentIndex(dialog.instrument_combo.findData("dmm1"))
    dialog.interval_edit.setText("0")
    dialog._add_row(dialog.readings, ["vout", "read_voltage", "", ""])
    assert dialog.save() is False
    assert not path.exists()
    assert "interval_s" in dialog.problems.text()


def test_switching_sources_keeps_what_was_typed(app, tmp_path, registry):
    params = {"duration_s": 60, "sources": [
        {"name": "a", "instrument": "dmm1", "interval_s": 1, "readings": [
            {"name": "v", "call": "read_voltage"}, {"name": "i", "call": "read_current"}]},
        {"name": "b", "instrument": "dmm1", "interval_s": 2, "readings": [
            {"name": "x", "call": "read_voltage", "args": {"range": 10}}]},
    ]}
    dialog, path = make(tmp_path, registry, params=params)
    dialog.source_list.setCurrentRow(1)
    dialog.source_list.setCurrentRow(0)  # back to the first: its two readings are still there
    assert dialog.readings.rowCount() == 2
    dialog.source_list.setCurrentRow(1)
    assert dialog.readings.rowCount() == 1 and dialog.interval_edit.text() == "2"
    dialog.save()
    assert saved(path) == params


def test_the_duration_and_the_sources_of_a_file_are_shown(app, tmp_path, registry):
    params = {"duration_s": 3600, "sources": [
        {"name": "daq", "instrument": "daq", "interval_s": 600, "scan": True,
         "channels": [{"name": "t", "channel_id": "101", "meas_type": "TEMP",
                       "probe_type": "TCouple", "sensor_type": "K"}]}]}
    dialog, path = make(tmp_path, registry, params=params)
    assert dialog.duration_edit.text() == "3600"
    assert dialog.source_list.count() == 1 and dialog.scan_check.isChecked()
    assert dialog.channels.rowCount() == 1 and dialog.channels.item(0, 0).text() == "t"
    dialog.duration_edit.setText("")
    dialog.samples_edit.setText("5")  # without a duration the source needs its own samples
    dialog.save()
    assert "duration_s" not in saved(path)  # empty: each source ends by its own samples
    assert saved(path)["sources"][0]["samples"] == 5


def test_removing_a_source(app, tmp_path, registry):
    params = {"duration_s": 60, "sources": [
        {"name": "a", "instrument": "dmm1", "interval_s": 1, "readings": [
            {"name": "v", "call": "read_voltage"}]},
        {"name": "b", "instrument": "dmm1", "interval_s": 2, "readings": [
            {"name": "x", "call": "read_voltage"}]},
    ]}
    dialog, path = make(tmp_path, registry, params=params)
    dialog.source_list.setCurrentRow(0)
    dialog._remove_source()
    assert dialog.source_list.count() == 1
    dialog.save()
    assert [s["name"] for s in saved(path)["sources"]] == ["b"]


def test_a_supply_reading_takes_its_channel_and_a_load_reading_does_not(app, tmp_path, registry):
    dialog, path = make(tmp_path, registry)
    dialog._add_source()
    dialog.name_edit.setText("psu")
    dialog.instrument_combo.setCurrentIndex(dialog.instrument_combo.findData("psu"))
    dialog.interval_edit.setText("60")
    dialog.samples_edit.setText("10")
    dialog._add_row(dialog.readings, ["v", "", "", ""])
    combo = dialog.readings.cellWidget(0, 1)
    combo.setCurrentIndex(combo.findData("read_voltage"))  # a supply: the channel starts at 1
    assert dialog.readings.item(0, 2).text() == "1"
    dialog.readings.item(0, 2).setText("2")
    dialog._add_source()
    dialog.name_edit.setText("load")
    dialog.instrument_combo.setCurrentIndex(dialog.instrument_combo.findData("load"))
    dialog.interval_edit.setText("30")
    dialog.samples_edit.setText("10")
    dialog._add_row(dialog.readings, ["p", "", "", ""])
    combo = dialog.readings.cellWidget(0, 1)
    assert [combo.itemData(i) for i in range(combo.count())] == ["read_voltage", "read_power"]
    combo.setCurrentIndex(combo.findData("read_power"))
    assert dialog.readings.item(0, 2).text() == ""  # a load with one input has no channel
    assert dialog.save()
    sources = saved(path)["sources"]
    assert sources[0]["readings"] == [{"name": "v", "call": "read_voltage", "channel": 2}]
    assert sources[1]["readings"] == [{"name": "p", "call": "read_power"}]


def test_a_saved_reading_shows_its_call_and_channel_again(app, tmp_path, registry):
    params = {"duration_s": 60, "sources": [{
        "name": "psu", "instrument": "psu", "interval_s": 5,
        "readings": [{"name": "i", "call": "read_current", "channel": 3}]}]}
    dialog, path = make(tmp_path, registry, params=params)
    combo = dialog.readings.cellWidget(0, 1)
    assert combo.currentText() == "read_current (A)"
    assert dialog.readings.item(0, 2).text() == "3"
    assert dialog.save() and saved(path) == params


def test_a_call_that_is_not_in_the_list_is_kept_as_typed(app, tmp_path, registry):
    params = {"duration_s": 60, "sources": [{
        "name": "dmm", "instrument": "dmm1", "interval_s": 5,
        "readings": [{"name": "x", "call": "measure_dc_voltage", "args": {"range": 10}}]}]}
    dialog, path = make(tmp_path, registry, params=params)
    assert dialog.readings.cellWidget(0, 1).currentText() == "measure_dc_voltage"
    assert dialog.save() and saved(path) == params
