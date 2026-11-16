# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Sizing helpers shared by the windows: size a window to its content, never beyond the screen.

At a display scale of 125% a Full HD monitor has only 1536x864 logical pixels, so a window with a
fixed size (``resize(1000, 700)``) can leave the screen. These helpers work in logical pixels, like
every other size in Qt.
"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QAbstractScrollArea, QHeaderView, QSizePolicy, QTableWidget, QWidget

from frontend.ui.theme_utils import set_class

# A window never takes more than this part of the usable area of the screen
SCREEN_FRACTION = 0.92
# A row of a table of widgets: enough for a line edit or a combo box with its border and padding
MIN_ROW_HEIGHT = 30


def available_size(widget: QWidget) -> QSize:
    """The usable area (without taskbar) of the screen the widget is on, in logical pixels."""
    screen = None
    handle = widget.windowHandle()
    if handle is not None:
        screen = handle.screen()
    if screen is None and widget.parentWidget() is not None:
        screen = widget.parentWidget().screen()
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return QSize(1280, 720)
    return screen.availableGeometry().size()


def clamp_to_screen(widget: QWidget, size: QSize) -> QSize:
    """``size`` made smaller, if needed, to stay inside the screen of the widget."""
    area = available_size(widget)
    return QSize(min(size.width(), int(area.width() * SCREEN_FRACTION)),
                 min(size.height(), int(area.height() * SCREEN_FRACTION)))


def resize_to_screen(widget: QWidget, width: int, height: int) -> None:
    """``resize(width, height)``, reduced to fit the screen."""
    widget.resize(clamp_to_screen(widget, QSize(width, height)))


def grow_to_fit(widget: QWidget) -> None:
    """Make the window large enough for its content (the size hint), without shrinking it and
    without leaving the screen. A content bigger than the screen scrolls instead."""
    hint = widget.sizeHint()
    size = clamp_to_screen(widget, QSize(max(widget.width(), hint.width()),
                                         max(widget.height(), hint.height())))
    if size != widget.size():
        widget.resize(size)


def fit_table_to_rows(table: QTableWidget, fixed_columns=(0,), min_column_width=80) -> None:
    """Lay out a table whose cells hold widgets (line edits, combo boxes).

    * the columns in ``fixed_columns`` are as wide as their content, the others share the width;
    * the table is as tall as its rows, so it has no scroll bar of its own: the window or the
      scroll area around it scrolls instead (two nested scroll bars are hard to use);
    * a minimum width keeps the cells readable, the window grows to it (see ``grow_to_fit``).
    """
    header = table.horizontalHeader()
    header.setMinimumSectionSize(min_column_width // 2)
    columns = table.columnCount()
    for column in range(columns):
        mode = (QHeaderView.ResizeMode.ResizeToContents if column in fixed_columns
                else QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(column, mode)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    # the widgets fill their cells: no padding around them (see ``widgetcells`` in the themes)
    set_class(table, "widgetcells")
    table.resizeRowsToContents()
    for row in range(table.rowCount()):
        table.setRowHeight(row, max(table.rowHeight(row), MIN_ROW_HEIGHT))
    # as tall as the rows (Qt knows the real height of the header once the theme is applied)
    table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    table.setMinimumWidth(columns * min_column_width + table.verticalHeader().sizeHint().width())
