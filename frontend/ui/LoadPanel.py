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

import copy
from typing import Any, Callable, Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
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
from ola.combinations import Plan, PlanError, loads_from_plan, plan_loads, tree_text
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
    if node.get("open") is True:
        return node.get("name") or "open"
    if "ref" in node and "r_ohm" not in node:
        return f"{node.get('kit', '?')}/{node['ref']}"
    ohm = node.get("r_ohm")
    return node.get("name") or (f"{ohm:g} ohm" if isinstance(ohm, (int, float)) else "?")


class _KitPick(QDialog):
    """Choose a kit, tick some of its resistors (or all) and how to connect them."""

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
        self.list.itemChanged.connect(lambda _item: self._update_ok())
        layout.addWidget(self.list)
        row = QHBoxLayout()
        for key, state in (("all", True), ("none", False)):
            button = QPushButton(t(f"eff_load_pick_{key}"))
            button.clicked.connect(lambda _c=False, on=state: self.check_all(on))
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._fill(self.kits.currentText())

    def _fill(self, name: str) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        kit = self.registry.get(name)
        for r in kit.resistors if kit else []:
            power = f", {r.power_w:g} W" if r.power_w else ""
            item = QListWidgetItem(f"{r.name}: {r.r_ohm:g} ohm, {r.tol_pct:g} %{power}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._update_ok()

    def check_all(self, on: bool) -> None:
        """Tick (or untick) every resistor of the kit."""
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for row in range(self.list.count()):
            self.list.item(row).setCheckState(state)

    def checked_rows(self) -> List[int]:
        """The rows of the ticked resistors."""
        return [
            row
            for row in range(self.list.count())
            if self.list.item(row).checkState() == Qt.CheckState.Checked
        ]

    def _update_ok(self) -> None:
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(bool(self.checked_rows()))  # nothing ticked: nothing to add

    def loads(self) -> List[dict]:
        """The loads to add: one per ticked resistor, or one group of all of them."""
        kit = self.registry.get(self.kits.currentText())
        if kit is None:
            return []
        rows = self.checked_rows()
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


class _PlanDialog(QDialog):
    """Calculate the loads for a range of output current from a kit of resistors."""

    def __init__(
        self,
        registry: KitRegistry,
        t: Callable[..., str],
        previous: Optional[dict] = None,
        parameters: Sequence[str] = (),
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self._t = t
        self.registry = registry
        self.plan: Optional[Plan] = None
        self.resistors: List[dict] = []
        self.setWindowTitle(t("eff_plan_title"))
        self.resize(900, 560)
        layout = QVBoxLayout(self)
        note = QLabel(t("eff_plan_help"))
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.kits = QComboBox()
        self.kits.addItems(registry.names())
        form.addRow(t("eff_load_kit"), self.kits)
        self.kind = QComboBox()
        self.kind.addItem(t("eff_plan_regulated"), "regulated")
        self.kind.addItem(t("eff_plan_unregulated"), "unregulated")
        self.kind.currentIndexChanged.connect(self._kind_changed)
        form.addRow(t("eff_plan_kind"), self.kind)
        self.fields: Dict[str, QLineEdit] = {}
        for key, tip in (
            ("vout_v", "V"),
            ("ratio", "0.5"),
            ("vin_v", "V"),
            ("i_min", "A"),
            ("i_max", "A"),
            ("points", ""),
            ("margin_pct", "%"),
        ):
            edit = QLineEdit()
            edit.setPlaceholderText(tip)
            edit.textChanged.connect(self._invalidate)
            self.fields[key] = edit
            form.addRow(t(f"eff_plan_{key}"), edit)
        self.learn = QCheckBox(t("eff_plan_learn"))
        self.learn.setToolTip(t("eff_plan_learn_help"))
        self.learn.toggled.connect(self._kind_changed)
        form.addRow(self.learn)
        self.vin_param = QComboBox()
        self.vin_param.addItems(list(parameters))
        self.vin_param.currentTextChanged.connect(self._invalidate)
        form.addRow(t("eff_plan_vin_param"), self.vin_param)
        learn_points = QLineEdit()
        learn_points.setPlaceholderText("5")
        learn_points.textChanged.connect(self._invalidate)
        self.fields["learn_points"] = learn_points
        form.addRow(t("eff_plan_learn_points"), learn_points)
        self._form = form
        layout.addLayout(form)
        row = QHBoxLayout()
        self.calculate_button = QPushButton(t("eff_plan_calculate"))
        self.calculate_button.clicked.connect(self.calculate)
        row.addWidget(self.calculate_button)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        layout.addLayout(row)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                t(f"eff_plan_col_{c}")
                for c in ("target", "combo", "ohm", "current", "dev", "load", "moves")
            ]
        )
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        previous = previous or {}
        if previous.get("kit") in registry.names():
            self.kits.setCurrentText(previous["kit"])
        self.kind.setCurrentIndex(max(0, self.kind.findData(previous.get("kind", "regulated"))))
        defaults = {"margin_pct": 80, "points": 10, "i_min": 0}
        for key, edit in self.fields.items():
            value = previous.get(key, defaults.get(key))
            edit.setText("" if value is None else f"{value:g}")
        self.learn.setChecked(bool(previous.get("learn")))
        if previous.get("vin_param"):
            self.vin_param.setCurrentText(previous["vin_param"])
        self._kind_changed()
        self._invalidate()

    def _kind_changed(self, *_args: Any) -> None:
        regulated = self.kind.currentData() == "regulated"
        learning = self.learn.isChecked()
        for widget, shown in (
            (self.fields["vout_v"], regulated),
            (self.fields["ratio"], not regulated),
            (self.fields["vin_v"], not regulated or learning),
            (self.vin_param, learning),
            (self.fields["learn_points"], learning),
        ):
            self._form.setRowVisible(widget, shown)
        self._invalidate()

    def _invalidate(self, *_args: Any) -> None:
        """An input changed: the table on screen is no longer the plan of the inputs."""
        self.plan = None
        self.table.setRowCount(0)
        self.summary.setText("")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

    def _number(self, key: str) -> Optional[float]:
        text = self.fields[key].text().strip()
        return parse_si(text) if text else None

    def inputs(self) -> Dict[str, Any]:
        """What the user typed (numbers, ``None`` for an empty or unreadable field)."""
        info: Dict[str, Any] = {"kit": self.kits.currentText(), "kind": self.kind.currentData()}
        for key in self.fields:
            info[key] = self._number(key)
        if self.learn.isChecked():
            info["learn"] = True
            info["vin_param"] = self.vin_param.currentText()
        else:  # the quick sweep's inputs mean nothing without it
            info["vin_v"] = info["vin_v"] if info["kind"] == "unregulated" else None
            info["learn_points"] = None
        return info

    def vout(self, info: Dict[str, Any]) -> Optional[float]:
        """The output voltage: the nominal one, or the ratio times the input voltage."""
        if info["kind"] == "regulated":
            return info["vout_v"]
        if info["ratio"] is None or info["vin_v"] is None:
            return None
        return info["ratio"] * info["vin_v"]

    def calculate(self) -> None:
        """Make the plan of the inputs and show it; the OK button is enabled if it worked."""
        self._invalidate()
        info = self.inputs()
        kit = self.registry.get(info["kit"])
        needed = ("i_min", "i_max", "points", "margin_pct")
        learning_missing = info.get("learn") and (not info["vin_param"] or info["vin_v"] is None)
        if (
            kit is None
            or self.vout(info) is None
            or any(info[k] is None for k in needed)
            or learning_missing
        ):
            self.summary.setText(self._t("eff_plan_missing"))
            return
        self.resistors = [
            {"kit": kit.name, "ref": r.name, "name": r.name, "r_ohm": r.r_ohm, "power_w": r.power_w}
            for r in kit.resistors
        ]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.plan = plan_loads(
                self.resistors,
                self.vout(info),
                info["i_min"],
                info["i_max"],
                int(info["points"]),
                margin=info["margin_pct"] / 100,
            )
        except PlanError as exc:
            self.summary.setText(str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        names = [r.name for r in kit.resistors]
        self.table.setRowCount(len(self.plan.points))
        for row, p in enumerate(self.plan.points):
            cells = (
                f"{p.target_a:.3f} A",
                tree_text(p.tree, names),
                f"{p.r_ohm:.4g}",
                f"{p.current_a:.3f} A",
                f"{p.deviation_pct:+.1f} %",
                f"{p.load_pct:.0f} %",
                str(p.changes),
            )
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))
        text = self._t("eff_plan_done", n=len(self.plan.points), moves=self.plan.changes)
        if self.plan.open_circuit:
            text += " " + self._t("eff_plan_open")
        self.summary.setText(text)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(self.plan.points))

    def loads(self) -> List[dict]:
        """The loads of the plan, as references to the kit."""
        refs = [{"kit": r["kit"], "ref": r["ref"]} for r in self.resistors]
        return loads_from_plan(self.plan, refs) if self.plan else []


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
        self._registry = registry  # given: always this one; None: the file, read at every use
        self._parameters: List[str] = []  # the parameters the program sets (the input of a plan)
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
            ("plan", self.plan_from_range),
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
        self._form = form
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

    def set_parameters(self, names: Sequence[str]) -> None:
        """The parameters the program sets: one of them is the input voltage of a learning run."""
        self._parameters = list(names)

    # ---- the kits ----------------------------------------------------------------------------
    @property
    def registry(self) -> KitRegistry:
        """The kits of resistors: the file is read again every time, so that a kit made in
        *Tools > Resistor kits* while the editor is open is seen. ``KitError`` if it is damaged."""
        return self._registry if self._registry is not None else KitRegistry()

    # ---- showing and reading the block -------------------------------------------------------
    def set_block(self, block: Optional[dict]) -> None:
        """Show the ``load`` block (a copy is kept and edited)."""
        self._loading = True
        self.block = copy.deepcopy(block) if isinstance(block, dict) else {"loads": []}
        switching = self.block.get("switching") or {}
        self.mode.setCurrentIndex(max(0, self.mode.findData(switching.get("mode", "manual"))))
        # the instrument of the relays only means something with the switch matrix, which cannot
        # be chosen yet: the row is shown only for a file that already has it
        self._form.setRowVisible(self.instrument, switching.get("mode") == "mux")
        self.instrument.setCurrentText(str(switching.get("instrument", "")))
        self.settle.setText("" if "settle_s" not in switching else f"{switching['settle_s']:g}")
        self.vout.setText(str(self.block.get("vout", "")))
        value = self.block.get("max_vout_v")
        self.max_vout.setText("" if value is None else f"{value:g}")
        self._fill_table()
        self._loading = False

    def _fill_table(self) -> None:
        loads = self.block.get("loads") or []
        try:
            kits: Optional[KitRegistry] = self.registry
        except KitError:
            kits = None  # the values of the kit cannot be shown, the references are kept
        self.table.setRowCount(len(loads))
        for row, load in enumerate(loads):
            self.table.setItem(row, 0, QTableWidgetItem(node_text(load)))
            self.table.setItem(row, 1, QTableWidgetItem(self._ohms(load, kits)))

    def _ohms(self, load: Any, kits: Optional[KitRegistry]) -> str:
        """The nominal resistance; for resistors of a kit, from the kit as it is now."""
        from ola.resistors import LoadError, has_refs, parse_load

        try:
            if has_refs(load):
                if kits is None:
                    return "?"
                load = kits.resolve_node(load)
            nominal = parse_load(load).resistance()[0]
            return "∞" if nominal == float("inf") else f"{nominal:.4g}"
        except (KitError, LoadError) as exc:
            return self._t("eff_load_not_found", error=exc)

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

    def plan_from_range(self) -> None:
        """Calculate the loads for a range of output current from a kit (replaces the list)."""
        try:
            names = self.registry.names()
        except KitError as exc:
            show_problem(self, self._t("eff_load"), str(exc), code="MEAS-001", exception=exc)
            return
        if not names:
            QMessageBox.information(self, self._t("eff_load"), self._t("eff_load_no_kits"))
            return
        dialog = _PlanDialog(self.registry, self._t, self.block.get("plan"), self._parameters, self)
        if dialog.exec() and dialog.plan is not None:
            info = {k: v for k, v in dialog.inputs().items() if v is not None}
            self.block["loads"] = dialog.loads()
            self.block["plan"] = info
            self._fill_table()
            self.changed.emit()

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
