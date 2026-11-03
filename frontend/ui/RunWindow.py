"""Window that runs a measurement and shows it live.

A thin layer over ``ola.run_view.RunModel`` (which decides what is shown and is tested without a
screen) and a ``Runner``. A timer takes the runner's events every 100 ms; the window shows:

* the state, a progress bar, time elapsed and left, and the buttons Start / Pause / Stop;
* *Results*: the table of points, growing while the measurement runs;
* *Plot*: any column against any other, one line per value of a third (for example efficiency
  against ``vin``, one line for each ``iout``);
* *Log*: messages, warnings and errors.

When the measurement asks something (a reading does not match the setpoint; an output that is
already on will be switched off) a **pop-up** shows the question with one button per choice; the
measurement waits until it is answered, and the pop-up closes by itself if the run is stopped.

Strings: ``frontend/lang/modules/run/<lang>.json``. Try it: ``python -m frontend.ui.RunWindow``
(simulated instruments; ``--fault`` makes the data logger disagree to see the pop-up).
"""

import sys
import time
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QStackedWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.efficiency_widgets import text_color
from frontend.ui.module_translator import CatalogTranslator
from frontend.ui.plot_widget import LinePlot
from frontend.ui.trace_plot import SmithChart, TracePlot
from ola.measurement import MeasurementError
from ola.run_view import (
    QUESTION_OUTPUTS_ON,
    QUESTION_VERIFY,
    VIEW_SMITH,
    RunModel,
    question_kind,
    trace_views,
    trace_xy,
)
from ola.runner import Runner
from ola.runs import export_points_csv, export_touchstone, export_trace_csv

POLL_MS = 100
TIMEOUT_CLOSE_S = 15  # how long closing the window waits for the run to stop
NO_GROUP = ""


