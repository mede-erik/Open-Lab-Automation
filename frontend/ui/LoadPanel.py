# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The panel of a *resistive load* parameter in the efficiency editor (``.rfe``).

It edits the ``load`` block of a parameter: the list of loads (each one resistor, or a series /
parallel group), how they are connected (by hand or through a multiplexer), and the reading that
checks the power in the resistors. The loads come from a **kit of resistors** (*Add from a kit*:
the resistors are only referenced, the kit is read when the measurement starts), or are typed in
(*New load*), and the resistors that were typed in can be saved as an **additional kit**
(*Save as a kit*): an existing kit is never changed. Strings: the ``eff_load_*`` keys of the
efficiency catalog. The logic is in ``ola.resistors`` and ``ola.resistor_kits``.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.core.errorhandler import show_problem
from ola.resistor_kits import Kit, KitError, KitRegistry, kit_from_loads
from ola.run_view import parse_si

MODES = ("manual", "mux")


def node_text(node: Any) -> str:
    """A load or a group in one line: ``10R``, ``22 || 47``, ``R1 + (R2 || R3)``."""
    if not isinstance(node, dict):
        return "?"
    for key, joint in (("series", " + "), ("parallel", " || ")):
        if key in node and isinstance(node[key], list):
            return "(" + joint.join(node_text(n) for n in node[key]) + ")"
    if "ref" in node and "r_ohm" not in node:
        return f"{node.get('kit', '?')}/{node['ref']}"
    ohm = node.get("r_ohm")
    return node.get("name") or (f"{ohm:g} ohm" if isinstance(ohm, (int, float)) else "?")


class _KitPick(QDialog):
    """Choose a kit, some of its resistors and how to connect them."""

    def __init__(self, registry: KitRegistry, t: Callable[..., str], parent: QWidget = None):
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle(t("eff_load_pick_title"))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kits = QComboBox()
        self.kits.addItems(registry.names())
        self.kits.currentTextChanged.connect(self._fill)
        form.addRow(t("eff_load_kit"), self.kits)
        self.how = QComboBox()
        for key in ("separate", "series", "parallel"):
            self.how.addItem(t(f"eff_load_how_{key}"), key)
        form.addRow(t("eff_load_how"), self.how)
        layout.addLayout(form)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._fill(self.kits.currentText())

    def _fill(self, name: str) -> None:
        self.list.clear()
        kit = self.registry.get(name)
        for r in kit.resistors if kit else []:
            power = f", {r.power_w:g} W" if r.power_w else ""
            self.list.addItem(QListWidgetItem(f"{r.name}: {r.r_ohm:g} ohm, {r.tol_pct:g} %{power}"))

    def loads(self) -> List[dict]:
        """The loads to add: one per selected resistor, or one group of all of them."""
        kit = self.registry.get(self.kits.currentText())
        if kit is None:
            return []
        rows = sorted(self.list.row(item) for item in self.list.selectedItems())
        refs = [self.registry.reference(kit.name, kit.resistors[row].name) for row in rows]
        how = self.how.currentData()
        if how == "separate" or len(refs) < 2:
            return refs
        return [{"name": " ".join(r["ref"] for r in refs), how: refs}]


