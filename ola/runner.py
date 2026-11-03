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
    ):
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
        self._point_index = 0
        self._t0 = 0.0
        self._derived_warned = False

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

    def stop(self) -> None:
        """Ask the run to stop; it ends as STOPPED after ``teardown`` (also wakes a paused run)."""
        with self._lock:
            if self._state in (RunState.RUNNING, RunState.PAUSED):
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
            values = data["values"]
            extra = self._derived(values)
            data = {
                "index": self._point_index,
                "elapsed_s": time.monotonic() - self._t0,
                "values": {**values, **extra},
            }
            self._point_index += 1
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

    def _main(self) -> None:
        ctx = MeasurementContext(self.bindings, self._emit, self._stop, self._resume)
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
