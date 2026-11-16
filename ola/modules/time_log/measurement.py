# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Time log: read values from instruments at a fixed interval, each instrument at its own rate.

Parameters, one entry per instrument (the format of the current version)::

    {"duration_s": 86400,                              # the whole log (optional)
     "sources": [
        {"name": "dmm", "instrument": "dmm1", "interval_s": 3600,
         "readings": [{"name": "vout", "call": "read_voltage"}]},
        {"name": "daq", "instrument": "daq", "interval_s": 600, "samples": 500,
         "readings": [{"name": "temp1", "call": "measure_temperature",
                       "args": {"channels": "101"}}]},
        {"name": "psu", "instrument": "psu1", "interval_s": 300,
         "readings": [{"name": "v", "call": "read_voltage"},
                      {"name": "i", "call": "read_current"}]}]}

A datalogger can be read **all its channels together**: such a source has ``"scan": true`` and
its ``channels`` (the settings of the ``.inst`` file: ``channel_id``, ``meas_type``, optional
``range``, ``resolution``, ``probe_type``, ``sensor_type``) instead of ``readings``. The datalogger
is configured once at the start of the run, and each sample is one scan (``read_scan``) whose values
go to the channels in channel-number order::

        {"name": "daq", "instrument": "daq", "interval_s": 600, "scan": true,
         "channels": [{"name": "temp1", "channel_id": "101", "meas_type": "TEMP",
                       "probe_type": "TCouple", "sensor_type": "K"},
                      {"name": "vout", "channel_id": "103", "meas_type": "VOLT:DC"}]}

Each source is written to its own table (the table is named after the source). A source ends
after its ``samples``, or when the next sample would fall after ``duration_s``; without
``duration_s`` every source needs ``samples``.

The earlier format is still read: one ``interval_s`` for all the ``channels`` (each with its
``instrument``), all written to the table of the results::

    {"interval_s": 1.0, "duration_s": 3600,            # or "samples": 100
     "channels": [{"name": "vout", "instrument": "dmm1", "call": "read_voltage"},
                  {"name": "temp1", "instrument": "daq", "call": "measure_temperature",
                   "args": {"channels": "101"}}]}

