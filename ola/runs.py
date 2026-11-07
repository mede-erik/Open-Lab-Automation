"""Run storage: results are written while the measurement runs (a crash loses nothing).

A run file is JSON Lines, one object per line::

    {"kind": "run",   ...header: run_id, measurement, params, bindings, started_at...}
    {"kind": "point", "table": "points", "index": 0, "elapsed_s": 0.5, "values": {...}, "t": ...}
    {"kind": "trace", "name": "ch1", "trace_kind": "real|complex", "x": [...], "y": [...],
     "meta": {...}, "t": ...}
    {"kind": "log",   ...}   {"kind": "error", ...}
    {"kind": "question", "id": ..., "text": ..., "choices": [...], "data": {...}}   a question
    {"kind": "answered", "id": ..., "choice": "retry", "auto": false}               its answer
    {"kind": "end",   "state": "finished|stopped|failed", "error": null | {...}}

A file without the final "end" line is a run that was interrupted: it can still be read.
Traces are stored inline as JSON (simple; very long waveforms will get a binary sidecar later).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from .identity import snapshot
from .measurement import Event
from .runner import FINAL_STATES, Runner


class RunWriter:
    """Listener for ``Runner`` that appends events to a run file."""

    def __init__(self, path: Union[str, Path], header: Mapping[str, Any]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(self.path, "w", encoding="utf-8", newline="\n")
        self._write({"kind": "run", **header})
        self.error: Optional[Dict[str, Any]] = None

    @staticmethod
    def header_for(runner: Runner, **extra: Any) -> Dict[str, Any]:
        """Header line of a run file built from a runner (run id, module, parameters, bound
        instruments); ``extra`` adds fields."""
        info = runner.measurement.info
        return {
            "run_id": runner.run_id,
            "measurement": getattr(info, "id", type(runner.measurement).__name__),
            "module_version": getattr(info, "version", None),
            "params": runner.measurement.params,
            "bindings": {r: [h.name for h in hs] for r, hs in runner.bindings.items()},
            # who made the measurement: kept as it was that day (see ola.identity)
            "instruments": {r: [snapshot(h) for h in hs] for r, hs in runner.bindings.items()},
            **extra,
        }

    def __call__(self, event: Event) -> None:
        if self._f is None:
            return
        if event.kind == "state":
            state = event.data["state"]
            if state in {s.value for s in FINAL_STATES}:
                self._write({"kind": "end", "state": state, "error": self.error, "t": event.t})
                self.close()
            return
        if event.kind == "error":
            self.error = event.data
        self._write({**event.data, "kind": event.kind, "t": event.t})  # "kind" always wins

    def _write(self, obj: Mapping[str, Any]) -> None:
        self._f.write(json.dumps(obj, ensure_ascii=False, default=str, allow_nan=True) + "\n")
        self._f.flush()

    def close(self) -> None:
        """Close the file (done automatically when the run ends)."""
        if self._f is not None:
            self._f.close()
            self._f = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def read_run(path: Union[str, Path]) -> Dict[str, Any]:
    """Read a run file. Tolerates a truncated last line (interrupted run)."""
    run: Dict[str, Any] = {
        "header": None,
        "points": [],
        "tables": {},
        "traces": [],
        "logs": [],
        "errors": [],
        "questions": [],
        "end": None,
    }
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                break  # truncated final line
            kind = obj.get("kind")
            if kind == "run":
                run["header"] = obj
            elif kind == "point":
                table = obj.get("table", "points")
                if table == "points":
                    run["points"].append(obj)
                else:
                    run["tables"].setdefault(table, []).append(obj)
            elif kind == "trace":
                run["traces"].append(obj)
            elif kind == "log":
                run["logs"].append(obj)
            elif kind == "error":
                run["errors"].append(obj)
            elif kind in ("question", "answered"):
                run["questions"].append(obj)
            elif kind == "end":
                run["end"] = obj
    return run


def export_points_csv(
    run_path: Union[str, Path], csv_path: Union[str, Path], table: str = "points"
) -> int:
    """Write the rows of one table of a run to CSV (columns: index, elapsed_s, then the values in
    order of first appearance). ``table`` is ``"points"`` or the name of another table, for
    example ``"samples"``. Returns the number of rows."""
    run = read_run(run_path)
    points: List[Dict[str, Any]] = (
        run["points"] if table == "points" else run["tables"].get(table, [])
    )
    columns: List[str] = []
    for p in points:
        for key in p["values"]:
            if key not in columns:
                columns.append(key)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "elapsed_s", *columns])
        for p in points:
            w.writerow([p["index"], p["elapsed_s"], *[p["values"].get(c, "") for c in columns]])
    return len(points)


def last_traces(run_path: Union[str, Path]) -> Dict[str, Dict[str, Any]]:
    """The latest trace of every name in a run file: ``{name: trace}`` (a trace is the dictionary
    stored in the file: ``x``, ``y``, ``trace_kind``, ``meta``). A measurement that repeats a
    sweep keeps all of them in the file; this gives the newest of each."""
    latest: Dict[str, Dict[str, Any]] = {}
    for trace in read_run(run_path)["traces"]:
        latest[trace["name"]] = trace
    return latest


def export_trace_csv(
    run_path: Union[str, Path], csv_path: Union[str, Path], name: Optional[str] = None
) -> int:
    """Write one trace of a run to CSV and return the number of rows. ``name``: which trace (the
    only one if the run has just one). A real trace gives ``x,y``; a complex one (S-parameters)
    gives ``x,re,im,magnitude_db,phase_deg``, the form most tools accept."""
    from . import rf

    traces = last_traces(run_path)
    if name is None:
        if len(traces) != 1:
            raise ValueError(f"the run has {len(traces)} traces ({sorted(traces)}): choose a name")
        name = next(iter(traces))
    if name not in traces:
        raise ValueError(f"no trace named {name!r} (the run has {sorted(traces)})")
    trace = traces[name]
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if trace.get("trace_kind") == "complex":
            values = rf.from_pairs(trace["y"])
            mag, ph = rf.magnitude_db(values), rf.phase_deg(values)
            w.writerow(["x", "re", "im", "magnitude_db", "phase_deg"])
            for x, v, m, p in zip(trace["x"], values, mag, ph):
                w.writerow([x, v.real, v.imag, m, p])
        else:
            w.writerow(["x", "y"])
            w.writerows(zip(trace["x"], trace["y"]))
    return len(trace["x"])


def export_touchstone(
    run_path: Union[str, Path],
    path: Union[str, Path],
    names: Optional[Mapping[str, str]] = None,
    z0: float = 50.0,
    fmt: str = "RI",
    unit: str = "HZ",
) -> int:
    """Write the S-parameter traces of a run as a Touchstone file and return the number of
    frequency points. ``names`` maps a parameter to the name of its trace, for example
    ``{"S21": "S21"}`` (the default: every trace called S11, S21, S12 or S22). All the traces
    must have the same frequencies. The file extension should be ``.s1p`` or ``.s2p``."""
    from . import rf

    traces = last_traces(run_path)
    mapping = dict(names) if names else {k: k for k in ("S11", "S21", "S12", "S22") if k in traces}
    if not mapping:
        raise ValueError(f"the run has no S-parameter traces (it has {sorted(traces)})")
    freq: Optional[List[float]] = None
    params: Dict[str, List[complex]] = {}
    for param, trace_name in mapping.items():
        if trace_name not in traces:
            raise ValueError(f"no trace named {trace_name!r} (the run has {sorted(traces)})")
        trace = traces[trace_name]
        if trace.get("trace_kind") != "complex":
            raise ValueError(f"trace {trace_name!r} is not complex: it cannot be an S-parameter")
        if freq is not None and list(trace["x"]) != freq:
            raise ValueError("the S-parameter traces do not have the same frequencies")
        freq = list(trace["x"])
        params[param] = rf.from_pairs(trace["y"])
    rf.write_touchstone(path, freq or [], params, z0=z0, fmt=fmt, unit=unit)
    return len(freq or [])
