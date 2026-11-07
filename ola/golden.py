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
from typing import Any, Dict, List, Mapping, Optional, Union

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


def check_against_golden(run: RunData, golden: RunData, spec: Mapping[str, Any]) -> GoldenResult:
    """The verdict of a run against a golden sample: see the module docstring for ``spec``
    (``curves``, ``summary``, ``min_overlap``). ``GoldenError`` if the spec is wrong or the two are
    not the same kind of measurement."""
    if not isinstance(spec, Mapping):
        raise GoldenError("the tolerances must be an object")
    unknown = sorted(set(spec) - {"curves", "summary", "min_overlap"})
    if unknown:
        raise GoldenError(f"unknown key(s) {unknown}: use curves, summary or min_overlap")
    if not spec.get("curves") and not spec.get("summary"):
        raise GoldenError("give at least one curve or one summary figure to check")
    if run.measurement != golden.measurement:
        raise GoldenError(
            f"the run is a {run.measurement} measurement and the golden sample a "
            f"{golden.measurement} one"
        )
    overlap = spec.get("min_overlap", DEFAULT_OVERLAP)
    if not _number(overlap) or not 0 < overlap <= 1:
        raise GoldenError("min_overlap must be above 0 and at most 1")
    result = GoldenResult(golden.label, run.label)
    for item in spec.get("curves") or []:
        if not isinstance(item, Mapping) or "trace" not in item or "tolerance" not in item:
            raise GoldenError("a curve to check needs 'trace' and 'tolerance' (and a 'view')")
        result.checks.append(
            check_curve(
                run, golden, str(item["trace"]), str(item.get("view", "value")),
                item["tolerance"], float(overlap),
            )  # fmt: skip
        )
    for key, tolerance in (spec.get("summary") or {}).items():
        result.checks.append(check_figure(run, golden, str(key), tolerance))
    for check in result.checks:
        if not check.passed:
            result.reasons.append(f"{check.name}: {check.detail}")
    return result


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
    "Check", "GoldenError", "GoldenResult", "check_against_golden", "check_curve", "check_figure",
    "find_golden", "format_result", "golden_path", "list_golden", "set_golden",
]  # fmt: skip
