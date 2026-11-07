# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The results comparison window (no screen needed, see conftest.py)."""

import glob
import json
import os
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from frontend.ui import CompareDialog as compare_module  # noqa: E402
from frontend.ui.CompareDialog import CompareDialog  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from tests.test_compare import cable_run  # noqa: E402

LANG_DIR = os.path.join(
    os.path.dirname(compare_module.__file__), "..", "lang", "modules", "compare"
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.fixture(autouse=True)
def no_real_dialogs(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected message box: {args[1:3]}")

    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture
def two_cables(registry, tmp_path):
    a = cable_run(registry, tmp_path, "Cable A", length=1.0)
    b = cable_run(registry, tmp_path, "Cable B", length=3.0, stamp="20261103_110000")
    return str(a), str(b)


@pytest.fixture
def dialog(app, two_cables):
    d = CompareDialog(list(two_cables))
    yield d
    d.close()


# ---- translations -------------------------------------------------------------------------------
def test_strings_are_in_every_language_with_the_same_placeholders():
    catalogs = {}
    for path in glob.glob(os.path.join(LANG_DIR, "*.json")):
        catalogs[os.path.basename(path)[:-5]] = json.load(open(path, encoding="utf-8"))
    assert set(catalogs) >= {"en", "it", "fr", "es", "de"}
    for lang, data in catalogs.items():
        assert set(data) == set(catalogs["en"]), lang
        for key, text in data.items():
            assert set(re.findall(r"\{(\w+)\}", text)) == set(
                re.findall(r"\{(\w+)\}", catalogs["en"][key])
            ), (lang, key)
    source = open(compare_module.__file__, encoding="utf-8").read()
    assert sorted(set(re.findall(r'"(cmp_[a-z_]+)"', source)) - set(catalogs["en"])) == []


# ---- the window ---------------------------------------------------------------------------------
def test_it_lists_the_runs_with_their_names_and_the_first_is_the_reference(dialog):
    assert dialog.run_list.count() == 2
    assert dialog.run_list.item(0).text() == "★ Cable A - 2026-11-03 10:00"
    assert dialog.run_list.item(1).text() == "Cable B - 2026-11-03 11:00"
    assert [r.name for r in dialog.checked_runs()] == ["Cable A", "Cable B"]
    assert "(2 of 2 runs)" in dialog.trace_box.itemText(0)


def test_the_curves_are_drawn_on_top_of_each_other(dialog):
    dialog.trace_box.setCurrentIndex(dialog.trace_box.findData("loss_db"))
    dialog._draw_curves()
    labels = [c[0] for c in dialog.plot.curves]
    assert labels == ["Cable A - 2026-11-03 10:00", "Cable B - 2026-11-03 11:00"]
    top = [c[2][-1] for c in dialog.plot.curves]
    assert top[1] > 2.5 * top[0]  # the 3 m cable loses about three times the 1 m cable
    assert dialog.plot.x_unit == "Hz" and dialog.plot.xlabel == "Frequency"


def test_a_complex_curve_can_be_seen_as_loss_phase_or_smith(dialog):
    dialog.trace_box.setCurrentIndex(dialog.trace_box.findData("S21"))
    dialog._draw_curves()
    views = [dialog.view_box.itemData(i) for i in range(dialog.view_box.count())]
    assert "loss_db" in views and "smith" in views
    dialog.view_box.setCurrentIndex(dialog.view_box.findData("loss_db"))
    dialog._draw_curves()
    assert dialog.plot.ylabel == "Loss (dB)" and all(y > 0 for y in dialog.plot.curves[0][2])
    dialog.view_box.setCurrentIndex(dialog.view_box.findData("smith"))
    dialog._draw_curves()
    assert dialog.stack.currentWidget() is dialog.smith and len(dialog.smith.curves) == 2


def test_the_difference_from_the_reference_with_its_figures(dialog):
    dialog.trace_box.setCurrentIndex(dialog.trace_box.findData("loss_db"))
    dialog.mode_box.setCurrentIndex(dialog.mode_box.findData("difference"))
    dialog._draw_curves()
    assert [c[0] for c in dialog.plot.curves] == [
        "Cable B - 2026-11-03 11:00"
    ]  # the reference has none
    assert dialog.plot.ylabel.startswith("Δ")
    assert all(d >= 0 for d in dialog.plot.curves[0][2])  # B (3 m) loses more than A (1 m)
    text = dialog.stats_label.text()
    assert "Difference from Cable A" in text and "largest +" in text and "GHz" in text


def test_choosing_another_reference_reverses_the_difference(dialog):
    dialog.trace_box.setCurrentIndex(dialog.trace_box.findData("loss_db"))
    dialog.mode_box.setCurrentIndex(dialog.mode_box.findData("difference"))
    dialog.run_list.setCurrentRow(1)
    dialog.make_reference()
    assert dialog.run_list.item(1).text().startswith("★ ")
    dialog._draw_curves()
    assert [c[0] for c in dialog.plot.curves] == ["Cable A - 2026-11-03 10:00"]
    assert all(d <= 0 for d in dialog.plot.curves[0][2])


def test_unticking_a_run_takes_it_out(dialog):
    dialog.run_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert [r.name for r in dialog.checked_runs()] == ["Cable A"]
    dialog.trace_box.setCurrentIndex(dialog.trace_box.findData("loss_db"))
    dialog._draw_curves()
    assert len(dialog.plot.curves) == 1
    assert "(1 of 1 runs)" in dialog.trace_box.itemText(0)


def test_the_summary_table_shows_the_changes_from_the_reference(dialog):
    keys = [dialog.summary.item(r, 0).text() for r in range(dialog.summary.rowCount())]
    row = keys.index("loss_868MHz_db")
    reference_cell, other_cell = (
        dialog.summary.item(row, 1).text(),
        dialog.summary.item(row, 2).text(),
    )
    assert "(" not in reference_cell  # the reference has no change
    assert re.search(r"\(\+\d", other_cell)  # the other lost more
    assert dialog.summary.horizontalHeaderItem(1).text().startswith("★ ")
    cable = dialog.summary.item(keys.index("cable"), 2).text()
    assert cable == "Cable B"  # text is shown as it is, with no change


def test_a_run_can_be_renamed_and_removed(dialog, monkeypatch):
    monkeypatch.setattr(
        QInputDialog, "getText", staticmethod(lambda *a, **k: ("the long one", True))
    )
    dialog.run_list.setCurrentRow(1)
    dialog.rename_selected()
    assert dialog.run_list.item(1).text() == "the long one"
    dialog.remove_selected()
    assert dialog.run_list.count() == 1 and dialog.reference == 0
    dialog.run_list.setCurrentRow(0)
    dialog.remove_selected()
    assert dialog.run_list.count() == 0 and dialog.plot.curves == []


def test_removing_a_run_before_the_reference_keeps_the_reference(dialog):
    dialog.run_list.setCurrentRow(1)
    dialog.make_reference()
    dialog.run_list.setCurrentRow(0)
    dialog.remove_selected()  # the first run goes: the reference is now the first
    assert dialog.reference == 0 and dialog.runs[0].name == "Cable B"
    assert dialog.run_list.item(0).text().startswith("★ ")


def test_files_that_cannot_be_compared_are_reported_together(dialog, tmp_path, monkeypatch):
    bad1, bad2 = tmp_path / "x_20261103_100000.jsonl", tmp_path / "y_20261103_100000.jsonl"
    bad1.write_text("")
    bad2.write_text("not json\n")
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[2])))
    dialog.add_files([str(bad1), str(bad2)])
    assert len(shown) == 1 and "x_20261103" in shown[0] and "y_20261103" in shown[0]
    assert dialog.run_list.count() == 2  # nothing was added


