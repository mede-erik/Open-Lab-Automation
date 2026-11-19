# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The variant of a run and the DUT of an efficiency file in the windows (no screen needed)."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.AssetsDialog import AssetHistoryDialog  # noqa: E402
from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog  # noqa: E402
from frontend.ui.FormEditorDialog import FormEditorDialog  # noqa: E402
from ola.assets import RunRef  # noqa: E402
from ola.duts import DutRegistry  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from tests.efficiency_params import INSTRUMENTS, good  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def archive(tmp_path):
    reg = DutRegistry(tmp_path / "duts.json")
    reg.create("converter", "Pippo", version="rev A")
    reg.add_version("DUT-0001", "rev B")
    return reg


def close(dialog):
    dialog.dirty = False  # a changed dialog would ask about saving and wait for an answer
    dialog.close()


# ---- the form of a measurement -----------------------------------------------------------------
@pytest.fixture
def form(app, tmp_path):
    registry = default_registry(user_dir="/nonexistent")
    d = FormEditorDialog(str(tmp_path / "m.file"), registry, "return_loss", instruments=["vna1"])
    yield d
    close(d)


def test_the_variant_is_written_as_lines_and_stored_as_a_dictionary(form):
    box = form.rows["device.variant"].widget
    box.setPlainText("R100 = 100 ohm\nfan = on")
    assert form.model.get("device.variant") == {"R100": "100 ohm", "fan": "on"}
    assert not form.rows["device.variant"].invalid
    box.setPlainText("")
    assert form.model.get("device.variant") is None


def test_a_bad_line_marks_the_field_and_stores_nothing_wrong(form):
    box = form.rows["device.variant"].widget
    box.setPlainText("R100 = 100 ohm")
    box.setPlainText("R100 = 100 ohm\nfan")
    row = form.rows["device.variant"]
    assert "2" in row.invalid  # the line number
    assert form.model.get("device.variant") == {"R100": "100 ohm"}  # what was right before


def test_a_variant_in_a_file_is_shown_as_lines(app, tmp_path):
    from ola.project import MeasurementFile

    registry = default_registry(user_dir="/nonexistent")
    path = tmp_path / "m.file"
    params = {"sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 11}, "confirm_setup": False,
              "device": {"label": "x", "variant": {"R100": "100 ohm", "fan": "on"}}}  # fmt: skip
    MeasurementFile(type="return_loss", role_bindings={"vna": ["vna1"]}, params=params).save(path)
    d = FormEditorDialog(str(path), registry, "return_loss", instruments=["vna1"])
    assert d.rows["device.variant"].widget.toPlainText() == "R100 = 100 ohm\nfan = on"
    close(d)


# ---- the efficiency editor ---------------------------------------------------------------------
def make(app, archive=None, device=None):
    params = good()
    if device is not None:
        params["device"] = device
    return EfficiencyEditorDialog(params=params, instruments=INSTRUMENTS, duts=archive)


def test_choosing_a_dut_writes_its_code_and_fills_the_name_and_the_version(app, archive):
    d = make(app, archive)
    d.dut_box.setCurrentIndex(d.dut_box.findData("DUT-0001"))
    d.dut_box.activated.emit(1)
    assert d.editor.params["device"] == {"name": "Pippo", "dut_id": "DUT-0001", "version": "rev B"}
    assert d.dirty and d.device_box.text() == "Pippo" and d.version_box.currentText() == "rev B"
    assert [d.version_box.itemText(i) for i in range(d.version_box.count())] == [
        "",
        "rev B",
        "rev A",
    ]
    close(d)


def test_a_name_and_a_version_already_typed_are_kept(app, archive):
    d = make(app, archive, {"name": "my board", "version": "proto"})
    d.dut_box.setCurrentIndex(d.dut_box.findData("DUT-0001"))
    d.dut_box.activated.emit(1)
    assert d.editor.params["device"] == {
        "name": "my board",
        "dut_id": "DUT-0001",
        "version": "proto",
    }
    close(d)


def test_the_variant_of_a_run_is_typed_as_lines(app, archive):
    d = make(app, archive)
    d.variant_edit.setPlainText("R100 = 100 ohm\nfan = off")
    assert d.editor.params["device"] == {"variant": {"R100": "100 ohm", "fan": "off"}}
    d.variant_edit.setPlainText("R100")
    assert d.editor.params["device"] == {"variant": {"R100": "100 ohm", "fan": "off"}}  # unchanged
    assert d.variant_edit.styleSheet()  # marked as wrong
    d.variant_edit.setPlainText("")
    assert "device" not in d.editor.params
    close(d)


def test_what_the_file_has_is_shown_in_the_boxes(app, archive):
    device = {"name": "Pippo", "dut_id": "DUT-0001", "version": "rev A", "variant": {"fan": "on"}}
    d = make(app, archive, device)
    assert d.dut_box.currentText() == "DUT-0001 - Pippo" and d.version_box.currentText() == "rev A"
    assert d.variant_edit.toPlainText() == "fan = on" and d.device_box.text() == "Pippo"
    close(d)


def test_a_code_that_is_not_one_is_marked_and_not_written(app, archive):
    d = make(app, archive)
    d.dut_box.setCurrentText("pippo board")
    d.dut_box.lineEdit().editingFinished.emit()
    assert "device" not in d.editor.params and d.dut_box.styleSheet()
    close(d)


def test_the_editor_works_without_an_archive(app):
    d = make(app, None)
    d.dut_box.setCurrentText("DUT-0003")
    d.dut_box.lineEdit().editingFinished.emit()
    assert d.editor.params["device"] == {"dut_id": "DUT-0003"}
    close(d)


# ---- the history -------------------------------------------------------------------------------
def test_the_history_has_a_variant_column_only_when_a_run_has_one(app, tmp_path):
    from pathlib import Path

    card = DutRegistry(tmp_path / "duts.json").create("converter", "Pippo")

    def ref(name, variant):
        return RunRef(
            Path(f"{name}.jsonl"), "2026-11-03 10:00", "efficiency", "finished", {}, variant
        )

    plain = AssetHistoryDialog(card, [ref("a", ""), ref("b", "")], trend=False)
    assert plain.table.columnCount() == 4
    with_variant = AssetHistoryDialog(card, [ref("a", "fan=on"), ref("b", "")], trend=False)
    assert with_variant.table.columnCount() == 5
    assert (
        with_variant.table.item(0, 3).text() == "fan=on"
        and with_variant.table.item(1, 3).text() == ""
    )
    assert with_variant.table.item(0, 4).text() == "a.jsonl"
