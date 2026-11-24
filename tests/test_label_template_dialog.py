# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The label template editor and its place in the label window, built offscreen."""

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("segno")

from frontend.ui.LabelDialog import LabelDialog  # noqa: E402
from frontend.ui.LabelTemplateDialog import LabelTemplateDialog  # noqa: E402
from ola.assets import Asset  # noqa: E402
from ola.label_templates import LabelTemplate, TemplateStore  # noqa: E402

pytestmark = pytest.mark.gui

CARD = Asset("DUT-0001", "converter", "Buck", "", {}, serial="S9", created="2026-11-24")


def test_the_editor_saves_a_valid_template_and_refuses_a_wrong_one(qtbot, tmp_path):
    store = TemplateStore(tmp_path / "t.json")
    dialog = LabelTemplateDialog(store, CARD)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("Mine")
    dialog.lines_edit.setPlainText("{id}\nS/N {serial}\n{nope}")
    assert "nope" in dialog.message.text()  # said while typing
    assert dialog.save() is False and store.names() == []
    dialog.lines_edit.setPlainText("{id}\nS/N {serial}")
    assert dialog.save() is True
    assert store.names() == ["Mine"] and list(store.get("Mine").lines) == ["{id}", "S/N {serial}"]
    assert dialog.list.count() == 1
    assert dialog.preview.drawing is not None


def test_new_copies_the_selected_format_and_delete_asks(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    store = TemplateStore(tmp_path / "t.json")
    dialog = LabelTemplateDialog(store, CARD, start_from="50x25")
    qtbot.addWidget(dialog)
    dialog.new_template()
    assert store.names() == ["50x25 copy"] and dialog.name_edit.text() == "50x25 copy"
    assert dialog.width_box.value() == 50.0 and "{id}" in dialog.lines_edit.toPlainText()
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    dialog.delete_template()
    assert store.names() == ["50x25 copy"]
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    dialog.delete_template()
    assert store.names() == []


def test_a_template_is_a_format_of_the_label_window(qtbot, tmp_path):
    store = TemplateStore(tmp_path / "t.json")
    store.put(LabelTemplate("Bench", 60, 30, lines=("{id}", "Owner {owner}", "S/N {serial}")))
    window = LabelDialog([CARD], None, templates=store)
    qtbot.addWidget(window)
    index = window.format_box.findData("tpl:Bench")
    assert index >= 0
    window.format_box.setCurrentIndex(index)
    assert not any(box.isEnabled() for box in window.field_boxes.values())
    page = window.current()
    assert (page.width, page.height) == (60, 30)
    shown = [i.text for i in page.items if hasattr(i, "text")]
    assert "DUT-0001" in shown and "S/N S9" in shown
    assert not any("Owner" in t for t in shown)  # the card has no owner: the line is not printed
    window.qr_box.setChecked(False)  # the QR can still be switched off
    assert window.current() is not None
    window.format_box.setCurrentIndex(window.format_box.findData("single:50x25"))  # a built-in one
    assert all(box.isEnabled() for box in window.field_boxes.values())


def test_a_damaged_templates_file_does_not_break_the_label_window(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "t.json"
    path.write_text("{broken")
    monkeypatch.setenv("OLA_LABEL_TEMPLATES", str(path))
    window = LabelDialog([CARD], None)
    qtbot.addWidget(window)
    assert window.templates is None and window.templates_error
    assert not window.templates_btn.isEnabled() and window.current() is not None
    assert path.read_text() == "{broken"  # left alone
