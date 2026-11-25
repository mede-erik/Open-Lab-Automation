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


# ---- rotation, QR left out, guidance, export --------------------------------------------------
def test_a_text_can_be_rotated_in_the_tool_and_the_whole_design_too(tool, store):
    tool.manual_radio.setChecked(True)
    tool.element_list.setCurrentRow(1)
    assert tool.rotation_box.isEnabled()
    tool.rotation_box.setCurrentIndex(tool.rotation_box.findData(90))
    assert tool.draft().elements[1].rotation == 90
    assert any(getattr(i, "rotation", 0) == 90 for i in tool.preview.drawing.items)
    tool.element_list.setCurrentRow(0)  # the QR code
    assert not tool.rotation_box.isEnabled()  # a QR code does not turn
    assert tool.save() is True
    assert TemplateStore(store.path).design("cable").elements[1].rotation == 90
    tool.auto_radio.setChecked(True)  # automatic again: the whole label can be written turned
    tool.height_box.setValue(60)
    tool.width_box.setValue(14)
    tool.rotate_box.setCurrentIndex(tool.rotate_box.findData(90))
    assert tool.draft().rotate == 90
    assert all(
        getattr(i, "rotation", 0) == 90 for i in tool.preview.drawing.items if hasattr(i, "text")
    )
    assert tool.save() is True and TemplateStore(store.path).design("cable").rotate == 90


def test_the_tool_guides_a_small_label(tool):
    assert "QR code fits" in tool.advice.text()
    tool.width_box.setValue(56)
    tool.height_box.setValue(30)
    tool.layout_box.setCurrentIndex(tool.layout_box.findData("cable_flag"))
    tool.diameter_box.setValue(4)
    text = tool.advice.text()
    assert "does not fit and is left out" in text and "at least" in text
    assert not any(hasattr(i, "matrix") for i in tool.preview.drawing.items)
    tool.qr_auto_box.setChecked(False)  # print it anyway: a warning instead
    assert any(hasattr(i, "matrix") for i in tool.preview.drawing.items)
    tool.qr_auto_box.setChecked(True)
    tool.diameter_box.setValue(0.5)  # a thinner cable leaves a bigger face: the QR code comes back
    assert any(hasattr(i, "matrix") for i in tool.preview.drawing.items)
    assert "QR code fits" in tool.advice.text()
    tool.save()
    assert tool.store.setup.qr_auto is True


def test_the_label_window_saves_every_label_as_a_file_and_the_chosen_dpi(qtbot, store, tmp_path):
    window = LabelDialog([sample_asset("cable"), sample_asset("attenuator")], None, templates=store)
    qtbot.addWidget(window)
    window.dpi_box.setCurrentIndex(window.dpi_box.findData(203))
    assert window.dpi() == 203
    svgs = window.write_each(str(tmp_path / "svg"), "svg")
    assert [p.rsplit("/", 1)[-1] for p in svgs] == ["CAB-0042.svg", "ATT-0042.svg"]
    assert 'width="50mm" height="25mm"' in open(svgs[0], encoding="utf-8").read()
    pngs = window.write_each(str(tmp_path / "png"), "png")
    from PyQt6.QtGui import QImage

    image = QImage(pngs[1])
    assert (image.width(), image.height()) == (round(50 / 25.4 * 203), round(25 / 25.4 * 203))
    assert round(image.dotsPerMeterX() * 0.0254) == 203  # the real size is in the file
    sheet = window.format_box.findData("sheet:A4 3x8 (70x37)")
    window.format_box.setCurrentIndex(sheet)
    assert window.file_names("svg") == ["page-1.svg"]
    window.dpi_box.setCurrentIndex(window.dpi_box.findData(300))
    window.format_box.setCurrentIndex(0)
    assert window.each_btn.isEnabled()


def test_the_label_window_shows_what_the_layout_decided(qtbot, store):
    from ola.label_design import LabelSetup

    store.set_setup(LabelSetup(width_mm=20, height_mm=10))
    window = LabelDialog([sample_asset("cable")], None, templates=store)
    qtbot.addWidget(window)
    assert "left out" in window.message.text()


def test_with_the_real_font_no_label_has_overlapping_text(qapp):
    """The same regression sweep with the real font of the system (what the preview and the PDF
    use), not the estimate: the widths differ from font to font."""
    from frontend.ui.label_paint import text_measure
    from ola.label_design import (
        LabelSetup,
        build_kind_drawing,
        default_design,
        setup_problems,
    )

    sizes = [(50, 25), (62, 29), (30, 15), (20, 10), (56, 30), (100, 29), (12, 40)]
    checked = 0
    for kind in KINDS:
        card = sample_asset(kind)
        for width, height in sizes:
            for layout in ("single", "cable_flag"):
                for rotate in (0, 90):
                    setup = LabelSetup(width_mm=width, height_mm=height, layout=layout,
                                       cable_diameter_mm=4)  # fmt: skip
                    if setup_problems(setup):
                        continue
                    design = default_design(kind)
                    design.rotate = rotate
                    drawing = build_kind_drawing(setup, design, card, "", text_measure)
                    checked += 1
                    bad = [w for w in drawing.warnings if "overlaps" in w or "outside" in w]
                    assert not bad, (kind, width, height, layout, rotate, bad)
    assert checked > 100


def test_the_tool_warns_when_two_texts_overlap_or_leave_the_label(tool):
    tool.manual_radio.setChecked(True)
    assert "overlaps" not in tool.message.text() and "outside" not in tool.message.text()
    tool.element_list.setCurrentRow(2)  # the name
    tool.x_box.setValue(tool.draft().elements[1].x)  # over the code
    tool.y_box.setValue(tool.draft().elements[1].y + 1)
    assert "overlaps" in tool.message.text()
    tool.x_box.setValue(48)  # off the right edge
    assert "outside the label" in tool.message.text()
    tool.rotation_box.setCurrentIndex(tool.rotation_box.findData(90))
    assert tool.message.text()  # still checked when the text is on its side
