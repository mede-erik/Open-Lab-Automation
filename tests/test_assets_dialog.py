# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The windows of the registry of cables and devices and of the labels (no screen needed)."""

import glob
import json
import os
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox  # noqa: E402

from frontend.ui import AssetEditDialog as edit_module  # noqa: E402
from frontend.ui import AssetsDialog as assets_module  # noqa: E402
from frontend.ui import LabelDialog as label_module  # noqa: E402
from frontend.ui.AssetEditDialog import (  # noqa: E402
    AssetEditDialog,
    parse_attribute,
    parse_extra,
    show_attribute,
)
from frontend.ui.AssetsDialog import AssetHistoryDialog, AssetsDialog  # noqa: E402
from frontend.ui.LabelDialog import LabelDialog  # noqa: E402
from ola.assets import KINDS, AssetRegistry  # noqa: E402
from ola.labels import FIELDS, PRESETS, SHEETS  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from ola.runner import Runner  # noqa: E402
from ola.runs import RunWriter  # noqa: E402
from ola.sim_vna import SimVna  # noqa: E402

LANG_DIR = os.path.join(os.path.dirname(assets_module.__file__), "..", "lang", "modules", "assets")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_real_dialogs(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected message box: {args[1:3]}")

    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture
def registry(tmp_path):
    reg = AssetRegistry(tmp_path / "assets.json")
    reg.create(
        "cable", "RG316 SMA-SMA", "1 m test lead", {"length_m": 1.0, "connectors": "SMA-SMA"}
    )
    reg.create("cable", "RG58 N-N", "2 m cable", {"length_m": 2.0})
    reg.create("antenna", "868 MHz whip")
    return reg


def cable_run(tmp_path, code, stamp, length=1.0):
    """A real cable measurement that names the cable ``code``, written as a run file."""
    params = {
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 101},
        "cable": {"label": "", "asset_id": code, "length_m": length},
        "frequencies_of_interest": [868e6],
        "confirm_setup": False,
    }
    reg = default_registry(user_dir="/nonexistent")
    runner = Runner(reg.create("cable", params), {"vna": [SimVna(length_m=length)]})
    path = tmp_path / "runs" / f"cable_{stamp}.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(20)
    return path


@pytest.fixture
def dialog(app, registry, tmp_path):
    cable_run(tmp_path, "CBL-0001", "20261103_100000")
    cable_run(tmp_path, "CBL-0001", "20261103_110000", length=1.0)
    d = AssetsDialog(registry, run_dirs=[tmp_path / "runs"])
    yield d
    d.close()


def select(d, *codes):
    """Select the rows of these codes (several rows at once, as with Ctrl+click)."""
    from PyQt6.QtCore import QItemSelectionModel

    d.table.clearSelection()
    flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    for row, asset in enumerate(d._shown):
        if asset.id in codes:
            d.table.selectionModel().select(d.table.model().index(row, 0), flags)


# ---- translations -----------------------------------------------------------------------------
def test_strings_are_in_every_language_and_every_key_used_exists():
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
    used = set()
    for module in (assets_module, edit_module, label_module):
        used |= set(
            re.findall(r'"((?:ast|lbl)_[a-z_]+)"', open(module.__file__, encoding="utf-8").read())
        )
    used |= {f"ast_kind_{k}" for k in KINDS}
    used |= {f"ast_attr_{n}" for v in KINDS.values() for n, _ in v["attributes"]}
    used |= {f"lbl_field_{k}" for k in FIELDS}
    used |= {f"ast_state_{s}" for s in ("finished", "stopped", "failed", "interrupted")}
    assert sorted(used - set(catalogs["en"])) == []


# ---- the details of a card --------------------------------------------------------------------
def test_details_are_numbers_when_they_are_measures():
    assert parse_attribute("1.5 m", "m") == 1.5 and parse_attribute("2", "m") == 2
    assert parse_attribute("868M", "Hz") == 868_000_000 and parse_attribute("SMA", "") == "SMA"
    assert parse_attribute("about 1 m", "m") == "about 1 m"  # not a number: kept as text
    assert parse_attribute("  ", "m") is None
    assert show_attribute(1.5, "m") == "1.5 m" and show_attribute(868e6, "Hz") == "868 MHz"
    assert (
        show_attribute("SMA", "") == "SMA"
        and show_attribute(None, "m") == ""
        and show_attribute(3, "") == "3"
    )


