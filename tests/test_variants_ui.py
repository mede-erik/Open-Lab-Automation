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


def fill(table, *rows):
    """What the user does: empty the table, then add a row for each (name, value)."""
    table.table.setRowCount(0)
    table._edited()
    for name, value in rows:
        table.add_row(name, value)


def test_the_variant_is_a_table_and_stored_as_a_dictionary(form):
    box = form.rows["device.variant"].widget
    fill(box, ("R100", "100 ohm"), ("fan", "on"))
    assert form.model.get("device.variant") == {"R100": "100 ohm", "fan": "on"}
    assert not form.rows["device.variant"].invalid
    fill(box)
    assert form.model.get("device.variant") is None


def test_a_bad_row_marks_the_field_and_stores_nothing_wrong(form):
    box = form.rows["device.variant"].widget
    fill(box, ("R100", "100 ohm"))
    box.add_row("", "on")  # a value with no name
    row = form.rows["device.variant"]
    assert "2" in row.invalid  # the number of the row
    assert form.model.get("device.variant") == {"R100": "100 ohm"}  # what was right before
    fill(box, ("R100", "1"), ("R100", "2"))  # the same name twice
    assert "R100" in row.invalid


def test_a_variant_in_a_file_is_shown_as_a_table(app, tmp_path):
    from ola.project import MeasurementFile

    registry = default_registry(user_dir="/nonexistent")
    path = tmp_path / "m.file"
    params = {"sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 11}, "confirm_setup": False,
              "device": {"label": "x", "variant": {"R100": "100 ohm", "fan": "on"}}}  # fmt: skip
    MeasurementFile(type="return_loss", role_bindings={"vna": ["vna1"]}, params=params).save(path)
    d = FormEditorDialog(str(path), registry, "return_loss", instruments=["vna1"])
    assert d.rows["device.variant"].widget.variant() == {"R100": "100 ohm", "fan": "on"}
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


def test_the_variant_of_a_run_is_a_table_with_rows_to_add(app, archive):
    d = make(app, archive)
    fill(d.variant_edit, ("R100", "100 ohm"), ("fan", "off"))
    assert d.editor.params["device"] == {"variant": {"R100": "100 ohm", "fan": "off"}}
    d.variant_edit.add_row("", "on")  # a value with no name
    assert d.editor.params["device"] == {"variant": {"R100": "100 ohm", "fan": "off"}}  # unchanged
    assert d.variant_edit.styleSheet()  # marked as wrong
    fill(d.variant_edit)
    assert "device" not in d.editor.params
    close(d)


def test_what_the_file_has_is_shown_in_the_boxes(app, archive):
    device = {"name": "Pippo", "dut_id": "DUT-0001", "version": "rev A", "variant": {"fan": "on"}}
    d = make(app, archive, device)
    assert d.dut_box.currentText() == "DUT-0001 - Pippo" and d.version_box.currentText() == "rev A"
    assert d.variant_edit.variant() == {"fan": "on"} and d.device_box.text() == "Pippo"
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


# ---- the table and the question of the start of a run -------------------------------------------
def test_the_table_has_rows_to_add_and_remove_and_suggests_the_names_used_before(app):
    from frontend.ui.VariantTable import VariantTable

    table = VariantTable(lambda key, **kw: key, ["R100", "fan"])
    seen = []
    table.changed.connect(lambda: seen.append(1))
    table.set_variant({"R100": "100 ohm"})
    assert table.variant() == {"R100": "100 ohm"} and not seen  # showing it is not an edit
    table.suggest.activated.emit(2)  # "fan", from the names used before
    assert table.table.rowCount() == 2 and table.table.item(1, 0).text() == "fan" and seen
    table.table.item(1, 1).setText("on")
    assert table.variant() == {"R100": "100 ohm", "fan": "on"}
    table.suggest.activated.emit(2)  # already there: not added twice
    assert table.table.rowCount() == 2
    table.table.selectRow(0)
    table.remove_selected()
    assert table.variant() == {"fan": "on"} and table.problem() is None
    table.add_row("", "5")
    assert "3" not in (table.problem() or "") and table.problem()  # a value with no name


def test_the_question_shows_the_last_variant_and_cannot_start_with_a_wrong_table(app):
    from PyQt6.QtWidgets import QDialogButtonBox

    from frontend.ui.VariantTable import VariantDialog

    question = {
        "dut_id": "DUT-0001", "dut": "Pippo", "version": "rev A", "current": {},
        "last": {"R100": "100 ohm"}, "names": ["R100", "fan"],
    }  # fmt: skip
    dialog = VariantDialog(question)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert dialog.variant() == {"R100": "100 ohm"} and ok.isEnabled()
    dialog.table.add_row("", "x")  # a value with no name
    assert not ok.isEnabled() and dialog.message.text()
    dialog.table.table.removeRow(1)
    dialog.table._edited()
    assert ok.isEnabled()
    dialog.table.add_row("fan", "on")
    assert dialog.variant() == {"R100": "100 ohm", "fan": "on"}
    dialog.close()


def test_starting_a_measurement_with_a_dut_asks_and_the_answer_is_for_that_run_only(
    app, tmp_path, monkeypatch
):
    import time

    from frontend.ui.ProjectWindow import ProjectWindow, demo_project
    from frontend.ui.VariantTable import VariantDialog
    from ola.demo_lab import DemoHandle, DemoLab
    from ola.project import MeasurementFile
    from ola.runs import read_run

    lab = DemoLab()
    window = ProjectWindow(
        demo_project(str(tmp_path)),
        connect=lambda name, cancel=None: DemoHandle(name, lab),
        registry=default_registry(user_dir="/nonexistent"),
    )
    ref = window.session.project.measurements[0]
    path = window.session.path(ref)
    content = MeasurementFile.load(path)
    content.params["device"] = {"dut_id": "DUT-0001", "variant": {"fan": "on"}}
    content.save(path)
    asked = []

    def answer(self):
        asked.append(self.variant())
        self.table.add_row("R100", "100 ohm")
        return 1

    monkeypatch.setattr(VariantDialog, "exec", answer)
    window.table.selectRow(0)
    window.run_measurement()
    assert asked == [{"fan": "on"}]  # proposed: the variant of the file (no earlier run)
    run = window.run_windows[0]
    deadline = time.time() + 30
    while not run.model.finished and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    header = read_run(next(window.session.run_dir.glob("*.jsonl")))["header"]
    assert header["params"]["device"]["variant"] == {"fan": "on", "R100": "100 ohm"}
    assert MeasurementFile.load(path).params["device"]["variant"] == {"fan": "on"}  # the file
    # next time the last run's variant is what is proposed
    monkeypatch.setattr(VariantDialog, "exec", lambda self: asked.append(self.variant()) or 0)
    n = len(window.run_windows)
    window.run_measurement()
    assert asked[-1] == {"fan": "on", "R100": "100 ohm"} and len(window.run_windows) == n  # cancel
    for r in window.run_windows:
        r.runner.stop()
        r.runner.join(5)
        r._timer.stop()
        r.model.state = "finished"
        r.close()
    window._timer.stop()
    window.close()
