# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The DUT windows: the archive, the card, the versions (no screen needed)."""

import json
import os
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from frontend.ui import DutEditDialog as edit_module  # noqa: E402
from frontend.ui import DutsDialog as duts_module  # noqa: E402
from frontend.ui import DutVersionsDialog as versions_module  # noqa: E402
from frontend.ui.DutEditDialog import DutEditDialog  # noqa: E402
from frontend.ui.DutsDialog import DutsDialog  # noqa: E402
from frontend.ui.DutVersionsDialog import DutVersionsDialog  # noqa: E402
from frontend.ui.LabelDialog import LabelDialog  # noqa: E402
from ola.assets import AssetRegistry  # noqa: E402
from ola.duts import DutRegistry  # noqa: E402

pytestmark = pytest.mark.gui

LANG = os.path.join(os.path.dirname(duts_module.__file__), "..", "lang", "modules")
LANGS = ("it", "en", "fr", "es", "de")


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
def archive(tmp_path):
    reg = DutRegistry(tmp_path / "duts.json")
    reg.create("converter", "Pippo", "boost 12 V to 5 V", {"max_power_w": 20}, version="rev A")
    reg.create("antenna", "868 MHz whip")
    reg.create("filter", "SAW 868", version="V01")
    return reg


def catalog(module, lang):
    with open(os.path.join(LANG, module, f"{lang}.json"), encoding="utf-8") as f:
        return json.load(f)


# ---- strings -----------------------------------------------------------------------------------
def test_the_catalog_is_in_every_language_with_the_same_keys():
    keys = {lang: set(catalog("duts", lang)) for lang in LANGS}
    assert all(keys[lang] == keys["en"] for lang in LANGS)
    for lang in LANGS:
        assert all(v.strip() for v in catalog("duts", lang).values())


def test_every_string_the_windows_use_exists_in_every_language():
    used = set()
    for module in (duts_module, edit_module, versions_module):
        source = open(module.__file__, encoding="utf-8").read()
        used |= set(re.findall(r'_t\(\s*"([a-z_0-9]+)"', source))
        used |= set(re.findall(r'"((?:dut|dutv)_[a-z_0-9]+|ast_[a-z_0-9]+)"', source))
    used |= {f"ast_kind_{c}" for c in ("antenna", "filter", "converter", "generic")}
    for lang in LANGS:
        have = set(catalog("duts", lang)) | set(catalog("assets", lang))
        assert not (used - have), (lang, sorted(used - have))


# ---- the list ----------------------------------------------------------------------------------
def test_the_list_shows_code_category_name_and_the_current_version(app, archive):
    d = DutsDialog(archive)
    assert d.table.rowCount() == 3
    row = [d.table.item(0, c).text() for c in range(7)]
    assert row[0] == "DUT-0001" and row[1] == "Converter" and row[2] == "Pippo"
    assert row[3] == "rev A" and row[4] == "boost 12 V to 5 V"
    assert d.table.item(1, 3).text() == ""  # the antenna has no version
    assert d.table.item(2, 3).text() == "V01"


def test_the_list_can_be_filtered_by_category_and_hides_what_is_retired(app, archive):
    archive.update("DUT-0002", retired=True)
    d = DutsDialog(archive)
    assert d.table.rowCount() == 3 and d.table.item(1, 6).text() != d.table.item(0, 6).text()
    d.retired_box.setChecked(False)
    assert [d.table.item(r, 0).text() for r in range(d.table.rowCount())] == [
        "DUT-0001",
        "DUT-0003",
    ]
    d.category_box.setCurrentIndex(d.category_box.findData("filter"))
    assert [d.table.item(r, 0).text() for r in range(d.table.rowCount())] == ["DUT-0003"]


def test_a_scanned_code_selects_the_card_even_if_it_is_hidden_or_an_old_code(
    app, tmp_path, archive
):
    components = AssetRegistry(tmp_path / "assets.json")
    components.create("antenna", "old whip")  # ANT-0001, moved to the archive as DUT-0004
    archive.migrate_from(components)
    d = DutsDialog(archive)
    d.category_box.setCurrentIndex(d.category_box.findData("filter"))
    d.scan_edit.setText("OLA:dut-1")
    d.scan()
    assert [x.id for x in d.selected()] == ["DUT-0001"] and d.table.rowCount() == 4
    d.scan_edit.setText("OLA:ANT-0001")  # the label already stuck on the antenna
    d.scan()
    assert [x.name for x in d.selected()] == ["old whip"]
    d.scan_edit.setText("DUT-0099")
    d.scan()
    assert "DUT-0099" in d.message.text() and not d.scan_edit.text()


# ---- the actions -------------------------------------------------------------------------------
def test_retire_and_bring_back(app, archive):
    d = DutsDialog(archive)
    d.table.selectRow(0)
    assert d.buttons["ast_retire"].isEnabled()
    d.toggle_retired()
    assert archive.get("DUT-0001").retired and d.table.item(0, 6).text() != "Active"
    d.table.selectRow(0)
    d.toggle_retired()
    assert not archive.get("DUT-0001").retired