def test_other_details_are_name_value_lines():
    assert parse_extra("colour = red\n\nlength_note = 1.5\nempty =\n") == {
        "colour": "red",
        "length_note": "1.5",
    }
    for bad, line in (("no equals sign", "1"), ("ok = 1\n= value", "2")):
        with pytest.raises(ValueError) as info:
            parse_extra(bad)
        assert str(info.value) == line


# ---- creating and changing a card -------------------------------------------------------------
def test_a_new_cable_is_saved_with_its_code_and_details(app, registry):
    d = AssetEditDialog(registry, kind="cable")
    d.name_edit.setText("  Semi-rigid 0.5 m ")
    d.description_edit.setText("test lead")
    d.owner_edit.setText("RF lab")
    d.attr_edits["length_m"].setText("0.5 m")
    d.attr_edits["connectors"].setText("SMA - SMA")
    d.extra_edit.setPlainText("colour = blue")
    d.save()
    card = d.saved
    assert (
        d.result() == QDialog.DialogCode.Accepted
        and card.id == "CBL-0003"
        and card.name == "Semi-rigid 0.5 m"
    )
    assert card.attributes == {"length_m": 0.5, "connectors": "SMA - SMA", "colour": "blue"}
    assert registry.get("CBL-0003").owner == "RF lab"
    assert AssetRegistry(registry.path).get("CBL-0003").attributes["length_m"] == 0.5  # on disk


def test_choosing_another_kind_changes_the_suggested_details(app, registry):
    d = AssetEditDialog(registry)
    assert list(d.attr_edits) == ["cable_type", "connectors", "length_m"]
    d.kind_box.setCurrentIndex(d.kind_box.findData("antenna"))
    assert list(d.attr_edits) == ["frequency_range", "connector", "gain_dbi"]
    d.name_edit.setText("whip 2")
    d.save()
    assert d.saved.id == "ANT-0002" and d.saved.kind == "antenna"


def test_the_name_is_required_and_a_bad_line_is_reported(app, registry):
    d = AssetEditDialog(registry)
    d.save()
    assert (
        "name cannot be empty" in d.message.text() and d.saved is None and len(registry.assets) == 3
    )
    d.name_edit.setText("x")
    d.extra_edit.setPlainText("fine = 1\nnot a detail")
    d.save()
    assert "Line 2" in d.message.text() and d.saved is None and len(registry.assets) == 3


def test_editing_keeps_the_code_and_the_kind_and_shows_what_was_saved(app, registry):
    card = registry.get("CBL-0001")
    d = AssetEditDialog(registry, asset=card)
    assert d.name_edit.text() == "RG316 SMA-SMA" and d.attr_edits["length_m"].text() == "1 m"
    assert d.attr_edits["connectors"].text() == "SMA-SMA" and not hasattr(d, "kind_box")
    d.name_edit.setText("RG316 SMA-SMA (new)")
    d.attr_edits["length_m"].setText("1.2")
    d.save()
    assert d.saved is card and card.id == "CBL-0001" and card.kind == "cable"
    assert card.name == "RG316 SMA-SMA (new)" and card.attributes["length_m"] == 1.2


