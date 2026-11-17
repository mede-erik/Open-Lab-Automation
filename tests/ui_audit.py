# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Find what is cut in a window that is shown: a text wider than its widget, a title of a table
column that does not fit, a widget of a table cell that is smaller than it asks. It measures with
the font of each widget, so it follows the theme, the language and the display scale."""

from typing import List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QWidget,
)

BUTTON_MARGIN = 16  # the padding of a button, a check box or a radio button
COMBO_MARGIN = 40  # the padding and the arrow of a combo box
TITLE_MARGIN = 14  # the padding of a title in the header of a table


def _shown(widget: QWidget) -> bool:
    return widget.isVisibleTo(widget.window()) and widget.width() > 4 and widget.height() > 4


def audit(root: QWidget) -> List[str]:
    """The problems found in ``root`` and its children, as readable lines (empty if none)."""
    issues: List[str] = []

    def add(kind: str, widget: QWidget, text: str, need: int, have: int) -> None:
        name = widget.objectName() or type(widget).__name__
        issues.append(f"{kind}: {name} {text[:40]!r} needs {need}px, has {have}px")

    for widget in root.findChildren(QWidget):
        if not _shown(widget):
            continue
        metrics = widget.fontMetrics()
        if isinstance(widget, QLabel):
            plain = widget.textFormat() != Qt.TextFormat.RichText
            if widget.text() and plain and not widget.wordWrap() and widget.pixmap().isNull():
                need = max(metrics.horizontalAdvance(line) for line in widget.text().split("\n"))
                need += 2 * widget.margin()
                if need > widget.width() + 1:
                    add("label cut", widget, widget.text(), need, widget.width())
        elif isinstance(widget, (QPushButton, QCheckBox, QRadioButton)) and widget.text():
            need = metrics.horizontalAdvance(widget.text().replace("&", "")) + BUTTON_MARGIN
            if need > widget.width() + 1:
                add("button cut", widget, widget.text(), need, widget.width())
        elif isinstance(widget, QGroupBox) and widget.title():
            need = metrics.horizontalAdvance(widget.title()) + 40
            if need > widget.width():
                add("group title cut", widget, widget.title(), need, widget.width())
        elif isinstance(widget, QComboBox) and widget.currentText():
            need = metrics.horizontalAdvance(widget.currentText()) + COMBO_MARGIN
            if need > widget.width() + 1:
                add("combo text cut", widget, widget.currentText(), need, widget.width())
        elif isinstance(widget, QHeaderView) and widget.orientation() == Qt.Orientation.Horizontal:
            model = widget.model()
            for section in range(widget.count() if model is not None else 0):
                if widget.isSectionHidden(section):
                    continue
                text = str(model.headerData(section, Qt.Orientation.Horizontal) or "")
                need = metrics.horizontalAdvance(text) + TITLE_MARGIN
                if text and need > widget.sectionSize(section) + 1:
                    add("header cut", widget, text, need, widget.sectionSize(section))

    for table in root.findChildren(QTableWidget):
        if not _shown(table):
            continue
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                cell = table.cellWidget(row, column)
                if cell is None or not cell.isVisible():
                    continue
                if cell.height() < min(cell.sizeHint().height(), table.rowHeight(row)) - 2:
                    add("cell widget short", cell, type(cell).__name__, cell.sizeHint().height(),
                        cell.height())
                if cell.width() < 24 and table.columnWidth(column) >= 24:
                    add("cell widget narrow", cell, type(cell).__name__, 24, cell.width())
    return issues
