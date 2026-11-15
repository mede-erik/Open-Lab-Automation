# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The window of the kits of resistors (no screen needed, see conftest.py)."""

import json
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox  # noqa: E402

from frontend.ui import ResistorKitsDialog as dialog_module  # noqa: E402
from frontend.ui.ResistorKitsDialog import ResistorKitsDialog, reference_text  # noqa: E402
from ola.resistor_kits import Kit, KitRegistry, KitResistor  # noqa: E402

LANG_DIR = os.path.join(
    os.path.dirname(dialog_module.__file__), "..", "lang", "modules", "resistors"
)


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
    kits = KitRegistry(tmp_path / "kits.json")
    kits.put(
        Kit("PWR", [KitResistor("R10", 10, 1, 50, "201", "blue"), KitResistor("R22", 22)], "bench")
    )
    kits.put(Kit("Small", [KitResistor("R1", 1)]))
    return kits


@pytest.fixture
def dialog(app, registry):
    d = ResistorKitsDialog(registry)
    yield d
    d.close()


def cell(d, row, column):
    return d.table.item(row, column).text()


def set_cell(d, row, column, text):
    d.table.item(row, column).setText(text)


# ---- translations -----------------------------------------------------------------------------
def test_strings_are_in_every_language_with_the_same_placeholders():
    import re

    catalogs = {}
    for lang in ("en", "it", "fr", "es", "de"):
        with open(os.path.join(LANG_DIR, f"{lang}.json"), encoding="utf-8") as f:
            catalogs[lang] = json.load(f)
    for lang, catalog in catalogs.items():
        assert set(catalog) == set(catalogs["en"]), lang
        for key, text in catalog.items():
            assert re.findall(r"\{(\w+)\}", text) == re.findall(
                r"\{(\w+)\}", catalogs["en"][key]
            ), (lang, key)


# ---- showing the kits -------------------------------------------------------------------------
def test_it_lists_the_kits_and_shows_the_resistors_of_the_first(dialog):
    assert [dialog.kit_list.item(i).text() for i in range(dialog.kit_list.count())] == [
        "PWR", "Small"]  # fmt: skip
    assert dialog.current == "PWR" and dialog.note_edit.text() == "bench"
    assert dialog.table.rowCount() == 2
    assert [cell(dialog, 0, c) for c in range(6)] == ["R10", "10", "1", "50", "201", "blue"]
    assert [cell(dialog, 1, c) for c in range(6)] == ["R22", "22", "", "", "", ""]
    assert not dialog.dirty and dialog.status.text() == ""


def test_choosing_another_kit_shows_its_resistors(dialog):
    dialog.kit_list.setCurrentRow(1)
    assert dialog.current == "Small" and dialog.table.rowCount() == 1
    assert cell(dialog, 0, 0) == "R1" and dialog.note_edit.text() == ""


def test_with_no_kit_the_window_says_so_and_has_nothing_to_edit(app, tmp_path):
    d = ResistorKitsDialog(KitRegistry(tmp_path / "none.json"))
    assert d.current is None and "No kit yet" in d.status.text()
    assert not d.table.isEnabled() and not d.add_btn.isEnabled() and not d.copy_btn.isEnabled()
    d.add_resistor()  # nothing happens
    d.remove_resistor()
    assert d.table.rowCount() == 0
    d.close()


# ---- editing and saving -----------------------------------------------------------------------
def test_editing_a_value_and_saving_writes_the_file(dialog, registry):
    set_cell(dialog, 1, 1, "4.7k")  # an SI prefix is understood
    set_cell(dialog, 1, 2, "5")
    set_cell(dialog, 1, 3, "25")
    set_cell(dialog, 1, 4, "202")
    assert dialog.dirty and dialog.status.text() == "Not saved yet"
    assert dialog.save()
    assert not dialog.dirty and str(registry.path) in dialog.status.text()
    saved = KitRegistry(registry.path).get("PWR").get("R22")
    assert (saved.r_ohm, saved.tol_pct, saved.power_w, saved.channel) == (4700, 5, 25, "202")
    assert saved.note == ""


def test_the_note_of_the_kit_is_saved(dialog, registry):
    dialog.note_edit.setText("on the left bench")
    dialog.note_edit.textEdited.emit("on the left bench")
    assert dialog.save()
    assert KitRegistry(registry.path).get("PWR").note == "on the left bench"


def test_a_resistor_is_added_with_a_name_that_is_free_and_removed(dialog, registry):
    dialog.add_resistor()
    dialog.add_resistor()
    assert [cell(dialog, r, 0) for r in range(4)] == ["R10", "R22", "R3", "R4"]
    assert dialog.table.currentRow() == 3 and cell(dialog, 3, 1) == "10"
    dialog.table.setCurrentCell(2, 0)
    dialog.remove_resistor()
    assert [cell(dialog, r, 0) for r in range(3)] == ["R10", "R22", "R4"] and dialog.dirty
    assert dialog.save() and len(KitRegistry(registry.path).get("PWR").resistors) == 3
    dialog.table.setCurrentCell(-1, -1)
    dialog.remove_resistor()  # no row selected: nothing to remove
    assert dialog.table.rowCount() == 3


