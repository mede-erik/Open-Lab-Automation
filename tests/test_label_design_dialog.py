# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The label design tool and the 'by type' format of the label window, built offscreen."""

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("segno")
from PyQt6.QtCore import QPointF, Qt  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from frontend.ui.LabelDesignDialog import LabelDesignDialog  # noqa: E402
from frontend.ui.LabelDialog import LabelDialog  # noqa: E402
from ola.label_design import DEFAULT_LINES, KINDS, sample_asset  # noqa: E402
from ola.label_templates import TemplateStore  # noqa: E402
from ola.labels import QR, Text  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture
def store(tmp_path):
    return TemplateStore(tmp_path / "t.json")


@pytest.fixture
def tool(qtbot, store):
    dialog = LabelDesignDialog(store)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def pick_kind(tool, kind):
    tool.kind_box.setCurrentIndex(tool.kind_box.findData(kind))


def test_the_tool_opens_on_the_ready_made_design(tool):
    assert tool.kind == "cable" and tool.kind_box.count() == len(KINDS)
    assert tool.lines_edit.toPlainText().splitlines() == list(DEFAULT_LINES["cable"])
    assert tool.preview.drawing is not None and tool.auto_radio.isChecked()
    assert (tool.width_box.value(), tool.height_box.value()) == (50.0, 25.0)


def test_the_size_and_the_changed_kinds_are_saved_the_others_are_not(tool, store):
    tool.width_box.setValue(62)
    tool.height_box.setValue(29)
    pick_kind(tool, "attenuator")
    tool.lines_edit.setPlainText("{id}\nAtt {nominal_db}\n{max_frequency}")
    pick_kind(tool, "cable")  # the unsaved change of the attenuator survives a change of kind
    pick_kind(tool, "attenuator")
    assert "Att {nominal_db}" in tool.lines_edit.toPlainText()
    assert tool.save() is True
    assert store.setup.width_mm == 62 and store.is_customised("attenuator")
    assert not store.is_customised("cable")  # looked at, not changed
    assert tool.preview.drawing.width == 62
    shown = [i.text for i in tool.preview.drawing.items if isinstance(i, Text)]
    assert "Att 10 dB" in shown and "6 GHz" in shown


def test_a_design_without_the_code_is_not_saved_and_says_why(tool, store):
    tool.lines_edit.setPlainText("{name}")
    assert "code" in tool.message.text()
    assert tool.save() is False and not store.designs
    assert tool.message.text()


def test_manual_starts_from_the_automatic_layout_and_elements_can_be_edited(tool, store):
    tool.manual_radio.setChecked(True)
    elements = tool.draft().elements
    assert elements and elements[0].type == "qr" and tool.element_list.count() == len(elements)
    assert tool.preview.editable
    tool.element_list.setCurrentRow(1)
    assert tool.text_edit.text() == "{id}"
    tool.x_box.setValue(30)
    tool.size_box.setValue(5)
    assert (elements[1].x, elements[1].size) == (30, 5)
    tool.text_edit.setText("{id} {kind}")
    assert tool.element_list.item(1).text() == "2. {id} {kind}"
    tool.add_element("text")
    assert len(tool.draft().elements) == len(elements) and tool.current_index() == len(elements) - 1
    before = len(elements)
    tool.remove_element()
    assert len(tool.draft().elements) == before - 1
    tool.add_element("qr")  # one QR code only
    tool.add_element("qr")
    assert sum(e.type == "qr" for e in tool.draft().elements) == 1
    assert tool.save() is True
    assert TemplateStore(store.path).design("cable").manual


def test_an_element_is_picked_and_moved_with_the_mouse(qtbot, tool):
    tool.manual_radio.setChecked(True)
    preview = tool.preview
    preview.repaint()  # the scale of the preview is known after a paint
    scale, dx, dy = preview.scale_dx_dy
    element = tool.draft().elements[1]
    x, y, w, h = element.box()
    start = QPointF(dx + (x + w / 2) * scale, dy + (y + h / 2) * scale)

    def mouse(kind, point):
        return QMouseEvent(
            kind, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )  # fmt: skip

    preview.mousePressEvent(mouse(QMouseEvent.Type.MouseButtonPress, start))
    assert tool.current_index() == 1
    preview.mouseMoveEvent(
        mouse(QMouseEvent.Type.MouseMove, QPointF(start.x() + 5 * scale, start.y() + 2 * scale))
    )
    preview.mouseReleaseEvent(mouse(QMouseEvent.Type.MouseButtonRelease, start))
    assert element.x == pytest.approx(x + 5, abs=0.2) and element.y == pytest.approx(y + 2, abs=0.2)
    assert tool.x_box.value() == pytest.approx(element.x, abs=0.1)  # the numbers follow


