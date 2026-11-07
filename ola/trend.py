# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""How a cable ages (no Qt): a figure of its measurements against the date.

Every time a cable is measured the run file keeps the code of the cable (see ``ola.assets``), so
all its measurements can be found again. The **loss** of a cable (the worst loss, or the loss at a
frequency of interest) normally stays the same for years and then grows as the connector wears, the
braid corrodes or the cable is bent too often. This module follows it::

    points = series("CBL-0042", ["runs"], "loss_868MHz_db")     # one point for each finished run
    trend = assess(points, limit=3.0, max_rate_per_year=0.5, warn_within_days=90)
    trend.verdict        # PASS, WARNING (the limit is near), FAIL, or NOT ENOUGH DATA
    trend.rate_per_year  # dB per year, from a straight line through the points
    trend.limit_date     # when the line reaches the limit (None if it never does)
    trend.reasons        # a sentence for each problem

The line is a least-squares fit; the slope counts as a change only if it is more than twice its
own uncertainty (so that the noise of a few measurements is not reported as aging). With fewer
than three points, or all in the same day, there is not enough to say anything.
"""

from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from .assets import history
from .compare import CompareError, load_run

DAY = 86400.0
YEAR = 365.25 * DAY
DEFAULT_FIGURE = "max_loss_db"
MIN_POINTS = 3


class TrendError(ValueError):
    """The trend cannot be worked out; the message says why."""


@dataclass
class TrendPoint:
    """One measurement of the series: the date, the value and the run it came from."""

    when: str  # ``2026-11-03 10:00``
    t: float  # seconds since the epoch
    value: float
    path: Path


@dataclass
class Trend:
    """The result of ``assess``."""

    figure: str
    points: List[TrendPoint] = field(default_factory=list)
    verdict: str = "NOT ENOUGH DATA"
    slope_per_day: Optional[float] = None
    rate_per_year: Optional[float] = None
    uncertainty_per_year: Optional[float] = None  # one standard error of the slope
    rms: Optional[float] = None  # scatter of the points around the line
    first: Optional[float] = None
    last: Optional[float] = None
    change: Optional[float] = None  # last - first
    significant: bool = False
    limit: Optional[float] = None
    limit_date: Optional[str] = None
    days_to_limit: Optional[float] = None
    reasons: List[str] = field(default_factory=list)

    @property
    def direction(self) -> str:
        """``worse``, ``better`` or ``steady`` (steady also when the change is not significant)."""
        if not self.significant or not self.rate_per_year:
            return "steady"
        return "worse" if self.rate_per_year > 0 else "better"

    def summary(self) -> str:
        """One line for a label or a log, for example ``+0.12 dB/year (worse), last 1.43``."""
        if self.rate_per_year is None:
            return f"{self.verdict}: {len(self.points)} measurement(s)"
        return (
            f"{self.verdict}: {self.rate_per_year:+.3g}/year ({self.direction}), "
            f"last {self.last:.3g} of {len(self.points)} measurements"
        )


def parse_when(when: str) -> float:
    """Seconds since the epoch of ``2026-11-03 10:00``."""
    return time.mktime(time.strptime(when[:16], "%Y-%m-%d %H:%M"))


def series(
    code: str,
    run_dirs: Iterable[Union[str, Path]],
    figure: str = DEFAULT_FIGURE,
    measurement: Optional[str] = "cable",
) -> List[TrendPoint]:
    """The value of ``figure`` (a key of the summary row) in every finished run of the object with
    this code, oldest first. Runs of another kind of measurement (``measurement``; None for any),
    runs that did not finish and runs without that figure are left out."""
    out: List[TrendPoint] = []
    for ref in history(code, run_dirs):
        if measurement and ref.measurement != measurement:
            continue
        try:
            run = load_run(ref.path)
        except CompareError:
            continue
        value = run.summary.get(figure)
        if (
            run.state != "finished"
            or not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            continue
        out.append(TrendPoint(run.when, parse_when(run.when), float(value), ref.path))
    return out


def figures(
    code: str, run_dirs: Iterable[Union[str, Path]], measurement: Optional[str] = "cable"
) -> List[str]:
    """The numeric figures that the finished runs of an object have (to choose what to follow)."""
    keys: List[str] = []
    for ref in history(code, run_dirs):
        if measurement and ref.measurement != measurement:
            continue
        try:
            summary = load_run(ref.path).summary
        except CompareError:
            continue
        for key, value in summary.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool) and key not in keys:
                keys.append(key)
    return keys


def fit_line(points: Sequence[TrendPoint]) -> Dict[str, float]:
    """The least-squares line through the points: ``slope`` (per second), ``intercept`` (at the
    time of the first point), ``se`` (one standard error of the slope), ``rms`` (the scatter of the
    points around the line)."""
    n = len(points)
    if n < 2:
        raise TrendError("a line needs at least two points")
    t0 = points[0].t
    xs = [p.t - t0 for p in points]
    ys = [p.value for p in points]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        raise TrendError("all the points are at the same time")
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    rss = sum(r * r for r in residuals)
    se = math.sqrt(rss / (n - 2) / sxx) if n > 2 else float("inf")
    return {"slope": slope, "intercept": intercept, "se": se, "rms": math.sqrt(rss / n)}


def assess(
    points: Sequence[TrendPoint],
    figure: str = DEFAULT_FIGURE,
    limit: Optional[float] = None,
    max_rate_per_year: Optional[float] = None,
    warn_within_days: Optional[float] = None,
    higher_is_worse: bool = True,
    min_points: int = MIN_POINTS,
) -> Trend:
    """The trend of a series. ``limit``: the value that must not be reached; ``max_rate_per_year``:
    the fastest change for the worse that is accepted; ``warn_within_days``: a ``WARNING`` if the
    line reaches the limit within that time. ``higher_is_worse`` is True for a loss (False for,
    say, a return loss)."""
    for name, value in (("limit", limit), ("max_rate_per_year", max_rate_per_year),
                        ("warn_within_days", warn_within_days)):  # fmt: skip
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise TrendError(f"{name} must be a number")
    trend = Trend(figure=figure, points=list(points), limit=limit)
    if not points:
        trend.reasons.append("no finished measurement with this figure")
        return trend
    trend.first, trend.last = points[0].value, points[-1].value
    trend.change = trend.last - trend.first
    sign = 1.0 if higher_is_worse else -1.0

    def worse_than_limit(value: float) -> bool:
        return sign * value >= sign * limit if limit is not None else False

    reasons = trend.reasons
    if limit is not None and worse_than_limit(trend.last):
        reasons.append(f"the last measurement ({trend.last:.3g}) is past the limit {limit:g}")
    enough = len(points) >= max(2, min_points) and points[-1].t - points[0].t >= DAY * 0.5
    if enough:
        line = fit_line(points)
        trend.slope_per_day = line["slope"] * DAY
        trend.rate_per_year = line["slope"] * YEAR
        trend.uncertainty_per_year = line["se"] * YEAR if math.isfinite(line["se"]) else None
        trend.rms = line["rms"]
        trend.significant = math.isfinite(line["se"]) and abs(line["slope"]) > 2 * line["se"]
        worse_rate = sign * trend.rate_per_year
        if max_rate_per_year is not None and trend.significant and worse_rate > max_rate_per_year:
            reasons.append(
                f"it changes for the worse by {worse_rate:.3g} per year (at most "
                f"{max_rate_per_year:g} is accepted)"
            )
        if limit is not None and trend.significant and worse_rate > 0:
            now = points[-1].t
            current = line["intercept"] + line["slope"] * (now - points[0].t)
            gap = sign * (limit - current)
            if gap > 0:
                trend.days_to_limit = gap / (worse_rate / YEAR) / DAY
                trend.limit_date = time.strftime(
                    "%Y-%m-%d", time.localtime(now + trend.days_to_limit * DAY)
                )
            else:
                trend.days_to_limit = 0.0
                trend.limit_date = time.strftime("%Y-%m-%d", time.localtime(now))
    if reasons:
        trend.verdict = "FAIL"
    elif not enough:
        trend.verdict = "NOT ENOUGH DATA"
        reasons.append(
            f"{len(points)} measurement(s) over {_span_days(points):.1f} day(s): at least "
            f"{max(2, min_points)} over a few days are needed for a trend"
        )
    elif (
        warn_within_days is not None
        and trend.days_to_limit is not None
        and trend.days_to_limit <= warn_within_days
    ):
        trend.verdict = "WARNING"
        reasons.append(
            f"at this rate it reaches the limit {limit:g} on {trend.limit_date} "
            f"(in {trend.days_to_limit:.0f} days)"
        )
    else:
        trend.verdict = "PASS"
    return trend


def _span_days(points: Sequence[TrendPoint]) -> float:
    return (points[-1].t - points[0].t) / DAY if points else 0.0


def trend_for(
    code: str,
    run_dirs: Iterable[Union[str, Path]],
    figure: str = DEFAULT_FIGURE,
    **options: Any,
) -> Trend:
    """``series`` and ``assess`` in one call; ``options`` are those of ``assess``."""
    return assess(series(code, run_dirs, figure), figure=figure, **options)


def export_csv(points: Sequence[TrendPoint], path: Union[str, Path]) -> None:
    """The series as a CSV file: date, value and the run it came from."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "value", "run"])
        for p in points:
            writer.writerow([p.when, p.value, p.path.name])


def format_trend(trend: Trend) -> str:
    """The result as text for a log or a terminal."""
    lines = [f"{trend.figure}: {trend.summary()}"]
    if trend.rate_per_year is not None and trend.uncertainty_per_year is not None:
        lines.append(
            f"  {trend.rate_per_year:+.3g} +/- {trend.uncertainty_per_year:.2g} per year, "
            f"scatter {trend.rms:.2g}"
        )
    for p in trend.points:
        lines.append(f"  {p.when}  {p.value:.4g}  {p.path.name}")
    lines.extend(f"  - {reason}" for reason in trend.reasons)
    return "\n".join(lines)


__all__ = [
    "Trend", "TrendError", "TrendPoint", "assess", "export_csv", "figures", "fit_line",
    "format_trend", "series", "trend_for",
]  # fmt: skip
