# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Kits of resistors (menu *Tools* > *Resistor kits...*).

The power resistors of a bench are used in many measurements, so they are kept once, in a kit, like
a cable in the registry: a name, the value, the tolerance and the power rating of each, and the
relay of the multiplexer that connects it, if it is always wired to the same one. A thin layer over
``ola.resistor_kits`` (which does the work and is tested without a screen):

* the list of kits, with **New kit**, **Rename** and **Delete**;
* the resistors of the selected kit in a table you edit (a value can be typed as ``4.7k``);
* **Save** writes the file; a value that is not a number or not allowed is said and nothing is
  written;
* **Copy the reference** puts ``{"kit": "PWR", "ref": "R22"}`` for the selected resistor on the
  clipboard, to paste into the ``loads`` of a measurement.

Strings: ``frontend/lang/modules/resistors/<lang>.json``.
"""

import json
import sys
from typing import Any, List, Optional, Sequence

from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.module_translator import CatalogTranslator
from ola.resistor_kits import Kit, KitError, KitRegistry, KitResistor
from ola.run_view import parse_si

COLUMNS = ("name", "value", "tol", "power", "relay", "note")


def reference_text(kit: str, resistor: str) -> str:
    """What to write in a load to use that resistor: ``{"kit": "PWR", "ref": "R22"}``."""
    return json.dumps({"kit": kit, "ref": resistor})


class ResistorKitsDialog(QDialog):
    """The window of the kits of resistors (see the module docstring)."""

    def __init__(
        self,
        registry: Optional[KitRegistry] = None,
        translator: Any = None,
        parent: Optional[QWidget] = None,
    ):
        """``registry``: the kits (the default file if omitted; ``KitError`` if it is damaged)."""
        super().__init__(parent)
        self.tr_ = CatalogTranslator("resistors", translator)
        self._t = self.tr_.t
        self.registry = registry if registry is not None else KitRegistry()
        self.current: Optional[str] = None  # the kit shown in the table
        self._loading = False
        self.dirty = False
        self.setWindowTitle(self._t("res_title"))
        self.resize(900, 520)
        self._build_ui()
        self._fill_list()

    # ================================================================ building
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        intro = QLabel(self._t("res_intro", ref='{"kit": "PWR", "ref": "R22"}'))
        intro.setWordWrap(True)
        root.addWidget(intro)
        body = QHBoxLayout()
        side = QVBoxLayout()
        side.addWidget(QLabel(self._t("res_kits")))
        self.kit_list = QListWidget()
        self.kit_list.setMaximumWidth(240)
        self.kit_list.currentTextChanged.connect(self._kit_chosen)
        side.addWidget(self.kit_list, 1)
        for key, handler in (
            ("res_new", self.new_kit),
            ("res_rename", self.rename_kit),
            ("res_delete", self.delete_kit),
        ):
            button = QPushButton(self._t(key))
            button.clicked.connect(lambda _c=False, h=handler: h())
            side.addWidget(button)
        body.addLayout(side)
        main = QVBoxLayout()
        note_row = QHBoxLayout()
        note_row.addWidget(QLabel(self._t("res_kit_note")))
        self.note_edit = QLineEdit()
        self.note_edit.textEdited.connect(lambda _t: self._changed())
        note_row.addWidget(self.note_edit, 1)
        main.addLayout(note_row)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([self._t(f"res_col_{c}") for c in COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(
            len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch
        )
        self.table.itemChanged.connect(lambda _i: self._changed())
        self.table.itemSelectionChanged.connect(self._update_reference)
        main.addWidget(self.table, 1)
        rows = QHBoxLayout()
        self.add_btn = QPushButton(self._t("res_add"))
        self.add_btn.clicked.connect(lambda _c=False: self.add_resistor())
        self.remove_btn = QPushButton(self._t("res_remove"))
        self.remove_btn.clicked.connect(lambda _c=False: self.remove_resistor())
        rows.addWidget(self.add_btn)
        rows.addWidget(self.remove_btn)
        rows.addStretch(1)
        main.addLayout(rows)
        self.reference_label = QLabel()
        self.reference_label.setWordWrap(True)
        main.addWidget(self.reference_label)
        body.addLayout(main, 1)
        root.addLayout(body, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        buttons = QHBoxLayout()
        self.copy_btn = QPushButton(self._t("res_copy"))
        self.copy_btn.clicked.connect(lambda _c=False: self.copy_reference())
        self.save_btn = QPushButton(self._t("res_save"))
        self.save_btn.clicked.connect(lambda _c=False: self.save())
        close = QPushButton(self._t("res_close"))
        close.clicked.connect(self.accept)
        buttons.addWidget(self.copy_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(close)
        root.addLayout(buttons)

    # ================================================================ the list of kits
    def _fill_list(self, select: str = "") -> None:
        self._loading = True
        self.kit_list.clear()
        for name in self.registry.names():
            self.kit_list.addItem(name)
        self._loading = False
        names = self.registry.names()
        target = select if select in names else (names[0] if names else "")
        self.current = None
        if target:
            self.kit_list.setCurrentRow(names.index(target))
            self._show_kit(target)
        else:
            self._show_kit("")

    def _kit_chosen(self, name: str) -> None:
        if self._loading or name == self.current or not name:
            return
        if self.dirty and not self._apply():
            self._select_in_list(self.current or "")  # the table has an error: stay
            return
        self._show_kit(name)

    def _select_in_list(self, name: str) -> None:
        self._loading = True
        names = self.registry.names()
        self.kit_list.setCurrentRow(names.index(name) if name in names else -1)
        self._loading = False

    def _show_kit(self, name: str) -> None:
        self._loading = True
        self.current = name or None
        kit = self.registry.get(name) if name else None
        self.note_edit.setText(kit.note if kit else "")
        self.note_edit.setEnabled(kit is not None)
        self.table.setRowCount(0)
        for resistor in kit.resistors if kit else []:
            self._add_row(resistor)
        self.table.setEnabled(kit is not None)
        for button in (self.add_btn, self.remove_btn, self.copy_btn):
            button.setEnabled(kit is not None)
        self.dirty = False
        self._loading = False
        self.status.setText("" if kit else self._t("res_none"))
        self._update_reference()

    # ================================================================ the table
    def _add_row(self, resistor: Optional[KitResistor] = None) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        r = resistor or KitResistor(f"R{row + 1}", 10.0)
        cells = (
            r.name,
            f"{r.r_ohm:g}",
            f"{r.tol_pct:g}" if r.tol_pct else "",
            f"{r.power_w:g}" if r.power_w else "",
            r.channel,
            r.note,
        )
        for column, text in enumerate(cells):
            self.table.setItem(row, column, QTableWidgetItem(text))

    def add_resistor(self) -> None:
        """A new row with a name that is not used yet."""
        if self.current is None:
            return
        used = {self.table.item(r, 0).text() for r in range(self.table.rowCount())}
        number = self.table.rowCount() + 1
        while f"R{number}" in used:
            number += 1
        self._add_row(KitResistor(f"R{number}", 10.0))
        self.table.setCurrentCell(self.table.rowCount() - 1, 0)
        self._changed()

    def remove_resistor(self) -> None:
        """Take out the selected row."""
        row = self.table.currentRow()
        if self.current is None or row < 0:
            return
        self.table.removeRow(row)
        self._changed()

    def _changed(self) -> None:
        if self._loading:
            return
        self.dirty = True
        self.status.setText(self._t("res_unsaved"))
        self._update_reference()

    def _number(self, row: int, column: int, text: str, empty: Optional[float]) -> Optional[float]:
        text = text.strip()
        if not text:
            return empty
        value = parse_si(text)
        if value is None:
            raise KitError(
                self._t("res_bad_number", row=row + 1,
                        column=self._t(f"res_col_{COLUMNS[column]}"), text=text)
            )  # fmt: skip
        return value

    def collect(self) -> Kit:
        """The kit as the table shows it. ``KitError`` if a value is not a number or not allowed."""
        resistors: List[KitResistor] = []
        for row in range(self.table.rowCount()):
            cell = [self.table.item(row, c).text() if self.table.item(row, c) else ""
                    for c in range(len(COLUMNS))]  # fmt: skip
            r_ohm = self._number(row, 1, cell[1], None)
            if r_ohm is None:
                raise KitError(self._t("res_bad_number", row=row + 1,
                                       column=self._t("res_col_value"), text=cell[1]))  # fmt: skip
            resistors.append(
                KitResistor(
                    cell[0].strip(),
                    r_ohm,
                    self._number(row, 2, cell[2], 0.0) or 0.0,
                    self._number(row, 3, cell[3], None),
                    cell[4].strip(),
                    cell[5].strip(),
                )
            )
        return Kit(self.current or "", resistors, self.note_edit.text().strip())

    def _apply(self) -> bool:
        """Put the table into the registry (in memory). False, with the reason shown, if it cannot
        be done."""
        try:
            kit = self.collect()
            self.registry.put(kit, save=False)
        except KitError as exc:
            self.status.setText(self._t("res_error", error=exc))
            return False
        return True

    def save(self) -> bool:
        """Write the kits to the file. False, with the reason shown, if something is wrong."""
        if self.current is not None and not self._apply():
            return False
        try:
            self.registry.save()
        except OSError as exc:
            self.status.setText(self._t("res_error", error=exc))
            return False
        self.dirty = False
        self.status.setText(self._t("res_saved", path=self.registry.path))
        return True

    # ================================================================ the kits
    def new_kit(self) -> None:
        """Ask for a name and make an empty kit."""
        if self.dirty and not self._apply():
            return
        name, ok = QInputDialog.getText(self, self._t("res_new"), self._t("res_new_prompt"))
        if not ok:
            return
        name = name.strip()
        if name in self.registry.kits:
            self.status.setText(self._t("res_error", error=name))
            return
        try:
            self.registry.put(Kit(name), save=False)
        except KitError as exc:
            self.status.setText(self._t("res_error", error=exc))
            return
        self._fill_list(name)
        self._changed()

    def rename_kit(self) -> None:
        """Ask for another name for the selected kit."""
        if self.current is None or (self.dirty and not self._apply()):
            return
        name, ok = QInputDialog.getText(
            self, self._t("res_rename"), self._t("res_rename_prompt"), text=self.current
        )
        if not ok:
            return
        try:
            self.registry.rename(self.current, name, save=False)
        except KitError as exc:
            self.status.setText(self._t("res_error", error=exc))
            return
        self._fill_list(name.strip())
        self._changed()

    def delete_kit(self) -> None:
        """Delete the selected kit, after asking."""
        kit = self.registry.get(self.current or "")
        if kit is None:
            return
        answer = QMessageBox.question(
            self,
            self._t("res_delete"),
            self._t("res_delete_confirm", name=kit.name, count=len(kit.resistors)),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.registry.delete(kit.name, save=False)
        self._fill_list()
        self._changed()

    # ================================================================ the reference
    def selected_reference(self) -> Optional[str]:
        """The reference to the selected resistor as text, or None."""
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        if self.current is None or item is None or not item.text().strip():
            return None
        return reference_text(self.current, item.text().strip())

    def _update_reference(self) -> None:
        ref = self.selected_reference()
        self.reference_label.setText(self._t("res_reference", ref=ref) if ref else "")

    def copy_reference(self) -> None:
        """Put the reference to the selected resistor on the clipboard."""
        ref = self.selected_reference()
        if ref is None:
            return
        QApplication.clipboard().setText(ref)
        self.status.setText(self._t("res_copied", ref=ref))


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the window (``python -m frontend.ui.ResistorKitsDialog [kits file]``)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = ResistorKitsDialog(KitRegistry(argv[0]) if argv else None)
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
