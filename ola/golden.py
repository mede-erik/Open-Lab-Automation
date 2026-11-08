# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A result against a golden sample (no Qt): is this cable, filter or amplifier like the good one?

A **golden sample** is a run file of a unit that is known to be good. A new run is checked against
it: each curve may differ from the golden one by at most a tolerance (the same at every frequency
or a line of the frequency), and each figure of the summary by at most a tolerance. The answer is a
**verdict** with the reasons, and it is the same kind of answer as a limit on a curve
(``ola.limits``): ``PASS`` or ``FAIL``::

    golden = load_run("golden/RG58.jsonl")
    run = load_run("runs/cable_20261107_101500.jsonl")
    result = check_against_golden(run, golden, {
        "curves": [{"trace": "S21", "view": "loss_db", "tolerance": 0.5}],
        "summary": {"loss_868MHz_db": 0.3, "max_vswr": {"rel": 0.1}},
    })
    result.verdict        # "PASS" or "FAIL" (or "NO DATA" if there was nothing to compare)
    result.reasons        # one sentence for each thing out of tolerance

The tolerance of a curve is a number (``0.5``: plus or minus 0.5 at every frequency), a line of
the frequency (``[[1e6, 0.2], [3e9, 0.8]]``: wider as the frequency rises) or an object with
``upper`` and ``lower`` for an asymmetric one (``{"upper": 0.5, "lower": 0.1}``: it may be 0.5 above
the golden curve and 0.1 below). The tolerance of a summary figure is a number (absolute), or
``{"abs": x}``, ``{"rel": r}`` (a fraction of the golden value) or both (the larger one counts).

The curves are compared at the frequencies of the golden curve where the run has data; the run
must cover at least ``min_overlap`` (0.9 by default) of the golden points, otherwise the check
fails for that (a run of a narrower sweep proves nothing about the missing part).

