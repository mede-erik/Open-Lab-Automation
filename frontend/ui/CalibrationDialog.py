"""The window that calibrates a vector network analyzer of the project, step by step.

It is only layout and signal wiring: the steps, the calls and the saving of the result are
``ola.vna_calibration_flow`` (the same code as the terminal tool). The instrument is reached
with ``connect(name)``, the ``ProjectConnector`` of the project, so a LiteVNA (driver) and a
network analyzer with SCPI behave the same way here.

The window has three pages: the settings (instrument, kind of calibration, ports, sweep and,
if the analyzer accepts it, the values of a real calibration kit), the standards to connect and
measure one at a time, and the result. Calls to the instrument run in a worker thread so the
window never freezes. A finished calibration is saved in the ``calibrations`` folder of the
project and listed in the project file.

The labels of the kit values are the usual English symbols with their units (``C0 (fF)``...).
"""

import logging
from dataclasses import fields
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.module_translator import CatalogTranslator
from ola import inst_file
from ola import vna_calibration_flow as flow
from ola.call_errors import CallError
from ola.vna_calibration import CalKit

log = logging.getLogger(__name__)

PAGE_SETTINGS, PAGE_STEPS, PAGE_DONE = 0, 1, 2
ERROR_STYLE = "color: #b00020;"


