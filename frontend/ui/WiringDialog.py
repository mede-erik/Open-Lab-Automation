"""The connection diagram of a measurement: which instrument goes where.

``WiringDialog`` shows the picture (a hand-drawn image of the module if it has one for these
parameters, else the diagram drawn by ``ola.wiring.layout``), the numbered list of what to
connect, and the notes ("calibrate first", "keep the antenna away from metal"). Before a
measurement starts it is a question (*Start* / *Cancel*, and a tick to stop showing it); from the
project window it is simply shown. *Save SVG* writes a drawn diagram as a file. Strings:
``frontend/lang/modules/wiring``. To look at one without a project:
``python -m frontend.ui.WiringDialog <module id> [measurement file] [language]``.
"""

from __future__ import annotations

from html import escape
from typing import Optional

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer
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
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
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


class ImageView(QWidget):
    """A picture (SVG or a raster image) shown as large as fits, keeping its proportions."""

    def __init__(self, path: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.path = str(path)
        self.svg: Optional[QSvgRenderer] = None
        self.image = QImage()
        if self.path.lower().endswith(".svg"):
            renderer = QSvgRenderer(self.path)
            self.svg = renderer if renderer.isValid() else None
        else:
            self.image = QImage(self.path)
        self.ok = self.svg is not None or not self.image.isNull()
        size = self.natural_size()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        self.setMinimumSize(320, max(120, int(320 * size.height() / max(1, size.width()))))

    def natural_size(self) -> QSize:
        """The size of the picture itself."""
        if self.svg is not None:
            return self.svg.defaultSize()
        return self.image.size() if not self.image.isNull() else QSize(4, 3)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt name)
        """The size of the picture, at most 900 pixels wide."""
        size = self.natural_size()
        factor = min(1.0, 900 / max(1, size.width()))
        return QSize(int(size.width() * factor), int(size.height() * factor))

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        """Paint the picture on a white background, centred."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("white"))
        size = self.natural_size()
        scale = min(self.width() / max(1, size.width()), self.height() / max(1, size.height()))
        w, h = size.width() * scale, size.height() * scale
        target = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        if self.svg is not None:
            self.svg.render(painter, target)
        elif not self.image.isNull():
            painter.drawImage(target, self.image)
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
        self.picture: Optional[ImageView] = None
        self.view: Optional[WiringView] = None
        self.status = QLabel()
        problems = list(diagram.warnings)
        if diagram.image is not None:
            self.picture = ImageView(str(diagram.image))
            if not self.picture.ok:
                problems.append(t("wir_image_failed", path=diagram.image))
                self.picture = None
        if self.picture is not None:
            root.addWidget(self.picture, 1)
        elif diagram.nodes:
            self.view = WiringView(self.drawing)
            root.addWidget(self.view)  # no stretch: the drawing is as tall as it needs
        self.connections = QLabel(self._connections_html())
        self.connections.setTextFormat(Qt.TextFormat.RichText)
        self.connections.setWordWrap(True)
        self.connections.setVisible(bool(diagram.steps or diagram.links))
        root.addWidget(self.connections)
        self.notes = QLabel(self._notes_html())
        self.notes.setTextFormat(Qt.TextFormat.RichText)
        self.notes.setWordWrap(True)
        self.notes.setVisible(bool(diagram.notes))
        root.addWidget(self.notes)
        self.status.setText(" ".join(problems))
        root.addWidget(self.status)
        root.addStretch(1)
        self.show_before = QCheckBox(t("wir_show_before"))
        self.show_before.setChecked(show_before)
        self.show_before.setVisible(confirm)
        root.addWidget(self.show_before)
        row = QHBoxLayout()
        self.save_btn = QPushButton(t("wir_save_svg"))
        self.save_btn.clicked.connect(self.save_svg)
        self.save_btn.setVisible(self.view is not None)
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
        """The numbered steps; without steps, the links of the diagram as sentences."""
        if self.diagram.steps:
            items = "".join(f"<li>{escape(step)}</li>" for step in self.diagram.steps)
            return f"<b>{escape(self.tr_.t('wir_steps'))}</b><ol>{items}</ol>"
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


def main(argv=None) -> int:
    """Show the diagram of a module, to try a ``wiring.json`` or a picture:
    ``python -m frontend.ui.WiringDialog <module id> [measurement file] [language]``."""
    import json
    import sys

    from PyQt6.QtWidgets import QApplication

    from ola.registry import default_registry
    from ola.wiring import diagram_for, load_wiring

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(main.__doc__)
        return 2
    from ola.measurement import MeasurementError

    try:
        info = default_registry().get(args[0])
    except MeasurementError as exc:
        print(exc)
        return 1
    wiring = load_wiring(info.path)
    if wiring is None:
        print(f"the module {args[0]} has no wiring.json")
        return 1
    params, names = {}, {}
    if len(args) > 1 and args[1] not in ("en", "it", "fr", "es", "de"):
        with open(args[1], encoding="utf-8") as handle:
            data = json.load(handle)
        params = data.get("params", data)
        names = {k: ([v] if isinstance(v, str) else list(v)) for k, v in
                 (data.get("role_bindings") or {}).items()}  # fmt: skip
    lang = args[-1] if args[-1] in ("en", "it", "fr", "es", "de") else "en"
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = WiringDialog(diagram_for(wiring, params, names, lang, info.path), None, info.name)
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
