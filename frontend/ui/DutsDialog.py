# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""DUT: the archive window (menu *Tools* > *DUT*).

A DUT is a device under test: an antenna, a filter, a converter, anything else. It has a code
(``DUT-0001``) and a name chosen by the user, a category and versions in free text (``rev A``). This
window lists the cards of ``ola.duts.DutRegistry`` and:

* **New / Edit / Versions / Retire / Delete**: the card and its versions (a retired DUT stays in
  the list, greyed, and in its old results; it is just not offered for new measurements). A code is
  never used again;
* **Label...**: the label of the selected DUTs, to print (``LabelDialog``, the one of the
  components): the code, a QR code, the name, the version and a few lines of what it is;
* **Scan or type a code**: a USB barcode scanner types the code (``OLA:DUT-0001``) in the box and
  the DUT is selected. The code a card had before (an antenna that was ``ANT-0003``) finds it too.

Strings: ``frontend/lang/modules/duts/<lang>.json``, then the ones of ``modules/assets``.
"""

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.DutEditDialog import DutEditDialog
from frontend.ui.DutVersionsDialog import DutVersionsDialog
from frontend.ui.efficiency_widgets import text_color
from frontend.ui.module_translator import CatalogTranslator, ChainedTranslator
from ola.assets import AssetError, RunRef, last_measurement_line, normalize_code, runs_of
from ola.duts import CATEGORIES, Dut, DutRegistry, index_dut_runs

RunDirs = Union[Sequence[Union[str, Path]], Callable[[], Sequence[Union[str, Path]]]]


class DutsDialog(QDialog):
    """The archive window (see the module docstring)."""

    def __init__(
        self,
        registry: Optional[DutRegistry] = None,
        translator: Any = None,
        run_dirs: RunDirs = (),
        parent: Optional[QWidget] = None,
    ):
        """``registry``: the cards (the default file if omitted; ``AssetError`` if damaged).
        ``run_dirs``: the runs folders to count and search, or a function that gives them now."""
        super().__init__(parent)
        self.tr_ = ChainedTranslator(
            CatalogTranslator("duts", translator), CatalogTranslator("assets", translator)
        )
        self._t = self.tr_.t
        self.translator = translator
        self.registry = registry if registry is not None else DutRegistry()
        self._run_dirs = run_dirs
        self.index: Dict[str, List[RunRef]] = {}
        self._shown: List[Dut] = []
        self.setWindowTitle(self._t("dut_title"))
        self.resize(980, 560)
        self._build_ui()
        self.refresh()

    def run_dirs(self) -> List[Union[str, Path]]:
        """The runs folders now."""
        dirs = self._run_dirs() if callable(self._run_dirs) else self._run_dirs
        return list(dirs)

    # ================================================================ building
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.file_label = QLabel(self._t("dut_file", path=str(self.registry.path)))
        self.file_label.setStyleSheet(f"color: {text_color('muted', self)};")
        root.addWidget(self.file_label)
        top = QHBoxLayout()
        self.scan_edit = QLineEdit()
        self.scan_edit.setPlaceholderText(self._t("dut_scan"))
        self.scan_edit.returnPressed.connect(self.scan)
        self.category_box = QComboBox()
        self.category_box.addItem(self._t("ast_kind_all"), None)
        for category in CATEGORIES:
            self.category_box.addItem(self._t(f"ast_kind_{category}"), category)
        self.category_box.currentIndexChanged.connect(lambda _i: self.refresh())
        self.retired_box = QCheckBox(self._t("ast_show_retired"))
        self.retired_box.setChecked(True)
        self.retired_box.toggled.connect(lambda _on: self.refresh())
        top.addWidget(self.scan_edit, 2)
        top.addWidget(self.category_box)
        top.addWidget(self.retired_box)
        root.addLayout(top)
        self.table = QTableWidget(0, 8)
        columns = ("ast_col_code", "dut_col_category", "ast_col_name", "dut_col_version",
                   "ast_col_description", "ast_col_created", "ast_col_runs",
                   "ast_col_status")  # fmt: skip
        self.table.setHorizontalHeaderLabels([self._t(c) for c in columns])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _i: self.edit_selected())
        root.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.buttons: Dict[str, QPushButton] = {}
        for key, handler in (
            ("ast_new", self.new_dut),
            ("ast_edit", self.edit_selected),
            ("dut_versions", self.edit_versions),
            ("ast_retire", self.toggle_retired),
            ("ast_delete", self.delete_selected),
            ("ast_label", self.make_labels),
            ("ast_history", self.show_history),
        ):
            button = QPushButton(self._t(key))
            button.clicked.connect(lambda _c=False, h=handler: h())
            self.buttons[key] = button
            row.addWidget(button)
        row.addStretch(1)
        root.addLayout(row)
        self.message = QLabel()
        root.addWidget(self.message)

    # ================================================================ the list
    def refresh(self) -> None:
        """Read the archive again and redraw the table (the selection is kept)."""
        keep = [d.id for d in self.selected()]
        self.index = index_dut_runs(self.run_dirs())
        category = self.category_box.currentData()
        self._shown = self.registry.list(category, self.retired_box.isChecked())  # type: ignore
        self.table.setRowCount(len(self._shown))
        for row, dut in enumerate(self._shown):
            status = self._t("ast_retired") if dut.retired else self._t("ast_active")
            version = self.registry.current_version(dut.id) or ""
            runs = runs_of(dut, self.index)
            cells = (dut.id, self._t(f"ast_kind_{dut.kind}"), dut.name, version, dut.description,
                     dut.created, str(len(runs)), status)  # fmt: skip
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if dut.retired:
                    item.setForeground(QBrush(QColor(text_color("muted", self))))
                self.table.setItem(row, col, item)
            if dut.id in keep:
                self.table.selectRow(row)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._update_buttons()

    def selected(self) -> List[Dut]:
        """The cards that are selected in the table."""
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self._shown[r] for r in rows if 0 <= r < len(self._shown)]

    def _update_buttons(self) -> None:
        chosen = self.selected()
        one = len(chosen) == 1
        for key in ("ast_edit", "ast_delete", "dut_versions", "ast_history"):
            self.buttons[key].setEnabled(one)
        self.buttons["ast_retire"].setEnabled(bool(chosen))
        self.buttons["ast_label"].setEnabled(bool(chosen))
        retired = bool(chosen) and all(d.retired for d in chosen)
        self.buttons["ast_retire"].setText(self._t("ast_reactivate" if retired else "ast_retire"))

    # ================================================================ actions
    def scan(self) -> None:
        """A typed or scanned code: select its card (``OLA:DUT-0001`` and ``dut-1`` work too, and
        so does a code the card had before)."""
        text = self.scan_edit.text().strip()
        self.scan_edit.clear()
        if not text:
            return
        code = normalize_code(text)
        card = self.registry.get(code) if code else None
        if card is None:
            self.message.setText(self._t("dut_scan_notfound", code=text))
            return
        self.message.setText("")
        if card not in self._shown:  # it is hidden by the filter: show everything
            self.category_box.setCurrentIndex(0)
            self.retired_box.setChecked(True)
            self.refresh()
        self.table.clearSelection()
        self.table.selectRow(self._shown.index(card))
        self.table.scrollToItem(self.table.item(self._shown.index(card), 0))

    def new_dut(self) -> None:
        """Make a new DUT."""
        category = self.category_box.currentData() or "converter"
        dialog = DutEditDialog(self.registry, self.translator, category=category, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved:
            self.refresh()
            self._select(dialog.saved.id)

    def edit_selected(self) -> None:
        """Change the card of the selected DUT."""
        chosen = self.selected()
        if len(chosen) != 1:
            return
        dialog = DutEditDialog(self.registry, self.translator, dut=chosen[0], parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def edit_versions(self) -> None:
        """The versions of the selected DUT."""
        chosen = self.selected()
        if len(chosen) != 1:
            return
        DutVersionsDialog(self.registry, self.translator, chosen[0].id, self).exec()
        self.refresh()

    def _select(self, code: str) -> None:
        for row, dut in enumerate(self._shown):
            if dut.id == code:
                self.table.selectRow(row)

    def toggle_retired(self) -> None:
        """Retire the selected DUTs (or bring them back if all of them are retired)."""
        chosen = self.selected()
        retire = not all(d.retired for d in chosen)
        try:
            for dut in chosen:
                self.registry.update(dut.id, save=False, retired=retire)
            self.registry.save()
        except (AssetError, OSError) as exc:
            QMessageBox.critical(self, self.windowTitle(), self._t("ast_error", error=exc))
        self.refresh()

    def delete_selected(self) -> None:
        """Delete the selected DUT, after asking; its code is not given again."""
        chosen = self.selected()
        if len(chosen) != 1:
            return
        dut = chosen[0]
        text = self._t("dut_confirm_delete", code=dut.id, name=dut.name)
        used = len(runs_of(dut, self.index))
        if used:
            text += "\n" + self._t("ast_confirm_delete_used", n=used)
        if QMessageBox.question(self, self._t("ast_delete"), text) != (
            QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.registry.delete(dut.id)
        except (AssetError, OSError) as exc:
            QMessageBox.critical(self, self.windowTitle(), self._t("ast_error", error=exc))
        self.refresh()

    def make_labels(self) -> None:
        """Open the label window for the selected DUTs."""
        from frontend.ui.LabelDialog import LabelDialog

        chosen = self.selected()
        if not chosen:
            return

        def latest(dut: Dut) -> str:
            runs = runs_of(dut, self.index)
            return last_measurement_line(runs[-1] if runs else None)

        self.label_tool = LabelDialog(chosen, self.translator, latest, self)
        self.label_tool.show()

    def show_history(self) -> None:
        """The measurements made on the selected DUT, found by its code (and by the codes it had
        before), with *Compare*."""
        from frontend.ui.AssetsDialog import AssetHistoryDialog

        chosen = self.selected()
        if len(chosen) != 1:
            return
        runs = runs_of(chosen[0], self.index)
        self.history_tool = AssetHistoryDialog(
            chosen[0], runs, self.translator, self, self.run_dirs(), trend=False
        )
        self.history_tool.show()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the DUT window (``python -m frontend.ui.DutsDialog [runs folder ...]``)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = DutsDialog(run_dirs=argv)
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
