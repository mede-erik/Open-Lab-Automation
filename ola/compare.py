"""Comparing saved results (no Qt): the logic behind the *Compare results* tool.

Pick two or more run files (``runs/*.jsonl``, written while a measurement ran) and see them
together: the curves they have in common drawn on top of each other (two cables, a filter before and
after a change), the **difference** between a curve and the one of a reference run, and the figures
of their summary rows side by side with the change from the reference::

    runs = [load_run("runs/cable_a.jsonl"), load_run("runs/cable_b.jsonl")]
    names = trace_names(runs)                         # the curves, with how many runs have each
    x, y = curve(runs[0], "S21", "loss_db")           # one curve in one view
    xs, d = difference(curve(runs[0], ...), curve(runs[1], ...))     # B - A on A's frequencies
    difference_stats(xs, d)                           # largest difference, where, mean, RMS
    summary_table(runs, reference=0)                  # the summary figures, with the changes

A run is described by its **label**: the name of the cable / filter / device saved with it, and the
date. Comparing runs of different kinds of measurement is allowed (``mixed_types`` says so).
"""

from __future__ import annotations

import csv
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from . import rf
from .run_view import trace_xy
from .runs import last_traces, read_run

# keys of the measurement parameters that hold the name of what was measured
LABEL_GROUPS = ("cable", "device", "filter")
_STAMP = re.compile(r"_(\d{8})_(\d{6})")


class CompareError(ValueError):
    """A run file cannot be compared; the message says why."""


@dataclass
class RunData:
    """What the comparison needs of one run file."""

    path: Path
    label: str
    measurement: str
    name: str  # what was measured: the cable, filter or device name (may be empty)
    when: str  # the date, ``2026-11-03 21:52``
    state: str
    traces: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # name -> trace
    points: List[Dict[str, Any]] = field(default_factory=list)  # rows of the main table
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> Dict[str, Any]:
        """The one summary row of a measurement that makes one (``{}`` for a table of many)."""
        return dict(self.points[0]) if len(self.points) == 1 else {}


def measured_name(params: Dict[str, Any]) -> str:
    """The name of what was measured, from the parameters of the run (``cable.label``,
    ``device.label``, ``filter.label``), or ``""``."""
    for group in LABEL_GROUPS:
        item = params.get(group)
        if isinstance(item, dict) and isinstance(item.get("label"), str) and item["label"].strip():
            return item["label"].strip()
    return ""


def run_date(path: Path) -> str:
    """``2026-11-03 21:52`` from the stamp in the file name (``..._20261103_215232.jsonl``), else
    from the time the file was written."""
    match = _STAMP.search(path.stem)
    if match:
        d, t = match.groups()
        return f"{d[:4]}-{d[4:6]}-{d[6:]} {t[:2]}:{t[2:4]}"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))


def load_run(path: Union[str, Path], label: Optional[str] = None) -> RunData:
    """Read a run file. ``CompareError`` if it is not readable or holds nothing to compare (no curve
    and no result). A run that was interrupted is still read."""
    path = Path(path)
    try:
        run = read_run(path)
    except (OSError, ValueError) as exc:
        raise CompareError(f"{path.name}: cannot read the file ({exc})") from exc
    header = run["header"]
    if header is None:
        raise CompareError(f"{path.name}: not a run file (it has no header)")
    traces = {}
    for name, trace in last_traces(path).items():
        y = rf.from_pairs(trace["y"]) if trace.get("trace_kind") == "complex" else list(trace["y"])
        traces[name] = {
            "name": name,
            "kind": trace.get("trace_kind", "real"),
            "x": list(trace["x"]),
            "y": y,
            "meta": dict(trace.get("meta") or {}),
        }
    points = [dict(p["values"]) for p in run["points"]]
    if not traces and not points:
        raise CompareError(f"{path.name}: the run has no results to compare")
    params = header.get("params") or {}
    name = measured_name(params)
    when = run_date(path)
    kind = str(header.get("measurement", "?"))
    return RunData(
        path=path,
        label=label or f"{name or kind} - {when}",
        measurement=kind,
        name=name,
        when=when,
        state=(run["end"] or {}).get("state", "interrupted"),
        traces=traces,
        points=points,
        params=params,
    )


def mixed_types(runs: Sequence[RunData]) -> bool:
    """True if the runs are not all the same kind of measurement."""
    return len({r.measurement for r in runs}) > 1


def trace_names(runs: Sequence[RunData]) -> List[Tuple[str, int]]:
    """The curves of the runs: ``[(name, number of runs that have it)]``, the ones in most runs
    first, otherwise in order of appearance."""
    counts: Dict[str, int] = {}
    for run in runs:
        for name in run.traces:
            counts[name] = counts.get(name, 0) + 1
    order = list(counts)
    return sorted(
        ((n, counts[n]) for n in order), key=lambda item: (-item[1], order.index(item[0]))
    )