``instrument`` is the name of an instrument bound to the ``instruments`` role. Samples are
scheduled from the start of the run (no drift): a slow read shortens the next wait, it does not
shift the whole log. If a read takes longer than the interval of its source, the samples it
should have taken in the meantime are skipped and a warning is logged. ``t_s`` is the time at
which the acquisition of the sample started. If a read fails the log stops with an error (what
was recorded stays).
"""

import time
from typing import Any, Dict, List, Optional

from ola.datalogger_setup import DataloggerSetupError, datalogger_calls, scan_order
from ola.measurement import Measurement, MeasurementContext, MeasurementError

RESERVED_NAMES = ("points", "t_s")  # "points" is the main table of the results, "t_s" the time


def _number(value: Any, minimum: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= minimum


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


class TimeLog(Measurement):
    """Time log measurement; the parameters are described in the module docstring."""

    def validate(self):
        """Check the parameters; return the list of problems (empty if OK)."""
        p = self.params
        if "sources" in p and "channels" in p:
            return ["use either 'sources' or 'channels', not both"]
        if "sources" not in p and "channels" not in p:
            return ["give 'sources' (one entry per instrument to read)"]
        duration = p.get("duration_s")
        problems: List[str] = []
        if duration is not None and not (_number(duration, 0) and duration > 0):
            problems.append("duration_s must be a number > 0")
        if "sources" in p:
            if "samples" in p or "interval_s" in p:
                problems.append("interval_s and samples belong to each source, not to the log")
            self._source_problems(p["sources"], duration, problems)
        else:
            self._channel_problems(p, duration, problems)
        return problems

    def _source_problems(self, sources: Any, duration: Any, problems: List[str]) -> None:
        if not isinstance(sources, list) or not sources:
            problems.append("sources must be a non-empty list")
            return
        names = set()
        for i, s in enumerate(sources):
            if not isinstance(s, dict) or not isinstance(s.get("name"), str) or not s["name"]:
                problems.append(f"source {i}: needs a 'name' (text)")
                continue
            name = s["name"]
            if name in RESERVED_NAMES:
                problems.append(f"source {name!r}: the name {name!r} is reserved")
            if name in names:
                problems.append(f"duplicate source name {name!r}")
            names.add(name)
            if not isinstance(s.get("instrument"), str) or not s["instrument"]:
                problems.append(f"source {name!r}: needs an 'instrument' (text)")
            if not _number(s.get("interval_s"), 0.001):
                problems.append(f"source {name!r}: interval_s must be a number >= 0.001")
            samples = s.get("samples")
            if samples is not None and not _count(samples):
                problems.append(f"source {name!r}: samples must be an integer >= 1")
            if samples is None and duration is None:
                problems.append(
                    f"source {name!r}: give samples, or duration_s for the log "
                    "(otherwise the log would never end)"
                )
            if s.get("scan") is True:
                self._scan_problems(s, name, problems)
                continue
            if "channels" in s:
                problems.append(f"source {name!r}: 'channels' is for a scan ('scan': true)")
            readings = s.get("readings")
            if not isinstance(readings, list) or not readings:
                problems.append(f"source {name!r}: readings must be a non-empty list")
                continue
            reading_names = set()
            for j, r in enumerate(readings):
                if not isinstance(r, dict) or not all(
                    isinstance(r.get(k), str) and r.get(k) for k in ("name", "call")
                ):
                    problems.append(f"source {name!r}, reading {j}: needs 'name' and 'call' (text)")
                    continue
                if r["name"] == "t_s" or r["name"] in reading_names:
                    problems.append(f"source {name!r}: reading name {r['name']!r} is not usable")
                reading_names.add(r["name"])
                if "args" in r and not isinstance(r["args"], dict):
                    problems.append(
                        f"source {name!r}, reading {r['name']!r}: 'args' must be an object"
                    )

    def _scan_problems(self, s: Dict[str, Any], name: str, problems: List[str]) -> None:
        """A datalogger read as one scan: its channels must be configurable and not repeated."""
        if "readings" in s:
            problems.append(f"source {name!r}: a scan has 'channels', not 'readings'")
        channels = s.get("channels")
        if not isinstance(channels, list) or not channels:
            problems.append(f"source {name!r}: channels must be a non-empty list")
            return
        names = set()
        for j, ch in enumerate(channels):
            if not isinstance(ch, dict) or not isinstance(ch.get("name"), str) or not ch["name"]:
                problems.append(f"source {name!r}, channel {j}: needs a 'name' (text)")
                continue
            if ch["name"] == "t_s" or ch["name"] in names:
                problems.append(f"source {name!r}: channel name {ch['name']!r} is not usable")
            names.add(ch["name"])
        try:
            order = scan_order([c for c in channels if isinstance(c, dict)])
            datalogger_calls(order)  # the same checks as the datalogger of the remote control
        except (DataloggerSetupError, TypeError, ValueError) as exc:
            problems.append(f"source {name!r}: {exc}")

    def _channel_problems(self, p: Dict[str, Any], duration: Any, problems: List[str]) -> None:
        """The earlier format: one interval and one stop for all the channels."""
        interval = p.get("interval_s")
        if not _number(interval, 0.001):
            problems.append("interval_s must be a number >= 0.001")
        samples = p.get("samples")
        if duration is None and samples is None:
            problems.append("give duration_s or samples (otherwise the log would never end)")
        if samples is not None and not _count(samples):
            problems.append("samples must be an integer >= 1")
        channels = p.get("channels")
        if not isinstance(channels, list) or not channels:
            problems.append("channels must be a non-empty list")
            return
        names = set()
        for i, ch in enumerate(channels):
            if not isinstance(ch, dict) or not all(
                isinstance(ch.get(k), str) and ch.get(k) for k in ("name", "instrument", "call")
            ):
                problems.append(f"channel {i}: needs 'name', 'instrument' and 'call' (strings)")
                continue
            if ch["name"] in names:
                problems.append(f"duplicate channel name {ch['name']!r}")
            names.add(ch["name"])
            if "args" in ch and not isinstance(ch["args"], dict):
                problems.append(f"channel {ch['name']}: 'args' must be an object")

    # ----- what runs ----------------------------------------------------------------------------
    def _plan(self) -> List[Dict[str, Any]]:
        """One group per table: its interval, its sample limit and its readings
        ``(name, instrument, call, args)``."""
        p = self.params
        if "sources" in p:
            plan = []
            for s in p["sources"]:
                group = {
                    "table": s["name"],
                    "interval": float(s["interval_s"]),
                    "samples": s.get("samples"),
                    "instrument": s["instrument"],
                    "readings": [],
                    "scan": None,
                }
                if s.get("scan") is True:
                    order = scan_order(list(s["channels"]))
                    group["scan"] = {
                        "setup": datalogger_calls(order),
                        "names": [c["name"] for c in order],
                    }
                else:
                    group["readings"] = [
                        (r["name"], s["instrument"], r["call"], r.get("args", {}))
                        for r in s["readings"]
                    ]
                plan.append(group)
            return plan
        return [
            {
                "table": "points",
                "interval": float(p["interval_s"]),
                "samples": p.get("samples"),
                "scan": None,
                "readings": [
                    (ch["name"], ch["instrument"], ch["call"], ch.get("args", {}))
                    for ch in p["channels"]
                ],
            }
        ]

    def setup(self, ctx: MeasurementContext) -> None:
        """Find each instrument's handle (fails before any read if one is unbound)."""
        by_name = {h.name: h for h in ctx.instruments("instruments")}
        self._groups = self._plan()
        for group in self._groups:
            if group["scan"] is not None:
                if group["instrument"] not in by_name:
                    raise MeasurementError(
                        f"source {group['table']!r}: instrument {group['instrument']!r} is not "
                        f"bound (bound: {sorted(by_name)})"
                    )
                group["scan_handle"] = by_name[group["instrument"]]
                for call, args in group["scan"]["setup"]:  # configured once, before the run
                    group["scan_handle"].call(call, **args)
                group["handles"] = []
                continue
            readers = []
            for name, instrument, call, args in group["readings"]:
                if instrument not in by_name:
                    where = (
                        f"source {group['table']!r}" if "sources" in self.params
                        else f"channel {name!r}"
                    )
                    raise MeasurementError(
                        f"{where}: instrument {instrument!r} is not bound "
                        f"(bound: {sorted(by_name)})"
                    )
                readers.append((name, by_name[instrument], call, args))
            group["handles"] = readers

    def _total(self, duration: Optional[float]) -> Optional[int]:
        """The number of samples of the whole log, if it can be known."""
        total = 0
        for group in self._groups:
            if group["samples"] is not None:
                total += group["samples"]
            elif duration is not None:
                total += int(duration / group["interval"]) + 1
            else:
                return None
        return total

    def _finished(self, state: Dict[str, Any], duration: Optional[float]) -> bool:
        group = state["group"]
        if group["samples"] is not None and state["n"] >= group["samples"]:
            return True
        return duration is not None and state["k"] * group["interval"] > duration

    @staticmethod
    def _scan(group: Dict[str, Any]) -> Dict[str, Any]:
        """One scan of the datalogger: its values go to the channels in channel-number order."""
        readings = group["scan_handle"].call("read_scan")
        names = group["scan"]["names"]
        if not isinstance(readings, (list, tuple)) or len(readings) < len(names):
            got = len(readings) if isinstance(readings, (list, tuple)) else type(readings).__name__
            raise MeasurementError(
                f"source {group['table']!r}: the datalogger gave {got} readings for "
                f"{len(names)} channels"
            )
        return dict(zip(names, readings))

    def run(self, ctx: MeasurementContext) -> None:
        """Take each source's samples at its own interval until every source is finished."""
        duration = self.params.get("duration_s")
        states = [{"group": g, "k": 0, "n": 0} for g in self._groups]
        total = self._total(duration)
        done = 0
        t0 = time.monotonic()
        while True:
            ctx.checkpoint()
            waiting = [s for s in states if not self._finished(s, duration)]
            if not waiting:
                return
            # the sample due first (ties: the order of the sources)
            state = min(waiting, key=lambda s: s["k"] * s["group"]["interval"])
            group = state["group"]
            due = state["k"] * group["interval"]
            ctx.sleep(max(0.0, t0 + due - time.monotonic()))
            ctx.checkpoint()
            values = {}
            t_sample = time.monotonic() - t0  # when the acquisition of this sample starts
            if group["scan"] is not None:
                values.update(self._scan(group))
            for name, handle, call, args in group["handles"]:
                values[name] = handle.call(call, **args)
            values["t_s"] = t_sample
            ctx.emit_point(values, table=group["table"])
            state["n"] += 1
            state["k"] += 1
            done += 1
            # the samples that fell due while this read was running are not taken
            now = time.monotonic() - t0
            due_next = int(now // group["interval"]) + 1
            if due_next > state["k"]:
                missed = due_next - state["k"]
                state["k"] = due_next
                ctx.log(
                    f"{group['table']}: {missed} sample(s) skipped: the reading took longer "
                    f"than its interval ({group['interval']:g} s)",
                    "warning",
                )
            ctx.progress(done, total)
