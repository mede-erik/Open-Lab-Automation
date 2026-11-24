# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The waveforms of a run: choose the step, the acquisition and the channels, and see them.

``WaveformView`` is a tab of the run window (the waveforms appear while the run goes) and the body
of ``WaveformDialog``, opened from the list of the runs of the project. It reads the binary files
of the run (``ola.wavefiles``) through ``ola.wave_view`` and draws them with ``WavePlot`` (zoom,
pan, two cursors). Several steps can be selected to draw the same acquisition at each of them
together; the results of the step (the row of the results table: what the converter was doing)
are written under the choices. If the run has two oscilloscopes with a signal in common they can
be put on one time axis (``ola.wave_align``). The capture shown can be exported as CSV.
Strings: ``frontend/lang/modules/run/<lang>.json``.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frontend.core.errorhandler import show_problem
from frontend.ui.module_translator import CatalogTranslator
from frontend.ui.WavePlot import WavePlot
from ola.wave_align import AlignmentError, align_run, export_aligned_csv
from ola.wave_view import (
    WaveCache,
    WaveIndex,
    describe_row,
    has_alignment,
    results_row,
    shifts_for,
)
from ola.wavefiles import WaveFileError, export_csv

Results = Callable[[], Sequence[Dict[str, Any]]]


class WaveformView(QWidget):
    """The waveform viewer of one run file (see the module docstring)."""

    def __init__(
        self,
        run_file: str,
        translator: Any = None,
        results: Optional[Results] = None,
        parent: Optional[QWidget] = None,
    ):
        """``results()`` gives the rows of the results table (the step is the row number)."""
        super().__init__(parent)
        self.run_file = run_file
        self._t = CatalogTranslator("run", translator).t
        self._results = results
        self.index = WaveIndex(run_file)
        self.cache = WaveCache()
        self._build()
        self.refresh()

    # ================================================================ building
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        side = QVBoxLayout()
        side.addWidget(QLabel(self._t("run_waves_steps")))
        self.steps_list = QListWidget()
        self.steps_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.steps_list.setMaximumWidth(240)
        self.steps_list.itemSelectionChanged.connect(self._steps_changed)
        side.addWidget(self.steps_list, 2)
        side.addWidget(QLabel(self._t("run_waves_acquisition")))
        self.acq_box = QComboBox()
        self.acq_box.activated.connect(lambda _i: self._acquisition_changed())
        side.addWidget(self.acq_box)
        side.addWidget(QLabel(self._t("run_waves_channels")))
        self.channel_list = QListWidget()
        self.channel_list.setMaximumWidth(240)
        self.channel_list.itemChanged.connect(lambda _item: self._redraw())
        side.addWidget(self.channel_list, 2)
        self.align_box = QCheckBox(self._t("run_waves_align"))
        self.align_box.setToolTip(self._t("run_waves_align_help"))
        self.align_box.toggled.connect(lambda _on: self._redraw())
        side.addWidget(self.align_box)
        self.align_btn = QPushButton(self._t("run_waves_align_now"))
        self.align_btn.clicked.connect(self.align_now)
        side.addWidget(self.align_btn)
        self.export_btn = QPushButton(self._t("run_waves_export"))
        self.export_btn.clicked.connect(self.export)
        side.addWidget(self.export_btn)
        self.reset_btn = QPushButton(self._t("run_waves_reset"))
        self.reset_btn.clicked.connect(lambda: self.plot.reset_view())
        side.addWidget(self.reset_btn)
        layout.addLayout(side)
        right = QVBoxLayout()
        self.plot = WavePlot()
        self.plot.empty_text = self._t("run_waves_none")
        right.addWidget(self.plot, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        right.addWidget(self.info)
        hint = QLabel(self._t("run_waves_hint"))
        hint.setWordWrap(True)
        right.addWidget(hint)
        layout.addLayout(right, 1)

    # ================================================================ what is shown
    def refresh(self) -> None:
        """The run may have added captures: read the folder again and keep the choices."""
        self.index.refresh()
        chosen = self.selected_steps()
        self.steps_list.blockSignals(True)
        self.steps_list.clear()
        for step in self.index.steps():
            item = QListWidgetItem(self._t("run_waves_step", step=step + 1))
            item.setData(Qt.ItemDataRole.UserRole, step)
            self.steps_list.addItem(item)
            item.setSelected(step in chosen)
        if self.steps_list.count() and not self.selected_steps():
            self.steps_list.item(0).setSelected(True)
        self.steps_list.blockSignals(False)
        self._fill_acquisitions()
        self._fill_channels()
        can_align = len({i.scope for i in self.index.items}) > 1
        self.align_btn.setEnabled(can_align)
        self.align_btn.setToolTip("" if can_align else self._t("run_waves_align_need"))
        self.align_box.setEnabled(has_alignment(self.run_file))
        self._redraw()

    def selected_steps(self) -> List[int]:
        """The steps selected in the list (numbers from 0)."""
        return sorted(
            int(i.data(Qt.ItemDataRole.UserRole)) for i in self.steps_list.selectedItems()
        )

    def acquisition(self) -> str:
        """The acquisition chosen."""
        return self.acq_box.currentData() or ""

    def _fill_acquisitions(self) -> None:
        steps = self.selected_steps()
        names: List[str] = []
        for step in steps or [None]:
            for name in self.index.acquisitions(step):
                if name not in names:
                    names.append(name)
        keep = self.acq_box.currentData()
        self.acq_box.blockSignals(True)
        self.acq_box.clear()
        for name in names:
            self.acq_box.addItem(name, name)
        self.acq_box.setCurrentIndex(max(self.acq_box.findData(keep), 0))
        self.acq_box.blockSignals(False)

    def _fill_channels(self) -> None:
        """The channels of the oscilloscopes in the acquisition of the selected steps; the ones that
        were ticked stay ticked, and at first the first channel of each oscilloscope is."""
        ticked = {
            (i.data(Qt.ItemDataRole.UserRole))
            for i in (self.channel_list.item(k) for k in range(self.channel_list.count()))
            if i.checkState() == Qt.CheckState.Checked
        }
        first_time = self.channel_list.count() == 0
        self.channel_list.blockSignals(True)
        self.channel_list.clear()
        seen_scopes: set = set()
        for step in self.selected_steps()[:1]:
            for info in self.index.find(step, self.acquisition()):
                for channel in info.channels:
                    signal = info.signals.get(channel)
                    label = f"{info.scope} - {channel}" + (f" ({signal})" if signal else "")
                    item = QListWidgetItem(label)
                    item.setData(Qt.ItemDataRole.UserRole, (info.scope, channel))
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    default = first_time and info.scope not in seen_scopes
                    on = (info.scope, channel) in ticked or default
                    item.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
                    seen_scopes.add(info.scope)
                    self.channel_list.addItem(item)
        self.channel_list.blockSignals(False)

    def checked_channels(self) -> List[tuple]:
        """The ``(oscilloscope, channel)`` that are ticked."""
        found = []
        for k in range(self.channel_list.count()):
            item = self.channel_list.item(k)
            if item.checkState() == Qt.CheckState.Checked:
                found.append(item.data(Qt.ItemDataRole.UserRole))
        return found

    def _steps_changed(self) -> None:
        self._fill_acquisitions()
        self._fill_channels()
        self._redraw()

    def _acquisition_changed(self) -> None:
        self._fill_channels()
        self._redraw()

    def _redraw(self) -> None:
        steps, acquisition = self.selected_steps(), self.acquisition()
        wanted = self.checked_channels()
        align = self.align_box.isChecked() and self.align_box.isEnabled()
        curves, missing = [], []
        for step in steps:
            shifts = shifts_for(self.run_file, step, acquisition) if align else {}
            for info in self.index.find(step, acquisition):
                try:
                    capture = self.cache.get(info.path)
                except WaveFileError:
                    missing.append(info.path.name)
                    continue
                for scope, channel in wanted:
                    if scope != info.scope or channel not in capture.voltages:
                        continue
                    name = f"{info.scope}.{channel}"
                    if len(steps) > 1:
                        name = f"{self._t('run_waves_step', step=step + 1)} {name}"
                    times = capture.times() + shifts.get(info.scope, 0.0)
                    curves.append((name, times, capture.voltages[channel]))
        self.plot.set_curves(curves, keep_view=True)
        self._show_info(steps, acquisition, missing)

    def _show_info(self, steps: List[int], acquisition: str, missing: List[str]) -> None:
        """Under the plot: what the converter was doing at the step (the results row)."""
        lines: List[str] = []
        rows = list(self._results() or []) if self._results else []
        for step in steps[:3]:
            infos = self.index.find(step, acquisition)
            text = describe_row(results_row(rows, step)) or describe_row(
                infos[0].setpoints if infos else {}
            )
            forced = any(i.forced for i in infos)
            line = f"<b>{self._t('run_waves_step', step=step + 1)}</b>: {text}"
            if forced:
                line += f" <i>({self._t('run_waves_forced')})</i>"
            lines.append(line)
        if len(steps) > 3:
            lines.append("...")
        if missing:
            lines.append(self._t("run_waves_missing", files=", ".join(missing)))
        self.info.setText("<br>".join(lines))

    # ================================================================ actions
    def align_now(self) -> None:
        """Put the oscilloscopes of every step on one time axis through the signal they share."""
        try:
            entries = align_run(self.run_file)
        except AlignmentError as exc:
            self.info.setText(str(exc))
            return
        self.refresh()
        done = [e for e in entries if "shift_s" in e]
        if done:
            self.align_box.setChecked(True)
        else:
            reason = entries[0].get("error", "") if entries else ""
            self.info.setText(self._t("run_waves_not_aligned", reason=reason))

    def export(self) -> None:
        """Write the capture shown as CSV (both oscilloscopes on one time axis if they are
        aligned and ticked)."""
        steps = self.selected_steps()
        if not steps:
            return
        infos = self.index.find(steps[0], self.acquisition())
        scopes = {s for s, _c in self.checked_channels()}
        shown = [i for i in infos if i.scope in scopes] or infos[:1]
        if not shown:
            return
        shifts = shifts_for(self.run_file, steps[0], self.acquisition())
        aligned = len(shown) >= 2 and self.align_box.isChecked() and shown[1].scope in shifts
        name = f"step{steps[0] + 1}_{self.acquisition()}" + ("_aligned" if aligned else "")
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("run_waves_export"), f"{name}.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            if aligned:
                export_aligned_csv(shown[0].path, shown[1].path, shifts[shown[1].scope], path)
            else:
                export_csv(shown[0].path, path)
        except Exception as exc:
            show_problem(
                self,
                self._t("run_title"),
                self._t("run_export_failed", error=exc),
                code="MEAS-004",
                exception=exc,
                level="critical",
            )


class WaveformDialog(QDialog):
    """The waveforms of a finished run, opened from the list of the runs of the project."""

    def __init__(self, run_file: str, translator: Any = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        from ola.runs import read_run

        self._t = CatalogTranslator("run", translator).t
        self.setWindowTitle(self._t("run_waves_title", run=str(run_file).rsplit("/", 1)[-1]))
        self.resize(1000, 640)
        rows = [r.get("values", r) for r in read_run(run_file)["points"]]
        layout = QVBoxLayout(self)
        self.view = WaveformView(run_file, translator, lambda: rows, self)
        layout.addWidget(self.view)
