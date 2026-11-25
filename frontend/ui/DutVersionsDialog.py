# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The versions of a device under test: list them, add one, retire one or bring it back.

A version is free text (``rev A``, ``RFB``, ``V01``): it is written the way it is used in the lab.
The same text twice is refused. A version that is retired stays in the list and in its old results,
it is just no longer the current one (the last version that is not retired). Strings:
``frontend/lang/modules/duts/<lang>.json``.
"""

from typing import Any, List, Optional

from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.efficiency_widgets import text_color
from frontend.ui.module_translator import CatalogTranslator, ChainedTranslator
from ola.assets import AssetError
from ola.duts import DutRegistry


class DutVersionsDialog(QDialog):
    """The versions of the DUT with this code (see the module docstring)."""

    def __init__(
        self,
        registry: DutRegistry,
        translator: Any = None,
        code: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.tr_ = ChainedTranslator(
            CatalogTranslator("duts", translator), CatalogTranslator("assets", translator)
        )
        self._t = self.tr_.t
        self.registry, self.code = registry, code
        card = registry.get(code)
        self.setWindowTitle(
            self._t("dutv_title", code=card.id if card else code, name=card.name if card else "")
        )
        self.resize(560, 420)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        columns = ("version", "date", "note", "status")
        self.table.setHorizontalHeaderLabels([self._t(f"dutv_col_{c}") for c in columns])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        root.addWidget(self.table, 1)
        add = QHBoxLayout()
        self.label_edit, self.note_edit = QLineEdit(), QLineEdit()
        self.label_edit.setPlaceholderText(self._t("dut_version_hint"))
        self.note_edit.setPlaceholderText(self._t("dutv_note"))
        self.label_edit.returnPressed.connect(self.add_version)
        self.note_edit.returnPressed.connect(self.add_version)
        self.add_button = QPushButton(self._t("dutv_add"))
        self.add_button.clicked.connect(self.add_version)
        add.addWidget(self.label_edit, 1)
        add.addWidget(self.note_edit, 2)
        add.addWidget(self.add_button)
        root.addLayout(add)
        self.message = QLabel()
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        row = QHBoxLayout()
        self.retire_button = QPushButton(self._t("dutv_retire"))
        self.retire_button.clicked.connect(self.toggle_retired)
        close = QPushButton(self._t("dutv_close"))
        close.clicked.connect(self.accept)
        row.addWidget(self.retire_button)
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

    def _versions(self) -> List[dict]:
        card = self.registry.get(self.code)
        return list(card.versions) if card is not None else []  # type: ignore[attr-defined]

    def refresh(self) -> None:
        """Read the versions again and redraw the table."""
        versions = self._versions()
        current = self.registry.current_version(self.code) if versions else None
        self.table.setRowCount(len(versions))
        for row, version in enumerate(versions):
            if version["retired"]:
                status = self._t("ast_retired")
            else:
                status = self._t("dutv_current") if version["label"] == current else ""
            cells = (version["label"], version["date"], version["note"], status)
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if version["retired"]:
                    item.setForeground(QBrush(QColor(text_color("muted", self))))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()
        self._update_buttons()

    def selected_label(self) -> Optional[str]:
        """The version that is selected in the table, or None."""
        rows = sorted({i.row() for i in self.table.selectedItems()})
        versions = self._versions()
        return versions[rows[0]]["label"] if rows and rows[0] < len(versions) else None

    def _update_buttons(self) -> None:
        label = self.selected_label()
        self.retire_button.setEnabled(label is not None)
        retired = any(v["retired"] for v in self._versions() if v["label"] == label)
        self.retire_button.setText(self._t("dutv_reactivate" if retired else "dutv_retire"))

    def add_version(self) -> None:
        """Add the version typed in the box; the reason is shown if it cannot be added."""
        try:
            self.registry.add_version(self.code, self.label_edit.text(), self.note_edit.text())
        except (AssetError, OSError) as exc:
            self.message.setText(str(exc))
            return
        self.message.setText("")
        self.label_edit.clear()
        self.note_edit.clear()
        self.refresh()

    def toggle_retired(self) -> None:
        """Retire the selected version, or bring it back if it is retired."""
        label = self.selected_label()
        if label is None:
            return
        retired = any(v["retired"] for v in self._versions() if v["label"] == label)
        try:
            self.registry.retire_version(self.code, label, retired=not retired)
        except (AssetError, OSError) as exc:
            self.message.setText(str(exc))
            return
        self.message.setText("")
        self.refresh()