def number(value: Any) -> str:
    """A value for a table cell: numbers with 6 significant digits, anything else as text."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "" if value is None else str(value)
    return f"{value:.6g}"


class QuestionDialog(QDialog):
    """Pop-up with a question of the measurement and one button per choice.

    It cannot be dismissed with the window's close button: an answer is needed (the default choice
    is the safe one, for example *abort*). ``close_now()`` closes it without an answer, used when
    the run was stopped meanwhile."""

    def __init__(self, question: Dict[str, Any], tr: CatalogTranslator, parent=None):
        super().__init__(parent)
        self.question, self.chosen = question, None
        self._force = False
        t = tr.t
        kind = question_kind(question)
        self.setWindowTitle(t(f"run_q_{kind}_title"))
        self.setModal(True)
        layout = QVBoxLayout(self)
        text = QLabel(question.get("text", ""))
        text.setWordWrap(True)
        text.setMinimumWidth(460)
        layout.addWidget(text)
        details = self._details(kind, question.get("data") or {}, t)
        if details:
            label = QLabel(details)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            layout.addWidget(label)
        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons: Dict[str, QPushButton] = {}
        for choice in question["choices"]:
            label = t(f"run_choice_{choice}")
            button = QPushButton(choice if label == f"run_choice_{choice}" else label)
            if choice == question.get("default"):
                button.setDefault(True)
                font = button.font()
                font.setBold(True)
                button.setFont(font)
            button.clicked.connect(lambda _c=False, c=choice: self._choose(c))
            self.buttons[choice] = button
            row.addWidget(button)
        layout.addLayout(row)

    @staticmethod
    def _details(kind: str, data: Dict[str, Any], t) -> str:
        if kind == QUESTION_VERIFY:
            return t(
                "run_q_verify_details",
                variable=data.get("variable", "?"),
                reading=data.get("reading", "?"),
                set_value=number(data.get("set_value")),
                read_value=number(data.get("read_value")),
                error=number(data.get("error_abs")),
                tol_abs=number(data.get("tol_abs")),
                tol_rel=number((data.get("tol_rel") or 0) * 100),
            )
        if kind == QUESTION_OUTPUTS_ON:
            names = ", ".join(
                f"{o.get('variable')} ({o.get('instrument')})" for o in data.get("outputs", [])
            )
            return t("run_q_outputs_on_details", outputs=names)
        return ""

    def _choose(self, choice: str) -> None:
        self.chosen = choice
        self._force = True
        self.done(QDialog.DialogCode.Accepted)

    def close_now(self) -> None:
        """Close without an answer (the question is no longer open)."""
        self._force = True
        self.done(QDialog.DialogCode.Rejected)

    def reject(self) -> None:  # Escape or the window's X: not an answer
        if self._force:
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self._force:
            event.accept()
        else:
            event.ignore()


class RunWindow(QWidget):
    """Runs ``runner`` and shows it. Call ``start()`` (or pass ``auto_start=True``)."""

    def __init__(
        self,
        runner: Runner,
        translator: Any = None,
        run_file: Optional[str] = None,
        title: str = "",
        auto_start: bool = False,
        parent: Optional[QWidget] = None,
    ):
        """``run_file``: path of the run file written by a ``RunWriter`` listener (enables the
        CSV export of the results at the end). ``translator``: the application's translator."""
        super().__init__(parent)
        self.runner, self.run_file = runner, run_file
        self.tr_ = CatalogTranslator("run", translator)
        self._t = self.tr_.t
        self.model = RunModel()
        self._dialog: Optional[QuestionDialog] = None
        self._logs_shown = 0
        self._rows_shown = 0
        self._table_columns: list = []
        self._plot_dirty = False
        self._axes_chosen = False
        self._traces_dirty = False
        self._traces_checked: dict = {}  # trace name -> shown
        self._tab_chosen = False  # the user picked a tab: do not switch tabs by ourselves
        self.setWindowTitle(f"{self._t('run_title')} - {title}" if title else self._t("run_title"))
        self.resize(1000, 700)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(POLL_MS)
        self._refresh()
        if auto_start:
            self.start()

    # ================================================================ building the window
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.state_label = QLabel()
        font = self.state_label.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self.state_label.setFont(font)
        self.start_btn = QPushButton(self._t("run_start"))
        self.pause_btn = QPushButton(self._t("run_pause"))
        self.stop_btn = QPushButton(self._t("run_stop"))
        self.export_btn = QPushButton(self._t("run_export"))
        self.start_btn.clicked.connect(self.start)
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.stop_btn.clicked.connect(self.stop)
        self.export_btn.clicked.connect(self.export_csv)
        top.addWidget(self.state_label, 1)
        for button in (self.start_btn, self.pause_btn, self.stop_btn, self.export_btn):
            top.addWidget(button)
        root.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        root.addWidget(self.progress)
        info = QHBoxLayout()
        self.message_label = QLabel()
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        info.addWidget(self.message_label, 1)
        info.addWidget(self.time_label)
        root.addLayout(info)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.tabs.addTab(self.table, self._t("run_tab_results"))
        self.tabs.addTab(self._build_plot_tab(), self._t("run_tab_plot"))
        self.tabs.addTab(self._build_traces_tab(), self._t("run_tab_traces"))
        self.tabs.tabBarClicked.connect(lambda _i: setattr(self, "_tab_chosen", True))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.tabs.addTab(self.log_view, self._t("run_tab_log"))
        root.addWidget(self.tabs, 1)
        self.file_label = QLabel(self._t("run_file", path=self.run_file) if self.run_file else "")
        root.addWidget(self.file_label)

    def _build_plot_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.x_box, self.y_box, self.group_box = QComboBox(), QComboBox(), QComboBox()
        for label, box in (
            ("run_plot_x", self.x_box),
            ("run_plot_y", self.y_box),
            ("run_plot_group", self.group_box),
        ):
            row.addWidget(QLabel(self._t(label)))
            row.addWidget(box, 1)
            box.activated.connect(self._axes_changed)
        layout.addLayout(row)
        self.plot = LinePlot()
        layout.addWidget(self.plot, 1)
        return page

    def _build_traces_tab(self) -> QWidget:
        """Curves (S-parameters, spectra, waveforms): which ones, how to show them, export."""
        page = QWidget()
        layout = QHBoxLayout(page)
        side = QVBoxLayout()
        self.trace_list = QListWidget()
        self.trace_list.setMaximumWidth(220)
        self.trace_list.itemChanged.connect(self._trace_choice_changed)
        self.view_box = QComboBox()
        self.view_box.activated.connect(lambda _i: self._draw_traces())
        self.log_x_box = QCheckBox(self._t("run_traces_log_x"))
        self.log_x_box.toggled.connect(lambda _on: self._draw_traces())
        self.csv_btn = QPushButton(self._t("run_traces_export_csv"))
        self.csv_btn.clicked.connect(self.export_trace)
        self.touchstone_btn = QPushButton(self._t("run_traces_export_touchstone"))
        self.touchstone_btn.clicked.connect(self.export_touchstone_file)
        side.addWidget(self.trace_list, 1)
        side.addWidget(QLabel(self._t("run_traces_view")))
        side.addWidget(self.view_box)
        side.addWidget(self.log_x_box)
        side.addWidget(self.csv_btn)
        side.addWidget(self.touchstone_btn)
        layout.addLayout(side)
        self.trace_plot = TracePlot()
        self.smith = SmithChart()
        self.trace_stack = QStackedWidget()
        self.trace_stack.addWidget(self.trace_plot)
        self.trace_stack.addWidget(self.smith)
        layout.addWidget(self.trace_stack, 1)
        return page

    # ================================================================ buttons
    def start(self) -> None:
        """Start the measurement. If it cannot start (missing instrument, invalid parameters) the
        reasons are shown and nothing is sent to any instrument."""
        try:
            self.runner.start()
        except MeasurementError as exc:
            QMessageBox.critical(
                self, self._t("run_title"), self._t("run_cannot_start", errors=str(exc))
            )
        self._tick()

    def toggle_pause(self) -> None:
        if self.model.state == "paused":
            self.runner.resume()
        else:
            self.runner.pause()
        self._tick()

    def stop(self) -> None:
        self.runner.stop()
        self._tick()

    def export_csv(self) -> None:
        """Write the table of points to a CSV file chosen by the user."""
        if not self.run_file:
            return
        path, _ = QFileDialog.getSaveFileName(self, self._t("run_export"), "", "CSV (*.csv)")
        if not path:
            return
        try:
            n = export_points_csv(self.run_file, path)
        except Exception as exc:
            QMessageBox.critical(
                self, self._t("run_title"), self._t("run_export_failed", error=exc)
            )
            return
        self.banner.setText(self._t("run_export_done", n=n, path=path))

    # ================================================================ following the run
    def _tick(self) -> None:
        events = self.runner.drain()
        for event in events:
            self.model.apply(event)
        if events:
            self._update_table()
            self._update_log()
            self._plot_dirty = True
            if any(e.kind == "trace" for e in events):
                self._traces_dirty = True
        if self._plot_dirty and self.tabs.currentIndex() == 1:
            self._update_plot()
        if self._traces_dirty:
            self._update_traces()
        self._refresh()
        self._handle_questions()
        if self.model.finished and not events and self._dialog is None:
            self._timer.stop()  # nothing more can happen; the window stays as a record

    def _refresh(self) -> None:
        m, state = self.model, self.model.state
        color = {
            "failed": text_color("error", self),
            "waiting": text_color("warning", self),
            "paused": text_color("warning", self),
            "finished": text_color("ok", self),
        }.get(state, text_color("muted", self))
        self.state_label.setText(
            f"<span style='color:{color}'>{self._t(f'run_state_{state}')}</span>"
        )
        running = state in ("running", "paused", "waiting", "stopping")
        self.start_btn.setEnabled(state == "idle")
        self.pause_btn.setEnabled(state in ("running", "paused"))
        self.pause_btn.setText(self._t("run_resume" if state == "paused" else "run_pause"))
        self.stop_btn.setEnabled(running and state != "stopping")
        self.export_btn.setEnabled(bool(self.run_file) and m.finished and bool(m.points))
        fraction = m.fraction
        if fraction is None:
            self.progress.setRange(0, 0 if running else 1)
            self.progress.setValue(1 if m.state == "finished" else 0)  # no total: full when done
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(fraction * 1000))
            self.progress.setFormat(f"{fraction * 100:.0f} %  ({m.done:g} / {m.total:g})")
        self.message_label.setText(m.message)
        parts = [self._t("run_elapsed", time=m.format_duration(m.elapsed(time.time())))]
        remaining = m.remaining(time.time())
        if remaining is not None:
            parts.append(self._t("run_remaining", time=m.format_duration(remaining)))
        self.time_label.setText("   ".join(parts))
        if state == "failed" and m.error:
            self.banner.setText(
                f"<span style='color:{text_color('error', self)}'>"
                f"{self._t('run_failed_banner', message=m.error.get('message', ''))}</span>"
            )
        elif state == "stopped":
            self.banner.setText(self._t("run_stopped_banner", n=len(m.points)))
        elif state == "finished":
            self.banner.setText(self._t("run_finished_banner", n=len(m.points)))

    def _update_table(self) -> None:
        m = self.model
        if m.columns != self._table_columns:  # a new column appeared: draw the header again
            self._table_columns = list(m.columns)
            self.table.setColumnCount(len(m.columns) + 1)
            self.table.setHorizontalHeaderLabels(["#", *m.columns])
            self.table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.ResizeToContents
            )
            self._rows_shown = 0
            self.table.setRowCount(0)
        bar = self.table.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 2
        for row_index in range(self._rows_shown, len(m.points)):
            self.table.insertRow(row_index)
            cells = [str(row_index + 1), *(number(m.points[row_index].get(c)) for c in m.columns)]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row_index, column, item)
        self._rows_shown = len(m.points)
        if at_end:
            self.table.scrollToBottom()

    def _update_log(self) -> None:
        colors = {"error": "error", "warning": "warning"}
        start = self._logs_shown
        for stamp, level, message in self.model.logs[start:]:
            clock = time.strftime("%H:%M:%S", time.localtime(stamp))
            color = text_color(colors.get(level, "muted"), self)
            safe = message.replace("&", "&amp;").replace("<", "&lt;")
            self.log_view.appendHtml(
                f"<span style='color:{text_color('muted', self)}'>{clock}</span> "
                f"<span style='color:{color}'>{level.upper():8s}</span> {safe}"
            )
        self._logs_shown = len(self.model.logs)

    # ================================================================ plot
    def _fill_box(self, box: QComboBox, names: list, none_label: Optional[str] = None) -> None:
        keep = box.currentData()
        box.blockSignals(True)
        box.clear()
        if none_label is not None:
            box.addItem(none_label, NO_GROUP)
        for name in names:
            box.addItem(name, name)
        position = box.findData(keep)
        box.setCurrentIndex(position if position >= 0 else 0)
        box.blockSignals(False)

    def _update_plot(self) -> None:
        self._plot_dirty = False
        names = self.model.numeric_columns()
        for box, none in (
            (self.x_box, None),
            (self.y_box, None),
            (self.group_box, self._t("run_plot_none")),
        ):
            if [d for d in map(box.itemData, range(box.count())) if d != NO_GROUP] != names:
                self._fill_box(box, names, none)
        if not self._axes_chosen and names:
            x, y, group = self.model.suggest_axes()
            for box, value in (
                (self.x_box, x),
                (self.y_box, y),
                (self.group_box, group or NO_GROUP),
            ):
                position = box.findData(value)
                if position >= 0:
                    box.setCurrentIndex(position)
        self._draw_plot()

    def _axes_changed(self, _index: int) -> None:
        self._axes_chosen = True
        self._draw_plot()

    def _draw_plot(self) -> None:
        x, y, group = (
            self.x_box.currentData(),
            self.y_box.currentData(),
            self.group_box.currentData(),
        )
        if x is None or y is None:
            self.plot.set_series([])
            return
        self.plot.set_series(self.model.series(x, y, [group] if group else None), x, y)

    # ================================================================ curves
    def _update_traces(self) -> None:
        """A trace arrived: refresh the list (new ones are shown), then draw."""
        self._traces_dirty = False
        m = self.model
        self.trace_list.blockSignals(True)
        have = [self.trace_list.item(i).text() for i in range(self.trace_list.count())]
        for name in m.trace_order:
            if name not in have:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
                self.trace_list.addItem(item)
                if not have and m.traces[name].get("meta", {}).get("log_x"):
                    self.log_x_box.setChecked(True)
        self.trace_list.blockSignals(False)
        if not self._tab_chosen and not m.points:  # a measurement of curves only: show them
            self.tabs.setCurrentIndex(2)
        self._draw_traces()

    def _trace_choice_changed(self, _item) -> None:
        self._draw_traces()

    def _shown_traces(self) -> list:
        names = [
            self.trace_list.item(i).text()
            for i in range(self.trace_list.count())
            if self.trace_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        return [self.model.traces[n] for n in names if n in self.model.traces]

    def _draw_traces(self) -> None:
        shown = self._shown_traces()
        kinds = {t["kind"] for t in shown}
        views = trace_views("complex" if "complex" in kinds else "real")
        if [self.view_box.itemData(i) for i in range(self.view_box.count())] != views:
            keep = self.view_box.currentData()
            self.view_box.clear()
            for view in views:
                self.view_box.addItem(self._t(f"run_view_{view}"), view)
            position = self.view_box.findData(keep)
            self.view_box.setCurrentIndex(max(position, 0))
        view = self.view_box.currentData() or views[0]
        has_export = bool(self.run_file) and bool(self.model.traces)
        self.csv_btn.setEnabled(has_export and self.trace_list.currentRow() >= 0)
        self.touchstone_btn.setEnabled(has_export and self._touchstone_names() != {})
        if view == VIEW_SMITH:
            self.trace_stack.setCurrentWidget(self.smith)
            self.smith.set_curves(
                [(t["name"], *trace_xy(t, view)) for t in shown if t["kind"] == "complex"]
            )
            return
        self.trace_stack.setCurrentWidget(self.trace_plot)
        curves, limits, meta = [], [], {}
        for t in shown:
            x, y = trace_xy(t, view if t["kind"] == "complex" else "value")
            curves.append((t["name"], x, y))
            meta = meta or t.get("meta", {})
            wanted = t.get("meta", {}).get("limits") or {}
            if wanted.get("view") == view:
                for edge in ("min", "max"):
                    if wanted.get(edge):
                        xs, ys = zip(*wanted[edge])
                        limits.append((self._t("run_traces_limit"), list(xs), list(ys)))
        ylabel = meta.get("ylabel") if view == "value" else self._t(f"run_view_{view}")
        self.trace_plot.set_curves(
            curves,
            meta.get("xlabel", ""),
            ylabel or "",
            limits,
            log_x=self.log_x_box.isChecked(),
            x_unit=meta.get("x_unit", ""),
        )

    def _touchstone_names(self) -> dict:
        """The S-parameter traces of the run (complex traces called S11, S21, S12, S22)."""
        return {
            n: n
            for n in ("S11", "S21", "S12", "S22")
            if n in self.model.traces and self.model.traces[n]["kind"] == "complex"
        }

    def export_trace(self) -> None:
        """Write the selected trace to CSV."""
        item = self.trace_list.currentItem()
        if not self.run_file or item is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("run_traces_export_csv"), f"{item.text()}.csv", "CSV (*.csv)"
        )
        if path:
            self._export(lambda: export_trace_csv(self.run_file, path, item.text()), path)

    def export_touchstone_file(self) -> None:
        """Write the S-parameters of the run as a Touchstone file."""
        names = self._touchstone_names()
        if not self.run_file or not names:
            return
        ports = 2 if set(names) - {"S11"} else 1
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("run_traces_export_touchstone"),
            f"result.s{ports}p",
            f"Touchstone (*.s{ports}p)",
        )
        if path:
            self._export(lambda: export_touchstone(self.run_file, path, names), path)

    def _export(self, action, path: str) -> None:
        try:
            action()
        except Exception as exc:
            QMessageBox.critical(
                self, self._t("run_title"), self._t("run_export_failed", error=exc)
            )
            return
        self.banner.setText(self._t("run_traces_export_done", path=path))

    # ================================================================ questions
    def _handle_questions(self) -> None:
        """Show the oldest open question in a pop-up; close the pop-up if it is no longer open."""
        open_ids = {q["id"] for q in self.runner.pending_questions}
        if self._dialog is not None:
            if self._dialog.question["id"] not in open_ids:
                self._dialog.close_now()
                self._dialog = None
            else:
                return
        if not open_ids:
            return
        question = self.runner.pending_questions[0]
        dialog = QuestionDialog(question, self.tr_, self)
        dialog.finished.connect(lambda _r, d=dialog: self._answered(d))
        self._dialog = dialog
        dialog.open()

    def _answered(self, dialog: QuestionDialog) -> None:
        if dialog.chosen is not None:
            try:
                self.runner.answer(dialog.question["id"], dialog.chosen)
            except MeasurementError:
                pass  # it was closed meanwhile (the run was stopped)
        if self._dialog is dialog:
            self._dialog = None
        self._tick()

    # ================================================================ closing
    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self.model.state in ("running", "paused", "waiting", "stopping"):
            answer = QMessageBox.question(self, self._t("run_title"), self._t("run_confirm_close"))
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.stop()
            self.runner.join(TIMEOUT_CLOSE_S)
        self._timer.stop()
        event.accept()


def main(argv: Optional[list] = None) -> int:
    """Run the demo efficiency measurement on simulated instruments."""
    from ola.demo_lab import INSTRUMENTS, DemoHandle, DemoLab, demo_params
    from ola.registry import default_registry

    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    lab = DemoLab(delay_s=0.05, vin_error=0.2 if "--fault" in argv else 0.0)
    lab.errors_left = 2 if "--fault" in argv else -1  # a few wrong readings, then fine
    registry = default_registry()
    measurement = registry.create("efficiency", demo_params(samples=3, interval_s=0.2))
    handles = [DemoHandle(name, lab) for name in INSTRUMENTS]
    runner = Runner(measurement, {"instruments": handles})
    window = RunWindow(runner, title="demo")
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
