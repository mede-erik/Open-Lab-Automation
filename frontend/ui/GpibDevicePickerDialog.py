# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Small window that lists the instruments on the bus of a GPIB adapter and returns the chosen one.

Opened by *Pick from the GPIB bus...* of the address editor of an instrument. It shows the result
of the last scan of the adapter (made here or in *Tools > GPIB adapters*) and can scan again
(in a thread). ``chosen`` is the ``ola.gpib_adapter.BusDevice`` picked, or None.
"""

import threading
from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from frontend.core import gpib_settings
from frontend.ui.GpibAdapterDialog import _Worker
from ola import gpib_adapter as ga
from ola.errors import TransportError
from ola.gpib_adapter import GpibAdapterConfig


class GpibDevicePickerDialog(QDialog):
    """Pick an instrument found on the bus of ``adapter`` (see the module docstring)."""

    def __init__(
        self,
        adapter: GpibAdapterConfig,
        tr,
        parent=None,
        rm_factory=None,
        asynchronous: bool = True,
    ):
        super().__init__(parent)
        self.adapter, self._t = adapter, tr.t
        self._engine_kw = {"rm_factory": rm_factory} if rm_factory is not None else {}
        self.asynchronous = asynchronous
        self._cancel = threading.Event()
        self._worker: Optional[_Worker] = None
        self.chosen: Optional[ga.BusDevice] = None
        self.devices: List[ga.BusDevice] = []
        self.setWindowTitle(self._t("gpb_pick_title"))
        self.resize(640, 360)

        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"{self._t('gpb_pick_adapter')}: {adapter.name}"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self._t("gpb_col_address"), self._t("gpb_col_resource"), self._t("gpb_col_idn")]
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda *_: self.accept())
        v.addWidget(self.table)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        row = QHBoxLayout()
        self.scan_button = QPushButton(self._t("gpb_pick_scan"))
        self.scan_button.clicked.connect(self.scan)
        row.addWidget(self.scan_button)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.use_button = buttons.addButton(
            self._t("gpb_pick_use"), QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        v.addLayout(row)
        self._show(gpib_settings.last_scan(adapter.name))

    def _show(self, devices: List[ga.BusDevice]):
        self.devices = list(devices)
        self.table.setRowCount(0)
        for d in devices:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for col, text in enumerate(
                (str(d.address), d.resource, d.idn or self._t("gpb_no_idn"))
            ):
                self.table.setItem(r, col, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        if devices:
            self.table.selectRow(0)
            self.status.setText("")
        else:
            self.status.setText(self._t("gpb_pick_none"))
        self.use_button.setEnabled(bool(devices))

    def scan(self):
        cfg = self.adapter
        self.scan_button.setEnabled(False)

        def job(progress):
            return ga.scan_bus(cfg, progress, self._cancel, **self._engine_kw)

        def done(devices):
            gpib_settings.remember_scan(cfg.name, devices)
            self._show(devices)
            if not devices:
                self.status.setText(self._t("gpb_scan_empty", adapter=cfg.name, count=0))

        def failed(exc):
            self.status.setText(self._t("gpb_scan_failed", error=str(exc)))

        def finished():
            self.scan_button.setEnabled(True)

        def progress(address, done_, total):
            if address >= 0:
                self.status.setText(self._t("gpb_scanning", address=address))

        if not self.asynchronous:
            try:
                done(job(lambda *a: None))
            except (ga.GpibError, TransportError, OSError, ValueError) as exc:
                failed(exc)
            finished()
            return
        self._worker = _Worker(job, self)
        self._worker.progressed.connect(progress)
        self._worker.succeeded.connect(done)
        self._worker.failed.connect(failed)
        self._worker.finished.connect(finished)
        self._worker.start()

    def accept(self):
        rows = {i.row() for i in self.table.selectedItems()}
        if not rows:
            return
        self.chosen = self.devices[min(rows)]
        self._stop()
        super().accept()

    def reject(self):
        self._stop()
        super().reject()

    def _stop(self):
        self._cancel.set()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(10000)
