# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The list of the files of the project, in the sidebar of the main window.

A plain ``QListWidget`` (the files are its items, their text is the file name) with one addition: an
item of a measurement that has runs shows a **small arrow** at its right (``RUNS_ROLE``: ``False``
closed, ``True`` open); clicking the arrow emits ``arrow_clicked(item)`` and the main window adds
(or removes) under the item one row for each run, with the name of its file. Those rows are marked
with ``RUN_ROLE`` (the path of the run file) and can be opened or deleted.
"""

from typing import Optional

from PyQt6.QtCore import QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPainter, QPolygonF
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate

RUNS_ROLE = Qt.ItemDataRole.UserRole + 1  # a measurement with runs: False closed, True open
RUN_ROLE = Qt.ItemDataRole.UserRole + 2  # a row of a run: the path of its file
ARROW_SIZE = 14


def arrow_rect(row: QRect) -> QRect:
    """Where the arrow is in the row of an item (at its right, centred vertically)."""
    top = row.top() + (row.height() - ARROW_SIZE) // 2
    return QRect(row.right() - ARROW_SIZE - 4, top, ARROW_SIZE, ARROW_SIZE)


class FileDelegate(QStyledItemDelegate):
    """Draws the item as usual and the arrow of a measurement that has runs."""

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        opened = index.data(RUNS_ROLE)
        if opened is None:
            return
        box = arrow_rect(option.rect)
        c = QPointF(box.center())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(option.palette.text())
        if opened:  # pointing down: the runs are listed under the file
            points = [QPointF(c.x() - 4, c.y() - 2), QPointF(c.x() + 4, c.y() - 2),
                      QPointF(c.x(), c.y() + 3)]  # fmt: skip
        else:  # pointing right
            points = [QPointF(c.x() - 2, c.y() - 4), QPointF(c.x() - 2, c.y() + 4),
                      QPointF(c.x() + 3, c.y())]  # fmt: skip
        painter.drawPolygon(QPolygonF(points))
        painter.restore()


class ProjectFilesList(QListWidget):
    """The list of the files (see the module docstring)."""

    arrow_clicked = pyqtSignal(QListWidgetItem)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(FileDelegate(self))

    def arrow_at(self, pos) -> Optional[QListWidgetItem]:
        """The item whose arrow is at this point of the list, or None."""
        item = self.itemAt(pos)
        if item is not None and item.data(RUNS_ROLE) is not None:
            if arrow_rect(self.visualItemRect(item)).contains(pos):
                return item
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt name)
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.arrow_at(event.position().toPoint())
            if item is not None:
                self.arrow_clicked.emit(item)
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt name)
        if self.arrow_at(event.position().toPoint()) is not None:
            return  # a double click on the arrow is two clicks on it, not "edit the file"
        super().mouseDoubleClickEvent(event)