def test_a_registry_that_cannot_be_written_says_so(app, registry, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    monkeypatch.setattr(registry, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    d = AssetEditDialog(registry)
    d.name_edit.setText("x")
    d.save()
    assert shown and "disk full" in shown[0] and d.saved is None


# ---- the registry window ----------------------------------------------------------------------
def test_the_list_shows_the_cards_and_how_many_times_each_was_measured(dialog):
    assert dialog.table.rowCount() == 3
    cells = [[dialog.table.item(r, c).text() for c in range(7)] for r in range(3)]
    assert cells[0][:3] == ["CBL-0001", "Cable", "RG316 SMA-SMA"] and cells[0][5] == "2"
    assert cells[1][0] == "CBL-0002" and cells[1][5] == "0" and cells[2][1] == "Antenna"
    assert cells[0][6] == "in use" and str(dialog.registry.path) in dialog.file_label.text()


def test_the_list_can_be_filtered_by_kind_and_retired_cards_hidden(dialog):
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData("antenna"))
    assert [a.id for a in dialog._shown] == ["ANT-0001"]
    dialog.kind_box.setCurrentIndex(0)
    select(dialog, "CBL-0002")
    dialog.toggle_retired()
    assert dialog.registry.get("CBL-0002").retired and dialog.table.item(1, 6).text() == "retired"
    dialog.retired_box.setChecked(False)
    assert [a.id for a in dialog._shown] == ["CBL-0001", "ANT-0001"]
    dialog.retired_box.setChecked(True)
    select(dialog, "CBL-0002")
    assert dialog.buttons["ast_retire"].text() == "Bring back"
    dialog.toggle_retired()
    assert not dialog.registry.get("CBL-0002").retired


def test_buttons_follow_the_selection(dialog):
    select(dialog)
    assert not any(
        dialog.buttons[k].isEnabled()
        for k in ("ast_edit", "ast_delete", "ast_label", "ast_history", "ast_retire")
    )
    assert dialog.buttons["ast_new"].isEnabled()
    select(dialog, "CBL-0001")
    assert all(
        dialog.buttons[k].isEnabled()
        for k in ("ast_edit", "ast_delete", "ast_label", "ast_history")
    )
    select(dialog, "CBL-0001", "CBL-0002")  # several: labels and retiring, not editing
    assert dialog.buttons["ast_label"].isEnabled() and dialog.buttons["ast_retire"].isEnabled()
    assert (
        not dialog.buttons["ast_edit"].isEnabled() and not dialog.buttons["ast_history"].isEnabled()
    )


def test_a_scanned_code_selects_its_card(dialog):
    dialog.scan_edit.setText("OLA:cbl-2")  # what a scanner types
    dialog.scan()
    assert [a.id for a in dialog.selected()] == ["CBL-0002"] and dialog.scan_edit.text() == ""
    dialog.scan_edit.setText("CBL-0099")
    dialog.scan()
    assert "No cable or device with the code CBL-0099" in dialog.message.text()
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData("antenna"))  # hides the cables
    dialog.scan_edit.setText("CBL-0001")
    dialog.scan()  # the filter is cleared so that the card can be shown
    assert [a.id for a in dialog.selected()] == ["CBL-0001"] and dialog.message.text() == ""


def test_new_and_edit_add_and_change_cards(dialog, monkeypatch):
    def fake_exec(self):  # fills the card and saves it, as the user would
        self.name_edit.setText("New filter")
        self.save()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(AssetEditDialog, "exec", fake_exec)
    dialog.kind_box.setCurrentIndex(dialog.kind_box.findData("filter"))
    dialog.new_asset()
    assert dialog.registry.get("FLT-0001").name == "New filter"
    assert [a.id for a in dialog.selected()] == ["FLT-0001"]  # the new card is selected
    dialog.table.itemDoubleClicked.emit(dialog.table.item(0, 0))  # a double click edits
    assert dialog.registry.get("FLT-0001") is not None