def test_a_file_already_there_is_not_added_twice(dialog, two_cables):
    dialog.add_files([two_cables[0]])
    assert dialog.run_list.count() == 2


def test_runs_of_different_kinds_are_flagged(app, registry, tmp_path, two_cables):
    from ola.runner import Runner
    from ola.runs import RunWriter
    from ola.sim_vna import SimVna

    params = {
        "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 101},
        "device": {"label": "whip"},
        "confirm_setup": False,
    }
    runner = Runner(
        registry.create("return_loss", params), {"vna": [SimVna(termination="antenna")]}
    )
    path = tmp_path / "rl_20261103_130000.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(20)
    d = CompareDialog([*two_cables, str(path)])
    try:
        assert "different kinds" in d.mixed_label.text()
        names = [d.trace_box.itemData(i) for i in range(d.trace_box.count())]
        assert names.index("S11") > names.index("loss_db")  # the ones in most runs come first
        d.trace_box.setCurrentIndex(d.trace_box.findData("S11"))
        d._draw_curves()
        assert len(d.stack.currentWidget().curves) == 1 and "1 of 3" in d.trace_box.currentText()
    finally:
        d.close()


# ---- tables of many points (efficiency) ---------------------------------------------------------
def make_table_run(tmp_path, name, scale):
    path = tmp_path / f"{name}_20261103_100000.jsonl"
    lines = [{"kind": "run", "run_id": name, "measurement": "efficiency", "params": {}}]
    n = 0
    for iout in (1, 2):
        for vin in (9, 12, 15):
            values = {"vin": vin, "iout": iout, "efficiency": 90 + scale * vin - iout}
            lines.append(
                {"kind": "point", "table": "points", "index": n, "elapsed_s": n, "values": values}
            )
            n += 1
    lines.append({"kind": "end", "state": "finished", "error": None})
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    return str(path)


def test_runs_with_tables_are_compared_column_against_column(app, tmp_path):
    d = CompareDialog([make_table_run(tmp_path, "old", 0.1), make_table_run(tmp_path, "new", 0.2)])
    try:
        assert [d.x_box.itemData(i) for i in range(d.x_box.count())] == [
            "vin",
            "iout",
            "efficiency",
        ]
        assert d.x_box.currentData() == "vin" and d.y_box.currentData() == "efficiency"
        d._draw_tables()
        assert len(d.table_plot.curves) == 2  # one line per run
        d.group_box.setCurrentIndex(d.group_box.findData("iout"))
        d._draw_tables()
        labels = [c[0] for c in d.table_plot.curves]
        assert len(labels) == 4 and labels[0].endswith("iout=1") and labels[3].endswith("iout=2")
        assert d.table_plot.xlabel == "vin" and d.table_plot.ylabel == "efficiency"
        assert d.summary.rowCount() == 0  # a table of many points has no summary row
    finally:
        d.close()