def test_delete_asks_first_and_the_code_is_not_given_again(app, archive, monkeypatch):
    d = DutsDialog(archive)
    d.table.selectRow(1)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    d.delete_selected()
    assert archive.get("DUT-0002") is not None
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    d.delete_selected()
    assert archive.get("DUT-0002") is None and d.table.rowCount() == 2
    assert archive.create("generic", "next").id == "DUT-0004"


def test_buttons_follow_the_selection(app, archive):
    d = DutsDialog(archive)
    assert not d.buttons["ast_edit"].isEnabled() and not d.buttons["ast_label"].isEnabled()
    d.table.selectRow(0)
    assert d.buttons["dut_versions"].isEnabled() and d.buttons["ast_delete"].isEnabled()
    d.table.selectAll()
    assert not d.buttons["ast_edit"].isEnabled() and d.buttons["ast_label"].isEnabled()


def test_the_label_window_opens_with_the_version_line(app, archive):
    d = DutsDialog(archive)
    d.table.selectRow(0)
    d.make_labels()
    assert isinstance(d.label_tool, LabelDialog) and "version" in d.label_tool.field_boxes
    d.label_tool.close()


# ---- the card ----------------------------------------------------------------------------------
def test_a_new_dut_has_a_category_a_name_and_a_first_version_if_given(app, archive):
    d = DutEditDialog(archive, category="antenna")
    d.name_edit.setText("  Dipole 433  ")
    d.version_edit.setText("rev B")
    d.attr_edits["gain_dbi"].setText("2.15")
    d.save()
    card = d.saved
    assert (card.id, card.category, card.name) == ("DUT-0004", "antenna", "Dipole 433")
    assert card.attributes == {"gain_dbi": 2.15} and archive.versions_of(card.id) == ["rev B"]


def test_a_new_dut_needs_a_name_and_may_have_no_version(app, archive):
    d = DutEditDialog(archive, category="generic")
    d.save()
    assert d.saved is None and d.message.text()
    d.name_edit.setText("board")
    d.save()
    assert d.saved.versions == []


def test_the_card_of_a_dut_that_exists_keeps_its_code_and_has_no_version_box(app, archive):
    d = DutEditDialog(archive, dut=archive.get("DUT-0001"))
    assert not hasattr(d, "version_edit") and d.name_edit.text() == "Pippo"
    d.name_edit.setText("Pippo 2")
    d.save()
    assert archive.get("DUT-0001").name == "Pippo 2" and archive.get("DUT-0001").id == "DUT-0001"


def test_a_converter_suggests_its_own_details(app, archive):
    d = DutEditDialog(archive, category="converter")
    assert list(d.attr_edits) == ["topology", "input_voltage", "output_voltage", "max_power_w"]


# ---- the versions ------------------------------------------------------------------------------
def test_versions_are_added_in_free_text_and_a_repeat_is_refused_with_a_sentence(app, archive):
    d = DutVersionsDialog(archive, code="DUT-0001")
    assert d.table.rowCount() == 1 and d.table.item(0, 3).text() == "current"
    d.label_edit.setText("RFB")
    d.note_edit.setText("new inductor")
    d.add_version()
    assert archive.versions_of("DUT-0001") == ["rev A", "RFB"]
    assert (
        d.table.rowCount() == 2
        and not d.label_edit.text()
        and d.table.item(1, 3).text() == "current"
    )
    d.label_edit.setText("rfb")
    d.add_version()
    assert "already has the version" in d.message.text() and d.table.rowCount() == 2
    d.label_edit.setText(" ")
    d.add_version()
    assert "cannot be empty" in d.message.text()


def test_a_retired_version_stays_and_is_no_longer_current(app, archive):
    archive.add_version("DUT-0001", "rev B")
    d = DutVersionsDialog(archive, code="DUT-0001")
    d.table.selectRow(1)
    d.toggle_retired()
    assert archive.current_version("DUT-0001") == "rev A" and d.table.rowCount() == 2
    assert d.table.item(1, 3).text() != "current" and d.table.item(0, 3).text() == "current"
    d.table.selectRow(1)
    assert d.retire_button.text() == d._t("dutv_reactivate")
    d.toggle_retired()
    assert archive.current_version("DUT-0001") == "rev B"


def test_the_versions_window_from_the_list_changes_what_the_list_shows(app, archive, monkeypatch):
    d = DutsDialog(archive)
    d.table.selectRow(0)
    archive.add_version("DUT-0001", "rev B")
    monkeypatch.setattr(versions_module.DutVersionsDialog, "exec", lambda self: 0)
    d.edit_versions()
    assert d.table.item(0, 3).text() == "rev B"
