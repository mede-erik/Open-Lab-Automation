"""Cables and devices: the registry window (menu *Tools* > *Cables and devices*).

Every physical object that is measured (cable, antenna, filter, amplifier, adapter...) has a code
(``CBL-0042``) and a card. This window lists the cards of ``ola.assets.AssetRegistry`` and:

* **New / Edit / Retire / Delete**: the card (a retired object stays in the list, greyed, and in
  its old results; it is just not offered for new measurements). A code is never used again;
* **Label...**: the label of the selected objects, to print (``LabelDialog``): the code, a QR code,
  and a few lines of what it is;
* **History...**: the measurements made on the selected object, found by its code, with
  **Compare** to put their curves together (``CompareDialog``) and **Trend** to see how a figure
  (the loss of a cable) changes with the date (``TrendDialog``);
* **Scan or type a code**: a USB barcode scanner types the code (``OLA:CBL-0042``) in the box and
  the object is selected; a code that is not in the registry says so.

The *Measurements* column counts the runs found in the runs folders it is given (the ones of the
open project). Strings: ``frontend/lang/modules/assets/<lang>.json``.
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

from frontend.ui.AssetEditDialog import AssetEditDialog
from frontend.ui.efficiency_widgets import text_color
from frontend.ui.module_translator import CatalogTranslator
from ola.assets import (
    KINDS,
    Asset,
    AssetError,
    AssetRegistry,
    RunRef,
    index_runs,
    last_measurement_line,
    normalize_code,
)

RunDirs = Union[Sequence[Union[str, Path]], Callable[[], Sequence[Union[str, Path]]]]


class AssetHistoryDialog(QDialog):
    """The measurements made on one object, oldest first, with *Compare*."""

    def __init__(
        self,
        asset: Asset,
        runs: Sequence[RunRef],
        translator: Any = None,
        parent: Optional[QWidget] = None,
        run_dirs: Sequence[Union[str, Path]] = (),
    ):
        super().__init__(parent)
        self.tr_ = CatalogTranslator("assets", translator)
        self._t = self.tr_.t
        self.asset, self.runs, self.translator = asset, list(runs), translator
        # where the trend looks for the runs: the folders given, else those of these runs
        self.run_dirs = list(run_dirs) or sorted({str(r.path.parent) for r in self.runs})
        self.setWindowTitle(self._t("ast_history_title", code=asset.id, name=asset.name))
        self.resize(760, 420)
        root = QVBoxLayout(self)
        if not self.runs:
            root.addWidget(QLabel(self._t("ast_h_none", code=asset.id)))
        self.table = QTableWidget(len(self.runs), 4)
        self.table.setHorizontalHeaderLabels(
            [self._t(k) for k in ("ast_h_date", "ast_h_measurement", "ast_h_state", "ast_h_file")]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for row, ref in enumerate(self.runs):
            for col, text in enumerate(
                (ref.when, ref.measurement, self._t(f"ast_state_{ref.state}"), ref.path.name)
            ):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        row_buttons = QHBoxLayout()
        row_buttons.addStretch(1)
        self.compare_btn = QPushButton(self._t("ast_compare"))
        self.compare_btn.setEnabled(len(self.runs) >= 1)
        self.compare_btn.clicked.connect(self.compare)
        self.trend_btn = QPushButton(self._t("ast_trend"))
        self.trend_btn.setEnabled(any(r.state == "finished" for r in self.runs))
        self.trend_btn.clicked.connect(self.show_trend)
        close = QPushButton(self._t("ast_close"))
        close.clicked.connect(self.accept)
        row_buttons.addWidget(self.trend_btn)
        row_buttons.addWidget(self.compare_btn)
        row_buttons.addWidget(close)
        root.addLayout(row_buttons)

    def compare(self) -> None:
        """Open the comparison tool with these runs (finished or stopped ones: they have data)."""
        from frontend.ui.CompareDialog import CompareDialog

        paths = [str(r.path) for r in self.runs]
        self.tool = CompareDialog(paths, self.translator, self)
        for run in self.tool.runs:  # a run made before the card existed has no name of its own
            if run.asset_id == self.asset.id and not run.name:
                run.label = f"{self.asset.id} {self.asset.name} - {run.when}"
        self.tool._fill_list()
        self.tool.show()

    def show_trend(self) -> None:
        """How the object ages: a figure of its measurements against the date."""
        from frontend.ui.TrendDialog import TrendDialog

        kinds = [r.measurement for r in self.runs if r.state == "finished"]
        kind = "cable" if "cable" in kinds else (kinds[-1] if kinds else "cable")
        self.trend_tool = TrendDialog(
            self.asset.id, self.run_dirs, self.translator, self, self.asset.name, kind
        )
        self.trend_tool.show()


class AssetsDialog(QDialog):
    """The registry window (see the module docstring)."""

    def __init__(
        self,
        registry: Optional[AssetRegistry] = None,
        translator: Any = None,
        run_dirs: RunDirs = (),
        parent: Optional[QWidget] = None,
    ):
        """``registry``: the cards (the default file if omitted; ``AssetError`` if it is damaged).
        ``run_dirs``: the runs folders to count and search, or a function that gives them now."""
        super().__init__(parent)
        self.tr_ = CatalogTranslator("assets", translator)
        self._t = self.tr_.t
        self.translator = translator
        self.registry = registry if registry is not None else AssetRegistry()
        self._run_dirs = run_dirs
        self.index: Dict[str, List[RunRef]] = {}
        self._shown: List[Asset] = []
        self.setWindowTitle(self._t("ast_title"))
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
        self.file_label = QLabel(self._t("ast_file", path=str(self.registry.path)))
        self.file_label.setStyleSheet(f"color: {text_color('muted', self)};")
        root.addWidget(self.file_label)
        top = QHBoxLayout()
        self.scan_edit = QLineEdit()
        self.scan_edit.setPlaceholderText(self._t("ast_scan"))
        self.scan_edit.returnPressed.connect(self.scan)
        self.kind_box = QComboBox()
        self.kind_box.addItem(self._t("ast_kind_all"), None)
        for kind in KINDS:
            self.kind_box.addItem(self._t(f"ast_kind_{kind}"), kind)
        self.kind_box.currentIndexChanged.connect(lambda _i: self.refresh())
        self.retired_box = QCheckBox(self._t("ast_show_retired"))
        self.retired_box.setChecked(True)
        self.retired_box.toggled.connect(lambda _on: self.refresh())
        top.addWidget(self.scan_edit, 2)
        top.addWidget(self.kind_box)
        top.addWidget(self.retired_box)
        root.addLayout(top)
        self.table = QTableWidget(0, 7)
        columns = ("code", "kind", "name", "description", "created", "runs", "status")
        self.table.setHorizontalHeaderLabels([self._t(f"ast_col_{c}") for c in columns])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _i: self.edit_selected())
        root.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.buttons: Dict[str, QPushButton] = {}
        for key, handler in (
            ("ast_new", self.new_asset),
            ("ast_edit", self.edit_selected),
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
        """Read the registry and the runs again and redraw the table (the selection is kept)."""
        keep = [a.id for a in self.selected()]
        self.index = index_runs(self.run_dirs())
        kind = self.kind_box.currentData()
        self._shown = self.registry.list(kind, self.retired_box.isChecked())
        self.table.setRowCount(len(self._shown))
        for row, asset in enumerate(self._shown):
            runs = self.index.get(asset.id, [])
            status = self._t("ast_retired") if asset.retired else self._t("ast_active")
            cells = (asset.id, self._t(f"ast_kind_{asset.kind}"), asset.name, asset.description,
                     asset.created, str(len(runs)), status)  # fmt: skip
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if asset.retired:
                    item.setForeground(QBrush(QColor(text_color("muted", self))))
                self.table.setItem(row, col, item)
            if asset.id in keep:
                self.table.selectRow(row)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._update_buttons()

    def selected(self) -> List[Asset]:
        """The cards that are selected in the table."""
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [self._shown[r] for r in rows if 0 <= r < len(self._shown)]

    def _update_buttons(self) -> None:
        chosen = self.selected()
        one = len(chosen) == 1
        self.buttons["ast_edit"].setEnabled(one)
        self.buttons["ast_delete"].setEnabled(one)
        self.buttons["ast_history"].setEnabled(one)
        self.buttons["ast_retire"].setEnabled(bool(chosen))
        self.buttons["ast_label"].setEnabled(bool(chosen))
        retired = bool(chosen) and all(a.retired for a in chosen)
        self.buttons["ast_retire"].setText(self._t("ast_reactivate" if retired else "ast_retire"))

    # ================================================================ actions
    def scan(self) -> None:
        """A typed or scanned code: select its card (``OLA:CBL-0042`` and ``cbl-42`` work too)."""
        text = self.scan_edit.text().strip()
        self.scan_edit.clear()
        if not text:
            return
        code = normalize_code(text)
        card = self.registry.get(code) if code else None
        if card is None:
            self.message.setText(self._t("ast_scan_notfound", code=text))
            return
        self.message.setText("")
        if card not in self._shown:  # it is hidden by the filter: show everything
            self.kind_box.setCurrentIndex(0)
            self.retired_box.setChecked(True)
            self.refresh()
        self.table.clearSelection()
        self.table.selectRow(self._shown.index(card))
        self.table.scrollToItem(self.table.item(self._shown.index(card), 0))

    def new_asset(self) -> None:
        kind = self.kind_box.currentData() or "cable"
        dialog = AssetEditDialog(self.registry, self.translator, kind=kind, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved:
            self.refresh()
            self._select(dialog.saved.id)

    def edit_selected(self) -> None:
        chosen = self.selected()
        if len(chosen) != 1:
            return
        dialog = AssetEditDialog(self.registry, self.translator, asset=chosen[0], parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def _select(self, code: str) -> None:
        for row, asset in enumerate(self._shown):
            if asset.id == code:
                self.table.selectRow(row)

    def toggle_retired(self) -> None:
        """Retire the selected objects (or bring them back if all of them are retired)."""
        chosen = self.selected()
        retire = not all(a.retired for a in chosen)
        try:
            for asset in chosen:
                self.registry.update(asset.id, save=False, retired=retire)
            self.registry.save()
        except (AssetError, OSError) as exc:
            QMessageBox.critical(self, self.windowTitle(), self._t("ast_error", error=exc))
        self.refresh()

    def delete_selected(self) -> None:
        chosen = self.selected()
        if len(chosen) != 1:
            return
        asset = chosen[0]
        used = len(self.index.get(asset.id, []))
        text = self._t("ast_confirm_delete", code=asset.id, name=asset.name)
        if used:
            text += "\n" + self._t("ast_confirm_delete_used", n=used)
        answer = QMessageBox.question(self, self._t("ast_delete"), text)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.registry.delete(asset.id)
        except (AssetError, OSError) as exc:
            QMessageBox.critical(self, self.windowTitle(), self._t("ast_error", error=exc))
        self.refresh()

    def make_labels(self) -> None:
        """Open the label window for the selected objects."""
        from frontend.ui.LabelDialog import LabelDialog

        chosen = self.selected()
        if not chosen:
            return

        def latest(asset: Asset) -> str:
            runs = self.index.get(asset.id, [])
            return last_measurement_line(runs[-1] if runs else None)

        self.label_tool = LabelDialog(chosen, self.translator, latest, self)
        self.label_tool.show()

    def show_history(self) -> None:
        """The measurements made on the selected object."""
        chosen = self.selected()
        if len(chosen) != 1:
            return
        runs = self.index.get(chosen[0].id, [])
        self.history_tool = AssetHistoryDialog(
            chosen[0], runs, self.translator, self, self.run_dirs()
        )
        self.history_tool.show()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the registry window (``python -m frontend.ui.AssetsDialog [runs folder ...]``)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = AssetsDialog(run_dirs=argv)
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
