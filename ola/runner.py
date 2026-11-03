"""Runs a measurement in its own thread: setup -> run -> teardown (always), with stop/pause.

    cancel = threading.Event()                    # one per run, shared with the handles
    runner = Runner(measurement, {"psu": [handle]}, listeners=[RunWriter(...)], stop_event=cancel)
    runner.start()          # validates, then returns; the work happens in a thread
    runner.pause(); runner.resume(); runner.stop()
    runner.join()
    runner.state            # FINISHED | STOPPED | FAILED
    runner.drain()          # events since the last call (for a GUI timer), if collect=True

Listeners are called in the runner thread; an exception in a listener is logged as a warning and
never stops the measurement. A GUI listener must hand events over to its own thread.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Union

from .instrument import Aborted
from .measurement import (
    Event,
    InstrumentHandle,
    Measurement,
    MeasurementContext,
    MeasurementError,
    Role,
    Stopped,
)


class RunState(str, Enum):
    """Lifecycle of a run; ``FINISHED``, ``STOPPED`` and ``FAILED`` are final."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"  # stopped on a question, until the user answers (or stops the run)
    STOPPING = "stopping"
    FINISHED = "finished"
    STOPPED = "stopped"
    FAILED = "failed"


FINAL_STATES = (RunState.FINISHED, RunState.STOPPED, RunState.FAILED)
Listener = Callable[[Event], None]
Binding = Union[InstrumentHandle, Sequence[InstrumentHandle]]