class _Job(QThread):
    """Runs ``function`` outside the GUI thread; reports its result or its exception."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, function: Callable[[], Any], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.function = function

    def run(self) -> None:  # noqa: D401 (Qt name)
        try:
            self.succeeded.emit(self.function())
        except Exception as exc:  # shown to the operator, whatever it is
            self.failed.emit(exc)


class CalibrationDialog(QDialog):
    """Calibration of one of the analyzers of the project (see the module docstring)."""

    def __init__(
        self,
        analyzers: Dict[str, str],
        library: Any,
        connect: Callable[..., Any],
        project_path: Optional[Path] = None,
        translator: Any = None,
        parent: Optional[QWidget] = None,
        entries: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """``analyzers``: ``{instance_name: model_id}`` of the project's VNAs
        (``flow.network_analyzers``). ``connect(name)``: gives the handle of an instrument.
        ``project_path``: the project file the calibration is listed in (None: not saved).
        ``entries``: the ``.inst`` entries by name; the usual sweep and the number of ports of an
        instrument are taken from its entry."""
        super().__init__(parent)
        self.tr_ = CatalogTranslator("calibration", translator)
        self._t = self.tr_.t
        self.analyzers, self.library, self.connect = analyzers, library, connect
        self.entries = entries or {}
        self.project_path = Path(project_path) if project_path else None
        self.session: Optional[flow.CalibrationSession] = None
        self.name = ""
        self.model_id = ""
        self.index = 0
        self.saved_path: Optional[Path] = None
        self._job: Optional[_Job] = None
        self.setWindowTitle(self._t("cal_title"))
        self.resize(560, 520)
        self._build_ui()
        self._instrument_changed()

    # ================================================================ building the window
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        self.pages = QStackedWidget()
        root.addWidget(self.pages)
        self.pages.addWidget(self._settings_page())
        self.pages.addWidget(self._steps_page())
        self.pages.addWidget(self._done_page())

    def _settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(self._t("cal_intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.instrument = QComboBox()
        for name in self.analyzers:
            self.instrument.addItem(name)
        self.instrument.currentIndexChanged.connect(self._instrument_changed)
        form.addRow(self._t("cal_instrument"), self.instrument)
        self.kind = QComboBox()
        self.kind.currentIndexChanged.connect(self._kind_changed)
        form.addRow(self._t("cal_kind"), self.kind)
        self.port = QSpinBox()
        self.port.setRange(1, 4)
        self.port2 = QSpinBox()
        self.port2.setRange(1, 4)
        self.port2.setValue(2)
        form.addRow(self._t("cal_port"), self.port)
        form.addRow(self._t("cal_port2"), self.port2)
        self.start = QLineEdit("1M")
        self.stop = QLineEdit("100M")
        self.points = QSpinBox()
        self.points.setRange(2, 100001)
        self.points.setValue(201)
        form.addRow(self._t("cal_start"), self.start)
        form.addRow(self._t("cal_stop"), self.stop)
        form.addRow(self._t("cal_points"), self.points)
        layout.addLayout(form)
        hint = QLabel(self._t("cal_sweep_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(self._kit_group())
        self.settings_error = QLabel()
        self.settings_error.setStyleSheet(ERROR_STYLE)
        self.settings_error.setWordWrap(True)
        layout.addWidget(self.settings_error)
        layout.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.begin_button = QPushButton(self._t("cal_begin"))
        self.begin_button.clicked.connect(self._begin)
        self.cancel_button = QPushButton(self._t("cal_cancel"))
        self.cancel_button.clicked.connect(self.reject)
        row.addWidget(self.begin_button)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        return page

    def _kit_group(self) -> QGroupBox:
        """The values of a calibration kit (a tick turns them on; ideal standards otherwise)."""
        self.kit_group = QGroupBox(self._t("cal_kit_use"))
        self.kit_group.setCheckable(True)
        self.kit_group.setChecked(False)
        self.kit_defaults = {f.name: getattr(CalKit(), f.name) for f in fields(CalKit)}
        self.kit_fields: Dict[str, QDoubleSpinBox] = {}
        outer = QVBoxLayout(self.kit_group)
        body = QWidget()  # the values: shown only when the box is ticked, scrolled when long
        values = QVBoxLayout(body)
        form = QFormLayout()
        for field, text in flow.KIT_BASIC:
            form.addRow(text, self._kit_spin(field))
        values.addLayout(form)
        self.kit_advanced = QGroupBox(self._t("cal_kit_advanced"))
        self.kit_advanced.setCheckable(True)
        self.kit_advanced.setChecked(False)
        advanced = QFormLayout(self.kit_advanced)
        for field, text in flow.KIT_ADVANCED:
            advanced.addRow(text, self._kit_spin(field))
        values.addWidget(self.kit_advanced)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        scroll.setFixedHeight(200)
        scroll.setVisible(False)
        self.kit_group.toggled.connect(scroll.setVisible)
        self.kit_group.toggled.connect(lambda _on: self._fit())
        outer.addWidget(scroll)
        row = QHBoxLayout()
        load = QPushButton(self._t("cal_kit_load"))
        load.clicked.connect(self._load_kit)
        save = QPushButton(self._t("cal_kit_save"))
        save.clicked.connect(self._save_kit)
        row.addWidget(load)
        row.addWidget(save)
        row.addStretch(1)
        outer.addLayout(row)
        return self.kit_group

    def _fit(self) -> None:
        """Give the window the room the kit values need (it never gets smaller than before)."""
        self.resize(self.width(), max(self.height(), self.sizeHint().height()))

    def _kit_spin(self, field: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-1e15, 1e15)
        spin.setDecimals(6)
        spin.setKeyboardTracking(False)
        spin.setValue(self.kit_defaults[field])
        self.kit_fields[field] = spin
        return spin

    def _steps_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.step_title = QLabel()
        self.step_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.step_title)
        self.step_text = QLabel()
        self.step_text.setWordWrap(True)
        layout.addWidget(self.step_text)
        self.step_list = QListWidget()
        layout.addWidget(self.step_list, 1)
        self.step_status = QLabel()
        self.step_status.setWordWrap(True)
        layout.addWidget(self.step_status)
        row = QHBoxLayout()
        row.addStretch(1)
        self.measure_button = QPushButton(self._t("cal_measure"))
        self.measure_button.clicked.connect(self._measure)
        self.steps_cancel = QPushButton(self._t("cal_cancel"))
        self.steps_cancel.clicked.connect(self.reject)
        row.addWidget(self.measure_button)
        row.addWidget(self.steps_cancel)
        layout.addLayout(row)
        return page

    def _done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        layout.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(self._t("cal_close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        return page

    # ================================================================ the settings page
    def _instrument_changed(self) -> None:
        """Offer the kinds of the chosen model; the kit only if the model takes one."""
        self.name = self.instrument.currentText()
        self.model_id = self.analyzers.get(self.name, "")
        self.kind.blockSignals(True)
        self.kind.clear()
        if self.model_id:
            for kind in flow.supported_kinds(self.library, self.model_id):
                self.kind.addItem(self._t(f"cal_kind_{kind}"), kind)
        self.kind.blockSignals(False)
        takes_kit = bool(self.model_id) and flow.supports_kit(self.library, self.model_id)
        self.kit_group.setEnabled(takes_kit)
        if not takes_kit:
            self.kit_group.setChecked(False)
        self.begin_button.setEnabled(self.kind.count() > 0)
        self._use_entry_defaults()
        self._kind_changed()

    def _use_entry_defaults(self) -> None:
        """The sweep and the ports the instrument was given in the instrument file."""
        entry = self.entries.get(self.name) or {}
        sweep = entry.get("sweep") or {}
        if sweep.get("start_hz") and sweep.get("stop_hz"):
            self.start.setText(inst_file.format_frequency(sweep["start_hz"]))
            self.stop.setText(inst_file.format_frequency(sweep["stop_hz"]))
        if sweep.get("points"):
            self.points.setValue(int(sweep["points"]))
        ports = int(entry.get("num_ports") or 4)
        self.port.setRange(1, ports)
        self.port2.setRange(1, ports)
        self.port2.setValue(min(2, ports))

    def _kind_changed(self) -> None:
        self.port2.setEnabled(self.kind.currentData() not in (None, "ONE_PORT"))

    def _kit_values(self) -> Optional[Dict[str, float]]:
        """The kit typed in the window, or None for ideal standards."""
        if not self.kit_group.isChecked():
            return None
        advanced = {field for field, _text in flow.KIT_ADVANCED}
        return {
            field: spin.value()
            for field, spin in self.kit_fields.items()
            if self.kit_advanced.isChecked() or field not in advanced
        }

    def _load_kit(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, self._t("cal_kit_load"), "", self._t("cal_kit_files")
        )
        if not path:
            return
        try:
            kit = flow.load_kit(path)
        except CallError as exc:
            self.settings_error.setText(self._t("cal_kit_error", error=exc))
            return
        self.settings_error.clear()
        for field, spin in self.kit_fields.items():  # what the file does not say is ideal
            spin.setValue(kit.get(field, self.kit_defaults[field]))
        advanced = {field for field, _text in flow.KIT_ADVANCED}
        self.kit_advanced.setChecked(any(field in advanced for field in kit))
        self.kit_group.setChecked(True)

    def _save_kit(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, self._t("cal_kit_save"), "kit.json", self._t("cal_kit_files")
        )
        if path:
            flow.save_kit(path, {f: s.value() for f, s in self.kit_fields.items()})

    # ================================================================ the calibration
    def _run(
        self,
        function: Callable[[], Any],
        on_done: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        status: str,
    ) -> None:
        """Run ``function`` in the worker thread; buttons stay off while it works."""
        self._busy(True, status)
        job = _Job(function, self)
        job.succeeded.connect(lambda result: (self._busy(False), on_done(result)))
        job.failed.connect(lambda exc: (self._busy(False), on_error(exc)))
        self._job = job
        job.start()

    def _busy(self, busy: bool, status: str = "") -> None:
        for button in (
            self.begin_button,
            self.measure_button,
            self.cancel_button,
            self.steps_cancel,
        ):
            button.setEnabled(not busy)
        if busy:
            self.step_status.setStyleSheet("")
            self.step_status.setText(status)

    def _begin(self) -> None:
        """Check the settings, connect to the instrument and choose the calibration."""
        kind = self.kind.currentData()
        port = self.port.value()
        port2 = None if kind == "ONE_PORT" else self.port2.value()
        try:
            sweep = flow.parse_sweep(self.start.text(), self.stop.text(), self.points.value())
            flow.plan_steps(kind, port, port2)  # the ports are checked before connecting
        except CallError as exc:
            self.settings_error.setText(self._t("cal_error", error=exc))
            return
        self.settings_error.clear()
        name, kit = self.name, self._kit_values()

        def begin():
            session = flow.CalibrationSession(self.connect(name), kind, port, port2, sweep, kit)
            session.start()
            return session

        self.pages.setCurrentIndex(PAGE_STEPS)
        self.step_title.setText("")
        self.step_text.setText("")
        self.step_list.clear()
        self.measure_button.setEnabled(False)
        self._run(begin, self._began, self._begin_failed, self._t("cal_connecting"))

    def _began(self, session: "flow.CalibrationSession") -> None:
        self.session, self.index = session, 0
        self.step_list.clear()
        for step in session.steps:
            self.step_list.addItem(self._step_text(step))
        self.step_status.clear()
        self._show_step()

    def _begin_failed(self, exc: Exception) -> None:
        """Back to the settings with the reason (nothing was calibrated)."""
        self.pages.setCurrentIndex(PAGE_SETTINGS)
        self.settings_error.setText(self._t("cal_error", error=exc))

    def _step_text(self, step: "flow.CalibrationStep") -> str:
        return self._t(
            f"cal_step_{step.standard}", port=step.port, port2=step.port2 if step.port2 else ""
        )

    def _show_step(self) -> None:
        steps: List[flow.CalibrationStep] = self.session.steps
        step = steps[self.index]
        self.step_title.setText(self._t("cal_step_title", n=self.index + 1, total=len(steps)))
        self.step_text.setText(self._step_text(step))
        self.step_list.setCurrentRow(self.index)
        self.measure_button.setEnabled(True)

    def _measure(self) -> None:
        step = self.session.steps[self.index]
        self._run(
            lambda: self.session.measure(step),
            self._measured,
            self._measure_failed,
            self._t("cal_measuring"),
        )

    def _measured(self, _result: Any) -> None:
        item = self.step_list.item(self.index)
        item.setText("✓ " + item.text())
        self.step_status.clear()
        self.index += 1
        if self.index < len(self.session.steps):
            self._show_step()
        else:
            self._finish()

    def _measure_failed(self, exc: Exception) -> None:
        """The standard stays to be measured again."""
        self.step_status.setStyleSheet(ERROR_STYLE)
        self.step_status.setText(self._t("cal_error", error=exc) + "\n" + self._t("cal_retry"))
        self.measure_button.setEnabled(True)

    def _finish(self) -> None:
        """Compute the calibration, switch it on and save it."""
        session, name, model_id, project = self.session, self.name, self.model_id, self.project_path

        def finish():
            session.finish()
            record = session.record(name, model_id)
            path = flow.save_and_attach(record, project) if project else None
            return record, path

        self.measure_button.setEnabled(False)
        self._run(finish, self._finished, self._measure_failed_at_end, self._t("cal_finishing"))

    def _finished(self, result) -> None:
        record, path = result
        self.saved_path = path
        lines = [self._t("cal_done")]
        if path is not None:
            lines.append(self._t("cal_saved", file=path))
        lines.append(self._t("cal_restorable" if record.data is not None else "cal_lost"))
        self.result_label.setText("\n\n".join(lines))
        self.pages.setCurrentIndex(PAGE_DONE)

    def _measure_failed_at_end(self, exc: Exception) -> None:
        """Computing or saving failed: the last standard can be measured again to retry."""
        self.index = len(self.session.steps) - 1
        self._measure_failed(exc)

    # ================================================================ closing
    def _wait_for_job(self) -> None:
        if self._job is not None and self._job.isRunning():
            self._job.wait()

    def reject(self) -> None:  # noqa: D401 (Qt name)
        """Cancel: an unfinished calibration is cleared on the instrument."""
        self._wait_for_job()
        if self.session is not None and not self.session.applied:
            try:
                self.session.handle.call("calibration_clear")
            except CallError as exc:
                log.warning("calibration_clear failed: %s", exc)
        super().reject()

    def done(self, result: int) -> None:  # noqa: D401 (Qt name)
        self._wait_for_job()
        super().done(result)