def test_delete_asks_and_warns_when_measurements_used_it(dialog, monkeypatch):
    asked = []

    def question(*a, **k):
        asked.append(a[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    select(dialog, "CBL-0001")
    dialog.delete_selected()
    assert "Delete CBL-0001 - RG316 SMA-SMA" in asked[0] and "2 measurement(s)" in asked[0]
    assert dialog.registry.get("CBL-0001") is None
    select(dialog, "CBL-0002")
    dialog.delete_selected()
    assert "measurement(s)" not in asked[1]  # nothing used it: no warning
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    select(dialog, "ANT-0001")
    dialog.delete_selected()
    assert dialog.registry.get("ANT-0001") is not None  # declined


def test_the_history_lists_the_runs_and_opens_the_comparison(dialog):
    select(dialog, "CBL-0001")
    dialog.show_history()
    history = dialog.history_tool
    assert isinstance(history, AssetHistoryDialog) and history.table.rowCount() == 2
    assert [history.table.item(r, 0).text() for r in range(2)] == [
        "2026-11-03 10:00",
        "2026-11-03 11:00",
    ]
    assert (
        history.table.item(0, 1).text() == "cable" and history.table.item(0, 2).text() == "finished"
    )
    history.compare()
    assert history.tool.run_list.count() == 2 and history.tool.run_list.item(0).text().startswith(
        "★ CBL-0001 RG316"
    )
    history.tool.close()
    history.close()


def test_a_card_with_no_measurements_says_so(app, registry):
    d = AssetHistoryDialog(registry.get("CBL-0002"), [])
    assert not d.compare_btn.isEnabled() and d.table.rowCount() == 0
    d.close()


def test_the_runs_folders_can_be_a_function_that_changes(app, registry, tmp_path):
    folders = []
    d = AssetsDialog(registry, run_dirs=lambda: folders)
    assert d.table.item(0, 5).text() == "0"
    cable_run(tmp_path, "CBL-0001", "20261103_100000")
    folders.append(tmp_path / "runs")  # the project changed
    d.refresh()
    assert d.table.item(0, 5).text() == "1"
    d.close()


# ---- the label window -------------------------------------------------------------------------
def labels(dialog, *codes):
    from frontend.ui.AssetsDialog import AssetsDialog  # noqa: F401

    select(dialog, *codes)
    dialog.make_labels()
    return dialog.label_tool


def test_the_label_window_draws_one_label_per_card(dialog):
    tool = labels(dialog, "CBL-0001", "CBL-0002")
    assert isinstance(tool, LabelDialog) and len(tool.pages) == 2
    assert [tool.page_box.itemText(i) for i in range(2)] == ["CBL-0001", "CBL-0002"]
    assert "2 label(s) on 2 page(s)" in tool.page_label.text()
    assert tool.preview.drawing is tool.pages[0]
    tool.page_box.setCurrentIndex(1)
    assert tool.preview.drawing is tool.pages[1]
    tool.close()


def test_the_label_has_the_latest_measurement_when_it_is_ticked(dialog):
    tool = labels(dialog, "CBL-0001")
    tool.format_box.setCurrentIndex(tool.format_box.findData("single:" + "62x29"))
    tool.field_boxes["last_measurement"].setChecked(True)
    shown = [t.text for t in tool.pages[0].items if hasattr(t, "text")]
    assert any(re.fullmatch(r"0\.\d+ dB @ 868MHz, 2026-11-03", t) for t in shown), shown
    tool.field_boxes["last_measurement"].setChecked(False)
    assert not any("868MHz" in getattr(t, "text", "") for t in tool.pages[0].items)
    tool.close()


def test_choosing_a_format_sets_its_lines_and_they_can_be_changed(dialog):
    tool = labels(dialog, "CBL-0001")
    tool.format_box.setCurrentIndex(tool.format_box.findData("single:" + "flag 60x15"))
    assert not tool.qr_box.isChecked() and tool.field_boxes["name"].isChecked()
    assert not tool.field_boxes["description"].isChecked()
    tool.field_boxes["description"].setChecked(True)
    assert any("test lead" in getattr(t, "text", "") for t in tool.pages[0].items)
    tool.format_box.setCurrentIndex(tool.format_box.findData("single:" + "50x25"))
    assert tool.qr_box.isChecked()  # the format's own defaults again
    tool.border_box.setChecked(True)
    assert any(type(i).__name__ == "Box" for i in tool.pages[0].items)
    tool.close()


def test_a_sheet_puts_all_the_labels_on_a_page_and_skips_the_used_places(dialog):
    tool = labels(dialog, "CBL-0001", "CBL-0002", "ANT-0001")
    tool.format_box.setCurrentIndex(tool.format_box.findData("sheet:" + "A4 3x8 (70x37)"))
    assert len(tool.pages) == 1 and (tool.pages[0].width, tool.pages[0].height) == (210, 297)
    assert tool.skip_box.isEnabled()
    before = min(t.y for t in tool.pages[0].items if getattr(t, "text", "") == "CBL-0001")
    tool.skip_box.setValue(3)  # the first row is used up
    after = min(t.y for t in tool.pages[0].items if getattr(t, "text", "") == "CBL-0001")
    assert after > before + 30
    tool.skip_box.setValue(23)  # one place left: the first label, then a fresh sheet for the others
    assert len(tool.pages) == 2
    tool.close()


def test_lines_that_do_not_fit_are_listed_under_the_preview(dialog):
    tool = labels(dialog, "CBL-0001")
    tool.format_box.setCurrentIndex(tool.format_box.findData("single:" + "40x20"))
    for box in tool.field_boxes.values():
        box.setChecked(True)
    assert "No room for these lines" in tool.message.text()
    tool.close()


def test_without_segno_the_window_says_how_to_get_it(dialog, monkeypatch):
    from ola import labels as labels_module

    def missing(text, error="q"):
        raise RuntimeError("the QR code needs the 'segno' package: pip install segno")

    monkeypatch.setattr(labels_module, "qr_matrix", missing)
    tool = labels(dialog, "CBL-0001")
    assert tool.pages == [] and "pip install segno" in tool.message.text()
    assert not tool.pdf_btn.isEnabled()
    tool.qr_box.setChecked(False)  # without the QR code there is nothing to miss
    assert len(tool.pages) == 1 and tool.pdf_btn.isEnabled()
    tool.close()


def test_the_labels_are_saved_as_pdf_image_and_svg(dialog, tmp_path, monkeypatch):
    tool = labels(dialog, "CBL-0001", "CBL-0002")
    for name, method, pattern in (
        ("l.pdf", tool.save_pdf, b"%PDF"),
        ("l.png", tool.save_png, b"\x89PNG"),
        ("l.svg", tool.save_svg, b"<svg"),
    ):
        target = str(tmp_path / name)
        monkeypatch.setattr(
            QFileDialog, "getSaveFileName", staticmethod(lambda *a, t=target, **k: (t, ""))
        )
        method()
        assert open(target, "rb").read(10).startswith(pattern) or pattern in open(
            target, "rb"
        ).read(200), name
        assert "Saved" in tool.message.text()
    pdf = open(tmp_path / "l.pdf", "rb").read()
    assert len(re.findall(rb"/Type /Page\b(?!s)", pdf)) == 2  # one page per label
    tool.close()


def test_cancelling_the_file_dialog_saves_nothing(dialog, tmp_path, monkeypatch):
    tool = labels(dialog, "CBL-0001")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    tool.save_pdf()
    tool.save_png()
    tool.save_svg()
    assert not list(tmp_path.glob("l.*")) and "Saved" not in tool.message.text()
    tool.close()


def test_every_preset_and_sheet_is_in_the_format_list(dialog):
    tool = labels(dialog, "CBL-0001")
    data = [tool.format_box.itemData(i) for i in range(tool.format_box.count())]
    assert [d for d in data if d.startswith("single:")] == [f"single:{n}" for n in PRESETS]
    assert [d for d in data if d.startswith("sheet:")] == [f"sheet:{n}" for n in SHEETS]
    tool.close()


# ---- inside the application ---------------------------------------------------------------------
def test_a_project_window_with_the_registry_saves_the_card_in_the_runs(app, registry, tmp_path):
    from frontend.ui.ProjectWindow import ProjectWindow
    from ola.assets import read_header
    from ola.project import MeasurementFile, Project

    reg = default_registry(user_dir="/nonexistent")
    project = Project.new("P", tmp_path / "proj")
    ref = project.add_measurement("cable", "Test lead", reg)
    params = {
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 101},
        "cable": {"label": "", "asset_id": "CBL-0001", "length_m": 1.0},
        "confirm_setup": False,
    }
    MeasurementFile(type="cable", role_bindings={"vna": ["vna1"]}, params=params).save(
        project.directory / ref.file
    )
    project.save()
    w = ProjectWindow(
        project,
        connect=lambda name, cancel=None: SimVna(length_m=1.0),
        registry=reg,
        assets=registry,
    )
    try:
        assert w.session.assets is registry
        runner, path = w.session.build_runner(w.session.project.measurements[0])
        runner.start()
        assert runner.join(20)
        assert read_header(path)["assets"]["CBL-0001"]["name"] == "RG316 SMA-SMA"
    finally:
        w._timer.stop()
        w.close()


def test_the_main_window_menu_opens_the_registry():
    """main_window.py opens a database, so it is not built here: check the wiring in the source."""
    path = os.path.join(os.path.dirname(assets_module.__file__), "main_window.py")
    source = open(path, encoding="utf-8").read()
    assert "from frontend.ui.AssetsDialog import AssetsDialog" in source
    assert 'CatalogTranslator("assets", self.translator).t("ast_menu")' in source
    assert "assets_action.triggered.connect(self.open_assets_tool)" in source
    assert "tools_menu.addAction(assets_action)" in source
    assert "assets=self.assets" in source  # the project window gets the same registry