# ---- export -------------------------------------------------------------------------------------
def test_the_overlay_is_exported_as_csv_and_the_plot_as_an_image(dialog, tmp_path, monkeypatch):
    dialog.trace_box.setCurrentIndex(dialog.trace_box.findData("loss_db"))
    dialog._draw_curves()
    csv_path, png = str(tmp_path / "o.csv"), str(tmp_path / "plot.png")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (csv_path, ""))
    )
    dialog.export_csv()
    assert open(csv_path).readline().startswith("x [Cable A")
    assert "Saved" in dialog.stats_label.text()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (png, "")))
    dialog.show()
    dialog.save_image()
    assert os.path.getsize(png) > 1000  # a real picture


def test_adding_files_with_the_file_dialog(dialog, tmp_path, registry, monkeypatch):
    third = cable_run(registry, tmp_path, "Cable C", length=2.0, stamp="20261103_120000")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([str(third)], ""))
    )
    dialog.add_dialog()
    assert dialog.run_list.count() == 3 and dialog.run_list.item(2).text().startswith("Cable C")
    assert dialog.run_list.item(2).checkState() == Qt.CheckState.Checked  # new ones are shown


def test_an_empty_tool_shows_nothing_and_does_not_fail(app):
    d = CompareDialog()
    try:
        assert d.run_list.count() == 0 and d.plot.curves == [] and d.summary.rowCount() == 0
        d.make_reference()
        d.remove_selected()
        d.rename_selected()  # nothing selected: nothing happens
    finally:
        d.close()


# ---- inside the application ---------------------------------------------------------------------
def test_the_project_window_opens_it_with_the_runs_of_the_selected_measurement(
    app, registry, tmp_path
):
    from frontend.ui.ProjectWindow import ProjectWindow
    from ola.demo_lab import DemoHandle, DemoLab, demo_params
    from ola.project import MeasurementFile, Project

    project = Project.new("P", tmp_path)
    ref = project.add_measurement("efficiency", "Conv", registry)
    MeasurementFile(
        type="efficiency", role_bindings={"instruments": ["psu1", "psu2", "daq1", "load1"]},
        params=demo_params(samples=1, interval_s=0.01),
    ).save(project.directory / ref.file)  # fmt: skip
    project.save()
    lab = DemoLab()
    w = ProjectWindow(
        project,
        connect=lambda name, cancel=None: DemoHandle(name, lab),
        registry=registry,
    )
    try:
        w.table.selectRow(0)
        for stamp in ("101010", "111111"):  # two runs of the measurement
            runner, path = w.session.build_runner(w.session.project.measurements[0])
            runner.start()
            assert runner.join(20)
            path.rename(path.with_name(path.name.rsplit("_", 1)[0] + f"_{stamp}.jsonl"))
        w._refresh_runs()
        assert w.runs_table.rowCount() == 2 and w.compare_btn.isEnabled()
        w.compare_runs()
        assert w._compare_tool.run_list.count() == 2
        tool = w._compare_tool
        assert tool.summary.rowCount() == 0 and tool.x_box.count() > 0  # tables, not a summary
        w._compare_tool.close()
    finally:
        w._timer.stop()
        w.close()


def test_the_main_window_menu_opens_the_tool():
    """main_window.py opens a database, so it is not built here: check the wiring in the source."""
    path = os.path.join(os.path.dirname(compare_module.__file__), "main_window.py")
    source = open(path, encoding="utf-8").read()
    assert "from frontend.ui.CompareDialog import CompareDialog" in source
    assert 'CatalogTranslator("compare", self.translator).t("cmp_menu")' in source
    assert "compare_action.triggered.connect(self.open_compare_tool)" in source
    assert "tools_menu.addAction(compare_action)" in source


def test_figures_show_frequencies_with_units_and_hide_changes_that_are_nothing(dialog):
    from frontend.ui.CompareDialog import changed, figure, signed

    assert figure(868e6, "peak_at_hz") == "868 MHz" and figure(868e6, "vin") == "8.68e+08"
    assert figure(None) == "" and figure("PASS") == "PASS" and figure(True) == "True"
    assert (
        signed(50e6, "f_low_hz") == "+50 MHz" and signed(-2.0) == "-2" and signed(0.31) == "+0.31"
    )
    assert changed(0.5, 10) and not changed(0.0, 10) and not changed(1e-12, 1.0)
    keys = [dialog.summary.item(r, 0).text() for r in range(dialog.summary.rowCount())]
    same = dialog.summary.item(keys.index("points"), 2).text()
    assert same == "301"  # the same in both runs: no "(+0)"
    top = dialog.summary.item(keys.index("max_loss_at_hz"), 2).text()
    assert top == "3 GHz"