class Runner:
    """Runs one measurement in a thread (single use); see the module docstring."""

    def __init__(
        self,
        measurement: Measurement,
        bindings: Mapping[str, Binding],
        roles: Optional[Sequence[Role]] = None,
        listeners: Sequence[Listener] = (),
        collect: bool = True,
        run_id: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
        unattended: Optional[str] = None,
    ):
        """``unattended``: for scripts and tests without a user. If set, every question of the
        measurement is answered immediately with this choice (or with the question's default if
        it is not one of its choices); otherwise the run waits for ``answer()``."""
        self.measurement = measurement
        self.roles = tuple(roles if roles is not None else measurement.roles)
        self.bindings: Dict[str, List[InstrumentHandle]] = {
            role: list(b) if isinstance(b, (list, tuple)) else [b] for role, b in bindings.items()
        }
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.started_at: Optional[float] = None
        self.error: Optional[Dict[str, Any]] = None
        self._listeners = list(listeners)
        self._events: "queue.Queue[Event]" = queue.Queue()
        self._collect = collect
        self._lock = threading.RLock()
        self._state = RunState.IDLE
        # May be created by the caller so instrument handles can share it (one per run).
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._resume = threading.Event()
        self._resume.set()
        self._thread: Optional[threading.Thread] = None
        self._row_index: Dict[str, int] = {}  # next row number of every table
        self._t0 = 0.0
        self._derived_warned = False
        self._unattended = unattended
        self._pending: Dict[str, Dict[str, Any]] = {}

    # ----- public -----------------------------------------------------------------------
    @property
    def state(self) -> RunState:
        """Current ``RunState``."""
        return self._state

    @property
    def stop_event(self) -> threading.Event:
        """The event set by ``stop()``; pass it as ``cancel`` to the instrument handles."""
        return self._stop

    def add_listener(self, listener: Listener) -> None:
        """Add a function called with every ``Event``, in the runner thread."""
        self._listeners.append(listener)

    def start(self) -> None:
        """Check bindings and parameters, then start the thread. Raises ``MeasurementError``
        (nothing is sent to any instrument) if the measurement cannot start."""
        with self._lock:
            if self._state is not RunState.IDLE:
                raise MeasurementError(f"run already started (state {self._state.value})")
            problems = self._check_bindings() + list(self.measurement.validate())
            if problems:
                raise MeasurementError("; ".join(problems))
            self.started_at = time.time()
            self._t0 = time.monotonic()
            self._set_state(RunState.RUNNING)
            self._thread = threading.Thread(
                target=self._main, name=f"run-{self.run_id}", daemon=True
            )
            self._thread.start()

    @property
    def pending_questions(self) -> List[Dict[str, Any]]:
        """The questions waiting for an answer (``id``, ``text``, ``choices``, ``default``,
        ``data``), oldest first. An interface that missed the ``question`` event can poll this."""
        with self._lock:
            return [dict(q["question"]) for q in self._pending.values()]

    def answer(self, question_id: str, choice: str) -> None:
        """Answer a question of the measurement. ``MeasurementError`` if there is no such pending
        question, ``ValueError`` if ``choice`` is not one of its choices."""
        with self._lock:
            entry = self._pending.get(question_id)
            if entry is None:
                raise MeasurementError(f"no pending question with id {question_id!r}")
            if choice not in entry["question"]["choices"]:
                raise ValueError(
                    f"{choice!r} is not one of the choices {entry['question']['choices']}"
                )
            entry["choice"] = choice
            entry["event"].set()

    def stop(self) -> None:
        """Ask the run to stop; it ends as STOPPED after ``teardown`` (also wakes a paused run)."""
        with self._lock:
            if self._state in (RunState.RUNNING, RunState.PAUSED, RunState.WAITING):
                self._set_state(RunState.STOPPING)
            self._stop.set()
            self._resume.set()  # wake a paused run so it can stop

    def pause(self) -> None:
        """Pause at the next ``ctx.checkpoint()`` / ``ctx.sleep()``."""
        with self._lock:
            if self._state is RunState.RUNNING:
                self._resume.clear()
                self._set_state(RunState.PAUSED)

    def resume(self) -> None:
        """Continue a paused run."""
        with self._lock:
            if self._state is RunState.PAUSED:
                self._set_state(RunState.RUNNING)
                self._resume.set()

    def join(self, timeout: Optional[float] = None) -> bool:
        """Wait for the end of the run. True if it has ended."""
        if self._thread is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def drain(self) -> List[Event]:
        """Events produced since the previous call (needs ``collect=True``)."""
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    # ----- internals --------------------------------------------------------------------
    def _check_bindings(self) -> List[str]:
        problems = []
        known = {r.name for r in self.roles}
        for role in self.roles:
            n = len(self.bindings.get(role.name, []))
            if n == 0 and role.required:
                problems.append(f"role '{role.name}' ({role.category}) has no instrument")
            if n > 1 and not role.multiple:
                problems.append(f"role '{role.name}' accepts one instrument, {n} given")
        for name in self.bindings:
            if name not in known:
                problems.append(f"unknown role '{name}'")
        return problems

    def _set_state(self, state: RunState) -> None:
        self._state = state
        self._publish(Event("state", {"state": state.value, "run_id": self.run_id}))

    def _publish(self, event: Event) -> None:
        if self._collect:
            self._events.put(event)
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as exc:  # a broken listener must not kill the measurement
                if event.kind != "log":
                    self._publish_log(f"listener {listener!r} failed: {exc}", "warning")

    def _publish_log(self, message: str, level: str) -> None:
        # logged without notifying the listeners again (avoids loops)
        if self._collect:
            self._events.put(Event("log", {"level": level, "message": message}))

    def _emit(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == "point":
            table = data.get("table", "points")
            values = data["values"]
            extra = self._derived(values) if table == "points" else {}
            index = self._row_index.get(table, 0)
            self._row_index[table] = index + 1
            data = {
                "table": table,
                "index": index,
                "elapsed_s": time.monotonic() - self._t0,
                "values": {**values, **extra},
            }
        self._publish(Event(kind, data))

    def _derived(self, values: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            extra = dict(self.measurement.derived(values))
        except Exception as exc:
            if not self._derived_warned:
                self._derived_warned = True
                self._publish(
                    Event("log", {"level": "warning", "message": f"derived() failed: {exc!r}"})
                )
            return {}
        clash = [k for k in extra if k in values]
        if clash:
            self._publish(
                Event(
                    "log",
                    {
                        "level": "warning",
                        "message": f"derived() ignored for measured keys: {clash}",
                    },
                )
            )
            extra = {k: v for k, v in extra.items() if k not in values}
        return extra

    def _fail(self, phase: str, exc: BaseException) -> None:
        info = {
            "phase": phase,
            "type": type(exc).__name__,
            "message": str(exc),
            "code": getattr(exc, "code", None),
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        }
        if self.error is None:
            self.error = info
        else:
            self.error.setdefault("also", []).append(info)
        self._publish(Event("error", info))

    def _ask(self, text: str, choices: List[str], default: str, data: Dict[str, Any]) -> str:
        """Publish a question and wait for ``answer()`` (called from the measurement thread)."""
        qid = uuid.uuid4().hex[:8]
        question = {"id": qid, "text": text, "choices": choices, "default": default, "data": data}
        self._publish(Event("question", dict(question)))
        if self._unattended is not None:
            choice = self._unattended if self._unattended in choices else default
            self._publish(Event("answered", {"id": qid, "choice": choice, "auto": True}))
            return choice
        entry = {"question": question, "event": threading.Event(), "choice": None}
        with self._lock:
            self._pending[qid] = entry
            if self._state is RunState.RUNNING:
                self._set_state(RunState.WAITING)
        try:
            while not entry["event"].wait(0.05):
                if self._stop.is_set():
                    raise Stopped()
        finally:
            with self._lock:
                self._pending.pop(qid, None)
                if self._state is RunState.WAITING and not self._pending:
                    self._set_state(RunState.RUNNING)
        self._publish(Event("answered", {"id": qid, "choice": entry["choice"], "auto": False}))
        return entry["choice"]

    def _main(self) -> None:
        ctx = MeasurementContext(self.bindings, self._emit, self._stop, self._resume, ask=self._ask)
        outcome = RunState.FINISHED
        try:
            ctx.checkpoint()
            self.measurement.setup(ctx)
            self.measurement.run(ctx)
            if self._stop.is_set():
                outcome = RunState.STOPPED
        except (Stopped, Aborted):  # Aborted: a stop interrupted an instrument call
            outcome = RunState.STOPPED
        except Exception as exc:
            outcome = RunState.FAILED
            self._fail("run", exc)
        finally:
            ctx._tearing_down = True
            try:
                self.measurement.teardown(ctx)
            except Exception as exc:
                outcome = RunState.FAILED
                self._fail("teardown", exc)
        with self._lock:
            self._set_state(outcome)
