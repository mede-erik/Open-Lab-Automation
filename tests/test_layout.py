# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Layout checks: the themes are valid, and the windows are sized so that nothing is cut.

These are the problems found going through the windows one by one: a rule of the theme that is
not valid QSS (the widgets inside table cells collapsed), an editor squeezed by the buttons of its
list, a table with its own scroll bar inside a scroll area.
"""

import os
import re
import shutil

import pytest

from tests.conftest import LIBRARY_PATH, REPO

STYLES = os.path.join(REPO, "frontend", "assets", "styles")
ICONS = os.path.join(REPO, "frontend", "assets", "icons")
THEMES = sorted(f for f in os.listdir(STYLES) if f.endswith(".qss"))
EXAMPLE_INST = os.path.join(REPO, "examples", "test-dcdc-project", "test_instruments.inst")


@pytest.mark.parametrize("theme", THEMES)
def test_theme_has_no_invalid_size_rules(theme):
    """``max-width: none`` is not valid QSS: Qt reads it as a size, and a widget in a table cell
    shrank to a few pixels."""
    text = open(os.path.join(STYLES, theme), encoding="utf-8").read()
    assert not re.search(r"max-(width|height):\s*none", text)


@pytest.mark.parametrize("theme", THEMES)
def test_theme_icons_exist(theme):
    """Every ``@ICONS@/name`` of a theme is a file of frontend/assets/icons."""
    text = open(os.path.join(STYLES, theme), encoding="utf-8").read()
    for name in re.findall(r"@ICONS@/([\w.\-]+)", text):
        assert os.path.isfile(os.path.join(ICONS, name)), name


@pytest.mark.parametrize("theme", ["dark_theme.qss", "light_theme.qss"])
def test_theme_defines_the_style_classes_used_by_the_code(theme):
    """The classes the windows give to their labels and buttons are defined by the themes in use."""
    text = open(os.path.join(STYLES, theme), encoding="utf-8").read()
    for name in ("infobox", "accent", "muted", "error", "ok", "action", "widgetcells"):
        assert f'[class="{name}"]' in text, name


def _qt():
    pytest.importorskip("PyQt6.QtWidgets")
    pytest.importorskip("pytestqt")


@pytest.mark.gui
def test_clamp_to_screen_never_exceeds_the_screen(qtbot, monkeypatch):
    _qt()
    from PyQt6.QtCore import QSize
    from PyQt6.QtWidgets import QWidget
    from frontend.ui import layout_utils

    monkeypatch.setattr(layout_utils, "available_size", lambda widget: QSize(1000, 600))
    widget = QWidget()
    qtbot.addWidget(widget)
    size = layout_utils.clamp_to_screen(widget, QSize(1400, 900))
    assert size.width() <= 1000 and size.height() <= 600
    assert layout_utils.clamp_to_screen(widget, QSize(300, 200)) == QSize(300, 200)


@pytest.mark.gui
def test_table_of_widgets_has_no_scrollbar_of_its_own(qtbot):
    _qt()
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLineEdit, QSizePolicy, QTableWidget
    from frontend.ui.layout_utils import MIN_ROW_HEIGHT, fit_table_to_rows

    table = QTableWidget(5, 3)
    qtbot.addWidget(table)
    for row in range(5):
        for column in range(3):
            table.setCellWidget(row, column, QLineEdit("x"))
    fit_table_to_rows(table, fixed_columns=(0,))
    assert table.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert table.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed
    assert all(table.rowHeight(row) >= MIN_ROW_HEIGHT for row in range(5))
    assert table.property("class") == "widgetcells"


@pytest.mark.gui
@pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")
def test_inst_dialog_editor_is_not_squeezed(qtbot, tmp_path, monkeypatch):
    """The editor of the selected instrument has the room it asks for: the buttons above the list
    used to make the list 640 px wide and leave 240 px to the editor."""
    _qt()
    from PyQt6.QtCore import QSize, QSettings
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui import layout_utils
    from frontend.ui.InstrumentConfigDialog import InstrumentConfigDialog

    monkeypatch.setattr(layout_utils, "available_size", lambda widget: QSize(1366, 728))
    QSettings("LabAutomation", "App").clear()
    work = tmp_path / "instruments.inst"
    shutil.copy(EXAMPLE_INST, work)
    dialog = InstrumentConfigDialog(str(work), LoadInstruments())
    qtbot.addWidget(dialog)
    dialog.show()
    screen = QSize(1366, 728)
    for row in range(dialog.list_widget.count()):
        dialog.list_widget.setCurrentRow(row)
        dialog.fit_to_editor()  # (the dialog does it itself when the event loop runs)
        dialog.layout().activate()
        viewport = dialog.editor_scroll.viewport()
        assert viewport.width() >= dialog.editor_widget.minimumSizeHint().width(), row
        assert dialog.list_widget.width() < dialog.width() // 2, row
        assert dialog.width() <= screen.width() and dialog.height() <= screen.height()
