"""The handle a measurement uses to talk to an instrument.

A measurement only knows ``handle.call(name, **args)`` and ``handle.name``: the logical call
name and logical arguments are the same for every brand. The handle plans the call for the
model of the instrument (``ola.call_planner``), has it executed (``ola.instrument``) and gives
back the logical value.

Errors are the CALL-xxx exceptions of ``ola.call_errors``.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from .call_planner import plan_call
from .instrument import Instrument
from .library import Library


class InstrumentHandle:
    """One instrument of a measurement, e.g. ``handle.call("set_voltage", value=5)``."""

    def __init__(
        self,
        name: str,
        library: Library,
        model_id: str,
        instrument: Instrument,
        cancel: Optional[threading.Event] = None,
    ):
        self.name = name
        self.model_id = model_id
        self._library = library
        self._instrument = instrument
        self._cancel = cancel

    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call and return its logical result (None for calls without result)."""
        plan = plan_call(self._library, self.model_id, name, args)
        return plan.interpret(self._instrument.run(plan, cancel=self._cancel))

    def readback(self, name: str, **args: Any) -> Any:
        """Read back the value of a ``set`` call (for example the voltage setpoint)."""
        plan = plan_call(self._library, self.model_id, name, args, readback=True)
        return plan.interpret(self._instrument.run(plan, cancel=self._cancel))

    def supports(self, name: str) -> bool:
        """True if the model defines the call (the call may still reject some values)."""
        commands = self._library.commands(self.model_id)
        return bool(commands) and name in commands

    def __repr__(self) -> str:
        return f"InstrumentHandle({self.name!r}, {self.model_id!r})"
