"""What a run window shows, without any screen: ``RunModel`` follows the events of a ``Runner``.

The window (``frontend/ui/RunWindow.py``) only draws this model, so everything that decides *what*
is shown (state, progress and time left, the table, the log, the open questions, the series of a
plot) is tested without Qt::

    model = RunModel()
    for event in runner.drain():      # every 100 ms, from a timer of the GUI
        model.apply(event)
    model.state, model.progress, model.points, model.pending ...
    model.series("vin", "efficiency", group_by=["iout"])     # lines for a plot

Rows of the main table (``points``) keep the order in which the runner produced them. Other tables
(``samples``...) are in ``model.tables``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .measurement import Event
from .runner import FINAL_STATES, RunState

FINAL_NAMES = tuple(s.value for s in FINAL_STATES)
# Kinds of question the window knows how to present; anything else is shown as plain text.
QUESTION_VERIFY = "verify"  # a reading disagrees with the setpoint: retry / abort / skip
QUESTION_OUTPUTS_ON = "outputs_on"  # outputs already on will be switched off: continue / abort
QUESTION_GENERIC = "generic"


def question_kind(question: Mapping[str, Any]) -> str:
    """Which kind of question this is, from the data the measurement attached to it."""
    data = question.get("data") or {}
    if "read_value" in data and "set_value" in data:
        return QUESTION_VERIFY
    if "outputs" in data:
        return QUESTION_OUTPUTS_ON
    return QUESTION_GENERIC


def is_number(value: Any) -> bool:
    """True for a finite int or float (``bool`` is not a number here)."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


