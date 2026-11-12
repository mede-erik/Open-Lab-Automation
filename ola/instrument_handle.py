# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The handle a measurement uses to talk to an instrument.

A measurement only knows ``handle.call(name, **args)`` and ``handle.name``: the logical call
name and logical arguments are the same for every brand. The handle plans the call for the
model of the instrument (``ola.call_planner``), has it executed (``ola.instrument``) and gives
back the logical value.

Errors are the CALL-xxx exceptions of ``ola.call_errors``.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from . import bench
from .call_planner import plan_call
from .compat import note_use, observe
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
        # the largest value of each quantity set or read through this handle (one run)
        self.observed: Dict[str, float] = {}
        # what a VNA was asked that not every VNA can do (S-parameters read, source power set)
        self.used: Dict[str, Any] = {}

    @property
    def library(self) -> Library:
        """The instrument library the calls are planned with."""
        return self._library

    @property
    def identity(self) -> Any:
        """Who the apparatus is (``ola.identity.Identity``), or None if it was not read."""
        return getattr(self._instrument, "identity", None)

    @property
    def calibration(self) -> Optional[dict]:
        """The calibration the application applied to this connection (file, kind, date, sweep,
        serial number), or None."""
        return getattr(self._instrument, "calibration", None)

    def set_calibration(self, info: Optional[dict]) -> None:
        """Remember which calibration was applied (None: none)."""
        self._instrument.calibration = dict(info) if info else None

    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call and return its logical result (None for calls without result)."""
        with bench.call_frame(self.name, name) as frame:
            with frame.part("plan"):
                plan = plan_call(self._library, self.model_id, name, args)
            raw = self._instrument.run(plan, cancel=self._cancel)
            with frame.part("interp"):
                result = plan.interpret(raw)
        try:
            observe(self.observed, name, args, result)
            note_use(self.used, name, args)
        except Exception:  # remembering what was asked must never break a measurement
            pass
        if name in ("calibration_begin", "calibration_clear"):
            self._instrument.calibration = None  # a new or removed calibration: the old one is gone
        return result

    def readback(self, name: str, **args: Any) -> Any:
        """Read back the value of a ``set`` call (for example the voltage setpoint)."""
        with bench.call_frame(self.name, f"{name} (readback)") as frame:
            with frame.part("plan"):
                plan = plan_call(self._library, self.model_id, name, args, readback=True)
            raw = self._instrument.run(plan, cancel=self._cancel)
            with frame.part("interp"):
                return plan.interpret(raw)

    def read_waveform_full(self, channel_number: int, bits: int = 8, stop: bool = True) -> Any:
        """The whole acquisition memory of a channel (blocks joined); see ``ola.waveform``."""
        from .waveform import read_waveform_full

        return read_waveform_full(self, channel_number, bits=bits, stop=stop)

    def supports(self, name: str) -> bool:
        """True if the model defines the call (the call may still reject some values)."""
        commands = self._library.commands(self.model_id)
        return bool(commands) and name in commands

    def __repr__(self) -> str:
        return f"InstrumentHandle({self.name!r}, {self.model_id!r})"