class _NewLoad(QDialog):
    """A resistor typed in: value, tolerance, rating, relay."""

    def __init__(self, t: Callable[..., str], parent: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(t("eff_load_new_title"))
        form = QFormLayout(self)
        self.edits: Dict[str, QLineEdit] = {}
        for key in ("name", "r_ohm", "tol_pct", "power_w", "channel"):
            edit = QLineEdit()
            self.edits[key] = edit
            form.addRow(t(f"eff_load_f_{key}"), edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def load(self) -> Optional[dict]:
        """The resistor as a load, or ``None`` if the value is not a number above 0."""
        out: Dict[str, Any] = {}
        for key, edit in self.edits.items():
            text = edit.text().strip()
            if not text:
                continue
            if key in ("name", "channel"):
                out[key] = text
                continue
            value = parse_si(text)
            if value is None:
                return None
            out[key] = value
        return out if out.get("r_ohm") else None


class LoadPanel(QGroupBox):
    """Edits one ``load`` block (see the module docstring); ``changed`` is emitted after an edit."""

    changed = pyqtSignal()

    def __init__(
        self,
        t: Callable[..., str],
        instruments: Sequence[str] = (),
        registry: Optional[KitRegistry] = None,
        parent: QWidget = None,
    ):
        super().__init__(t("eff_load"), parent)
        self._t = t
        self._registry = registry
        self._loading = False
        self.block: Dict[str, Any] = {}
        layout = QVBoxLayout(self)
        note = QLabel(t("eff_load_help"))
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([t("eff_load_col_load"), t("eff_load_col_ohm")])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self.buttons: Dict[str, QPushButton] = {}
        for key, handler in (
            ("add_kit", self.add_from_kit),
            ("add_new", self.add_new),
            ("remove", self.remove_selected),
            ("save_kit", self.save_as_kit),
        ):
            button = QPushButton(t(f"eff_load_{key}"))
            button.clicked.connect(handler)
            self.buttons[key] = button
            row.addWidget(button)
        layout.addLayout(row)
        form = QFormLayout()
        self.mode = QComboBox()
        for mode in MODES:
            self.mode.addItem(t(f"eff_load_mode_{mode}"), mode)
        # the switch matrix (series / parallel wiring by relays) is for a future version: shown, but
        # it cannot be chosen
        item = self.mode.model().item(self.mode.findData("mux"))
        item.setEnabled(False)
        self.mode.currentIndexChanged.connect(self._edited)
        form.addRow(t("eff_load_mode"), self.mode)
        self.instrument = QComboBox()
        self.instrument.setEditable(True)
        self.instrument.addItems(list(instruments))
        self.instrument.currentTextChanged.connect(self._edited)
        form.addRow(t("eff_load_instrument"), self.instrument)
        self.settle = QLineEdit()
        self.settle.setPlaceholderText("s")
        self.settle.textChanged.connect(self._edited)
        form.addRow(t("eff_load_settle"), self.settle)
        self.vout = QLineEdit()
        self.vout.setPlaceholderText("vout@daq")
        self.vout.textChanged.connect(self._edited)
        form.addRow(t("eff_load_vout"), self.vout)
        self.max_vout = QLineEdit()
        self.max_vout.setPlaceholderText("V")
        self.max_vout.textChanged.connect(self._edited)
        form.addRow(t("eff_load_max_vout"), self.max_vout)
        layout.addLayout(form)

    # ---- the kits ----------------------------------------------------------------------------
    @property
    def registry(self) -> KitRegistry:
        """The kits of resistors (opened on first use: the file may be damaged)."""
        if self._registry is None:
            self._registry = KitRegistry()
        return self._registry

    # ---- showing and reading the block -------------------------------------------------------
    def set_block(self, block: Optional[dict]) -> None:
        """Show the ``load`` block (a copy is kept and edited)."""
        self._loading = True
        self.block = dict(block) if isinstance(block, dict) else {"loads": []}
        switching = self.block.get("switching") or {}
        self.mode.setCurrentIndex(max(0, self.mode.findData(switching.get("mode", "manual"))))
        self.instrument.setCurrentText(str(switching.get("instrument", "")))
        self.settle.setText("" if "settle_s" not in switching else f"{switching['settle_s']:g}")
        self.vout.setText(str(self.block.get("vout", "")))
        value = self.block.get("max_vout_v")
        self.max_vout.setText("" if value is None else f"{value:g}")
        self._fill_table()
        self._loading = False

    def _fill_table(self) -> None:
        loads = self.block.get("loads") or []
        self.table.setRowCount(len(loads))
        for row, load in enumerate(loads):
            self.table.setItem(row, 0, QTableWidgetItem(node_text(load)))
            self.table.setItem(row, 1, QTableWidgetItem(self._ohms(load)))

    @staticmethod
    def _ohms(load: Any) -> str:
        from ola.resistors import LoadError, parse_load

        try:
            return f"{parse_load(load).resistance()[0]:.4g}"
        except LoadError:
            return "(kit)"  # a resistor of a kit: its value is known when the run starts

    def _edited(self, *_args: Any) -> None:
        if self._loading:
            return
        switching: Dict[str, Any] = {"mode": self.mode.currentData()}
        if self.mode.currentData() == "mux":
            switching["instrument"] = self.instrument.currentText().strip()
        settle = self._number(self.settle.text())
        if settle is not None:
            switching["settle_s"] = settle
        self.block["switching"] = switching
        vout = self.vout.text().strip()
        for key, value in (
            ("vout", vout or None),
            ("max_vout_v", self._number(self.max_vout.text())),
        ):
            if value is None:
                self.block.pop(key, None)
            else:
                self.block[key] = value
        self.changed.emit()

    @staticmethod
    def _number(text: str) -> Optional[float]:
        try:
            return float(parse_si(text.strip())) if text.strip() else None
        except (TypeError, ValueError):
            return None

    # ---- the buttons -------------------------------------------------------------------------
    def _add(self, loads: List[dict]) -> None:
        if not loads:
            return
        self.block.setdefault("loads", []).extend(loads)
        self._fill_table()
        self.changed.emit()

    def add_from_kit(self) -> None:
        """Pick resistors of a kit: they are referenced, not copied."""
        try:
            names = self.registry.names()
        except KitError as exc:
            show_problem(self, self._t("eff_load"), str(exc), code="MEAS-001", exception=exc)
            return
        if not names:
            QMessageBox.information(self, self._t("eff_load"), self._t("eff_load_no_kits"))
            return
        dialog = _KitPick(self.registry, self._t, self)
        if dialog.exec():
            self._add(dialog.loads())

    def add_new(self) -> None:
        """Type in a resistor."""
        dialog = _NewLoad(self._t, self)
        if dialog.exec():
            load = dialog.load()
            if load is None:
                show_problem(
                    self, self._t("eff_load"), self._t("eff_load_bad_value"), code="MEAS-001"
                )
                return
            self._add([load])

    def remove_selected(self) -> None:
        """Remove the selected loads."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        loads = self.block.get("loads") or []
        for row in rows:
            if 0 <= row < len(loads):
                del loads[row]
        self._fill_table()
        self.changed.emit()

    def save_as_kit(self) -> None:
        """Save the resistors typed in as a **new** kit; the kits that exist are not touched."""
        title = self._t("eff_load_save_kit")
        name, ok = QInputDialog.getText(self, title, self._t("eff_load_kit_name"))
        if not ok or not name.strip():
            return
        try:
            registry = self.registry
            if registry.get(name.strip()) is not None:
                raise KitError(self._t("eff_load_kit_exists", name=name.strip()))
            kit: Kit = kit_from_loads(name, self.block.get("loads"))
            registry.put(kit)
        except KitError as exc:
            show_problem(
                self, self._t("eff_load_save_kit"), str(exc), code="MEAS-001", exception=exc
            )
            return
        text = self._t("eff_load_kit_saved", name=kit.name, n=len(kit.resistors))
        QMessageBox.information(self, title, text)
