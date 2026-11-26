# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Open a run that was made before: its file read back as if the run were happening again.

``ReplayRunner`` has the part of the interface of ``ola.runner.Runner`` that the run window uses
(``drain``, ``pending_questions``, ``start``, ``stop``...) and gives, in one go, the events written
in a run file: the points, the traces, the log, the error, the benchmark report and the end. The
window then shows the table, the plots, the curves, the waveforms and the log of that run exactly
as it did when the run was made, with nothing to start (the run is over). The questions that were
asked during the run are not asked again. A run that has no ``end`` line (interrupted: a crash, the
program closed) is shown as *stopped* and says so in its log. No Qt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .measurement import Event

_EVENTS = {"point", "trace", "log", "error", "bench", "progress"}  # what the file keeps of a run


class ReplayError(Exception):
    """The file is not a run file, or cannot be read."""


class ReplayRunner:
    """The events of a run file, to be shown by the run window (see the module docstring)."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.header: Optional[Dict[str, Any]] = None
        self.ended = False  # the file had an ``end`` line
        self.run_id = ""
        self._events: List[Event] = self._read()

    def _read(self) -> List[Event]:
        events: List[Event] = []
        end: Optional[Dict[str, Any]] = None
        last_t = 0.0
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        break  # a truncated last line: an interrupted run
                    if not isinstance(obj, dict):
                        continue
                    kind, t = obj.pop("kind", None), obj.pop("t", None)
                    if kind == "run":
                        self.header = {"kind": "run", **obj}
                        self.run_id = str(obj.get("run_id", ""))
                        last_t = float(obj.get("started_at") or 0.0)
                        continue
                    t = float(t) if isinstance(t, (int, float)) else last_t
                    last_t = t
                    if kind == "end":
                        end = {**obj, "t": t}
                    elif kind in _EVENTS:
                        events.append(Event(str(kind), obj, t))
        except OSError as exc:
            raise ReplayError(f"{self.path}: cannot be read: {exc}") from exc
        if self.header is None:
            raise ReplayError(f"{self.path} is not a run file")
        start = events[0].t if events else last_t
        head = [Event("state", {"state": "running", "run_id": self.run_id}, start)]
        if end is None:  # interrupted: it can still be read
            tail = [
                Event("log", {"level": "warning", "message": "the run was interrupted"}, last_t),
                Event("state", {"state": "stopped", "run_id": self.run_id}, last_t),
            ]
        else:
            self.ended = True
            state = str(end.get("state", "finished"))
            error = end.get("error")
            tail = [Event("error", dict(error), end["t"])] if isinstance(error, dict) else []
            tail.append(Event("state", {"state": state, "run_id": self.run_id}, end["t"]))
        # an error is also written before the end by the run itself: show it once
        if tail and tail[0].kind == "error" and any(e.kind == "error" for e in events):
            tail = tail[1:]
        return head + events + tail

    # ----- the part of the interface of Runner that the run window uses ------------------------
    def drain(self) -> List[Event]:
        """All the events, the first time; nothing after."""
        events, self._events = self._events, []
        return events

    @property
    def pending_questions(self) -> List[Dict[str, Any]]:
        """None: the questions of the run are not asked again."""
        return []

    def start(self) -> None:
        """Nothing to start: the run is over."""

    def stop(self) -> None:
        """Nothing to stop."""

    def pause(self) -> None:
        """Nothing to pause."""

    def resume(self) -> None:
        """Nothing to resume."""

    def answer(self, question_id: str, choice: str) -> None:
        """Nothing is asked."""

    def join(self, timeout: Optional[float] = None) -> bool:
        """Always done."""
        return True


__all__ = ["ReplayError", "ReplayRunner"]
