# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The window that lets you use a project received from someone else with your own instruments.

The measurements of the project name the instruments of the sender; this window lists the names that
are not in your instrument file and, for each, offers your instruments of the same category (marked
with what they would have less than the one the measurement was made with, or that they cannot do
the sweep). *Apply* names the chosen instruments in the measurements; runs already made are not
touched. Layout only: the logic is ``ola.role_mapping``.
"""

from typing import Any, Callable, Dict, Optional

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.core.Translator import Translator
from ola import role_mapping
from ola.project_rename import RenameError

COLUMNS = ("roles_col_missing", "roles_col_used_by", "roles_col_category", "roles_col_instead")


class RolesDialog(QDialog):
    """Choose, for each instrument the measurements name and you do not have, one of yours."""

    def __init__(
        self,
        session: Any,
        characteristics_of: Optional[Callable[[str], Dict[str, float]]] = None,
        abilities_of: Optional[Callable[[str], Dict[str, Any]]] = None,
        translator: Optional[Any] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.t = (translator or Translator()).t
        self.session = session
        self.characteristics_of = characteristics_of or (lambda name: {})
        self.abilities_of = abilities_of
        self.gaps = role_mapping.find_gaps(session)
        self.setWindowTitle(self.t("roles_title"))
        self.resize(820, 340)
        layout = QVBoxLayout(self)
        intro = QLabel(self.t("roles_intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.table = QTableWidget(len(self.gaps), len(COLUMNS))
        self.table.setHorizontalHeaderLabels([self.t(c) for c in COLUMNS])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.combos: Dict[str, QComboBox] = {}
        for row, gap in enumerate(self.gaps):
            category = self.t(gap.category) if gap.category != "any" else "-"
            for column, text in enumerate((gap.name, ", ".join(gap.measurements), category)):
                self.table.setItem(row, column, QTableWidgetItem(text))
            combo = self._combo(gap)
            self.combos[gap.name] = combo
            self.table.setCellWidget(row, 3, combo)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.apply_button = QPushButton(self.t("roles_apply"))
        self.apply_button.clicked.connect(self.apply)
        later = QPushButton(self.t("roles_later"))
        later.clicked.connect(self.reject)
        row.addWidget(self.apply_button)
        row.addWidget(later)
        layout.addLayout(row)

    def _combo(self, gap: "role_mapping.Gap") -> QComboBox:
        combo = QComboBox()
        combo.addItem(self.t("roles_leave"), None)
        for name in role_mapping.candidates_for(self.session, gap):
            try:
                found = role_mapping.preview(
                    self.session, gap, name, self.characteristics_of, self.abilities_of
                )
            except Exception:  # a preview is a help: the instrument can still be chosen
                found = []
            if any(f.blocking for f in found):
                text = self.t("roles_blocked").format(name=name)
            elif found:
                text = self.t("roles_differences").format(name=name, n=len(found))
            else:
                text = name
            combo.addItem(text, name)
        if combo.count() == 1:
            combo.setItemText(0, self.t("roles_none"))
        return combo

    def chosen(self) -> Dict[str, Optional[str]]:
        """What is selected: ``{name in the measurements: your instrument or None}``."""
        return {name: combo.currentData() for name, combo in self.combos.items()}

    def apply(self) -> None:
        """Name the chosen instruments in the measurements."""
        for old, new in self.chosen().items():
            if not new:
                continue
            try:
                role_mapping.map_instrument(self.session, old, new)
            except RenameError as exc:
                QMessageBox.warning(
                    self, self.t("roles_title"), self.t("roles_failed").format(error=exc)
                )
                return
        self.accept()
