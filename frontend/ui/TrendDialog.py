# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""How a cable ages: a figure of its measurements against the date (from *History...* of the
registry window, *Trend...*).

A thin layer over ``ola.trend`` (which does the work and is tested without a screen): choose the
figure (the worst loss, the loss at a frequency of interest...), and optionally the limit, the
fastest change for the worse that is accepted and how near the limit is a warning. The plot shows
the measurements against the days since the first one, the straight line through them and the
limit; under it the verdict, the rate per year and the date the line reaches the limit. The series
can be saved as CSV. Strings: ``frontend/lang/modules/assets/<lang>.json`` (``ast_t_*``).
"""

import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence, Union

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.module_translator import CatalogTranslator
from frontend.ui.trace_plot import TracePlot
from ola import trend
from ola.trend import DAY, Trend


class TrendDialog(QDialog):
    """The trend of one object (see the module docstring)."""

    def __init__(
        self,
        code: str,
        run_dirs: Sequence[Union[str, Path]],
        translator: Any = None,
        parent: Optional[QWidget] = None,
        name: str = "",
        measurement: str = "cable",
    ):
        super().__init__(parent)
        self.tr_ = CatalogTranslator("assets", translator)
        self._t = self.tr_.t
        self.code, self.run_dirs, self.measurement = code, list(run_dirs), measurement
        self.result: Optional[Trend] = None
        self.setWindowTitle(self._t("ast_t_title", code=code, name=name))
        self.resize(900, 640)
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        grid = QGridLayout()
        self.figure_box = QComboBox()
        self.figure_box.activated.connect(lambda _i: self.update_trend())
        grid.addWidget(QLabel(self._t("ast_t_figure")), 0, 0)
        grid.addWidget(self.figure_box, 0, 1, 1, 3)
        self.limit_on, self.limit = self._option("ast_t_limit", 3.0, 0.001, 1e6, 1, grid)
        self.rate_on, self.rate = self._option("ast_t_rate", 0.5, 0.0, 1e6, 2, grid)
        self.warn_on, self.warn = self._option("ast_t_warn", 90.0, 0.0, 36500.0, 3, grid)
        self.warn.setDecimals(0)
        self.lower_worse = QCheckBox(self._t("ast_t_lower_worse"))
        self.lower_worse.toggled.connect(lambda _on: self.update_trend())
        grid.addWidget(self.lower_worse, 4, 0, 1, 4)
        root.addLayout(grid)
        self.plot = TracePlot()
        root.addWidget(self.plot, 1)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumHeight(180)
        root.addWidget(self.text)
        buttons = QHBoxLayout()
        self.csv_btn = QPushButton(self._t("ast_t_csv"))
        self.csv_btn.clicked.connect(self.export_csv)
        close = QPushButton(self._t("ast_close"))
        close.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(self.csv_btn)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _option(self, key: str, value: float, low: float, high: float, row: int, grid):
        box = QCheckBox(self._t(key))
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(3)
        spin.setValue(value)
        spin.setEnabled(False)
        box.toggled.connect(spin.setEnabled)
        box.toggled.connect(lambda _on: self.update_trend())
        spin.valueChanged.connect(lambda _v: self.update_trend())
        grid.addWidget(box, row, 0, 1, 2)
        grid.addWidget(spin, row, 2)
        return box, spin

    # ================================================================ the data
    def reload(self) -> None:
        """Find the figures the runs have again (after a new measurement) and draw."""
        keep = self.figure_box.currentData()
        keys = trend.figures(self.code, self.run_dirs, self.measurement)
        self.figure_box.clear()
        for key in keys:
            self.figure_box.addItem(key, key)
        preferred = keep if keep in keys else trend.DEFAULT_FIGURE
        self.figure_box.setCurrentIndex(max(self.figure_box.findData(preferred), 0))
        self.update_trend()

    def options(self) -> dict:
        """The options of ``ola.trend.assess`` as they are set in the window."""
        return {
            "limit": self.limit.value() if self.limit_on.isChecked() else None,
            "max_rate_per_year": self.rate.value() if self.rate_on.isChecked() else None,
            "warn_within_days": self.warn.value() if self.warn_on.isChecked() else None,
            "higher_is_worse": not self.lower_worse.isChecked(),
        }

    def update_trend(self) -> Optional[Trend]:
        """Work out the trend of the chosen figure and show it."""
        figure = self.figure_box.currentData()
        self.csv_btn.setEnabled(False)
        if not figure:
            self.result = None
            self.plot.set_curves([])
            self.text.setPlainText(self._t("ast_t_none", code=self.code))
            return None
        points = trend.series(self.code, self.run_dirs, figure, self.measurement)
        self.result = trend.assess(points, figure=figure, **self.options())
        self._draw(self.result)
        self.text.setPlainText(trend.format_trend(self.result))
        self.csv_btn.setEnabled(bool(points))
        return self.result

    def _draw(self, result: Trend) -> None:
        points = result.points
        if not points:
            self.plot.set_curves([])
            return
        t0 = points[0].t
        days = [(p.t - t0) / DAY for p in points]
        curves = [(self._t("ast_t_measured"), days, [p.value for p in points])]
        end = days[-1]
        if result.days_to_limit is not None:
            end = days[-1] + result.days_to_limit
        if result.slope_per_day is not None:
            line = trend.fit_line(points)
            xs = [0.0, end]
            ys = [line["intercept"] + line["slope"] * x * DAY for x in xs]
            curves.append((self._t("ast_t_line"), xs, ys))
        limits: List = []
        if result.limit is not None:
            limits.append((self._t("ast_t_limit_line"), [0.0, max(end, 1.0)],
                           [result.limit, result.limit]))  # fmt: skip
        self.plot.set_curves(
            curves, self._t("ast_t_days", date=points[0].when[:10]), result.figure, limits
        )

    def export_csv(self) -> None:
        """Save the series of the chosen figure."""
        if self.result is None or not self.result.points:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("ast_t_csv"), f"{self.code}_{self.result.figure}.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            trend.export_csv(self.result.points, path)
        except OSError as exc:
            self.text.appendPlainText(self._t("ast_t_failed", error=exc))
            return
        self.text.appendPlainText(self._t("ast_t_saved", path=path))


def main(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m frontend.ui.TrendDialog CODE runs-folder [...]``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = TrendDialog(argv[0], argv[1:])
    dialog.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
