"""Tool to compare saved results (menu *Tools* > *Compare results*).

Pick two or more run files (``runs/*.jsonl``) and see them together. A thin layer over
``ola.compare`` (which does the work and is tested without a screen):

* **Curves**: the curves the runs have in common (a cable's S21, a filter's gain...) drawn on top
  of each other, in any view (dB, loss, phase, Smith chart...) with a read-out under the mouse; or
  the **difference** of each run from the *reference* run (other - reference) with the largest
  difference, the mean and the RMS;
* **Summary**: the figures of the summary rows side by side, each with its change from the
  reference;
* **Tables**: for runs with many points (an efficiency measurement) any column against another,
  one line per run (and per value of a third column);
* **Golden sample**: the reference run is the good unit and every other ticked run is checked
  against it (``ola.golden``): a tolerance on a curve and on figures of the summary, a verdict for
  each run with the reasons. The reference can be kept in the ``golden/`` folder of the project,
  and a golden sample kept there can be opened as the reference.

The first run is the reference until another is chosen. Runs can be renamed (the default name is
the cable / filter / device name and the date). The overlay can be saved as CSV and the plot as an
image. Strings: ``frontend/lang/modules/compare/<lang>.json`` (the names of the views are those of
the run window).
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.module_translator import CatalogTranslator
from frontend.ui.trace_plot import SmithChart, TracePlot
from ola import compare, golden
from ola.compare import CompareError, RunData
from ola.run_view import VIEW_SMITH, format_si, trace_views, trace_xy

NO_GROUP = ""
REFERENCE_MARK = "★ "
SIDES = ("both", "upper", "lower")  # which side of the golden curve the tolerance limits
WIDE = 1e9  # the tolerance of the side that is not limited


def figure(value: Any, key: str = "") -> str:
    """A value for a cell of the summary table: numbers with 6 significant digits, a frequency (a
    figure whose name ends in ``_hz``) with its unit (``868 MHz``)."""
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    return format_si(float(value), "Hz") if key.endswith("_hz") else f"{value:.6g}"


def signed(value: float, key: str = "") -> str:
    """A change, with its sign: ``+0.31``, ``-2``, ``+50 MHz``."""
    if key.endswith("_hz"):
        return ("+" if value > 0 else "") + format_si(float(value), "Hz")
    return f"{value:+.4g}"


def changed(value: float, reference: float) -> bool:
    """False for a change too small to be one (rounding noise): it is not worth showing."""
    return abs(value) > 1e-9 * max(1.0, abs(reference))


class CompareDialog(QDialog):
    """The comparison window (see the module docstring)."""

    def __init__(
        self,
        paths: Sequence[str] = (),
        translator: Any = None,
        parent: Optional[QWidget] = None,
        start_dir: str = "",
    ):
        super().__init__(parent)
        self.tr_ = CatalogTranslator("compare", translator)
        self.views_tr = CatalogTranslator("run", translator)  # the names of the views
        self._t = self.tr_.t
        self.start_dir = start_dir
        self.runs: List[RunData] = []
        self.reference = 0
        self._loading = False
        self._log_set = False
        self.setWindowTitle(self._t("cmp_title"))
        self.resize(1100, 760)
        self._build_ui()
        self.add_files(list(paths))

    # ================================================================ building the window
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        side = QVBoxLayout()
        side.addWidget(QLabel(self._t("cmp_runs")))
        self.run_list = QListWidget()
        self.run_list.setMaximumWidth(300)
        self.run_list.itemChanged.connect(lambda _i: self._refresh())
        side.addWidget(self.run_list, 1)
        for key, handler in (
            ("cmp_add", self.add_dialog),
            ("cmp_remove", self.remove_selected),
            ("cmp_reference", self.make_reference),
            ("cmp_rename", self.rename_selected),
        ):
            button = QPushButton(self._t(key))
            button.clicked.connect(lambda _c=False, h=handler: h())
            side.addWidget(button)
        self.mixed_label = QLabel()
        self.mixed_label.setWordWrap(True)
        side.addWidget(self.mixed_label)
        root.addLayout(side)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_curves_tab(), self._t("cmp_tab_curves"))
        self.summary = QTableWidget(0, 0)
        self.summary.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.summary, self._t("cmp_tab_summary"))
        self.tabs.addTab(self._build_tables_tab(), self._t("cmp_tab_tables"))
        self.tabs.addTab(self._build_golden_tab(), self._t("cmp_tab_golden"))
        root.addWidget(self.tabs, 1)

    def _build_curves_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.trace_box, self.view_box, self.mode_box = QComboBox(), QComboBox(), QComboBox()
        self.mode_box.addItem(self._t("cmp_mode_overlay"), "overlay")
        self.mode_box.addItem(self._t("cmp_mode_difference"), "difference")
        self.log_box = QCheckBox(self._t("cmp_log_x"))
        for label, widget in (
            ("cmp_trace", self.trace_box),
            ("cmp_view", self.view_box),
            ("cmp_mode", self.mode_box),
        ):
            row.addWidget(QLabel(self._t(label)))
            row.addWidget(widget, 1)
            widget.activated.connect(lambda _i: self._draw_curves())
        self.log_box.toggled.connect(lambda _on: self._draw_curves())
        row.addWidget(self.log_box)
        layout.addLayout(row)
        self.plot, self.smith = TracePlot(), SmithChart()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.plot)
        self.stack.addWidget(self.smith)
        layout.addWidget(self.stack, 1)
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        layout.addWidget(self.stats_label)
        buttons = QHBoxLayout()
        self.csv_btn = QPushButton(self._t("cmp_export_csv"))
        self.csv_btn.clicked.connect(self.export_csv)
        self.image_btn = QPushButton(self._t("cmp_save_image"))
        self.image_btn.clicked.connect(self.save_image)
        buttons.addStretch(1)
        buttons.addWidget(self.csv_btn)
        buttons.addWidget(self.image_btn)
        layout.addLayout(buttons)
        return page

    def _build_tables_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.x_box, self.y_box, self.group_box = QComboBox(), QComboBox(), QComboBox()
        for label, box in (
            ("cmp_x", self.x_box),
            ("cmp_y", self.y_box),
            ("cmp_group", self.group_box),
        ):
            row.addWidget(QLabel(self._t(label)))
            row.addWidget(box, 1)
            box.activated.connect(lambda _i: self._draw_tables())
        layout.addLayout(row)
        self.table_plot = TracePlot()
        layout.addWidget(self.table_plot, 1)
        return page

    def _build_golden_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(self._t("cmp_g_intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        self.g_trace_box, self.g_view_box, self.g_side_box = QComboBox(), QComboBox(), QComboBox()
        self.g_trace_box.activated.connect(lambda _i: self._fill_golden_views())
        for side in SIDES:
            self.g_side_box.addItem(self._t(f"cmp_g_side_{side}"), side)
        self.g_tolerance = QDoubleSpinBox()
        self.g_tolerance.setRange(0.0, 1e6)
        self.g_tolerance.setDecimals(3)
        self.g_tolerance.setValue(0.5)
        self.g_curve_box = QCheckBox(self._t("cmp_g_check_curve"))
        self.g_curve_box.setChecked(True)
        row.addWidget(self.g_curve_box)
        for label, widget in (
            ("cmp_trace", self.g_trace_box),
            ("cmp_view", self.g_view_box),
            ("cmp_g_tolerance", self.g_tolerance),
            ("cmp_g_side", self.g_side_box),
        ):
            row.addWidget(QLabel(self._t(label)))
            row.addWidget(widget, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel(self._t("cmp_g_overlap")))
        self.g_overlap = QSpinBox()
        self.g_overlap.setRange(1, 100)
        self.g_overlap.setValue(round(golden.DEFAULT_OVERLAP * 100))
        self.g_overlap.setSuffix(" %")
        row.addWidget(self.g_overlap)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(QLabel(self._t("cmp_g_figures")))
        self.g_figures = QTableWidget(0, 2)
        self.g_figures.setHorizontalHeaderLabels(
            [self._t("cmp_key"), self._t("cmp_g_figure_tolerance")]
        )
        self.g_figures.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.g_figures, 1)
        self.g_result = QPlainTextEdit()
        self.g_result.setReadOnly(True)
        layout.addWidget(self.g_result, 1)
        buttons = QHBoxLayout()
        self.g_open_btn = QPushButton(self._t("cmp_g_open"))
        self.g_open_btn.clicked.connect(self.open_golden)
        self.g_save_btn = QPushButton(self._t("cmp_g_save"))
        self.g_save_btn.clicked.connect(self.save_golden)
        self.g_check_btn = QPushButton(self._t("cmp_g_check"))
        self.g_check_btn.clicked.connect(self.check_golden)
        for button in (self.g_open_btn, self.g_save_btn):
            button.setEnabled(bool(self.project_dir()))
        buttons.addWidget(self.g_open_btn)
        buttons.addWidget(self.g_save_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.g_check_btn)
        layout.addLayout(buttons)
        return page

    # ================================================================ the runs
    def add_dialog(self) -> None:
        """Choose run files to add."""
        paths, _ = QFileDialog.getOpenFileNames(
            self, self._t("cmp_open_title"), self.start_dir, "Run files (*.jsonl)"
        )
        self.add_files(paths)

    def add_files(self, paths: Sequence[str]) -> None:
        """Load run files; the ones that cannot be compared are reported together."""
        errors = []
        for path in paths:
            if any(str(r.path) == str(path) for r in self.runs):
                continue  # already there
            try:
                self.runs.append(compare.load_run(path))
            except CompareError as exc:
                errors.append(str(exc))
        if errors:
            QMessageBox.warning(
                self, self._t("cmp_title"), self._t("cmp_load_failed", errors="\n".join(errors))
            )
        self._fill_list()

    def _fill_list(self) -> None:
        current = self.run_list.currentRow()  # kept too, so that a rename does not lose it
        checked = {}  # what was ticked, kept when the list is drawn again
        for i in range(self.run_list.count()):
            item = self.run_list.item(i)
            checked[item.data(Qt.ItemDataRole.UserRole)] = item.checkState()
        self._loading = True
        self.run_list.clear()
        for n, run in enumerate(self.runs):
            mark = REFERENCE_MARK if n == self.reference else ""
            item = QListWidgetItem(mark + run.label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, str(run.path))
            item.setToolTip(str(run.path))
            item.setCheckState(checked.get(str(run.path), Qt.CheckState.Checked))
            self.run_list.addItem(item)
        self._loading = False
        if self.run_list.count() and current >= 0:
            self.run_list.setCurrentRow(min(current, self.run_list.count() - 1))
        self._refresh()

    def _selected_index(self) -> Optional[int]:
        row = self.run_list.currentRow()
        return row if 0 <= row < len(self.runs) else None

    def remove_selected(self) -> None:
        n = self._selected_index()
        if n is None:
            return
        del self.runs[n]
        if n < self.reference:
            self.reference -= 1
        elif n == self.reference:
            self.reference = 0
        self.reference = min(self.reference, max(len(self.runs) - 1, 0))
        self._fill_list()

    def make_reference(self) -> None:
        """The selected run becomes the one the others are compared with."""
        n = self._selected_index()
        if n is not None:
            self.reference = n
            self._fill_list()

    def rename_selected(self) -> None:
        n = self._selected_index()
        if n is None:
            return
        text, ok = QInputDialog.getText(
            self, self._t("cmp_rename"), self._t("cmp_rename_prompt"), text=self.runs[n].label
        )
        if ok and text.strip():
            self.runs[n].label = text.strip()
            self._fill_list()

    def checked_runs(self) -> List[RunData]:
        """The runs that are ticked, in list order."""
        return [
            self.runs[i]
            for i in range(self.run_list.count())
            if self.run_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _reference_run(self, runs: Sequence[RunData]) -> Optional[RunData]:
        """The reference if it is ticked, else the first ticked run."""
        ref = self.runs[self.reference] if self.runs else None
        return ref if ref in runs else (runs[0] if runs else None)

    # ================================================================ showing
    def _refresh(self) -> None:
        if self._loading:
            return
        runs = self.checked_runs()
        mixed = compare.mixed_types(runs)
        self.mixed_label.setText(self._t("cmp_mixed") if mixed else "")
        self._fill_trace_box(runs)
        if not self._log_set and any(
            t.get("meta", {}).get("log_x") for r in runs for t in r.traces.values()
        ):  # a frequency sweep that was made logarithmic starts on a logarithmic axis
            self._log_set = True
            self.log_box.setChecked(True)
        self._draw_curves()
        self._fill_summary(runs)
        self._fill_table_boxes(runs)
        self._draw_tables()
        self._fill_golden_boxes(runs)

    def _fill_trace_box(self, runs: Sequence[RunData]) -> None:
        keep = self.trace_box.currentData()
        self.trace_box.blockSignals(True)
        self.trace_box.clear()
        for name, count in compare.trace_names(runs):
            self.trace_box.addItem(f"{name}  ({self._t('cmp_count', n=count, m=len(runs))})", name)
        position = self.trace_box.findData(keep)
        self.trace_box.setCurrentIndex(max(position, 0))
        self.trace_box.blockSignals(False)

    def _kind_of(self, runs: Sequence[RunData], name: str) -> str:
        return (
            "complex"
            if any(r.traces.get(name, {}).get("kind") == "complex" for r in runs)
            else "real"
        )

    def _fill_view_box(self, kind: str) -> None:
        views = trace_views(kind)
        if [self.view_box.itemData(i) for i in range(self.view_box.count())] != views:
            keep = self.view_box.currentData()
            self.view_box.blockSignals(True)
            self.view_box.clear()
            for view in views:
                self.view_box.addItem(self.views_tr.t(f"run_view_{view}"), view)
            self.view_box.setCurrentIndex(max(self.view_box.findData(keep), 0))
            self.view_box.blockSignals(False)

    def _draw_curves(self) -> None:
        runs = self.checked_runs()
        name = self.trace_box.currentData()
        self.stats_label.setText("")
        if not runs or name is None:
            self.plot.set_curves([])
            self.smith.set_curves([])
            self.stack.setCurrentWidget(self.plot)
            self.stats_label.setText(self._t("cmp_none_common") if runs else "")
            self.csv_btn.setEnabled(False)
            return
        self._fill_view_box(self._kind_of(runs, name))
        view = self.view_box.currentData()
        having = [r for r in runs if name in r.traces]
        self.csv_btn.setEnabled(bool(having))
        if view == VIEW_SMITH:  # no difference on the chart: it is the curves themselves
            self.stack.setCurrentWidget(self.smith)
            self.smith.set_curves([(r.label, *trace_xy(r.traces[name], view)) for r in having
                                   if r.traces[name]["kind"] == "complex"])  # fmt: skip
            return
        self.stack.setCurrentWidget(self.plot)
        meta = having[0].traces[name].get("meta", {}) if having else {}
        ylabel = meta.get("ylabel") if view == "value" else self.views_tr.t(f"run_view_{view}")
        xlabel, unit = meta.get("xlabel", ""), meta.get("x_unit", "")
        log = self.log_box.isChecked() or bool(
            meta.get("log_x") and not self.log_box.isChecked() and False
        )
        if self.mode_box.currentData() == "difference":
            self._draw_difference(runs, having, name, view, xlabel, unit, ylabel or "", log)
        else:
            curves = [(r.label, *compare.curve(r, name, view)) for r in having]
            self.plot.set_curves(curves, xlabel, ylabel or "", log_x=log, x_unit=unit)

    def _draw_difference(self, runs, having, name, view, xlabel, unit, ylabel, log) -> None:
        reference = self._reference_run(having)
        if reference is None:
            self.plot.set_curves([])
            return
        ref_curve = compare.curve(reference, name, view)
        curves, lines = [], []
        for run in having:
            if run is reference:
                continue
            xs, diffs = compare.difference(ref_curve, compare.curve(run, name, view))
            if not xs:
                lines.append(self._t("cmp_diff_nooverlap", label=run.label))
                continue
            curves.append((run.label, xs, diffs))
            st = compare.difference_stats(xs, diffs)
            lines.append(self._t(
                "cmp_diff_stats", label=run.label, max=signed(st["max_abs"]),
                at=format_si(st["at_x"], unit) if unit else f"{st['at_x']:.6g}",
                mean=signed(st["mean"]), rms=f"{st['rms']:.4g}",
            ))  # fmt: skip
        self.plot.set_curves(curves, xlabel, "Δ " + ylabel, log_x=log, x_unit=unit)
        head = self._t("cmp_diff_header", ref=reference.label)
        self.stats_label.setText(head + "\n" + "\n".join(lines))

    def _fill_summary(self, runs: Sequence[RunData]) -> None:
        reference = self._reference_run(runs)
        index = runs.index(reference) if reference in runs else 0
        rows = compare.summary_table(runs, index) if runs else []
        self.summary.clear()
        self.summary.setRowCount(len(rows))
        self.summary.setColumnCount(len(runs) + 1)
        self.summary.setHorizontalHeaderLabels(
            [self._t("cmp_key")]
            + [(REFERENCE_MARK if n == index else "") + r.label for n, r in enumerate(runs)]
        )
        for row_no, row in enumerate(rows):
            self.summary.setItem(row_no, 0, QTableWidgetItem(row["key"]))
            for col, (value, delta) in enumerate(zip(row["values"], row["deltas"]), 1):
                shown = delta is not None and changed(delta, value or 0.0)
                text = figure(value, row["key"]) + (
                    f"  ({signed(delta, row['key'])})" if shown else ""
                )
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.summary.setItem(row_no, col, item)
        self.summary.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

    def _fill_table_boxes(self, runs: Sequence[RunData]) -> None:
        columns = compare.points_columns(runs)
        if [self.x_box.itemData(i) for i in range(self.x_box.count())] == columns:
            return
        for box, none in (
            (self.x_box, None),
            (self.y_box, None),
            (self.group_box, self._t("cmp_none_group")),
        ):
            keep = box.currentData()
            box.blockSignals(True)
            box.clear()
            if none is not None:
                box.addItem(none, NO_GROUP)
            for column in columns:
                box.addItem(column, column)
            box.setCurrentIndex(max(box.findData(keep), 0))
            box.blockSignals(False)
        if columns:  # a sensible start: the first column against the last
            self.x_box.setCurrentIndex(0)
            self.y_box.setCurrentIndex(len(columns) - 1)

    def _draw_tables(self) -> None:
        x, y, group = (
            self.x_box.currentData(),
            self.y_box.currentData(),
            self.group_box.currentData(),
        )
        curves = []
        if x and y:
            for run in self.checked_runs():
                if len(run.points) > 1:
                    for label, xs, ys in compare.points_series(
                        run, x, y, [group] if group else None
                    ):
                        curves.append((f"{run.label}: {label}" if group else run.label, xs, ys))
        self.table_plot.set_curves(curves, x or "", y or "")

    # ================================================================ export
    def export_csv(self) -> None:
        """Save the curve on show (one column pair per run) as CSV."""
        name, view = self.trace_box.currentData(), self.view_box.currentData()
        if name is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("cmp_export_csv"), f"{name}.csv", "CSV (*.csv)"
        )
        if path:
            self._do(
                lambda: compare.export_overlay_csv(path, self.checked_runs(), name, view), path
            )

    def save_image(self) -> None:
        """Save the plot as an image."""
        widget = self.stack.currentWidget()
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("cmp_save_image"), "comparison.png", "PNG (*.png)"
        )
        if path:
            self._do(lambda: widget.grab().save(path) or True, path)

    # ================================================================ the golden sample
    def project_dir(self) -> str:
        """The folder of the open project: the parent of its ``runs`` folder ('' if none)."""
        if not self.start_dir:
            return ""
        start = Path(self.start_dir)
        return str(start.parent if start.name == "runs" else start)

    def _fill_golden_boxes(self, runs: Sequence[RunData]) -> None:
        keep = self.g_trace_box.currentData()
        self.g_trace_box.clear()
        for name, _count in compare.trace_names(runs):
            self.g_trace_box.addItem(name, name)
        self.g_trace_box.setCurrentIndex(max(self.g_trace_box.findData(keep), 0))
        self._fill_golden_views()
        reference = self._reference_run(runs)
        kept: Dict[str, str] = {}
        for row in range(self.g_figures.rowCount()):
            key, tol = self.g_figures.item(row, 0), self.g_figures.item(row, 1)
            if key is not None and tol is not None and tol.text().strip():
                kept[key.text()] = tol.text()
        keys = [k for k, v in (reference.summary if reference else {}).items()
                if compare._is_number(v)]  # fmt: skip
        self.g_figures.setRowCount(len(keys))
        for row, key in enumerate(keys):
            item = QTableWidgetItem(key)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.g_figures.setItem(row, 0, item)
            self.g_figures.setItem(row, 1, QTableWidgetItem(kept.get(key, "")))

    def _fill_golden_views(self) -> None:
        name = self.g_trace_box.currentData()
        runs = self.checked_runs()
        views = trace_views(self._kind_of(runs, name)) if name else []
        views = [v for v in views if v != VIEW_SMITH]
        keep = self.g_view_box.currentData()
        self.g_view_box.clear()
        for view in views:
            self.g_view_box.addItem(self.views_tr.t(f"run_view_{view}"), view)
        default = "loss_db" if "loss_db" in views else keep
        self.g_view_box.setCurrentIndex(max(self.g_view_box.findData(keep or default), 0))

    def golden_spec(self) -> Dict[str, Any]:
        """The tolerances written in the tab, as the spec of ``ola.golden``. A figure tolerance is a
        number (absolute) or ``5%`` (relative); ``ValueError`` for anything else."""
        spec: Dict[str, Any] = {"min_overlap": self.g_overlap.value() / 100.0}
        name = self.g_trace_box.currentData()
        if self.g_curve_box.isChecked() and name:
            value = self.g_tolerance.value()
            side = self.g_side_box.currentData()
            tolerance: Any = (
                value
                if side == "both"
                else (
                    {"upper": value, "lower": WIDE}
                    if side == "upper"
                    else {"upper": WIDE, "lower": value}
                )
            )
            spec["curves"] = [
                {"trace": name, "view": self.g_view_box.currentData() or "value",
                 "tolerance": tolerance}
            ]  # fmt: skip
        figures: Dict[str, Any] = {}
        for row in range(self.g_figures.rowCount()):
            key, tol = self.g_figures.item(row, 0), self.g_figures.item(row, 1)
            text = tol.text().strip().replace(",", ".") if tol is not None else ""
            if not text or key is None:
                continue
            try:
                figures[key.text()] = (
                    {"rel": float(text[:-1]) / 100.0} if text.endswith("%") else float(text)
                )
            except ValueError as exc:
                raise ValueError(
                    self._t("cmp_g_bad_tolerance", figure=key.text(), text=text)
                ) from exc
        if figures:
            spec["summary"] = figures
        return spec

    def check_golden(self) -> List[golden.GoldenResult]:
        """Check every ticked run but the reference against the reference; show the results."""
        runs = self.checked_runs()
        reference = self._reference_run(runs)
        others = [r for r in runs if r is not reference]
        if reference is None or not others:
            self.g_result.setPlainText(self._t("cmp_g_need_two"))
            return []
        try:
            spec = self.golden_spec()
            results = [golden.check_against_golden(run, reference, spec) for run in others]
        except (ValueError, golden.GoldenError) as exc:
            self.g_result.setPlainText(self._t("cmp_g_error", error=exc))
            return []
        passed = sum(r.passed for r in results)
        head = self._t("cmp_g_header", ref=reference.label, passed=passed, n=len(results))
        self.g_result.setPlainText(
            head + "\n\n" + "\n\n".join(golden.format_result(r) for r in results)
        )
        return results

    def save_golden(self) -> None:
        """Keep the reference run in the ``golden/`` folder of the project under a name."""
        runs = self.checked_runs()
        reference = self._reference_run(runs)
        project = self.project_dir()
        if reference is None or not project:
            return
        name, ok = QInputDialog.getText(
            self, self._t("cmp_g_save"), self._t("cmp_g_name_prompt"),
            text=reference.name or reference.measurement,
        )  # fmt: skip
        if not ok or not name.strip():
            return
        try:
            path = golden.set_golden(project, name, reference.path)
        except (golden.GoldenError, CompareError, OSError) as exc:
            self.g_result.setPlainText(self._t("cmp_g_error", error=exc))
            return
        self.g_result.setPlainText(self._t("cmp_g_saved", path=path))

    def open_golden(self) -> None:
        """Add a golden sample of the project and make it the reference."""
        folder = Path(self.project_dir()) / golden.GOLDEN_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("cmp_g_open"), str(folder), "Run files (*.jsonl)"
        )
        if path:
            self.use_as_golden(path)

    def use_as_golden(self, path: str) -> None:
        """Add a run file (if it is not there) and make it the reference."""
        self.add_files([path])
        for n, run in enumerate(self.runs):
            if str(run.path) == str(path):
                self.reference = n
                if Path(path).parent.name == golden.GOLDEN_DIR:
                    run.label = f"{self._t('cmp_g_golden')} {Path(path).stem}"
                self._fill_list()
                return

    def _do(self, action, path: str) -> None:
        try:
            action()
        except Exception as exc:
            QMessageBox.critical(
                self, self._t("cmp_title"), self._t("cmp_export_failed", error=exc)
            )
            return
        self.stats_label.setText(self._t("cmp_saved", path=path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the tool, with run files given on the command line."""
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = CompareDialog(argv)
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
