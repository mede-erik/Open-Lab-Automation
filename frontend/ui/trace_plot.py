# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Plots of curves (``TracePlot``) and the Smith chart (``SmithChart``), drawn with QPainter.

``TracePlot`` draws several curves against x, with a linear or logarithmic x axis (frequency),
dashed limit lines, and a read-out that follows the mouse (each curve's value at the x under it).
``SmithChart`` draws reflection coefficients on the Smith chart (circles of constant resistance and
reactance); under the mouse it reads the nearest point as a reflection coefficient and an impedance.
Both take their colours from the application palette, so they follow the dark or light theme.
"""

import math
from typing import List, Optional, Sequence, Tuple

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from frontend.ui.plot_widget import LINE_COLORS, draw_empty_chart
from ola import rf
from ola.run_view import format_si, log_ticks, nice_ticks

# A curve: (label, xs, ys). A limit is drawn dashed, in red, and is not part of the read-out.
Curve = Tuple[str, Sequence[float], Sequence[float]]
LIMIT_COLOR = "#e53935"


def tick_label(value: float, unit: str) -> str:
    """A label for an axis value: with a prefix if the axis has a unit (``2 GHz``)."""
    return format_si(value, unit) if unit else f"{value:.6g}"


class TracePlot(QWidget):
    """Curves against x; see the module docstring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.curves: List[Curve] = []
        self.limits: List[Curve] = []
        self.xlabel = self.ylabel = ""
        # Which y axis each curve (and limit) belongs to: curves with the same key share a scale.
        # One key for everything: a single axis. ``axis_labels`` gives the title of each axis.
        self.curve_axes: List[str] = []
        self.limit_axes: List[str] = []
        self.axis_labels = {}
        self.x_unit = ""  # unit of x for the tick labels ("Hz": 1 MHz, 2 GHz...)
        self.log_x = False
        self.empty_text = ""  # shown while there is no data (the panel gives it, translated)
        self._hover: Optional[float] = None
        self._plot = QRectF()
        self.setMouseTracking(True)
        self.setMinimumSize(360, 240)

    def set_curves(
        self,
        curves: Sequence[Curve],
        xlabel: str = "",
        ylabel: str = "",
        limits: Sequence[Curve] = (),
        log_x: bool = False,
        x_unit: str = "",
        curve_axes: Sequence[str] = (),
        limit_axes: Sequence[str] = (),
        axis_labels=None,
    ) -> None:
        """Replace what is drawn. ``log_x`` is ignored if x has values that are not positive.

        ``curve_axes`` (one key per curve) and ``limit_axes`` put curves of different kinds on
        their own y scales (the first on the left, the others on the right); ``axis_labels`` maps
        a key to the title of its axis. Without them every curve shares one axis."""
        self.curves, self.limits = list(curves), list(limits)
        self.curve_axes = list(curve_axes)
        self.limit_axes = list(limit_axes)
        self.axis_labels = dict(axis_labels or {})
        self.xlabel, self.ylabel, self.x_unit = xlabel, ylabel, x_unit
        self.log_x = log_x and all(x > 0 for c in self.curves for x in c[1])
        self.update()

    # ----- numbers ----------------------------------------------------------------------------
    def ranges(self) -> Optional[Tuple[float, float, float, float]]:
        """``(xmin, xmax, ymin, ymax)`` over curves and limits, or None if there is nothing."""
        xs = [x for c in self.curves + self.limits for x in c[1]]
        ys = [y for c in self.curves + self.limits for y in c[2] if math.isfinite(y)]
        if not xs or not ys:
            return None
        return min(xs), max(xs), min(ys), max(ys)

    def y_axes(self) -> List[Tuple[str, str, List[int], float, float]]:
        """The y scales: ``(key, title, indexes of its curves, ymin, ymax)``, first the left one.

        Curves without a key, or all curves if no keys were given, share one scale."""
        keys = [
            self.curve_axes[i] if i < len(self.curve_axes) else "" for i in range(len(self.curves))
        ]
        order: List[str] = []
        for key in keys:
            if key not in order:
                order.append(key)
        axes = []
        for key in order:
            members = [i for i, k in enumerate(keys) if k == key]
            values = [y for i in members for y in self.curves[i][2] if math.isfinite(y)]
            for j, limit in enumerate(self.limits):
                if (self.limit_axes[j] if j < len(self.limit_axes) else order[0]) == key:
                    values += [y for y in limit[2] if math.isfinite(y)]
            if values:
                title = self.axis_labels.get(key, self.ylabel if len(order) == 1 else key)
                axes.append((key, title, members, min(values), max(values)))
        return axes

    def readout(self, x: float) -> List[str]:
        """Lines of text with the value of every curve at the point nearest to ``x``."""
        lines = []
        for label, xs, ys in self.curves:
            if not xs:
                continue
            i = min(range(len(xs)), key=lambda k: abs(xs[k] - x))
            lines.append(f"{label}: {ys[i]:.5g}  @ {tick_label(xs[i], self.x_unit)}")
        return lines

    # ----- drawing ----------------------------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt name)
        pos = event.position()
        self._hover = self._x_at(pos.x()) if self._plot.contains(pos) else None
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        self._hover = None
        self.update()

    def _x_at(self, px: float) -> Optional[float]:
        bounds = self.ranges()
        if bounds is None or self._plot.width() <= 0:
            return None
        x0, x1 = bounds[0], bounds[1]
        t = (px - self._plot.left()) / self._plot.width()
        if self.log_x and x0 > 0:
            return 10 ** (math.log10(x0) + t * (math.log10(x1) - math.log10(x0)))
        return x0 + t * (x1 - x0)

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
            draw_empty_chart(painter, self.rect(), text, grid, self.empty_text)
            return
        xmin, xmax, ymin, ymax = bounds
        if self.log_x:
            xticks = log_ticks(xmin, xmax)
            x0, x1 = math.log10(xmin), math.log10(xmax) if xmax > xmin else math.log10(xmin) + 1
        else:
            xticks = nice_ticks(xmin, xmax, 7)
            x0, x1 = min(xticks + [xmin]), max(xticks + [xmax])
        axes = self.y_axes()
        scales = []  # per axis: (title, color, ticks, y0, y1, label width)
        for key, title, members, lo, hi in axes:
            ticks = nice_ticks(lo, hi, 6)
            width = max(metrics.horizontalAdvance(tick_label(t, "")) for t in ticks)
            color = QColor(LINE_COLORS[members[0] % len(LINE_COLORS)]) if len(axes) > 1 else text
            scales.append((title, color, ticks, min(ticks + [lo]), max(ticks + [hi]), width))
        left = scales[0][5] + 46
        extra = [s[5] + 44 for s in scales[1:]]  # the axes on the right: label width + room
        bottom = 46 + (metrics.height() if self.xlabel else 0)
        plot = QRectF(
            left,
            14,
            max(self.width() - left - 16 - sum(extra), 10),
            max(self.height() - 14 - bottom, 10),
        )
        self._plot = plot

        def px(x: float) -> float:
            value = math.log10(x) if self.log_x else x
            return plot.left() + (value - x0) / ((x1 - x0) or 1) * plot.width()

        def make_py(y0: float, y1: float):
            return lambda y: plot.bottom() - (y - y0) / ((y1 - y0) or 1) * plot.height()

        pys = [make_py(sc[3], sc[4]) for sc in scales]

        for t in xticks:
            if not (self.log_x and t <= 0):
                painter.setPen(QPen(grid))
                painter.drawLine(QPointF(px(t), plot.top()), QPointF(px(t), plot.bottom()))
                painter.setPen(text)
                label = tick_label(t, self.x_unit)
                where = QPointF(
                    px(t) - metrics.horizontalAdvance(label) / 2,
                    plot.bottom() + metrics.height() + 2,
                )
                painter.drawText(where, label)
        offset = 0.0
        for n, (title, color, ticks, _y0, _y1, width) in enumerate(scales):
            py = pys[n]
            for t in ticks:
                if n == 0:  # the grid follows the first scale only
                    painter.setPen(QPen(grid))
                    painter.drawLine(QPointF(plot.left(), py(t)), QPointF(plot.right(), py(t)))
                painter.setPen(color)
                label = tick_label(t, "")
                if n == 0:
                    x_text = plot.left() - metrics.horizontalAdvance(label) - 6
                else:
                    x_text = plot.right() + offset + 6
                    painter.drawLine(
                        QPointF(plot.right() + offset, py(t)),
                        QPointF(plot.right() + offset + 4, py(t)),
                    )
                painter.drawText(QPointF(x_text, py(t) + metrics.ascent() / 2 - 1), label)
            if n > 0:
                painter.setPen(QPen(color, 1))
                painter.drawLine(
                    QPointF(plot.right() + offset, plot.top()),
                    QPointF(plot.right() + offset, plot.bottom()),
                )
            title_x = 12 if n == 0 else plot.right() + offset + width + 28
            if title:
                painter.save()
                painter.setPen(color)
                painter.translate(title_x, plot.center().y())
                painter.rotate(-90)
                box = QRectF(
                    -plot.height() / 2, -metrics.height(), plot.height(), metrics.height() + 2
                )
                painter.drawText(box, Qt.AlignmentFlag.AlignCenter, title)
                painter.restore()
            if n > 0:
                offset += width + 44
        painter.setPen(QPen(text, 1))
        painter.drawRect(plot)
        if self.xlabel:
            box = QRectF(
                plot.left(), self.height() - metrics.height() - 4, plot.width(), metrics.height()
            )
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self.xlabel)
        painter.setClipRect(plot.adjusted(-4, -4, 4, 4))
        keys = [a[0] for a in axes]
        for j, (_label, xs, ys) in enumerate(self.limits):  # the limits, dashed
            pen = QPen(QColor(LIMIT_COLOR), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            key = self.limit_axes[j] if j < len(self.limit_axes) else keys[0]
            py = pys[keys.index(key)] if key in keys else pys[0]
            points = QPolygonF([QPointF(px(x), py(y)) for x, y in zip(xs, ys)])
            painter.drawPolyline(points)
        for n, (_label, xs, ys) in enumerate(self.curves):
            color = QColor(LINE_COLORS[n % len(LINE_COLORS)])
            key = self.curve_axes[n] if n < len(self.curve_axes) else ""
            py = pys[keys.index(key)] if key in keys else pys[0]
            points = QPolygonF([QPointF(px(x), py(y)) for x, y in zip(xs, ys) if math.isfinite(y)])
            painter.setPen(QPen(color, 2))
            painter.drawPolyline(points)
            if len(points) <= 60:  # markers only when there are few points
                painter.setBrush(color)
                for p in points:
                    painter.drawEllipse(p, 3, 3)
        painter.setClipping(False)
        self._legend(painter, plot, metrics, palette)
        if self._hover is not None:
            self._draw_hover(painter, plot, metrics, palette, px)

    def _legend(self, painter, plot: QRectF, metrics, palette) -> None:
        entries = [(c[0], LINE_COLORS[n % len(LINE_COLORS)]) for n, c in enumerate(self.curves)]
        entries += [(c[0], LIMIT_COLOR) for c in self.limits[:1]]
        if len(entries) < 2:
            return
        width = max(metrics.horizontalAdvance(label) for label, _ in entries) + 30
        box = QRectF(
            plot.right() - width - 6,
            plot.top() + 4,
            width,
            len(entries) * (metrics.height() + 3) + 6,
        )
        background = QColor(palette.base().color())
        background.setAlpha(210)
        painter.fillRect(box, background)
        for n, (label, color) in enumerate(entries):
            yy = box.top() + 6 + n * (metrics.height() + 3) + metrics.height() / 2
            painter.setPen(QPen(QColor(color), 3))
            painter.drawLine(QPointF(box.left() + 5, yy), QPointF(box.left() + 18, yy))
            painter.setPen(palette.windowText().color())
            painter.drawText(QPointF(box.left() + 23, yy + metrics.ascent() / 2 - 1), label)

    def _draw_hover(self, painter, plot: QRectF, metrics, palette, px) -> None:
        painter.setPen(QPen(palette.windowText().color(), 1, Qt.PenStyle.DotLine))
        x = px(self._hover)
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        lines = self.readout(self._hover)
        if not lines:
            return
        width = max(metrics.horizontalAdvance(line) for line in lines) + 12
        height = len(lines) * metrics.height() + 8
        left = x + 10 if x + 10 + width < plot.right() else x - 10 - width
        box = QRectF(left, plot.bottom() - height - 6, width, height)
        background = QColor(palette.base().color())
        background.setAlpha(230)
        painter.fillRect(box, background)
        painter.setPen(palette.windowText().color())
        painter.drawRect(box)
        for n, line in enumerate(lines):
            painter.drawText(
                QPointF(
                    box.left() + 6, box.top() + 4 + (n + 1) * metrics.height() - metrics.descent()
                ),
                line,
            )


# Circles drawn on the Smith chart: normalised resistances and reactances.
SMITH_VALUES = (0.2, 0.5, 1.0, 2.0, 5.0)


class SmithChart(QWidget):
    """Reflection coefficients on the Smith chart; ``set_curves([(label, re, im), ...])``."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.curves: List[Curve] = []
        self.z0 = 50.0
        self._hover: Optional[Tuple[float, float]] = None
        self._center, self._radius = QPointF(), 1.0
        self.setMouseTracking(True)
        self.setMinimumSize(300, 300)

    def set_curves(self, curves: Sequence[Curve], z0: float = 50.0) -> None:
        """Replace what is drawn (x of a curve = real part, y = imaginary part of Gamma)."""
        self.curves, self.z0 = list(curves), z0
        self.update()

    def nearest(self, gx: float, gy: float) -> Optional[Tuple[str, complex]]:
        """The curve point nearest to a point of the chart: ``(label, gamma)``; None if no data."""
        best = None
        for label, xs, ys in self.curves:
            for x, y in zip(xs, ys):
                d = (x - gx) ** 2 + (y - gy) ** 2
                if best is None or d < best[0]:
                    best = (d, label, complex(x, y))
        return (best[1], best[2]) if best else None

    def readout(self, gx: float, gy: float) -> Optional[str]:
        """Text for the point nearest to ``(gx, gy)``: reflection coefficient and impedance."""
        found = self.nearest(gx, gy)
        if found is None:
            return None
        label, gamma = found
        z = rf.gamma_to_z([gamma], self.z0)[0]
        z_text = (
            "open"
            if math.isinf(z.real)
            else f"{z.real:.4g} {'+' if z.imag >= 0 else '-'} j{abs(z.imag):.4g} ohm"
        )
        sign = "+" if gamma.imag >= 0 else "-"
        g_text = f"{gamma.real:.4f} {sign} j{abs(gamma.imag):.4f}"
        return f"{label}: G = {g_text}   Z = {z_text}   VSWR {rf.vswr([gamma])[0]:.3g}"

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt name)
        pos = event.position()
        gx, gy = (pos.x() - self._center.x()) / self._radius, (
            self._center.y() - pos.y()
        ) / self._radius
        self._hover = (gx, gy) if gx * gx + gy * gy <= 1.1 else None
        self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        self._hover = None
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt name)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        text = palette.windowText().color()
        grid = QColor(text)
        grid.setAlpha(70)
        painter.fillRect(self.rect(), palette.base())
        side = min(self.width(), self.height()) - 50
        radius = max(side / 2, 10)
        center = QPointF(self.width() / 2, (self.height() - 24) / 2 + 6)
        self._center, self._radius = center, radius

        def pt(gx: float, gy: float) -> QPointF:
            return QPointF(center.x() + gx * radius, center.y() - gy * radius)

        painter.setPen(QPen(text, 1.5))
        painter.drawEllipse(center, radius, radius)
        painter.setPen(QPen(grid, 1))
        painter.drawLine(pt(-1, 0), pt(1, 0))
        clip = QPainterPath()
        clip.addEllipse(center, radius, radius)
        painter.save()
        painter.setClipPath(clip)
        for r in SMITH_VALUES:  # constant resistance: centre (r/(1+r), 0), radius 1/(1+r)
            c, rad = r / (1 + r), 1 / (1 + r)
            painter.drawEllipse(pt(c, 0), rad * radius, rad * radius)
        for x in SMITH_VALUES:  # constant reactance: centre (1, +-1/x), radius 1/x
            rad = 1 / x
            painter.drawEllipse(pt(1, rad), rad * radius, rad * radius)
            painter.drawEllipse(pt(1, -rad), rad * radius, rad * radius)
        painter.restore()
        painter.setPen(text)
        metrics = QFontMetrics(self.font())
        for r in (0.0,) + SMITH_VALUES:  # labels of the resistance circles on the real axis
            label = f"{r * self.z0:g}"
            gx = (r - 1) / (r + 1)
            painter.drawText(
                pt(gx, 0) + QPointF(-metrics.horizontalAdvance(label) / 2, metrics.height() + 2),
                label,
            )

        for n, (_label, xs, ys) in enumerate(self.curves):
            color = QColor(LINE_COLORS[n % len(LINE_COLORS)])
            points = QPolygonF([pt(x, y) for x, y in zip(xs, ys)])
            painter.setPen(QPen(color, 2))
            painter.drawPolyline(points)
            painter.setBrush(color)
            if len(points):  # a dot at the first point (lowest frequency), a square at the last
                painter.drawEllipse(points[0], 4, 4)
                end = points[len(points) - 1]
                painter.drawRect(QRectF(end.x() - 4, end.y() - 4, 8, 8))
        if len(self.curves) > 1:
            for n, (label, _xs, _ys) in enumerate(self.curves):
                painter.setPen(QColor(LINE_COLORS[n % len(LINE_COLORS)]))
                painter.drawText(QPointF(10, 18 + n * (metrics.height() + 2)), label)
        if self._hover is not None:
            line = self.readout(*self._hover)
            if line:
                painter.setPen(text)
                painter.drawText(QPointF(8, self.height() - 8), line)
