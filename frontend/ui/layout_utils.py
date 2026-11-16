# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Sizing helpers shared by the windows: size a window to its content, never beyond the screen.

At a display scale of 125% a Full HD monitor has only 1536x864 logical pixels, so a window with a
fixed size (``resize(1000, 700)``) can leave the screen. These helpers work in logical pixels, like
every other size in Qt.
"""

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractScrollArea,
    QHeaderView,
    QLayout,
    QLayoutItem,
    QSizePolicy,
    QTableWidget,
    QWidget,
)

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


class FlowLayout(QLayout):
    """A row of widgets that goes on a new line when the window is too narrow.

    A row of buttons in a fixed ``QHBoxLayout`` is as wide as all its buttons, so with a longer
    language (or a larger display scale) the buttons are cut or the window cannot be narrowed.
    """

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        """As large as the largest item (every item can be on a line of its own)."""
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _arrange(self, rect: QRect, apply: bool) -> int:
        """Place the items line by line; the height used (the items are moved only if ``apply``)."""
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, line_height = area.x(), area.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:  # no room: next line
                x = area.x()
                y += line_height + self.spacing()
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()