class RunModel:
    """The state of a run as the window shows it, built from ``Event`` objects."""

    def __init__(self) -> None:
        self.state: str = RunState.IDLE.value
        self.run_id: Optional[str] = None
        self.points: List[Dict[str, Any]] = []  # values of the main table, in order
        self.tables: Dict[str, List[Dict[str, Any]]] = {}  # the other tables
        self.columns: List[str] = []  # columns of ``points``, in order of first appearance
        self.done: float = 0
        self.total: Optional[float] = None
        self.message: str = ""
        self.logs: List[Tuple[float, str, str]] = []  # (time, level, message)
        self.error: Optional[Dict[str, Any]] = None
        self.pending: Dict[str, Dict[str, Any]] = {}  # open questions by id
        self.answers: List[Dict[str, Any]] = []  # answered questions
        self.first_t: Optional[float] = None  # time of the first event
        self.last_t: Optional[float] = None
        self.end_t: Optional[float] = None
        self.waited_s: float = 0.0  # time spent waiting for the user (not counted in the ETA)
        self._asked_at: Dict[str, float] = {}

    # ----- following the run ------------------------------------------------------------------
    @property
    def finished(self) -> bool:
        """True once the run has ended (finished, stopped or failed)."""
        return self.state in FINAL_NAMES

    def apply(self, event: Event) -> None:
        """Take one event into account."""
        if self.first_t is None:
            self.first_t = event.t
        self.last_t = event.t
        data = event.data
        if event.kind == "state":
            self.state = data["state"]
            self.run_id = data.get("run_id", self.run_id)
            if self.finished:
                self.end_t = event.t
        elif event.kind == "point":
            row = dict(data["values"])
            row["elapsed_s"] = data.get("elapsed_s")
            if data.get("table", "points") == "points":
                self.points.append(row)
                for key in data["values"]:
                    if key not in self.columns:
                        self.columns.append(key)
            else:
                self.tables.setdefault(data["table"], []).append(row)
        elif event.kind == "progress":
            self.done, self.total = data.get("done", 0), data.get("total")
            self.message = data.get("message", "")
        elif event.kind == "log":
            self.logs.append((event.t, data.get("level", "info"), data.get("message", "")))
        elif event.kind == "error":
            self.error = data
            self.logs.append((event.t, "error", data.get("message", "")))
        elif event.kind == "question":
            self.pending[data["id"]] = dict(data)
            self._asked_at[data["id"]] = event.t
        elif event.kind == "answered":
            question = self.pending.pop(data["id"], None)
            asked = self._asked_at.pop(data["id"], None)
            if asked is not None and not data.get("auto"):
                self.waited_s += max(0.0, event.t - asked)
            if question is not None:
                self.answers.append({**question, "choice": data.get("choice")})

    # ----- numbers for the top of the window --------------------------------------------------
    @property
    def fraction(self) -> Optional[float]:
        """Progress between 0 and 1, or None if the total is not known."""
        if not self.total:
            return None
        return max(0.0, min(1.0, self.done / self.total))

    def elapsed(self, now: Optional[float] = None) -> float:
        """Seconds since the run started (until it ended, if it has)."""
        if self.first_t is None:
            return 0.0
        end = self.end_t if self.end_t is not None else (now if now is not None else self.last_t)
        return max(0.0, (end or self.first_t) - self.first_t)

    def remaining(self, now: Optional[float] = None) -> Optional[float]:
        """Estimated seconds left, from the speed so far (time spent waiting for the user is not
        counted); None while there is nothing to base it on, or when the run has ended."""
        if self.finished or not self.fraction or self.done <= 0:
            return None
        working = max(self.elapsed(now) - self.waited_s, 0.0)
        return working * (1 - self.fraction) / self.fraction

    @staticmethod
    def format_duration(seconds: Optional[float]) -> str:
        """``3725`` -> ``"1 h 02 min"``, ``75`` -> ``"1 min 15 s"``, ``None`` -> ``"-"``."""
        if seconds is None:
            return "-"
        seconds = int(round(seconds))
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return f"{hours} h {minutes:02d} min"
        if minutes:
            return f"{minutes} min {secs:02d} s"
        return f"{secs} s"

    # ----- the table and the plot -------------------------------------------------------------
    def numeric_columns(self) -> List[str]:
        """Columns whose values are all numbers (the ones a plot can use)."""
        return [
            c
            for c in self.columns
            if any(is_number(r.get(c)) for r in self.points)
            and all(is_number(r.get(c)) or r.get(c) is None for r in self.points)
        ]

    def varying_columns(self) -> List[str]:
        """Numeric columns that take more than one value (the swept parameters and the results)."""
        out = []
        for c in self.numeric_columns():
            values = {r.get(c) for r in self.points if is_number(r.get(c))}
            if len(values) > 1:
                out.append(c)
        return out

    def suggest_axes(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """A sensible plot to start with: ``(x, y, group_by)``. ``x`` is the first changing column
        (the fastest sweep), ``y`` is ``efficiency`` if there is one (else the last column), and
        the lines are grouped by the second changing column that is a setpoint."""
        varying = self.varying_columns()
        if not varying:
            numeric = self.numeric_columns()
            return (numeric[0] if numeric else None, numeric[-1] if numeric else None, None)
        x = varying[0]
        y = "efficiency" if "efficiency" in self.columns else varying[-1]
        # setpoints have no "@" in the name and come before the readings in the table
        group = next((c for c in varying[1:] if "@" not in c and c != y), None)
        return x, y, group

    def series(
        self, x: str, y: str, group_by: Optional[Sequence[str]] = None
    ) -> List[Tuple[str, List[float], List[float]]]:
        """Lines for a plot: ``[(label, xs, ys), ...]``, each line sorted by ``x``. With
        ``group_by`` there is one line for every combination of those columns; rows without a
        number in ``x`` or ``y`` are left out."""
        groups: Dict[Tuple[Any, ...], List[Tuple[float, float]]] = {}
        for row in self.points:
            if not (is_number(row.get(x)) and is_number(row.get(y))):
                continue
            key = tuple(row.get(g) for g in (group_by or ()))
            groups.setdefault(key, []).append((float(row[x]), float(row[y])))
        out = []
        for key, pairs in groups.items():
            pairs.sort(key=lambda p: p[0])
            label = ", ".join(f"{g}={_short(v)}" for g, v in zip(group_by or (), key)) or y
            out.append((label, [p[0] for p in pairs], [p[1] for p in pairs]))
        out.sort(key=lambda s: s[0])
        return out


def _short(value: Any) -> str:
    return f"{value:g}" if is_number(value) else str(value)


def nice_ticks(low: float, high: float, count: int = 6) -> List[float]:
    """Round tick values covering ``low`` .. ``high`` (about ``count`` of them), for plot axes."""
    if not (math.isfinite(low) and math.isfinite(high)):
        return []
    if high < low:
        low, high = high, low
    if high - low <= 1e-9 * max(abs(low), abs(high)):  # flat, or only rounding noise
        pad = abs(low) * 0.1 or 1.0
        low, high = low - pad, high + pad
    raw = (high - low) / max(count - 1, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    first = math.ceil(low / step - 1e-9) * step
    decimals = max(0, 3 - math.floor(math.log10(step)))  # enough digits for the step
    ticks, value = [], first
    while value <= high + step * 1e-9:
        ticks.append(round(value, decimals))
        value += step
    return ticks
