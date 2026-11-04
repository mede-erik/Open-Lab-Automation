"""The connection diagram of a measurement: which instrument goes where.

``WiringDialog`` shows the diagram (``ola.wiring``), the connections as a list and the notes
("calibrate first", "keep the antenna away from metal"). Before a measurement starts it is a
question (*Start* / *Cancel*, and a tick to stop showing it); from the project window it is
simply shown. The diagram is drawn in millimetres by ``ola.wiring.layout`` and painted here;
*Save SVG* writes it as a file. Strings: ``frontend/lang/modules/wiring``.
"""

from __future__ import annotations

from html import escape
from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.label_paint import paint_drawing
from frontend.ui.module_translator import CatalogTranslator
from ola.labels import Drawing, render_svg
from ola.wiring import Diagram, connection_lines, layout

PIXELS_PER_MM = 5.0  # the size the diagram asks for; it shrinks to fit a narrower window


class WiringView(QWidget):
    """Paints a diagram, as large as fits the width."""

    def __init__(self, drawing: Drawing, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.drawing = drawing
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.setMinimumSize(320, int(320 * drawing.height / drawing.width))

    def scale(self) -> float:
        """Pixels per millimetre for the present size of the widget."""
        return min(
            PIXELS_PER_MM, self.width() / self.drawing.width, self.height() / self.drawing.height
        )

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt name)
        """The size the diagram would like."""
        return QSize(
            int(self.drawing.width * PIXELS_PER_MM), int(self.drawing.height * PIXELS_PER_MM)
        )

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        """Paint the diagram, centred."""
        s = self.scale()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dx = (self.width() - self.drawing.width * s) / 2
        dy = (self.height() - self.drawing.height * s) / 2
        painter.setClipRect(QRectF(0, 0, self.width(), self.height()))
        paint_drawing(painter, self.drawing, s, dx, dy)
        painter.end()


class WiringDialog(QDialog):
    """The diagram window. ``confirm=True``: *Start* accepts, *Cancel* rejects (``show_before``
    tells whether the tick to keep showing it is still on)."""

    def __init__(
        self,
        diagram: Diagram,
        translator=None,
        name: str = "",
        confirm: bool = False,
        show_before: bool = True,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.tr_ = CatalogTranslator("wiring", translator)
        t = self.tr_.t
        self.diagram = diagram
        self.drawing = layout(diagram)
        self.setWindowTitle(t("wir_title", name=name))
        root = QVBoxLayout(self)
        intro = QLabel(t("wir_intro_run" if confirm else "wir_intro_view"))
        intro.setWordWrap(True)
        root.addWidget(intro)
        self.view = WiringView(self.drawing)
        root.addWidget(self.view, 1)
        self.connections = QLabel(self._connections_html())
        self.connections.setTextFormat(Qt.TextFormat.RichText)
        self.connections.setWordWrap(True)
        root.addWidget(self.connections)
        self.notes = QLabel(self._notes_html())
        self.notes.setTextFormat(Qt.TextFormat.RichText)
        self.notes.setWordWrap(True)
        self.notes.setVisible(bool(diagram.notes))
        root.addWidget(self.notes)
        self.status = QLabel()
        root.addWidget(self.status)
        self.show_before = QCheckBox(t("wir_show_before"))
        self.show_before.setChecked(show_before)
        self.show_before.setVisible(confirm)
        root.addWidget(self.show_before)
        row = QHBoxLayout()
        self.save_btn = QPushButton(t("wir_save_svg"))
        self.save_btn.clicked.connect(self.save_svg)
        row.addWidget(self.save_btn)
        row.addStretch(1)
        self.start_btn = QPushButton(t("wir_start"))
        self.start_btn.setDefault(True)
        self.start_btn.setVisible(confirm)
        self.start_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton(t("wir_cancel" if confirm else "wir_close"))
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.start_btn)
        row.addWidget(self.cancel_btn)
        root.addLayout(row)
        self.resize(760, 520)

    def _connections_html(self) -> str:
        items = "".join(f"<li>{escape(line)}</li>" for line in connection_lines(self.diagram))
        return f"<b>{escape(self.tr_.t('wir_connections'))}</b><ul>{items}</ul>"

    def _notes_html(self) -> str:
        items = "".join(f"<li>{escape(note)}</li>" for note in self.diagram.notes)
        return f"<b>{escape(self.tr_.t('wir_notes'))}</b><ul>{items}</ul>"

    def save_svg(self, path: Optional[str] = None) -> bool:
        """Write the diagram as an SVG file (asks for the file if ``path`` is not given)."""
        t = self.tr_.t
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, t("wir_save_svg"), "", "SVG (*.svg)")
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(render_svg(self.drawing))
        except OSError as exc:
            self.status.setText(t("wir_failed", error=exc))
            return False
        self.status.setText(t("wir_saved", path=path))
        return True
