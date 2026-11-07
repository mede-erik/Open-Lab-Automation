# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Paints a label ``Drawing`` (``ola.labels``) on a screen widget, a PDF or an image.

The drawing is in millimetres; ``paint_drawing`` scales it to pixels. A PDF is written at its real
size, one page per drawing (a single label is a page of its own size, a sheet of labels an A4 page),
and an image at a resolution in dots per inch (300 for a label printer). The texts use
``Helvetica`` (any sans-serif the system has if not).
"""

from typing import Sequence

from PyQt6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)

from ola.labels import QR, Box, Drawing, Line, Text

FONT_FAMILY = "Helvetica"
MEASURE_PIXELS = 200  # the size the font is measured at: large, so hinting does not matter
MEASURE_MARGIN = 1.02  # and 2 % on top, for the rounding of the real size to whole pixels


def make_font(pixel_size: int, bold: bool) -> QFont:
    """The font of the labels: the same one for painting and for measuring."""
    font = QFont(FONT_FAMILY)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(max(1, pixel_size))
    font.setBold(bold)
    return font


def text_measure(text: str, size_mm: float, bold: bool = False) -> float:
    """The width in mm of ``text`` at font size ``size_mm`` in the font that is **really used**
    (the one the system gives for ``FONT_FAMILY``, which on a computer without Helvetica is a
    wider one). Pass it as ``measure`` to ``ola.labels.build_drawing`` so that the layout fits
    the text to the label with the true widths. Needs a ``QGuiApplication``."""
    metrics = QFontMetricsF(make_font(MEASURE_PIXELS, bold))
    return metrics.horizontalAdvance(text) / MEASURE_PIXELS * size_mm * MEASURE_MARGIN


def paint_drawing(painter: QPainter, drawing: Drawing, scale: float, dx: float = 0, dy: float = 0):
    """Paint ``drawing`` with ``scale`` pixels per millimetre, its corner at ``(dx, dy)`` pixels.
    The background is white."""
    painter.save()
    painter.translate(dx, dy)
    painter.fillRect(QRectF(0, 0, drawing.width * scale, drawing.height * scale), QColor("white"))
    black = QColor("black")
    for item in drawing.items:
        if isinstance(item, Text):
            painter.setFont(make_font(round(item.size * scale), item.bold))
            painter.setPen(black)
            x = item.x * scale
            if item.anchor == "middle":
                x -= painter.fontMetrics().horizontalAdvance(item.text) / 2
            elif item.anchor == "end":
                x -= painter.fontMetrics().horizontalAdvance(item.text)
            painter.drawText(QPointF(x, item.y * scale), item.text)
        elif isinstance(item, Box):
            painter.setPen(QPen(black, 0.2 * scale))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(item.x * scale, item.y * scale, item.w * scale, item.h * scale))
        elif isinstance(item, Line):
            pen = QPen(black, 0.15 * scale)
            if item.dashed:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(
                QPointF(item.x1 * scale, item.y1 * scale), QPointF(item.x2 * scale, item.y2 * scale)
            )
        elif isinstance(item, QR):
            _paint_qr(painter, item, scale)
    painter.restore()


def _paint_qr(painter: QPainter, qr: QR, scale: float) -> None:
    """The modules, each a filled square; edges are rounded to whole pixels so that modules touch
    exactly (a gap between two dark modules would be a white line in the code)."""
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("black"))
    for r, row in enumerate(qr.matrix):
        for c, dark in enumerate(row):
            if dark:
                x0, x1 = round((qr.x + c * qr.module) * scale), round(
                    (qr.x + (c + 1) * qr.module) * scale
                )
                y0, y1 = round((qr.y + r * qr.module) * scale), round(
                    (qr.y + (r + 1) * qr.module) * scale
                )
                painter.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))


def render_image(drawing: Drawing, dpi: int = 300) -> QImage:
    """The drawing as an image at ``dpi`` dots per inch (the size in pixels is its size in mm)."""
    scale = dpi / 25.4
    image = QImage(
        round(drawing.width * scale), round(drawing.height * scale), QImage.Format.Format_RGB32
    )
    image.setDotsPerMeterX(round(dpi / 0.0254))
    image.setDotsPerMeterY(round(dpi / 0.0254))
    painter = QPainter(image)
    paint_drawing(painter, drawing, scale)
    painter.end()
    return image


def write_pdf(path: str, drawings: Sequence[Drawing], dpi: int = 300) -> None:
    """A PDF with one page per drawing, each at its real size in millimetres. ``ValueError`` if
    there is nothing to write."""
    if not drawings:
        raise ValueError("there is no label to write")
    scale = dpi / 25.4
    writer = QPdfWriter(path)
    writer.setResolution(dpi)
    first = drawings[0]
    writer.setPageLayout(_layout(first))
    painter = QPainter(writer)
    for n, drawing in enumerate(drawings):
        if n:
            writer.setPageLayout(_layout(drawing))
            writer.newPage()
        paint_drawing(painter, drawing, scale)
    painter.end()


def _layout(drawing: Drawing) -> QPageLayout:
    size = QPageSize(QSizeF(drawing.width, drawing.height), QPageSize.Unit.Millimeter)
    return QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))