def test_a_flag_is_always_automatic(tool):
    tool.manual_radio.setChecked(True)
    tool.layout_box.setCurrentIndex(tool.layout_box.findData("flag"))
    assert not tool.manual_radio.isEnabled()
    assert not tool.preview.editable


def test_back_to_the_ready_made_design_asks_first(tool, store, monkeypatch):
    tool.lines_edit.setPlainText("{id}\nmine")
    assert tool.save() and store.is_customised("cable")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    tool.reset_kind()
    assert store.is_customised("cable")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    tool.reset_kind()
    assert not store.is_customised("cable")
    assert tool.lines_edit.toPlainText().splitlines() == list(DEFAULT_LINES["cable"])


def test_the_label_window_draws_each_card_with_the_design_of_its_kind(qtbot, store):
    store.set_setup(store.setup.__class__(width_mm=60, height_mm=30))
    window = LabelDialog([sample_asset("cable"), sample_asset("attenuator")], None, templates=store)
    qtbot.addWidget(window)
    assert window.format_box.currentData() == "kind:" and len(window.pages) == 2
    assert all((p.width, p.height) == (60, 30) for p in window.pages)
    cable = [i.text for i in window.pages[0].items if isinstance(i, Text)]
    att = [i.text for i in window.pages[1].items if isinstance(i, Text)]
    assert cable[2] == "SMA - SMA 1 m" and att[2] == "10 dB, 6 GHz, 2 W"  # not the same lines
    assert all(not box.isEnabled() for box in window.field_boxes.values())  # lines: the design's
    window.qr_box.setChecked(False)  # for this printing only
    assert not any(isinstance(i, QR) for i in window.pages[0].items)
    assert store.setup.qr is True


def test_boxes_and_lines_are_added_edited_and_drawn(tool, store):
    from ola.labels import Box, Line

    tool.manual_radio.setChecked(True)
    tool.add_element("box")
    box = tool.draft().elements[-1]
    assert box.type == "box" and tool.element_form.isEnabled()
    assert tool.h_box.isEnabled() and tool.stroke_box.isEnabled() and not tool.text_edit.isEnabled()
    tool.stroke_box.setValue(0.6)
    tool.dashed_box.setChecked(True)
    tool.h_box.setValue(20)
    assert (box.stroke, box.dashed, box.h) == (0.6, True, 20)
    tool.add_element("line")
    line = tool.draft().elements[-1]
    assert (
        line.type == "line"
        and line.h == 0
        and tool.element_list.item(tool.current_index()).text().endswith("Line")
    )
    shapes = [i for i in tool.preview.drawing.items if isinstance(i, (Box, Line))]
    assert any(isinstance(i, Box) and i.stroke == 0.6 and i.dashed for i in shapes)
    assert tool.save() is True
    assert [e.type for e in TemplateStore(store.path).design("cable").elements][-2:] == [
        "box",
        "line",
    ]


def test_the_cable_flag_asks_for_the_diameter_and_says_how_it_is_split(tool):
    assert not tool.diameter_box.isVisibleTo(tool)
    tool.width_box.setValue(110)
    tool.layout_box.setCurrentIndex(tool.layout_box.findData("cable_flag"))
    assert tool.diameter_box.isVisibleTo(tool) and tool.cable_info.isVisibleTo(tool)
    tool.diameter_box.setValue(5)
    text = tool.cable_info.text()
    assert "15.7" not in text and "18.7" in text  # round the cable: pi x 5 + 3 overlap
    drawing = tool.preview.drawing
    assert (
        drawing.width == 110
        and sum(1 for i in drawing.items if hasattr(i, "dashed") and i.dashed) == 2
    )
    tool.diameter_box.setValue(40)  # too thick for this strip
    assert "at least" in tool.message.text() and tool.preview.drawing is None
    assert tool.save() is False  # nothing is saved


def test_on_a_cable_flag_the_elements_are_relative_to_a_face(tool, store):
    from ola.label_design import cable_flag_geometry

    tool.width_box.setValue(110)
    tool.layout_box.setCurrentIndex(tool.layout_box.findData("cable_flag"))
    tool.manual_radio.setChecked(True)
    face = cable_flag_geometry(tool.setup()).faces[0][0]
    assert tool.preview.editable and tool.preview.offset_x == pytest.approx(face)
    elements = tool.draft().elements
    assert elements[1].x < tool.setup().width_mm - face  # relative: small numbers
    tool._moved(1, 10.0, 4.0)
    assert (elements[1].x, elements[1].y) == (10.0, 4.0)
    assert tool.save() is True and store.setup.layout == "cable_flag"
