# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Benchmark mode: where does the time of a call or of a measurement go?

Off by default and then almost free (one variable check per instrumented place). Turn it on with
the environment variable ``OLA_BENCH=1`` (also works for the GUI), with
``ProjectSession.build_runner(..., bench=True)`` or ``Runner(..., bench=True)``. At the end of a
run the runner publishes a ``bench`` event with the report (it is also written to the run file as
a ``{"kind": "bench"}`` line); ``format_report`` turns it into text.

What is measured (all times from ``time.perf_counter_ns``):

* **calls** - every ``handle.call``: total, and its parts: ``plan`` (library lookup and building
  the steps), ``lock`` (waiting for another thread's call on the same instrument), ``io`` (steps
  executed on the instrument), ``delay`` (deliberate ``delay`` steps of the library),
  ``interp`` (turning the raw answer into the logical value) and ``overhead`` (the rest: what
  the software adds).
* **steps** - every step of every call, per instrument and command (numbers in the command are
  replaced by ``#`` so ``VOLT 5`` and ``VOLT 12`` are one row). A query is split in ``tx``
  (sending) and ``rx`` (waiting for the answer): ``rx`` is the response latency of the instrument
  plus the link.
* **phases**, **emit** (publishing a point or trace, listeners included), **listener** (each
  listener, e.g. the run writer), **wait** (waits that are part of the measurement: ``sleep``
  and questions to the user) and **connect** (opening a connection and reading the identity).
* **summary** of the thread that runs the measurement: wall time split in waiting by design,
  instrument calls, emit and the rest (the measurement's own code).
"""

from __future__ import annotations

import os
import platform
import re
import statistics
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPORT_VERSION = 1
MAX_SAMPLES = 1_000_000  # total spans kept; further ones are counted in ``dropped``

_NUMBER = re.compile(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?")
_PARTS = ("plan", "lock", "io", "delay", "interp", "overhead")


def now() -> int:
    """The clock of the benchmark, in nanoseconds."""
    return time.perf_counter_ns()


def normalize(text: str, limit: int = 60) -> str:
    """A command without its numbers, so that all values of one command are one row."""
    return _NUMBER.sub("#", str(text).strip())[:limit]


class _Stat:
    """The durations (ns) of one (category, name), in total and per thread."""

    __slots__ = ("samples", "by_thread")

    def __init__(self) -> None:
        self.samples: List[int] = []
        self.by_thread: Dict[str, int] = {}


class Bench:
    """The collector. One is active at a time (see ``enable``); it is thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stats: Dict[Tuple[str, str], _Stat] = {}
        self._parts: Dict[str, Dict[str, int]] = {}  # call -> part -> total ns (for the means)
        self.t0 = now()
        self.count = 0
        self.dropped = 0

    def record(self, category: str, name: str, duration_ns: int) -> None:
        """Add one measured duration."""
        thread = threading.current_thread().name
        with self._lock:
            if self.count >= MAX_SAMPLES:
                self.dropped += 1
                return
            self.count += 1
            stat = self._stats.get((category, name))
            if stat is None:
                stat = self._stats[(category, name)] = _Stat()
            stat.samples.append(duration_ns)
            stat.by_thread[thread] = stat.by_thread.get(thread, 0) + duration_ns

    def record_call(self, name: str, total_ns: int, parts: Dict[str, int]) -> None:
        """Add one logical call with its parts (see the module docstring)."""
        self.record("call", name, total_ns)
        with self._lock:
            sums = self._parts.setdefault(name, {})
            for part, value in parts.items():
                sums[part] = sums.get(part, 0) + value

    # ----- report -----------------------------------------------------------------------
    def report(self, run_thread: Optional[str] = None) -> Dict[str, Any]:
        """The results so far as a JSON-friendly dict. ``run_thread``: name of the thread that
        runs the measurement, for the time summary."""
        with self._lock:
            stats = {key: (list(s.samples), dict(s.by_thread)) for key, s in self._stats.items()}
            parts = {name: dict(p) for name, p in self._parts.items()}
            dropped = self.dropped
        rows = []
        for (category, name), (samples, by_thread) in sorted(stats.items()):
            row = {"category": category, "name": name, **_summary(samples)}
            if category == "call" and name in parts:
                row["parts_ms"] = {
                    part: round(parts[name].get(part, 0) / len(samples) / 1e6, 4) for part in _PARTS
                }
            rows.append(row)
        return {
            "version": REPORT_VERSION,
            "backend": _backend(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "elapsed_s": round((now() - self.t0) / 1e9, 4),
            "dropped": dropped,
            "summary": _time_summary(stats, run_thread),
            "rows": rows,
        }


def _backend() -> str:
    try:
        from .transport import BACKEND

        return BACKEND
    except Exception:  # pragma: no cover - the report must never fail for this
        return "?"


def _summary(samples: List[int]) -> Dict[str, Any]:
    ms = sorted(s / 1e6 for s in samples)
    n = len(ms)
    return {
        "n": n,
        "total_ms": round(sum(ms), 4),
        "mean_ms": round(sum(ms) / n, 4),
        "median_ms": round(statistics.median(ms), 4),
        "p95_ms": round(ms[min(n - 1, int(n * 0.95))], 4),
        "min_ms": round(ms[0], 4),
        "max_ms": round(ms[-1], 4),
    }


def _time_summary(stats: Dict, run_thread: Optional[str]) -> Dict[str, float]:
    """Wall time of the measurement thread split into waiting, instrument calls, emit, other."""
    if run_thread is None:
        return {}

    def spent(category: str, name: Optional[str] = None) -> float:
        total = 0
        for (cat, nm), (_, by_thread) in stats.items():
            if cat == category and (name is None or nm == name):
                total += by_thread.get(run_thread, 0)
        return total / 1e9

    wall = spent("phase")
    wait, calls, emit = spent("wait"), spent("call"), spent("emit")
    return {
        "wall_s": round(wall, 4),
        "wait_s": round(wait, 4),
        "calls_s": round(calls, 4),
        "emit_s": round(emit, 4),
        "other_s": round(max(0.0, wall - wait - calls - emit), 4),
    }


# ----- global switch ----------------------------------------------------------------------
_active: Optional[Bench] = None
_tls = threading.local()


def env_enabled() -> bool:
    """True if ``OLA_BENCH`` asks for the benchmark (1, true, yes, on)."""
    return os.environ.get("OLA_BENCH", "").strip().lower() in ("1", "true", "yes", "on")


def enable(fresh: bool = False) -> Bench:
    """Start collecting. Keeps the running collector unless ``fresh`` (a new, empty one)."""
    global _active
    if _active is None or fresh:
        _active = Bench()
    return _active


def disable() -> None:
    """Stop collecting (the collector returned by ``enable`` keeps what it has)."""
    global _active
    _active = None


def current() -> Optional[Bench]:
    """The active collector, or None when the benchmark is off."""
    return _active


def stamp() -> int:
    """``now()`` when the benchmark is on, 0 when it is off (to bracket a place cheaply)."""
    return time.perf_counter_ns() if _active is not None else 0


class _NullSpan:
    """What ``span`` and ``call_frame`` return when the benchmark is off: does nothing."""

    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def part(self, name: str) -> "_NullSpan":
        """No-op twin of ``_Frame.part``."""
        return self


_NULL = _NullSpan()


class _Span:
    __slots__ = ("bench", "category", "name", "t")

    def __init__(self, bench: Bench, category: str, name: str):
        self.bench, self.category, self.name = bench, category, name

    def __enter__(self) -> "_Span":
        self.t = time.perf_counter_ns()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.bench.record(self.category, self.name, time.perf_counter_ns() - self.t)


def span_record(category: str, name: str, duration_ns: int) -> None:
    """Record a duration measured by the caller (nothing when the benchmark is off)."""
    bench = _active
    if bench is not None:
        bench.record(category, name, duration_ns)


def span(category: str, name: str):
    """``with span("phase", "setup"):`` records the time spent inside (nothing when off)."""
    bench = _active
    return _NULL if bench is None else _Span(bench, category, name)


class _Part:
    __slots__ = ("frame", "name", "t")

    def __init__(self, frame: "_Frame", name: str):
        self.frame, self.name = frame, name

    def __enter__(self) -> "_Part":
        self.t = time.perf_counter_ns()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.frame.add(self.name, time.perf_counter_ns() - self.t)


class _Frame:
    """One logical call being timed: collects the parts spent by the planner and the instrument."""

    __slots__ = ("bench", "name", "t", "parts", "outer")

    def __init__(self, bench: Bench, name: str):
        self.bench, self.name, self.parts = bench, name, {}

    def add(self, part: str, ns: int) -> None:
        """Add ``ns`` to a part of the call."""
        self.parts[part] = self.parts.get(part, 0) + ns

    def part(self, name: str) -> _Part:
        """``with frame.part("plan"):`` adds the time spent inside to that part."""
        return _Part(self, name)

    def __enter__(self) -> "_Frame":
        self.outer = getattr(_tls, "frame", None)
        _tls.frame = self
        self.t = time.perf_counter_ns()
        return self

    def __exit__(self, *exc: Any) -> None:
        total = time.perf_counter_ns() - self.t
        _tls.frame = self.outer
        known = sum(self.parts.get(p, 0) for p in _PARTS if p != "overhead")
        self.parts["overhead"] = max(0, total - known)
        self.bench.record_call(self.name, total, self.parts)


def call_frame(instrument: str, call: str):
    """``with call_frame("psu", "set_voltage") as frame:`` times one logical call and its parts."""
    bench = _active
    return _NULL if bench is None else _Frame(bench, f"{instrument}.{call}")


def add_to_call(part: str, ns: int) -> None:
    """Add time to a part of the call being timed on this thread (if any)."""
    frame = getattr(_tls, "frame", None)
    if frame is not None:
        frame.add(part, ns)


class StepTimer:
    """Times one step on an instrument: ``sent()`` after sending, ``done()`` at the end.

    Created only when the benchmark is on (``StepTimer.start`` returns None otherwise)."""

    __slots__ = ("bench", "name", "t0", "t_sent", "is_delay")

    def __init__(self, bench: Bench, name: str, is_delay: bool):
        self.bench, self.name, self.is_delay = bench, name, is_delay
        self.t_sent = 0
        self.t0 = time.perf_counter_ns()

    @staticmethod
    def start(instrument: str, op: str, text: Optional[str]) -> "Optional[StepTimer]":
        """A timer for a step of ``instrument``, or None if the benchmark is off."""
        bench = _active
        if bench is None:
            return None
        label = f"{op} {normalize(text)}" if text else op
        return StepTimer(bench, f"{instrument}: {label}", op == "delay")

    def sent(self) -> None:
        """The command has been sent; what follows is the wait for the answer."""
        self.t_sent = time.perf_counter_ns()

    def done(self) -> None:
        """The step ended (also when it failed)."""
        end = time.perf_counter_ns()
        total = end - self.t0
        if self.is_delay:
            self.bench.record("delay", self.name, total)
            add_to_call("delay", total)
            return
        self.bench.record("step", self.name, total)
        if self.t_sent:
            self.bench.record("tx", self.name, self.t_sent - self.t0)
            self.bench.record("rx", self.name, end - self.t_sent)
        add_to_call("io", total)


# ----- text report ------------------------------------------------------------------------
def rows_of(report: Dict[str, Any], category: str) -> List[Dict[str, Any]]:
    """The rows of one category, slowest (by total time) first."""
    rows = [r for r in report.get("rows", []) if r["category"] == category]
    return sorted(rows, key=lambda r: r["total_ms"], reverse=True)


def format_report(report: Dict[str, Any], top: int = 15) -> str:
    """The report as readable text (tables in milliseconds)."""
    out: List[str] = []
    out.append(
        f"Benchmark - transport {report.get('backend')}, Python {report.get('python')}, "
        f"{report.get('elapsed_s')} s"
    )
    summary = report.get("summary") or {}
    if summary and summary.get("wall_s"):
        wall = summary["wall_s"]
        out.append("")
        out.append(f"Measurement thread: {wall:.3f} s")
        for key, label in (
            ("wait_s", "waiting by design (sleep, questions)"),
            ("calls_s", "instrument calls"),
            ("emit_s", "publishing results (writer, listeners)"),
            ("other_s", "measurement code and the rest"),
        ):
            value = summary.get(key, 0.0)
            out.append(f"  {label:42s} {value:9.3f} s  {100 * value / wall:5.1f} %")
    sections = (
        ("call", "Calls (ms; parts = mean per call)"),
        ("step", "Steps on the instruments (ms)"),
        ("rx", "Instrument response: wait for the answer after sending (ms)"),
        ("tx", "Sending a command (ms)"),
        ("delay", "Delays of the library (ms)"),
        ("phase", "Phases (ms)"),
        ("emit", "Publishing results (ms)"),
        ("listener", "Listeners (ms)"),
        ("wait", "Waits by design (ms)"),
        ("connect", "Connections (ms)"),
    )
    for category, title in sections:
        rows = rows_of(report, category)
        if not rows:
            continue
        out.append("")
        out.append(title)
        out.append(
            f"  {'name':44s} {'n':>6s} {'mean':>9s} {'median':>9s} {'p95':>9s} {'max':>9s} "
            f"{'total':>10s}"
        )
        for r in rows[:top]:
            out.append(
                f"  {r['name'][:44]:44s} {r['n']:6d} {r['mean_ms']:9.3f} {r['median_ms']:9.3f} "
                f"{r['p95_ms']:9.3f} {r['max_ms']:9.3f} {r['total_ms']:10.1f}"
            )
            parts = r.get("parts_ms")
            if parts:
                shown = "  ".join(f"{p} {parts[p]:.3f}" for p in _PARTS)
                out.append(f"      parts: {shown}")
        if len(rows) > top:
            out.append(f"  ... and {len(rows) - top} more")
    if report.get("dropped"):
        out.append(f"\n{report['dropped']} samples were dropped (limit {MAX_SAMPLES}).")
    return "\n".join(out)


def compare_reports(
    old: Dict[str, Any], new: Dict[str, Any], categories: Iterable[str] = ("call", "step", "rx")
) -> str:
    """Median of every row in two reports side by side, with the change in per cent."""
    keep = set(categories)
    first = {(r["category"], r["name"]): r for r in old.get("rows", []) if r["category"] in keep}
    second = {(r["category"], r["name"]): r for r in new.get("rows", []) if r["category"] in keep}
    out = [f"{'row':58s} {'old ms':>9s} {'new ms':>9s} {'change':>8s}"]
    for key in sorted(set(first) | set(second)):
        a, b = first.get(key), second.get(key)
        label = f"{key[0]}: {key[1]}"[:58]
        if a and b:
            base = a["median_ms"]
            change = f"{100 * (b['median_ms'] - base) / base:+7.1f}%" if base else "     n/a"
            out.append(f"{label:58s} {base:9.3f} {b['median_ms']:9.3f} {change:>8s}")
        else:
            side = a or b
            tag = "removed" if a else "new"
            out.append(f"{label:58s} {side['median_ms']:9.3f} {'':9s} {tag:>8s}")
    return "\n".join(out)
