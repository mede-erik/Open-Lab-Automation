"""Measurement core: what a measurement module implements and what the framework gives it.

A *measurement* (efficiency, Bode, ripple, time log...) is a class derived from
``Measurement``. It never opens windows, writes files or talks SCPI: it asks instruments for
logical calls through handles (``handle.call("set_voltage", value=5)``) and reports what it
measures through the ``MeasurementContext`` (points, traces, progress, log). The runner
(``ola/runner.py``) decides when and in which thread it runs, handles stop/pause and always
calls ``teardown`` so the instruments are left in a safe state.

Qt-free on purpose: usable by the GUI, by scripts and by tests.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence

API_VERSION = 1


class MeasurementError(Exception):
    """A measurement cannot start or cannot continue (bad parameters, missing instrument...)."""


class Stopped(Exception):
    """Raised by ``ctx.checkpoint()`` / ``ctx.sleep()`` when the user stopped the run.

    Not an error: the runner turns it into the STOPPED state. A module must not catch it
    (use ``teardown`` for cleanup)."""


@dataclass(frozen=True)
class Role:
    """What a measurement needs from the instruments of the project (not a specific model)."""

    name: str
    category: str  # e.g. "power_supply", "oscilloscope", "any"
    required: bool = True
    multiple: bool = False  # the role may be bound to several instruments
    description: str = ""


class InstrumentHandle(Protocol):
    """The only way a measurement touches an instrument.

    ``call`` takes a logical call name of the instrument library and its logical arguments
    and returns the logical result (``None`` for actions). The glue that implements it
    (library + call planner + step executor) lives outside this module."""

    name: str

    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call of the instrument library; return its logical result."""


@dataclass
class Event:
    """Everything a run reports. ``kind``: state | point | trace | progress | log | error."""

    kind: str
    data: Dict[str, Any]
    t: float = field(default_factory=time.time)  # wall-clock time


Emit = Callable[[str, Dict[str, Any]], None]


class MeasurementContext:
    """The measurement's window on the framework (created by the runner)."""

    def __init__(
        self,
        bindings: Mapping[str, Sequence[InstrumentHandle]],
        emit: Emit,
        stop_event: threading.Event,
        resume_event: threading.Event,
    ):
        self._bindings = {role: list(handles) for role, handles in bindings.items()}
        self._emit = emit
        self._stop = stop_event
        self._resume = resume_event
        self._tearing_down = False

    # ----- instruments ------------------------------------------------------------------
    def instruments(self, role: str) -> List[InstrumentHandle]:
        """All instruments bound to ``role`` (empty list for an unbound optional role)."""
        return list(self._bindings.get(role, []))

    def instrument(self, role: str) -> InstrumentHandle:
        """The single instrument bound to ``role``."""
        handles = self._bindings.get(role, [])
        if len(handles) != 1:
            raise MeasurementError(
                f"role '{role}' needs exactly one instrument, {len(handles)} bound"
            )
        return handles[0]

    # ----- results ----------------------------------------------------------------------
    def emit_point(self, values: Mapping[str, Any]) -> None:
        """One row of scalar results (e.g. ``{"vin": 12.0, "vout": 5.01, "iout": 0.5}``)."""
        self._emit("point", {"values": dict(values)})

    def emit_trace(
        self,
        name: str,
        x: Sequence[float],
        y: Sequence[Any],
        kind: str = "real",
        **meta: Any,
    ) -> None:
        """A waveform / spectrum / frequency response. ``kind="complex"`` takes complex ``y``."""
        x, y = list(x), list(y)
        if len(x) != len(y):
            raise MeasurementError(f"trace '{name}': x has {len(x)} points, y has {len(y)}")
        if kind == "complex":
            y = [[complex(v).real, complex(v).imag] for v in y]
        elif kind != "real":
            raise MeasurementError(f"trace '{name}': kind must be 'real' or 'complex'")
        self._emit("trace", {"name": name, "trace_kind": kind, "x": x, "y": y, "meta": dict(meta)})

    def progress(self, done: float, total: Optional[float] = None, message: str = "") -> None:
        """Report how far the run is: ``done`` of ``total`` (for example points measured)."""
        self._emit("progress", {"done": done, "total": total, "message": message})

    def log(self, message: str, level: str = "info") -> None:
        """Add a message to the run log (``level``: info, warning or error)."""
        self._emit("log", {"level": level, "message": message})

    # ----- control ----------------------------------------------------------------------
    @property
    def stop_requested(self) -> bool:
        """True once the user asked to stop (``checkpoint()`` raises ``Stopped`` for you)."""
        return self._stop.is_set()

    @property
    def cancel_event(self) -> threading.Event:
        """Set when the user stops the run. The instrument handles are built with this event
        (``InstrumentHandle(..., cancel=ctx.cancel_event)``) so a stop also interrupts a long
        delay or wait inside an instrument call."""
        return self._stop

    def checkpoint(self) -> None:
        """Call regularly: raises ``Stopped`` if the user stopped the run and blocks while the
        run is paused. No-op during teardown."""
        if self._tearing_down:
            return
        while True:
            if self._stop.is_set():
                raise Stopped()
            if self._resume.wait(timeout=0.05):
                return

    def sleep(self, seconds: float) -> None:
        """Interruptible sleep (stop is honoured within ~50 ms; pause after the sleep)."""
        if not (isinstance(seconds, (int, float)) and math.isfinite(seconds)):
            raise MeasurementError(f"sleep needs a finite number of seconds, got {seconds!r}")
        if self._tearing_down:
            time.sleep(max(0.0, seconds))
            return
        end = time.monotonic() + max(0.0, seconds)
        while True:
            self.checkpoint()
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            if self._stop.wait(min(remaining, 0.05)):
                raise Stopped()


class Measurement:
    """Base class of every measurement module.

    The runner calls ``validate`` (before starting), then ``setup``, ``run`` and, always,
    ``teardown``. ``params`` is the content of the measurement file."""

    roles: Sequence[Role] = ()
    info: Any = None  # ModuleInfo, set by the registry

    def __init__(self, params: Mapping[str, Any]):
        self.params: Dict[str, Any] = dict(params)

    def validate(self) -> List[str]:
        """Parameter problems as human-readable strings (empty list = OK). No I/O."""
        return []

    def setup(self, ctx: MeasurementContext) -> None:
        """Bring the instruments to the initial state."""

    def run(self, ctx: MeasurementContext) -> None:
        """Do the measurement: reach the instruments and report results through ``ctx``. Call
        ``ctx.checkpoint()`` or ``ctx.sleep()`` regularly so stop and pause work."""
        raise NotImplementedError

    def teardown(self, ctx: MeasurementContext) -> None:
        """ALWAYS called, also after errors and stops: leave the instruments in a safe state
        (outputs off...). ``ctx.checkpoint()`` does not raise here."""

    def derived(self, values: Mapping[str, Any]) -> Dict[str, Any]:
        """Quantities computed from one point (e.g. efficiency); merged into the point."""
        return {}