@pytest.mark.parametrize(
    "column,text,message",
    [
        (1, "ten", "Resistor 2, Resistance (ohm): 'ten' is not a number"),
        (1, "", "Resistor 2, Resistance (ohm): '' is not a number"),
        (1, "-5", "above 0"),
        (2, "x", "Resistor 2, Tolerance (%): 'x' is not a number"),
        (2, "150", "from 0 to below 100"),
        (3, "0", "above 0"),
        (0, "R10", "two resistors are called 'R10'"),
        (0, "", "give a name"),
    ],
)
def test_a_wrong_value_is_said_and_nothing_is_written(dialog, registry, column, text, message):
    before = registry.path.read_text(encoding="utf-8")
    set_cell(dialog, 1, column, text)
    assert not dialog.save()
    assert message in dialog.status.text() and dialog.status.text().startswith("Cannot save")
    assert registry.path.read_text(encoding="utf-8") == before
    assert dialog.dirty


def test_a_table_with_an_error_does_not_let_you_leave_the_kit(dialog):
    set_cell(dialog, 0, 1, "ten")
    dialog.kit_list.setCurrentRow(1)  # try to go to the other kit
    assert dialog.current == "PWR" and dialog.kit_list.currentItem().text() == "PWR"
    assert "is not a number" in dialog.status.text()
    set_cell(dialog, 0, 1, "12")
    dialog.kit_list.setCurrentRow(1)  # now it can: the change is kept in memory
    assert dialog.current == "Small"
    dialog.kit_list.setCurrentRow(0)
    assert cell(dialog, 0, 1) == "12"


# ---- new, rename, delete ----------------------------------------------------------------------
def test_a_new_kit_is_made_and_saved(dialog, registry, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Heaters", True)))
    dialog.new_kit()
    assert dialog.current == "Heaters" and dialog.table.rowCount() == 0
    assert [dialog.kit_list.item(i).text() for i in range(3)] == ["Heaters", "PWR", "Small"]
    dialog.add_resistor()
    assert dialog.save()
    assert [r.name for r in KitRegistry(registry.path).get("Heaters").resistors] == ["R1"]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("PWR", True)))
    dialog.new_kit()  # a name that exists
    assert dialog.status.text().startswith("Cannot save") and dialog.current == "Heaters"
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", True)))
    dialog.new_kit()
    assert "give a name" in dialog.status.text()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("X", False)))
    dialog.new_kit()  # cancelled
    assert dialog.registry.names() == ["Heaters", "PWR", "Small"]


def test_a_kit_is_renamed(dialog, registry, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Power", True)))
    dialog.rename_kit()
    assert dialog.current == "Power" and dialog.registry.names() == ["Power", "Small"]
    assert dialog.table.rowCount() == 2 and dialog.dirty
    assert dialog.save() and KitRegistry(registry.path).names() == ["Power", "Small"]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Small", True)))
    dialog.rename_kit()  # the name is taken
    assert "already a kit called 'Small'" in dialog.status.text() and dialog.current == "Power"


def test_a_kit_is_deleted_only_when_confirmed(dialog, registry, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: QMessageBox.StandardButton.No))  # fmt: skip
    dialog.delete_kit()
    assert dialog.registry.names() == ["PWR", "Small"]
    asked = []

    def yes(parent, title, text):
        asked.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(yes))
    dialog.delete_kit()
    assert "PWR" in asked[0] and "2 resistor(s)" in asked[0]
    assert dialog.registry.names() == ["Small"] and dialog.current == "Small"
    assert dialog.save() and KitRegistry(registry.path).names() == ["Small"]
    dialog.delete_kit()
    assert dialog.registry.names() == [] and dialog.current is None
    dialog.delete_kit()  # nothing left to delete


# ---- the reference ----------------------------------------------------------------------------
def test_the_reference_of_the_selected_resistor_is_shown_and_copied(dialog, app):
    assert dialog.selected_reference() is None  # nothing selected yet
    dialog.table.setCurrentCell(1, 0)
    ref = reference_text("PWR", "R22")
    assert ref == '{"kit": "PWR", "ref": "R22"}' and dialog.selected_reference() == ref
    assert ref in dialog.reference_label.text()
    dialog.copy_reference()
    assert app.clipboard().text() == ref and "Copied" in dialog.status.text()
    set_cell(dialog, 1, 0, "R22b")  # renamed in the table: the reference follows
    assert "R22b" in dialog.reference_label.text()
    dialog.table.setCurrentCell(-1, -1)
    assert dialog.reference_label.text() == ""


def test_the_main_window_has_the_menu_entry():
    from frontend.ui import main_window

    source = open(main_window.__file__, encoding="utf-8").read()
    assert 'CatalogTranslator("resistors", self.translator).t("res_menu")' in source
    assert "resistors_action.triggered.connect(self.open_resistor_kits_tool)" in source
