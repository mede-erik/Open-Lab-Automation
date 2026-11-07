"""The pop-up that says an instrument of a measurement has less than the ones used before.

Shown before a measurement starts when ``ProjectSession.compatibility`` finds something (see
``ola.compat``): for each difference the instrument, the characteristic, what this instrument has,
what the previous instrument had and what the previous runs needed. The user decides: *Continue*
(the differences are written in the run file) or *Cancel*. A difference that makes the
measurement impossible (``blocking``) leaves only *Close*: the measurement has to be changed.

Layout only; the comparison is ``ola.compat``.
"""

from typing import Any, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.core.Translator import Translator
from ola.compat import Finding, format_value

COLUMNS = (
    "compat_col_role",
    "compat_col_instrument",
    "compat_col_characteristic",
    "compat_col_this",
    "compat_col_previous",
    "compat_col_need",
)
BLOCKING_COLOR = "#b00020"


class CompatibilityDialog(QDialog):
    """Lists the differences; ``exec()`` is Accepted only if the user chose to continue."""

    def __init__(
        self,
        findings: List[Finding],
        translator: Optional[Any] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.t = (translator or Translator()).t
        self.findings = findings
        self.blocking = any(f.blocking for f in findings)
        self.setWindowTitle(self.t("compat_title"))
        self.resize(760, 360)
        layout = QVBoxLayout(self)
        intro = QLabel(self.t("compat_intro_block" if self.blocking else "compat_intro_warn"))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self._table(), 1)
        row = QHBoxLayout()
        row.addStretch(1)
        if self.blocking:
            close = QPushButton(self.t("compat_close"))
            close.clicked.connect(self.reject)
            row.addWidget(close)
        else:
            self.continue_button = QPushButton(self.t("compat_continue"))
            self.continue_button.clicked.connect(self.accept)
            cancel = QPushButton(self.t("compat_cancel"))
            cancel.setDefault(True)  # going on is the choice that has to be made on purpose
            cancel.clicked.connect(self.reject)
            row.addWidget(self.continue_button)
            row.addWidget(cancel)
        layout.addLayout(row)

    def _table(self) -> QTableWidget:
        table = QTableWidget(len(self.findings), len(COLUMNS))
        table.setHorizontalHeaderLabels([self.t(c) for c in COLUMNS])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, f in enumerate(self.findings):
            previous = format_value(f.characteristic, f.previous)
            if f.previous_name and f.previous is not None:
                previous += f" ({f.previous_name})"
            cells = (
                f.role,
                f.instrument,
                self.t("compat_char_" + f.characteristic),
                format_value(f.characteristic, f.value),
                previous,
                format_value(f.characteristic, f.need),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if f.blocking:
                    item.setForeground(Qt.GlobalColor.red)
                table.setItem(row, column, item)
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        self.table = table
        return table