``set_golden`` copies a run file into the ``golden/`` folder of a project under a name, and
``find_golden`` finds it again: the golden sample of a kind of cable is chosen once.
"""

from __future__ import annotations

import math
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from .compare import CompareError, RunData, curve, difference, difference_stats, load_run
from .limits import LimitError, Limits

DEFAULT_OVERLAP = 0.9
GOLDEN_DIR = "golden"


class GoldenError(ValueError):
    """The golden sample or its tolerances cannot be used; the message says why."""


@dataclass
class Check:
    """One thing that was checked: a curve, or a figure of the summary."""

    name: str
    passed: bool
    detail: str
    worst: Optional[float] = None  # largest difference from the golden value (sign kept)
    at_x: Optional[float] = None  # where, for a curve
    margin: Optional[float] = None  # distance to the tolerance (negative if it fails)


@dataclass
class GoldenResult:
    """The verdict against a golden sample and what it is made of."""

    golden: str
    run: str
    checks: List[Check] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """``PASS``, ``FAIL`` or ``NO DATA`` (nothing could be compared)."""
        if not self.checks:
            return "NO DATA"
        return "PASS" if all(c.passed for c in self.checks) else "FAIL"

    @property
    def passed(self) -> bool:
        """True only for ``PASS``."""
        return self.verdict == "PASS"

    def summary(self) -> str:
        """One line for a log."""
        failed = [c for c in self.checks if not c.passed]
        return f"{self.verdict}: {len(self.checks) - len(failed)} of {len(self.checks)} checks ok"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _limits_for(tolerance: Any, what: str) -> Limits:
    """The limits on the difference ``run - golden`` that a tolerance means."""
    if _number(tolerance):
        if tolerance < 0:
            raise GoldenError(f"{what}: the tolerance cannot be negative")
        spec: Dict[str, Any] = {"max": float(tolerance), "min": -float(tolerance)}
    elif isinstance(tolerance, (list, tuple)):
        points = [list(p) for p in tolerance]
        if any(len(p) != 2 or not _number(p[1]) or p[1] < 0 for p in points):
            raise GoldenError(f"{what}: a tolerance line is [[frequency, tolerance], ...]")
        spec = {"max": points, "min": [[f, -t] for f, t in points]}
    elif isinstance(tolerance, Mapping):
        unknown = sorted(set(tolerance) - {"upper", "lower"})
        if unknown or not tolerance:
            raise GoldenError(f"{what}: a tolerance object has 'upper' and 'lower'")
        spec = {}
        if "upper" in tolerance:
            spec["max"] = tolerance["upper"]
        if "lower" in tolerance:
            spec["min"] = -tolerance["lower"] if _number(tolerance["lower"]) else tolerance["lower"]
    else:
        raise GoldenError(f"{what}: the tolerance must be a number, a line or an object")
    from .limits import parse_limits

    try:
        return parse_limits(spec)
    except LimitError as exc:
        raise GoldenError(f"{what}: {exc}") from exc


def check_curve(
    run: RunData,
    golden: RunData,
    trace: str,
    view: str,
    tolerance: Any,
    min_overlap: float = DEFAULT_OVERLAP,
) -> Check:
    """One curve of ``run`` against the same curve of ``golden`` in one view."""
    name = f"{trace} ({view})"
    limits = _limits_for(tolerance, name)
    try:
        reference = curve(golden, trace, view)
        other = curve(run, trace, view)
    except CompareError as exc:
        return Check(name, False, str(exc))
    xs, diffs = difference(reference, other)
    covered = len(xs) / len(reference[0]) if reference[0] else 0.0
    if covered < min_overlap:
        return Check(
            name,
            False,
            f"the run covers {covered:.0%} of the golden curve (at least {min_overlap:.0%} needed)",
        )
    stats = difference_stats(xs, diffs)
    verdict = limits.check(xs, diffs)
    worst = stats["max_abs"]
    text = f"largest difference {worst:+.3g} at {stats['at_x']:g}, RMS {stats['rms']:.3g}"
    if not verdict.passed:
        text += f"; {len(verdict.failing)} of {verdict.checked} points out of tolerance"
    return Check(name, verdict.passed, text, worst, stats["at_x"], verdict.margin)


def check_figure(run: RunData, golden: RunData, key: str, tolerance: Any) -> Check:
    """One figure of the one-row summaries against the golden one: ``abs`` and / or ``rel``."""
    if _number(tolerance):
        tolerance = {"abs": tolerance}
    if not isinstance(tolerance, Mapping) or not set(tolerance) <= {"abs", "rel"} or not tolerance:
        raise GoldenError(f"{key}: the tolerance is a number or an object with 'abs' and 'rel'")
    if any(not _number(v) or v < 0 for v in tolerance.values()):
        raise GoldenError(f"{key}: the tolerance cannot be negative")
    want, got = golden.summary.get(key), run.summary.get(key)
    if not _number(want):
        return Check(key, False, "the golden sample has no such figure")
    if not _number(got):
        return Check(key, False, "the run has no such figure")
    allowed = max(float(tolerance.get("abs", 0.0)), abs(want) * float(tolerance.get("rel", 0.0)))
    delta = got - want
    return Check(
        key,
        abs(delta) <= allowed,
        f"{got:.4g} against {want:.4g} (difference {delta:+.3g}, allowed {allowed:.3g})",
        delta,
        None,
        allowed - abs(delta),
    )


def _allowed(tolerance: Mapping[str, float], want: float) -> float:
    return max(float(tolerance.get("abs", 0.0)), abs(want) * float(tolerance.get("rel", 0.0)))


def _row_key(row: Mapping[str, Any], match: Sequence[str]) -> Optional[tuple]:
    key = []
    for column in match:
        value = row.get(column)
        if value is None:
            return None
        key.append(round(float(value), 9) if _number(value) else str(value))
    return tuple(key)


def check_rows(
    run: RunData, golden: RunData, spec: Mapping[str, Any], min_overlap: float = DEFAULT_OVERLAP
) -> List[Check]:
    """The rows of the main table against those of the golden sample, for a measurement that gives
    a table of many rows (ripple for each load current, efficiency for each input and output...).
    ``spec`` is ``{"match": [columns], "columns": {column: tolerance}}``: the rows are paired by
    the values of the ``match`` columns, and each of the ``columns`` gets a check over all the
    pairs (its largest difference and where). The run must have at least ``min_overlap`` of the
    golden rows, like a curve."""
    match = list(spec["match"])
    golden_rows = {}
    for row in golden.points:
        key = _row_key(row, match)
        if key is not None:
            golden_rows.setdefault(key, row)
    pairs = []
    for row in run.points:
        key = _row_key(row, match)
        if key is not None and key in golden_rows:
            pairs.append((key, row, golden_rows[key]))
    checks: List[Check] = []
    covered = len({k for k, _r, _g in pairs}) / len(golden_rows) if golden_rows else 0.0
    if covered < min_overlap:
        checks.append(
            Check(
                f"rows by {', '.join(match)}",
                False,
                f"the run has {covered:.0%} of the rows of the golden sample "
                f"(at least {min_overlap:.0%} needed)",
            )
        )
        return checks
    for column, raw in spec["columns"].items():
        tolerance = {"abs": raw} if _number(raw) else dict(raw)
        worst: Optional[float] = None
        worst_key: Optional[tuple] = None
        margin: Optional[float] = None
        compared = bad = 0
        for key, row, gold in pairs:
            got, want = row.get(column), gold.get(column)
            if not (_number(got) and _number(want)):
                continue
            compared += 1
            delta = got - want
            room = _allowed(tolerance, want) - abs(delta)
            bad += room < 0
            if worst is None or abs(delta) > abs(worst):
                worst, worst_key = delta, key
            margin = room if margin is None else min(margin, room)
        name = f"{column} (rows)"
        if not compared:
            checks.append(Check(name, False, "no pair of rows has this column"))
            continue
        where = ", ".join(f"{c}={v:g}" if isinstance(v, float) else f"{c}={v}"
                          for c, v in zip(match, worst_key or ()))  # fmt: skip
        text = f"largest difference {worst:+.3g} at {where}"
        if bad:
            text += f"; {bad} of {compared} rows out of tolerance"
        checks.append(Check(name, not bad, text, worst, None, margin))
    return checks


def check_against_golden(run: RunData, golden: RunData, spec: Mapping[str, Any]) -> GoldenResult:
    """The verdict of a run against a golden sample: see the module docstring for ``spec``
    (``curves``, ``summary``, ``min_overlap``). ``GoldenError`` if the spec is wrong or the two are
    not the same kind of measurement."""
    problems = validate_spec(spec)
    if problems:
        raise GoldenError("; ".join(problems))
    if run.measurement != golden.measurement:
        raise GoldenError(
            f"the run is a {run.measurement} measurement and the golden sample a "
            f"{golden.measurement} one"
        )
    overlap = spec.get("min_overlap", DEFAULT_OVERLAP)
    result = GoldenResult(golden.label, run.label)
    for item in spec.get("curves") or []:
        result.checks.append(
            check_curve(
                run, golden, str(item["trace"]), str(item.get("view", "value")),
                item["tolerance"], float(overlap),
            )  # fmt: skip
        )
    for key, tolerance in (spec.get("summary") or {}).items():
        result.checks.append(check_figure(run, golden, str(key), tolerance))
    if spec.get("rows"):
        result.checks.extend(check_rows(run, golden, spec["rows"], float(overlap)))
    for check in result.checks:
        if not check.passed:
            result.reasons.append(f"{check.name}: {check.detail}")
    return result


def validate_spec(spec: Any) -> List[str]:
    """The problems of a tolerances ``spec`` as sentences, without any run (for the editor and
    the check of a measurement file). Empty if it can be used."""
    problems: List[str] = []
    if not isinstance(spec, Mapping):
        return ["the tolerances must be an object with 'curves' and / or 'summary'"]
    unknown = sorted(set(spec) - {"curves", "summary", "rows", "min_overlap"})
    if unknown:
        problems.append(f"unknown key(s) {unknown}: use curves, summary, rows or min_overlap")
    if not spec.get("curves") and not spec.get("summary") and not spec.get("rows"):
        problems.append("give at least one curve, summary figure or table column to check")
    rows = spec.get("rows")
    if rows is not None:
        if (
            not isinstance(rows, Mapping)
            or not isinstance(rows.get("match"), list)
            or not rows["match"]
            or not all(isinstance(c, str) and c for c in rows["match"])
            or not isinstance(rows.get("columns"), Mapping)
            or not rows["columns"]
        ):
            problems.append(
                'rows is {"match": [columns that pair the rows], "columns": {column: tolerance}}'
            )
        else:
            for column, tolerance in rows["columns"].items():
                tol = {"abs": tolerance} if _number(tolerance) else tolerance
                if (
                    not isinstance(tol, Mapping)
                    or not tol
                    or not set(tol) <= {"abs", "rel"}
                    or any(not _number(v) or v < 0 for v in tol.values())
                ):
                    problems.append(
                        f"rows.{column}: the tolerance is a number or an object with 'abs' and "
                        "'rel' (not negative)"
                    )
    overlap = spec.get("min_overlap", DEFAULT_OVERLAP)
    if not _number(overlap) or not 0 < overlap <= 1:
        problems.append("min_overlap must be above 0 and at most 1")
    curves = spec.get("curves") or []
    if not isinstance(curves, list):
        problems.append("curves must be a list")
        curves = []
    for n, item in enumerate(curves, 1):
        if not isinstance(item, Mapping) or "trace" not in item or "tolerance" not in item:
            problems.append(f"curve {n} needs 'trace' and 'tolerance' (and a 'view')")
            continue
        try:
            _limits_for(item["tolerance"], f"curve {n} ({item['trace']})")
        except GoldenError as exc:
            problems.append(str(exc))
    figures = spec.get("summary") or {}
    if not isinstance(figures, Mapping):
        problems.append("summary must be an object: {figure: tolerance}")
        figures = {}
    for key, tolerance in figures.items():
        tol = {"abs": tolerance} if _number(tolerance) else tolerance
        if (
            not isinstance(tol, Mapping)
            or not tol
            or not set(tol) <= {"abs", "rel"}
            or any(not _number(v) or v < 0 for v in tol.values())
        ):
            problems.append(
                f"{key}: the tolerance is a number or an object with 'abs' and 'rel' (not negative)"
            )
    return problems


def run_from_result(
    measurement: str,
    traces: Mapping[str, Mapping[str, Any]],
    summary: Mapping[str, Any],
    label: str = "this run",
    params: Optional[Mapping[str, Any]] = None,
    points: Optional[Sequence[Mapping[str, Any]]] = None,
) -> RunData:
    """A run that is being measured, as the comparison sees a run file: ``traces`` is
    ``{name: {"x": [...], "y": [...], "kind": "real" | "complex"}}`` and ``summary`` the one
    summary row (or ``points``, all the rows of the main table of a measurement that gives many).
    So that a measurement can check itself against a golden sample before it ends."""
    return RunData(
        path=Path(""),
        label=label,
        measurement=measurement,
        name="",
        asset_id="",
        when="",
        state="finished",
        traces={
            name: {
                "name": name,
                "kind": trace.get("kind", "real"),
                "x": list(trace["x"]),
                "y": list(trace["y"]),
                "meta": dict(trace.get("meta") or {}),
            }
            for name, trace in traces.items()
        },
        points=[dict(p) for p in points] if points is not None else [dict(summary)],
        params=dict(params or {}),
    )


def check_step(ctx: Any, run: RunData, spec: Mapping[str, Any]) -> Dict[str, Any]:
    """The golden-sample step of a measurement: ``spec`` is the ``golden`` parameter (``run``, the
    golden run file, found from its ``name`` by the project; ``tolerances``). Emits a table
    ``golden`` (one row per check), logs the reasons, and returns the figures to add to the summary
    row: ``golden_verdict`` (``PASS``, ``FAIL`` or ``NO DATA``) and ``golden_failed``. A golden
    sample that cannot be read is ``NO DATA`` with an error in the log, not a failed run."""
    path = spec.get("run")
    name = spec.get("name") or (Path(path).stem if path else "")
    try:
        if not path:
            raise GoldenError(f"no golden sample file for {name!r}")
        reference = load_run(path, label=f"golden {name}")
        result = check_against_golden(run, reference, spec.get("tolerances") or {})
    except (GoldenError, CompareError) as exc:
        ctx.log(f"golden sample check not done: {exc}", "error")
        return {"golden_verdict": "NO DATA"}
    for check in result.checks:
        ctx.emit_point(
            {
                "check": check.name,
                "passed": check.passed,
                "difference": check.worst,
                "at": check.at_x,
                "margin": check.margin,
                "detail": check.detail,
            },
            table="golden",
        )
    ctx.log(f"golden sample {name}: {result.summary()}", "info" if result.passed else "warning")
    for reason in result.reasons:
        ctx.log(f"golden sample: {reason}", "warning")
    failed = sum(not c.passed for c in result.checks)
    return {"golden_verdict": result.verdict, "golden_failed": failed}


class GoldenRecorder:
    """The context of a measurement that checks itself against a golden sample: everything goes
    through to the real context, the curves are also kept, and the summary row (the one row of the
    table ``points``) gets ``golden_verdict`` before it goes out (see ``check_step``). A measurement
    uses it with one line at the start of its ``run``: ``ctx = recording(ctx, "filter", params)``.
    """

    def __init__(
        self,
        ctx: Any,
        measurement: str,
        params: Mapping[str, Any],
        summary_row: bool = True,
        derive: Optional[Any] = None,
    ):
        self._ctx, self._measurement, self._params = ctx, measurement, params
        self._summary_row = summary_row
        self._derive = derive  # the measurement's ``derived``: the columns the runner adds
        self.traces: Dict[str, Dict[str, Any]] = {}
        self.rows: List[Dict[str, Any]] = []
        self._checked = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)

    def emit_trace(self, name: str, x: Any, y: Any, kind: str = "real", **meta: Any) -> None:
        """Keep the curve, then send it on."""
        self.traces[name] = {"x": list(x), "y": list(y), "kind": kind, "meta": dict(meta)}
        self._ctx.emit_trace(name, x, y, kind=kind, **meta)

    def emit_point(self, values: Mapping[str, Any], table: str = "points") -> None:
        """The first row of the main table is the summary: checked, then sent on. A measurement
        of many rows (``summary_row=False``) keeps them for ``finish``."""
        if table == "points" and not self._summary_row:
            row = dict(values)
            if self._derive is not None:
                try:
                    row.update({k: v for k, v in self._derive(values).items() if k not in row})
                except Exception:  # the runner reports it; the check uses what there is
                    pass
            self.rows.append(row)
        elif table == "points" and not self._checked:
            self._checked = True
            from .compare import measured_name

            label = measured_name(dict(self._params)) or "this run"
            run = run_from_result(self._measurement, self.traces, values, label, self._params)
            values = {**values, **check_step(self._ctx, run, self._params["golden"])}
        self._ctx.emit_point(values, table)

    def finish(self) -> Optional[Dict[str, Any]]:
        """For a measurement of many rows, at the end of its run: check all the rows and the
        curves, and send the verdict as the one row of the table ``golden_result``."""
        if self._summary_row or self._checked:
            return None
        self._checked = True
        from .compare import measured_name

        label = measured_name(dict(self._params)) or "this run"
        run = run_from_result(
            self._measurement, self.traces, {}, label, self._params, points=self.rows
        )
        verdict = check_step(self._ctx, run, self._params["golden"])
        self._ctx.emit_point(verdict, table="golden_result")
        return verdict


def recording(
    ctx: Any,
    measurement: str,
    params: Mapping[str, Any],
    summary_row: bool = True,
    derive: Optional[Any] = None,
) -> Any:
    """``ctx`` itself, or a ``GoldenRecorder`` around it when the parameters ask for a golden
    sample (a non-empty ``golden``). ``summary_row=False`` for a measurement whose main table has
    many rows: it then calls ``finish(ctx)`` at the end of its run. ``derive`` is the measurement's
    ``derived`` (the columns the runner adds to each row, such as an efficiency formula)."""
    if params.get("golden"):
        return GoldenRecorder(ctx, measurement, params, summary_row, derive)
    return ctx


def finish(ctx: Any) -> Optional[Dict[str, Any]]:
    """The end of the run of a measurement of many rows: the golden-sample check if there is one
    (see ``GoldenRecorder.finish``); nothing otherwise."""
    return ctx.finish() if isinstance(ctx, GoldenRecorder) else None


def check_golden_param(params: Mapping[str, Any], out: List[Any]) -> None:
    """The problems of the ``golden`` parameter of a measurement (``ola.efficiency_spec.Problem``
    with the path of the field), appended to ``out``."""
    from .efficiency_spec import Problem

    spec = params.get("golden")
    if spec is None or spec == {}:  # an editor with both fields empty leaves an empty object
        return
    if not isinstance(spec, Mapping):
        out.append(Problem("golden", "must be an object with 'name' (or 'run') and 'tolerances'"))
        return
    if not (spec.get("name") or spec.get("run")):
        out.append(Problem("golden.name", "the name of the golden sample (in the project)"))
    for key in ("name", "run"):
        if key in spec and not isinstance(spec[key], str):
            out.append(Problem(f"golden.{key}", "must be text"))
    for problem in validate_spec(spec.get("tolerances")):
        out.append(Problem("golden.tolerances", problem))


# ----- tolerances from several good units --------------------------------------------------------
DEFAULT_FACTOR = 2.0
DEFAULT_FLOOR = 0.05
MAX_LINE_POINTS = 40


def derive_tolerances(
    reference: RunData,
    good: Sequence[RunData],
    curves: Sequence[Sequence[str]] = (),
    figures: Optional[Sequence[str]] = None,
    factor: float = DEFAULT_FACTOR,
    floor: float = DEFAULT_FLOOR,
    max_points: int = MAX_LINE_POINTS,
    rows: Optional[Mapping[str, Sequence[str]]] = None,
) -> Dict[str, Any]:
    """Tolerances worked out from **several good units** instead of written by hand: how far each
    good unit is from the golden one (``reference``), times ``factor``, and at least ``floor``.

    ``curves`` is a list of ``(trace, view)``: each gets a tolerance **line** of the frequency (at
    most about ``max_points`` points, in flat stretches that each take the largest difference in
    them, so the line is never tighter than the units it was made from). ``figures`` are keys of
    the summary (all the numeric ones the reference has, by default): each gets an absolute
    tolerance. A spread of good
    units is the honest measure of what is normal: with only two or three of them, keep ``factor``
    at 2 or more. ``rows`` (``{"match": [...], "columns": [...]}``) does the same for a table of
    rows: each column gets the largest difference over the paired rows of the good units.
    ``GoldenError`` without a good unit, or if none has a curve asked for."""
    if not good:
        raise GoldenError("at least one good unit besides the golden one is needed")
    if factor <= 0 or floor < 0:
        raise GoldenError("the factor must be above 0 and the floor not negative")
    spec: Dict[str, Any] = {}
    for trace, view in curves:
        try:
            ref_curve = curve(reference, trace, view)
        except CompareError as exc:
            raise GoldenError(str(exc)) from exc
        xs = list(ref_curve[0])
        worst = [0.0] * len(xs)
        found = 0
        for unit in good:
            if trace not in unit.traces:
                continue
            found += 1
            dx, diffs = difference(ref_curve, curve(unit, trace, view))
            where = {x: i for i, x in enumerate(xs)}
            for x, d in zip(dx, diffs):
                i = where[x]
                worst[i] = max(worst[i], abs(d))
        if not found:
            raise GoldenError(f"no good unit has the curve {trace!r}")
        # flat stretches (two points each, the same value), so that the line between two grid
        # points never falls below the largest difference of the stretch
        step = max(1, math.ceil(len(xs) / max(1, max_points // 2)))
        line: List[List[float]] = []
        for start in range(0, len(xs), step):
            end = min(start + step, len(xs)) - 1
            tol = max(floor, factor * max(worst[start : end + 1]))  # noqa: E203
            line.append([xs[start], tol])
            if end != start:
                line.append([xs[end], tol])
        spec.setdefault("curves", []).append({"trace": trace, "view": view, "tolerance": line})
    keys = (
        list(figures)
        if figures is not None
        else [k for k, v in reference.summary.items() if _number(v)]
    )
    summary: Dict[str, float] = {}
    for key in keys:
        want = reference.summary.get(key)
        got = [u.summary.get(key) for u in good if _number(u.summary.get(key))]
        if _number(want) and got:
            summary[key] = max(floor, factor * max(abs(g - want) for g in got))
    if summary:
        spec["summary"] = summary
    if rows:
        match = list(rows.get("match") or [])
        gold = {k: r for r in reference.points if (k := _row_key(r, match)) is not None}
        columns: Dict[str, float] = {}
        for column in rows.get("columns") or []:
            diffs = [
                abs(row[column] - gold[key][column])
                for unit in good
                for row in unit.points
                if (key := _row_key(row, match)) in gold
                and _number(row.get(column))
                and _number(gold[key].get(column))
            ]
            if diffs:
                columns[column] = max(floor, factor * max(diffs))
        if columns:
            spec["rows"] = {"match": match, "columns": columns}
    if not spec:
        raise GoldenError("nothing to work the tolerances out from")
    return spec


# ----- the golden samples of a project -----------------------------------------------------------
def _safe(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip()).strip("._")
    if not cleaned:
        raise GoldenError("give the golden sample a name (letters, digits, - and _)")
    return cleaned


def golden_path(project_dir: Union[str, Path], name: str) -> Path:
    """Where the golden sample of that name is kept: ``<project>/golden/<name>.jsonl``."""
    return Path(project_dir) / GOLDEN_DIR / f"{_safe(name)}.jsonl"


def set_golden(project_dir: Union[str, Path], name: str, run_path: Union[str, Path]) -> Path:
    """Make a run the golden sample of that name (a copy of the file). The run must be a finished
    one with results; an old golden sample of the same name is replaced. Returns the new path."""
    run = load_run(run_path)
    if run.state != "finished":
        raise GoldenError(f"{Path(run_path).name}: the run did not finish ({run.state})")
    target = golden_path(project_dir, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(run_path, target)
    return target


def find_golden(project_dir: Union[str, Path], name: str) -> Optional[RunData]:
    """The golden sample of that name, or None if there is none."""
    path = golden_path(project_dir, name)
    return load_run(path, label=f"golden {name}") if path.is_file() else None


def list_golden(project_dir: Union[str, Path]) -> List[str]:
    """The names of the golden samples of a project, sorted."""
    folder = Path(project_dir) / GOLDEN_DIR
    return sorted(p.stem for p in folder.glob("*.jsonl")) if folder.is_dir() else []


def format_result(result: GoldenResult) -> str:
    """The result as text for a log or a terminal."""
    lines = [f"{result.summary()}  ({result.run} against {result.golden})"]
    for check in result.checks:
        lines.append(f"  {'ok  ' if check.passed else 'FAIL'} {check.name}: {check.detail}")
    return "\n".join(lines)


__all__ = [
    "Check", "GoldenError", "GoldenRecorder", "GoldenResult", "check_against_golden",
    "check_curve", "check_figure", "check_golden_param", "check_rows", "check_step",
    "derive_tolerances", "find_golden", "finish",
    "format_result", "golden_path", "list_golden", "recording", "run_from_result", "set_golden",
    "validate_spec",
]  # fmt: skip
