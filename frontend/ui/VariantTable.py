# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The variant of a DUT as a table (name, value), and the question asked when a run starts.

``VariantTable`` is the widget: one row per named value (``R100`` / ``100 ohm``, ``fan`` / ``on``),
with buttons to add and remove rows; the name box suggests the names used before. It is used in
the editors of the measurements and in ``VariantDialog``, which is shown when a measurement that
names a DUT starts: it proposes the variant of the last run of that DUT, and its answer is the
variant of this run only (the file of the measurement is not changed). Strings:
``frontend/lang/modules/variants/<lang>.json``. The logic is in ``ola.variants``.
"""

from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.efficiency_widgets import text_color
from frontend.ui.module_translator import CatalogTranslator
from ola.variants import problem


class VariantTable(QWidget):
    """A table of names and values; ``changed`` is emitted after every edit."""

    changed = pyqtSignal()

    def __init__(
        self,
        t: Callable[..., str],
        names: Sequence[str] = (),
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._t = t
        self._names = list(names)
        self._busy = False
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([t("var_name"), t("var_value")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMaximumHeight(160)
        self.table.itemChanged.connect(lambda _item: self._edited())
        add = QPushButton(t("var_add"))
        add.clicked.connect(lambda: self.add_row())
        remove = QPushButton(t("var_remove"))
        remove.clicked.connect(self.remove_selected)
        self.suggest = QComboBox()  # the names used before: choose one to add it as a new row
        self.suggest.setEditable(False)
        self.suggest.activated.connect(self._suggested)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(self.suggest)
        row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(row)
        self.set_names(names)

    # ---- the names ---------------------------------------------------------------------------
    def set_names(self, names: Sequence[str]) -> None:
        """The names to suggest (those of the earlier runs of the DUT)."""
        self._names = list(names)
        self.suggest.blockSignals(True)
        self.suggest.clear()
        self.suggest.addItem(self._t("var_suggest"), None)
        for name in self._names:
            self.suggest.addItem(name, name)
        self.suggest.blockSignals(False)
        self.suggest.setVisible(bool(self._names))

    def _suggested(self, index: int) -> None:
        name = self.suggest.itemData(index)
        if name:
            if name not in self.variant():
                self.add_row(name)
            self.suggest.setCurrentIndex(0)

    # ---- the value ---------------------------------------------------------------------------
    def variant(self) -> Dict[str, str]:
        """The rows as ``{name: value}`` (rows without a name are left out, the last of two rows
        with the same name wins)."""
        out: Dict[str, str] = {}
        for row in range(self.table.rowCount()):
            name = self._text(row, 0)
            if name:
                out[name] = self._text(row, 1)
        return out

    def set_variant(self, variant: Optional[Mapping[str, Any]]) -> None:
        """Show a variant; does not emit ``changed``."""
        self._busy = True
        items = list((variant or {}).items())
        self.table.setRowCount(len(items))
        for row, (name, value) in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(str(name)))
            self.table.setItem(row, 1, QTableWidgetItem(str(value)))
        self._busy = False

    def problem(self) -> Optional[str]:
        """What is wrong with the table (a sentence), or None: two rows with one name, or a row
        with a value and no name."""
        seen = set()
        for row in range(self.table.rowCount()):
            name, value = self._text(row, 0), self._text(row, 1)
            if not name and value:
                return self._t("var_no_name", row=str(row + 1))
            if name in seen:
                return self._t("var_twice", name=name)
            seen.add(name)
        return problem(self.variant())

    def add_row(self, name: str = "", value: str = "") -> None:
        """A new row at the end, ready to type in."""
        row = self.table.rowCount()
        self._busy = True
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(value))
        self._busy = False
        self.table.setCurrentCell(row, 1 if name else 0)
        self.table.editItem(self.table.item(row, 1 if name else 0))
        self._edited()

    def remove_selected(self) -> None:
        """Remove the selected rows."""
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self._edited()

    def _text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item is not None else ""

    def _edited(self) -> None:
        if not self._busy:
            self.changed.emit()


class VariantDialog(QDialog):
    """The question of the start of a run: the variant of the DUT for this run."""

    def __init__(self, question: Mapping[str, Any], translator: Any = None, parent=None):
        """``question`` is what ``ProjectSession.variant_question`` gives."""
        super().__init__(parent)
        self._t = CatalogTranslator("variants", translator).t
        self.setWindowTitle(self._t("var_title"))
        self.resize(520, 380)
        layout = QVBoxLayout(self)
        version = f", {question['version']}" if question.get("version") else ""
        head = QLabel(self._t("var_question", dut=question["dut"], version=version))
        head.setWordWrap(True)
        layout.addWidget(head)
        self.table = VariantTable(self._t, question.get("names") or [])
        self.table.set_variant(question.get("last"))
        self.table.changed.connect(self._check)
        layout.addWidget(self.table)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self._t("var_start"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._check()

    def _check(self) -> None:
        text = self.table.problem()
        color = text_color("error", self.message)  # readable on a light and on a dark theme
        self.message.setText(f"<span style='color:{color}'>{text}</span>" if text else "")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(text is None)

    def variant(self) -> Dict[str, str]:
        """The variant for this run (empty: none)."""
        return self.table.variant()