def curve(run: RunData, name: str, view: str) -> Tuple[List[float], List[float]]:
    """One curve of a run in one view (``magnitude_db``, ``loss_db``, ``value``... see
    ``ola.run_view.trace_views``). ``CompareError`` if the run has no such curve."""
    if name not in run.traces:
        raise CompareError(f"{run.label}: has no curve '{name}'")
    return trace_xy(run.traces[name], view)


def difference(
    reference: Tuple[Sequence[float], Sequence[float]],
    other: Tuple[Sequence[float], Sequence[float]],
) -> Tuple[List[float], List[float]]:
    """``other - reference`` at the x of the reference, where both exist: the other curve is read
    between its points (linear); the x outside its range are left out (nothing is invented).
    Returns ``(xs, differences)``; empty lists if the curves do not overlap."""
    rx, ry = reference
    ox, oy = other
    if not ox or not rx:
        return [], []
    low, high = min(ox), max(ox)
    xs: List[float] = []
    out: List[float] = []
    for x, y in zip(rx, ry):
        if low <= x <= high:
            xs.append(x)
            out.append(rf.value_at(ox, oy, x) - y)
    return xs, out


def difference_stats(xs: Sequence[float], diffs: Sequence[float]) -> Dict[str, float]:
    """The largest difference (``max_abs``, its sign kept, and where), the mean and the RMS.
    ``{}`` if there is nothing."""
    if not diffs:
        return {}
    worst = max(range(len(diffs)), key=lambda i: abs(diffs[i]))
    return {
        "max_abs": diffs[worst],
        "at_x": xs[worst],
        "mean": sum(diffs) / len(diffs),
        "rms": math.sqrt(sum(d * d for d in diffs) / len(diffs)),
        "points": float(len(diffs)),
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def summary_table(runs: Sequence[RunData], reference: int = 0) -> List[Dict[str, Any]]:
    """The summary figures side by side: ``[{"key", "values": [...], "deltas": [...]}]``.
    ``values`` has one entry per run (None where a run has no such figure) and ``deltas`` the change
    of each run from the reference run (None for the reference itself, for text, and where a
    number is missing). Only runs with a one-row summary are used (a run with a table of many
    points has none: its curves are compared instead)."""
    keys: List[str] = []
    for run in runs:
        for key in run.summary:
            if key not in keys:
                keys.append(key)
    base = runs[reference].summary if 0 <= reference < len(runs) else {}
    rows = []
    for key in keys:
        values = [r.summary.get(key) for r in runs]
        deltas: List[Optional[float]] = []
        for n, value in enumerate(values):
            ref = base.get(key)
            same = n == reference or not (_is_number(value) and _is_number(ref))
            deltas.append(None if same else value - ref)
        rows.append({"key": key, "values": values, "deltas": deltas})
    return rows


def points_columns(runs: Sequence[RunData]) -> List[str]:
    """The numeric columns of the main tables that every run with a table has (to compare an
    efficiency run with another: the same set-points and results)."""
    sets = []
    for run in runs:
        if len(run.points) > 1:
            sets.append({k for k in run.points[0] if all(_is_number(p.get(k)) for p in run.points)})
    if len(sets) < 1:
        return []
    common = set.intersection(*sets)
    first = next(r for r in runs if len(r.points) > 1)
    return [k for k in first.points[0] if k in common and k != "elapsed_s"]


def points_series(
    run: RunData, x: str, y: str, group_by: Optional[Sequence[str]] = None
) -> List[Tuple[str, List[float], List[float]]]:
    """Lines from the main table of a run (an efficiency run: ``y`` against ``x``, one line per
    value of the ``group_by`` columns); same as the *Plot* tab of the run window."""
    from .run_view import RunModel

    model = RunModel()
    model.points = [dict(p) for p in run.points]
    model.columns = list(run.points[0]) if run.points else []
    return model.series(x, y, group_by)


def export_overlay_csv(
    path: Union[str, Path],
    runs: Sequence[RunData],
    name: str,
    view: str,
) -> int:
    """Write one curve of every run that has it to a CSV: for each run an ``x`` and a ``y`` column
    (their x may differ). Returns the number of rows. ``CompareError`` if no run has the curve."""
    series = [(r.label, *curve(r, name, view)) for r in runs if name in r.traces]
    if not series:
        raise CompareError(f"no run has a curve '{name}'")
    rows = max(len(s[1]) for s in series)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([c for label, _, _ in series for c in (f"x [{label}]", f"y [{label}]")])
        for i in range(rows):
            w.writerow(
                [v for _, xs, ys in series for v in ((xs[i], ys[i]) if i < len(xs) else ("", ""))]
            )
    return rows
