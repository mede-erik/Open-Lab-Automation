"""Helpers for the measurement-core tests."""

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ola.measurement import Measurement, MeasurementContext
from ola.runner import FINAL_STATES, Runner


class FakeHandle:
    """InstrumentHandle that records its calls and answers from a dict / function."""

    def __init__(
        self, name: str, answers: Optional[Dict[str, Any]] = None, fail_on: Optional[str] = None
    ):
        self.name = name
        self.answers = answers or {}
        self.fail_on = fail_on
        self.calls: List[tuple] = []
        self._lock = threading.Lock()

    def call(self, name: str, **args: Any) -> Any:
        with self._lock:
            self.calls.append((name, args))
        if name == self.fail_on:
            raise RuntimeError(f"{self.name}: {name} failed")
        answer = self.answers.get(name)
        return answer(**args) if callable(answer) else answer


class Scripted(Measurement):
    """A measurement whose behaviour is given by functions (for tests)."""

    def __init__(
        self,
        run: Callable[[MeasurementContext], None],
        params=None,
        setup=None,
        teardown=None,
        validate=None,
        derived=None,
        roles=(),
    ):
        super().__init__(params or {})
        self._run, self._setup, self._teardown = run, setup, teardown
        self._validate, self._derived = validate, derived
        self.roles = roles
        self.order: List[str] = []

    def validate(self):
        self.order.append("validate")
        return self._validate() if self._validate else []

    def setup(self, ctx):
        self.order.append("setup")
        if self._setup:
            self._setup(ctx)

    def run(self, ctx):
        self.order.append("run")
        self._run(ctx)

    def teardown(self, ctx):
        self.order.append("teardown")
        if self._teardown:
            self._teardown(ctx)

    def derived(self, values):
        return self._derived(values) if self._derived else {}


def run_to_end(runner: Runner, timeout: float = 5.0) -> Runner:
    runner.start()
    assert runner.join(timeout), "run did not finish"
    assert runner.state in FINAL_STATES
    return runner


def wait_for(predicate, timeout: float = 2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return False
