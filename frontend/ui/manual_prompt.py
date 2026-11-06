"""The pop-up that asks the operator to do an action by hand on a manual instrument.

A manual instrument (a bench supply or load without remote control) cannot be told what to do:
when a measurement calls ``set_voltage(12)`` on it, the operator is asked to set 12 V and to press
*Done*. ``ManualPrompter`` is the ``prompt`` that ``ola.connection.ProjectConnector`` hands to such
handles. It is called from the thread of the run and waits for the operator; the pop-up is shown by
the GUI thread and does not block the rest of the program. If the run is stopped meanwhile the
pop-up closes by itself and the action counts as cancelled (which stops the run; it is not an
error).
"""

import threading
from typing import Any, List, Optional

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from frontend.ui.module_translator import CatalogTranslator

POLL_S = 0.1  # how often the waiting run looks at its stop event


class _Pending:
    """One question waiting for the operator."""

    def __init__(self, request: Any, cancel: Optional[threading.Event]):
        self.request, self.cancel = request, cancel
        self.done = threading.Event()
        self.result = False
        self.dialog: Optional[QDialog] = None


class ManualPrompter(QObject):
    """``prompter(request, cancel) -> bool``: True if the operator did it, False if they cancelled
    (or the run was stopped). Create it in the GUI thread; call it from the run's thread."""

    _show = pyqtSignal(object)
    _close = pyqtSignal(object)

    def __init__(self, translator: Any = None, parent_widget: Optional[QWidget] = None):
        super().__init__(parent_widget)
        self.tr_ = CatalogTranslator("project", translator)
        self.parent_widget = parent_widget
        self.dialogs: List[QDialog] = []  # the pop-ups on screen now
        self._show.connect(self._on_show, Qt.ConnectionType.QueuedConnection)
        self._close.connect(self._on_close, Qt.ConnectionType.QueuedConnection)

    def __call__(self, request: Any, cancel: Optional[threading.Event] = None) -> bool:
        if QThread.currentThread() is self.thread():
            raise RuntimeError(
                "ManualPrompter must be called from the thread of a run, not the GUI"
            )
        pending = _Pending(request, cancel)
        self._show.emit(pending)
        while not pending.done.wait(POLL_S):
            if cancel is not None and cancel.is_set():
                self._close.emit(pending)
                return False
        return pending.result

    # ----- in the GUI thread -----------------------------------------------------------------
    def _on_show(self, pending: _Pending) -> None:
        t = self.tr_.t
        dialog = QDialog(self.parent_widget)
        dialog.setWindowTitle(t("prj_manual_title"))
        layout = QVBoxLayout(dialog)
        text = QLabel(pending.request.text)
        font = text.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        text.setFont(font)
        text.setWordWrap(True)
        text.setMinimumWidth(420)
        layout.addWidget(text)
        layout.addWidget(QLabel(t("prj_manual_help")))
        row = QHBoxLayout()
        row.addStretch(1)
        done, cancel = QPushButton(t("prj_manual_done")), QPushButton(t("prj_cancel"))
        done.setDefault(True)
        done.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        row.addWidget(done)
        row.addWidget(cancel)
        layout.addLayout(row)
        dialog.done_button, dialog.cancel_button = done, cancel
        dialog.finished.connect(lambda code, p=pending, d=dialog: self._finished(p, d, code))
        pending.dialog = dialog
        self.dialogs.append(dialog)
        dialog.open()

    def _finished(self, pending: _Pending, dialog: QDialog, code: int) -> None:
        pending.result = code == QDialog.DialogCode.Accepted and not pending.done.is_set()
        if dialog in self.dialogs:
            self.dialogs.remove(dialog)
        pending.done.set()

    def _on_close(self, pending: _Pending) -> None:
        if pending.dialog is not None:
            pending.dialog.reject()
