# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The plot of waveforms (``WavePlot``), drawn with QPainter.

A waveform has up to millions of samples, so the plot keeps the whole arrays and draws only what
is on screen: ``ola.wave_view.decimate`` turns the visible part into the minimum and the maximum of
each pixel column (a glitch of one sample is never lost) and, zoomed in far enough, the samples
themselves. The mouse: the wheel zooms the time axis around the pointer (with Ctrl, the voltage
axis), dragging moves the view, a double click shows everything again, a click puts a cursor (two
cursors give the time and voltage differences: a rise time, a ripple), and under the pointer the
value of each curve is read. The colours follow the application palette (light and dark themes).
"""

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from frontend.ui.plot_widget import LINE_COLORS, draw_empty_chart
from ola.run_view import format_si, nice_ticks
from ola.wave_view import decimate

# A curve: (label, times in s, values in V), numpy arrays.
WaveCurve = Tuple[str, np.ndarray, np.ndarray]
ZOOM_STEP = 1.25


class WavePlot(QWidget):
    """Waveforms against time, with zoom, pan and two cursors; see the module docstring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.curves: List[WaveCurve] = []
        self.empty_text = ""
        self.y_unit = "V"
        self.view: Optional[List[float]] = None  # [x0, x1, y0, y1]; None: show everything
        self.cursors: List[Tuple[float, float]] = []  # (time, value of the first curve) x 0..2
        self._hover: Optional[float] = None
        self._drag: Optional[Tuple[float, float, List[float]]] = None
        self._moved = False
        self._plot = QRectF()
        self.setMouseTracking(True)
        self.setMinimumSize(420, 260)

    # ----- what is drawn ----------------------------------------------------------------------
    def set_curves(self, curves: Sequence[WaveCurve], keep_view: bool = True) -> None:
        """Replace the curves. The zoom is kept unless ``keep_view`` is False or nothing is left."""
        self.curves = [(n, np.asarray(t), np.asarray(v)) for n, t, v in curves]
        if not keep_view or not self.curves:
            self.view = None
            self.cursors = []
        self.update()

    def full_range(self) -> Optional[Tuple[float, float, float, float]]:
        """``(x0, x1, y0, y1)`` of everything, or None if there is nothing."""
        if not self.curves or not all(len(c[1]) for c in self.curves):
            return None
        x0 = min(float(c[1][0]) for c in self.curves)
        x1 = max(float(c[1][-1]) for c in self.curves)
        y0 = min(float(np.nanmin(c[2])) for c in self.curves)
        y1 = max(float(np.nanmax(c[2])) for c in self.curves)
        if y1 <= y0:
            y0, y1 = y0 - 0.5, y1 + 0.5
        if x1 <= x0:
            x1 = x0 + 1e-9
        pad = 0.05 * (y1 - y0)
        return x0, x1, y0 - pad, y1 + pad

    def current_view(self) -> Optional[Tuple[float, float, float, float]]:
        """The part shown: the zoom, or everything."""
        full = self.full_range()
        if full is None:
            return None
        if self.view is None:
            return full
        x0, x1, y0, y1 = self.view
        return x0, x1, y0, y1

    def reset_view(self) -> None:
        """Show everything again."""
        self.view = None
        self.update()

    def value_at(self, index: int, x: float) -> Optional[float]:
        """The value of curve ``index`` at the sample nearest to time ``x``."""
        t, v = self.curves[index][1], self.curves[index][2]
        if len(t) == 0:
            return None
        k = int(np.clip(np.searchsorted(t, x), 1, len(t) - 1)) if len(t) > 1 else 0
        if len(t) > 1 and abs(t[k - 1] - x) < abs(t[k] - x):
            k -= 1
        return float(v[k])

    def readout(self, x: float) -> List[str]:
        """One line per curve with its value at the time ``x``."""
        lines = []
        for i, curve in enumerate(self.curves):
            value = self.value_at(i, x)
            if value is not None:
                lines.append(f"{curve[0]}: {format_si(value, self.y_unit)}")
        return lines

    def cursor_text(self) -> str:
        """The difference between the two cursors (``dt = 120 ns, dV = 4.1 V``), or ''."""
        if len(self.cursors) < 2:
            return ""
        (xa, ya), (xb, yb) = self.cursors
        return f"dt = {format_si(abs(xb - xa), 's')}, dV = {format_si(abs(yb - ya), self.y_unit)}"

    # ----- the mouse --------------------------------------------------------------------------
    def _to_data(self, pos: QPointF) -> Optional[Tuple[float, float]]:
        view = self.current_view()
        if view is None or self._plot.width() <= 0 or not self._plot.contains(pos):
            return None
        x0, x1, y0, y1 = view
        x = x0 + (pos.x() - self._plot.left()) / self._plot.width() * (x1 - x0)
        y = y1 - (pos.y() - self._plot.top()) / self._plot.height() * (y1 - y0)
        return x, y

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt name)
        view = self.current_view()
        point = self._to_data(event.position())
        if view is None or point is None:
            return
        factor = 1 / ZOOM_STEP if event.angleDelta().y() > 0 else ZOOM_STEP
        x0, x1, y0, y1 = view
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:  # the voltage axis
            y0, y1 = point[1] - (point[1] - y0) * factor, point[1] + (y1 - point[1]) * factor
        else:  # the time axis, around the pointer
            x0, x1 = point[0] - (point[0] - x0) * factor, point[0] + (x1 - point[0]) * factor
        self.view = [x0, x1, y0, y1]
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        view = self.current_view()
        if view is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag = (event.position().x(), event.position().y(), list(view))
            self._moved = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt name)
        pos = event.position()
        if self._drag is not None and self._plot.width() > 0:
            px, py, (x0, x1, y0, y1) = self._drag
            if abs(pos.x() - px) + abs(pos.y() - py) > 3:
                self._moved = True
            dx = (pos.x() - px) / self._plot.width() * (x1 - x0)
            dy = (pos.y() - py) / self._plot.height() * (y1 - y0)
            self.view = [x0 - dx, x1 - dx, y0 + dy, y1 + dy]
        point = self._to_data(pos)
        self._hover = point[0] if point else None
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if self._drag is not None and not self._moved:  # a click: a cursor
            point = self._to_data(event.position())
            if point is not None and self.curves:
                value = self.value_at(0, point[0])
                if len(self.cursors) >= 2:
                    self.cursors = []
                self.cursors.append((point[0], value if value is not None else point[1]))
                self.update()
        self._drag = None

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt name)
        self.reset_view()
        self.cursors = []

    def leaveEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        self._hover = None
        self.update()

    # ----- drawing ----------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        text = palette.windowText().color()
        grid = QColor(text)
        grid.setAlpha(40)
        painter.fillRect(self.rect(), palette.base())
        painter.setPen(text)
        view = self.current_view()
        if view is None:
            draw_empty_chart(painter, self.rect(), text, grid, self.empty_text)
            return
        x0, x1, y0, y1 = view
        metrics = QFontMetrics(self.font())
        xticks = nice_ticks(x0, x1, 8)
        yticks = nice_ticks(y0, y1, 6)
        left = max(metrics.horizontalAdvance(format_si(t, self.y_unit)) for t in yticks) + 14
        plot = QRectF(left, 12, max(self.width() - left - 14, 10), max(self.height() - 52, 10))
        self._plot = plot

        def px(x: float) -> float:
            return plot.left() + (x - x0) / ((x1 - x0) or 1) * plot.width()

        def py(y: float) -> float:
            return plot.bottom() - (y - y0) / ((y1 - y0) or 1) * plot.height()

        painter.setPen(grid)
        for tick in xticks:
            if x0 <= tick <= x1:
                painter.drawLine(QPointF(px(tick), plot.top()), QPointF(px(tick), plot.bottom()))
        for tick in yticks:
            if y0 <= tick <= y1:
                painter.drawLine(QPointF(plot.left(), py(tick)), QPointF(plot.right(), py(tick)))
        painter.setPen(text)
        painter.drawRect(plot)
        for tick in xticks:
            if x0 <= tick <= x1:
                label = format_si(tick, "s")
                painter.drawText(
                    QPointF(px(tick) - metrics.horizontalAdvance(label) / 2, plot.bottom() + 16),
                    label,
                )
        for tick in yticks:
            if y0 <= tick <= y1:
                label = format_si(tick, self.y_unit)
                painter.drawText(
                    QPointF(plot.left() - metrics.horizontalAdvance(label) - 4, py(tick) + 4), label
                )
        painter.setClipRect(plot)
        columns = max(int(plot.width()), 50)
        for i, (_name, t, v) in enumerate(self.curves):
            xs, ys = decimate(t, v, x0, x1, columns)
            if len(xs) == 0:
                continue
            path = QPainterPath(QPointF(px(xs[0]), py(ys[0])))
            for x, y in zip(xs[1:], ys[1:]):
                if math.isfinite(y):
                    path.lineTo(QPointF(px(x), py(y)))
            painter.setPen(QPen(QColor(LINE_COLORS[i % len(LINE_COLORS)]), 1.3))
            painter.drawPath(path)
        for number, (cx, _cy) in enumerate(self.cursors):
            color = QColor(text)
            color.setAlpha(170)
            painter.setPen(QPen(color, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(px(cx), plot.top()), QPointF(px(cx), plot.bottom()))
            painter.drawText(QPointF(px(cx) + 3, plot.top() + 12), "AB"[number])
        if self._hover is not None:
            painter.setPen(grid)
            painter.drawLine(
                QPointF(px(self._hover), plot.top()), QPointF(px(self._hover), plot.bottom())
            )
        painter.setClipping(False)
        lines = self.readout(self._hover) if self._hover is not None else []
        if self._hover is not None:
            lines.insert(0, format_si(self._hover, "s"))
        extra = self.cursor_text()
        if extra:
            lines.append(extra)
        for row, line in enumerate(lines):
            painter.setPen(text)
            painter.drawText(QPointF(plot.left() + 8, plot.top() + 14 + 14 * row), line)
        for i, (name, _t, _v) in enumerate(self.curves):  # the legend, right-aligned
            color = QColor(LINE_COLORS[i % len(LINE_COLORS)])
            painter.setPen(color)
            width = metrics.horizontalAdvance(name)
            painter.drawText(QPointF(plot.right() - width - 8, plot.top() + 14 + 14 * i), name)
