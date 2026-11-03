"""Instrument: runs plans on one instrument.

A *plan* (produced by the call planner, no I/O there) is a list of steps for `scpi`
instruments, or a driver function + arguments for `driver` instruments (Analog Discovery...).
This module only executes; it knows nothing about maps, enums or vendors.

Rules (PLAN.md 7.1, 7.2):

* **One lock per instrument, held for the whole call** - all the steps of one call (e.g.
  channel select + set value) run without another thread's calls in between, delays included.
  Other instruments are independent objects with their own lock.
* Steps run in order and stop at the first failure -> ``StepFailedError`` (CALL-004) with the
  step index; the original ``TRN-xxx`` exception is kept as ``cause``.
* After a failed or aborted call the next call first discards pending input, so a late answer
  can never be read as the answer of the next command.
* ``run`` returns the list of raw results, one per step (``None`` for write/delay); a driver
  plan returns a one-element list. Interpretation of the results belongs to the planner.
"""

from __future__ import annotations

import threading
import time
from typing import Any, List, Optional, Protocol, Sequence

from .call_errors import CallNotSupportedError, StepFailedError
from .steps import Step


class Aborted(Exception):
    """The call was cancelled through its ``cancel`` event (not an instrument error)."""


class Driver(Protocol):
    """What a driver module must provide (Analog Discovery 2/3, ...)."""

    def call(self, function: str, args: dict) -> Any:
        """Run driver function ``function`` with ``args`` and return its result."""


def _attr(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class Instrument:
    """One instrument: its transport (or driver) and the lock that serialises calls. Use ``run`` to
    execute a plan."""

    def __init__(self, name: str, transport=None, driver: Optional[Driver] = None):
        self.name = name
        self.transport = transport
        self.driver = driver
        self._lock = threading.RLock()
        self._stale = False  # a previous call failed: discard pending input first

    # ----- public ---------------------------------------------------------------------
    def run(self, plan, cancel: Optional[threading.Event] = None) -> List[Any]:
        """Execute a plan (object or dict with ``call``, ``access`` and ``steps``/``driver``)."""
        call = _attr(plan, "call", "?")
        access = _attr(plan, "access", "scpi")
        if access == "driver":
            return self._run_driver(call, _attr(plan, "driver"), cancel)
        if access != "scpi":
            raise ValueError(f"unknown plan access {access!r}")
        return self.execute_steps(call, _attr(plan, "steps") or [], cancel)

    def execute_steps(
        self, call: str, steps: Sequence, cancel: Optional[threading.Event] = None
    ) -> List[Any]:
        """Run ``steps`` of call ``call`` under the instrument lock; return the raw result of each
        step (``None`` for write/delay). Raises ``StepFailedError`` (CALL-004) at the first
        failure and ``Aborted`` if ``cancel`` is set."""
        steps = [Step.coerce(s) for s in steps]  # ValueError here = bad plan, not CALL-004
        if self.transport is None:
            raise CallNotSupportedError(f"instrument '{self.name}' has no transport", call=call)
        results: List[Any] = []
        with self._lock:
            self._recover(call)
            for index, step in enumerate(steps):
                try:
                    if cancel is not None and cancel.is_set():
                        raise Aborted(f"call '{call}' aborted before step {index}")
                    results.append(self._execute(step, cancel))
                except Aborted:
                    self._stale = True
                    raise
                except Exception as exc:
                    self._stale = True
                    raise StepFailedError(call, index, exc) from exc
        return results

    # ----- internals --------------------------------------------------------------------
    def _recover(self, call: str) -> None:
        if not self._stale:
            return
        try:
            self.transport.flush_input()
        except Exception as exc:
            raise StepFailedError(call, 0, exc) from exc
        self._stale = False

    def _execute(self, step: Step, cancel) -> Any:
        if step.op == "delay":
            seconds = step.ms / 1000.0
            if cancel is None:
                time.sleep(seconds)
            elif cancel.wait(seconds):
                raise Aborted("aborted during delay")
            return None
        if step.op == "write":
            self.transport.send(step.text)
            return None
        if step.op == "query":
            self.transport.send(step.text)
        # query and read: collect the answer
        if step.returns == "binary":
            return self.transport.read_block(step.timeout_ms)
        line = self.transport.read_line(step.timeout_ms)
        if step.returns == "string":
            return line
        if step.returns == "float":
            return float(line)
        value = float(line)  # "int": accept "1", "+1", "1.0" but not "1.5"
        if value != int(value):
            raise ValueError(f"expected an integer answer, got {line!r}")
        return int(value)

    def _run_driver(self, call: str, spec, cancel) -> List[Any]:
        if self.driver is None or not spec:
            raise CallNotSupportedError(
                f"instrument '{self.name}' has no driver for call '{call}'", call=call
            )
        function, args = _attr(spec, "function"), dict(_attr(spec, "args") or {})
        with self._lock:
            if cancel is not None and cancel.is_set():
                raise Aborted(f"call '{call}' aborted")
            try:
                return [self.driver.call(function, args)]
            except Exception as exc:
                raise StepFailedError(call, 0, exc) from exc
