"""A small line plot drawn with QPainter (no extra library), readable in light and dark themes.

``LinePlot.set_series([(label, xs, ys), ...], xlabel, ylabel)`` draws one line per series with
round axis ticks (``ola.run_view.nice_ticks``), a light grid and a legend. Colours come from the
application palette, so the plot follows the theme.
"""

from typing import List, Sequence, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from ola.run_view import nice_ticks

Series = Tuple[str, Sequence[float], Sequence[float]]
# Distinct colours that work on a light and on a dark background.
LINE_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#17becf",
]


def format_tick(value: float) -> str:
    """A short label for an axis value (``0.5``, ``12``, ``1.5e-06``)."""
    return f"{value:.6g}"


class LinePlot(QWidget):
    """Lines with markers on a plain grid; ``set_series`` redraws."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: List[Series] = []
        self.xlabel = self.ylabel = ""
        self.setMinimumSize(320, 220)

    def set_series(self, series: Sequence[Series], xlabel: str = "", ylabel: str = "") -> None:
        self.series, self.xlabel, self.ylabel = list(series), xlabel, ylabel
        self.update()

    def ranges(self):
        """``(xmin, xmax, ymin, ymax)`` of all the data, or None if there is none."""
        xs = [x for _, sx, _ in self.series for x in sx]
        ys = [y for _, _, sy in self.series for y in sy]
        if not xs or not ys:
            return None
        return min(xs), max(xs), min(ys), max(ys)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        text = palette.windowText().color()
        grid = QColor(text)
        grid.setAlpha(40)
        painter.fillRect(self.rect(), palette.base())
        painter.setPen(text)
        metrics = QFontMetrics(self.font())
        bounds = self.ranges()
        if bounds is None:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "-")
            return
        xmin, xmax, ymin, ymax = bounds
        xticks, yticks = nice_ticks(xmin, xmax, 7), nice_ticks(ymin, ymax, 6)
        x0, x1 = min(xticks + [xmin]), max(xticks + [xmax])
        y0, y1 = min(yticks + [ymin]), max(yticks + [ymax])
        left = max(metrics.horizontalAdvance(format_tick(t)) for t in yticks) + 46
        right, top, bottom = 16, 14, 46 + (metrics.height() if self.xlabel else 0)
        plot = QRectF(
            left, top, max(self.width() - left - right, 10), max(self.height() - top - bottom, 10)
        )

        def px(x: float) -> float:
            return plot.left() + (x - x0) / ((x1 - x0) or 1) * plot.width()

        def py(y: float) -> float:
            return plot.bottom() - (y - y0) / ((y1 - y0) or 1) * plot.height()

        for t in xticks:
            painter.setPen(QPen(grid))
            painter.drawLine(QPointF(px(t), plot.top()), QPointF(px(t), plot.bottom()))
            painter.setPen(text)
            label = format_tick(t)
            painter.drawText(
                QPointF(
                    px(t) - metrics.horizontalAdvance(label) / 2,
                    plot.bottom() + metrics.height() + 2,
                ),
                label,
            )
        for t in yticks:
            painter.setPen(QPen(grid))
            painter.drawLine(QPointF(plot.left(), py(t)), QPointF(plot.right(), py(t)))
            painter.setPen(text)
            label = format_tick(t)
            painter.drawText(
                QPointF(
                    plot.left() - metrics.horizontalAdvance(label) - 6,
                    py(t) + metrics.ascent() / 2 - 1,
                ),
                label,
            )
        painter.setPen(QPen(text, 1))
        painter.drawRect(plot)
        if self.xlabel:
            painter.drawText(
                QRectF(
                    plot.left(),
                    self.height() - metrics.height() - 4,
                    plot.width(),
                    metrics.height(),
                ),
                Qt.AlignmentFlag.AlignCenter,
                self.xlabel,
            )
        if self.ylabel:
            painter.save()
            painter.translate(12, plot.center().y())
            painter.rotate(-90)
            painter.drawText(
                QRectF(-plot.height() / 2, -metrics.height(), plot.height(), metrics.height() + 2),
                Qt.AlignmentFlag.AlignCenter,
                self.ylabel,
            )
            painter.restore()

        painter.setClipRect(plot.adjusted(-4, -4, 4, 4))
        for n, (_label, sx, sy) in enumerate(self.series):
            color = QColor(LINE_COLORS[n % len(LINE_COLORS)])
            points = QPolygonF([QPointF(px(x), py(y)) for x, y in zip(sx, sy)])
            painter.setPen(QPen(color, 2))
            painter.drawPolyline(points)
            painter.setBrush(color)
            for p in points:
                painter.drawEllipse(p, 3.5, 3.5)
        painter.setClipping(False)
        if len(self.series) > 1:  # legend, inside the plot, top right
            y = plot.top() + 6
            width = max(metrics.horizontalAdvance(s[0]) for s in self.series) + 30
            box = QRectF(
                plot.right() - width - 6,
                plot.top() + 4,
                width,
                len(self.series) * (metrics.height() + 3) + 6,
            )
            background = QColor(palette.base().color())
            background.setAlpha(210)
            painter.fillRect(box, background)
            for n, (label, _, _) in enumerate(self.series):
                color = QColor(LINE_COLORS[n % len(LINE_COLORS)])
                painter.setPen(QPen(color, 3))
                yy = y + n * (metrics.height() + 3) + metrics.height() / 2
                painter.drawLine(QPointF(box.left() + 5, yy), QPointF(box.left() + 18, yy))
                painter.setPen(text)
                painter.drawText(QPointF(box.left() + 23, yy + metrics.ascent() / 2 - 1), label)
