# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Remote-control panel of a vector network analyzer: sweep settings, the S-parameters to read,
a single or continuous sweep, the curves in dB or as impedance, min/max markers and the export of
the last sweep as Touchstone.

Layout and signal wiring only: the controls offered, the checks and the sweep are
``ola.vna_controls``. The instrument is reached with ``connect()`` (a handle of
``ola.connection.ProjectConnector``), so a LiteVNA (driver) and an analyzer with SCPI behave the
same way. A sweep runs in a worker thread so the window never freezes. No SCPI is written here.
"""

from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.trace_plot import TracePlot
from ola import vna_controls as vc
from ola.run_view import format_si


class _SweepWorker(QThread):
    """One sweep, away from the window: ``done((freq, data, notes))`` or ``failed(text)``."""

    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, connect, sweep, sparameters, configure, parent=None):
        super().__init__(parent)
        self.connect, self.sweep = connect, sweep
        self.sparameters, self.configure = sparameters, configure

    def run(self):
        try:
            handle = self.connect()
            self.done.emit(vc.run_one_sweep(handle, self.sweep, self.sparameters, self.configure))
        except Exception as exc:  # the error says what went wrong (CALL-xxx, TRN-xxx, connection)
            self.failed.emit(str(exc))


class VnaPanel(QGroupBox):
    """One network analyzer of the instrument file."""

    def __init__(
        self,
        title: str,
        controls: vc.VnaControls,
        connect: Callable[[], Any],
        t: Callable[[str], str],
        asynchronous: bool = True,
        parent=None,
    ):
        super().__init__(title, parent)
        self.controls, self.connect, self.t = controls, connect, t
        self.asynchronous = asynchronous  # False in the tests: the sweep runs in the caller
        self.worker: Optional[_SweepWorker] = None
        self.freq: List[float] = []
        self.data: Dict[str, List[complex]] = {}
        self._sent_sweep: Optional[dict] = None  # the sweep the instrument has
        layout = QVBoxLayout(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        if not controls.usable:
            layout.addWidget(QLabel(t("vna_not_supported")))
            self.plot = None
            return

        # sweep settings
        form = QFormLayout()
        c = controls
        limits = ""
        if c.frequency_min is not None and c.frequency_max is not None:
            limits = f" ({format_si(c.frequency_min, 'Hz')} – {format_si(c.frequency_max, 'Hz')})"
        self.start = QLineEdit(format_si(max(c.frequency_min or 1e6, 1e6), "").replace(" ", ""))
        self.stop = QLineEdit(
            format_si(min(c.frequency_max or 1e9, 1e9), "").replace(" ", "")
        )
        for edit in (self.start, self.stop):
            edit.setPlaceholderText("2.4G, 100k, 1500000")
        form.addRow(t("vna_start") + limits, self.start)
        form.addRow(t("vna_stop"), self.stop)
        self.points = QSpinBox()
        self.points.setRange(2, c.max_points or 100001)
        self.points.setValue(min(201, c.max_points or 201))
        form.addRow(t("vna_points"), self.points)
        self.log = QCheckBox(t("vna_log"))
        if c.has("set_sweep_type"):
            form.addRow("", self.log)
        self.if_bandwidth = QLineEdit()
        self.if_bandwidth.setPlaceholderText(t("vna_unchanged"))
        if c.has("set_if_bandwidth"):
            form.addRow(t("vna_if_bandwidth"), self.if_bandwidth)
        self.power = QLineEdit()
        self.power.setPlaceholderText(t("vna_unchanged"))
        if c.has("set_source_power"):
            form.addRow(t("vna_power"), self.power)
        row = QHBoxLayout()
        self.sparameter_checks: Dict[str, QCheckBox] = {}
        for name in c.sparameters:
            check = QCheckBox(name)
            check.setChecked(name in ("S11", "S21"))
            check.toggled.connect(self._redraw)
            self.sparameter_checks[name] = check
            row.addWidget(check)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        form.addRow(t("vna_traces"), holder)
        self.format = QComboBox()
        self.format.addItem(t("vna_format_db"), vc.FORMAT_DB)
        self.format.addItem(t("vna_format_impedance"), vc.FORMAT_IMPEDANCE)
        self.format.currentIndexChanged.connect(self._redraw)
        form.addRow(t("vna_format"), self.format)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.sweep_button = QPushButton(t("vna_sweep"))
        self.sweep_button.clicked.connect(self.sweep_once)
        self.continuous = QCheckBox(t("vna_continuous"))
        self.continuous.toggled.connect(self._continuous_toggled)
        self.export_button = QPushButton(t("vna_export"))
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        for w in (self.sweep_button, self.continuous, self.export_button):
            buttons.addWidget(w)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.plot = TracePlot()
        self.plot.setMinimumHeight(260)
        layout.addWidget(self.plot)
        self.markers = QLabel("")
        self.markers.setWordWrap(True)
        layout.addWidget(self.markers)
        layout.addWidget(self.status)

    # ----- the sweep ------------------------------------------------------------------------
    def _settings(self):
        """(sweep, S-parameters) from the form, or (None, problems as text)."""
        try:
            start = vc.parse_frequency(self.start.text())
            stop = vc.parse_frequency(self.stop.text())
            if_bw = vc.parse_frequency(self.if_bandwidth.text()) if (
                self.controls.has("set_if_bandwidth") and self.if_bandwidth.text().strip()
            ) else None
            power = float(self.power.text().replace(",", ".")) if (
                self.controls.has("set_source_power") and self.power.text().strip()
            ) else None
        except ValueError:
            return None, self.t("vna_err_number")
        problems = vc.check_sweep(self.controls, start, stop, self.points.value())
        selected = [n for n, c in self.sparameter_checks.items() if c.isChecked()]
        if not selected:
            problems.append("vna_err_traces")
        if problems:
            return None, "\n".join(self.t(p) for p in problems)
        sweep = vc.sweep_settings(
            start, stop, self.points.value(), self.log.isChecked(), if_bw, power
        )
        return (sweep, selected), ""

    def sweep_once(self) -> bool:
        """Start one sweep (nothing if one is running). False if the form is not valid."""
        if self.worker is not None and self.worker.isRunning():
            return False
        settings, problem = self._settings()
        if settings is None:
            self.status.setText(problem)
            self.continuous.setChecked(False)
            return False
        sweep, selected = settings
        configure = sweep != self._sent_sweep
        self.sweep_button.setEnabled(False)
        self.status.setText(self.t("vna_running"))
        worker = _SweepWorker(self.connect, sweep, selected, configure, self)
        worker.done.connect(lambda result, s=sweep: self._done(result, s))
        worker.failed.connect(self._failed)
        self.worker = worker
        if self.asynchronous:
            worker.start()
        else:
            worker.run()
        return True

    def _done(self, result, sweep):
        self.freq, self.data, notes = result
        self._sent_sweep = sweep
        self.sweep_button.setEnabled(True)
        self.export_button.setEnabled(bool(self.freq))
        texts = [self.t("vna_not_calibrated") if n == "not_calibrated" else n for n in notes]
        self.status.setText("\n".join(texts))
        self._redraw()
        if self.continuous.isChecked():
            self._next()

    def _next(self):
        """The next sweep of a continuous run, once the event loop is free."""
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, self._continue)

    def _continue(self):
        if self.continuous.isChecked():
            self.sweep_once()

    def _failed(self, text: str):
        self.sweep_button.setEnabled(True)
        self._sent_sweep = None  # set the sweep again next time
        self.status.setText(self.t("vna_err_call").format(error=text))
        self.continuous.setChecked(False)

    def _continuous_toggled(self, on: bool):
        if on:
            self.sweep_once()

    def stop_reading(self):
        """Stop a continuous sweep and wait for the one running (panel removed, tab closed)."""
        if self.plot is None:
            return
        self.continuous.setChecked(False)
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(30000)

    # ----- drawing and export ---------------------------------------------------------------
    def _redraw(self, *_args):
        if self.plot is None or not self.freq:
            return
        shown = {n: v for n, v in self.data.items()
                 if n in self.sparameter_checks and self.sparameter_checks[n].isChecked()}
        fmt = self.format.currentData()
        drawn = vc.curves(self.freq, shown, fmt)
        ylabel = self.t("vna_axis_db") if fmt == vc.FORMAT_DB else self.t("vna_axis_ohm")
        self.plot.set_curves(drawn, xlabel=self.t("vna_axis_frequency"), ylabel=ylabel,
                             log_x=self.log.isChecked(), x_unit="Hz")
        unit = "dB" if fmt == vc.FORMAT_DB else "Ω"
        lines = []
        for curve in drawn:
            found = vc.markers(curve)
            if found:
                (fmin, ymin), (fmax, ymax) = found["min"], found["max"]
                lines.append(self.t("vna_markers").format(
                    trace=curve[0], fmin=format_si(fmin, "Hz"), ymin=f"{ymin:.4g} {unit}",
                    fmax=format_si(fmax, "Hz"), ymax=f"{ymax:.4g} {unit}"))
        if fmt == vc.FORMAT_IMPEDANCE and not drawn:
            lines.append(self.t("vna_no_reflection"))
        self.markers.setText("\n".join(lines))

    def export(self, path: Optional[str] = None) -> bool:
        """Save the last sweep as Touchstone (asks where if ``path`` is not given)."""
        if not self.freq:
            return False
        suffix = vc.touchstone_suffix(self.data)
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, self.t("vna_export"), f"sweep{suffix}", f"Touchstone (*{suffix})"
            )
            if not path:
                return False
        if not path.lower().endswith(suffix):
            path += suffix
        try:
            vc.export_touchstone(path, self.freq, self.data)
        except Exception as exc:
            self.status.setText(self.t("vna_err_call").format(error=exc))
            return False
        self.status.setText(self.t("vna_saved").format(path=path))
        return True
