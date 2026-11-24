# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Waveforms taken during a converter measurement (no Qt).

The efficiency measurements (``.eff``, ``.rfe``) can take the waveform of an oscilloscope at every
step, or every *N* steps (``scope_capture`` in the parameters)::

    "scope_capture": {"instrument": "osc1", "every": 2,
                      "channels": [1, 2], "bits": 8, "wait_s": 2.0}      # the last three optional

The oscilloscope is the one bound to the role ``scope``. The **acquisitions** are the scope
settings files of the project that are switched on (``Project.scope_settings``: a long view, a
rising edge, a falling edge...): at a capture step they are made **one after another, in the order
of the list**. For each one the oscilloscope is set as the file says (``ola.was_calls``), the
acquisition is armed (a single one if the model has it), the trigger is waited for and the whole
memory of every channel the file enables (or ``channels``) is read, with the channels of that
capture taken together so that they share one trigger and one time base. Each capture is a binary
file of the folder of the run (``ola.wavefiles``) and the run file gets one row of the table
``waves`` with where it is. The project writes the files in ``acquisitions`` when the run starts.

A failure of the oscilloscope at a step is a warning in the log: the measurement goes on, and the
other acquisitions and steps are still captured. If the model can tell the trigger status the
program waits for the trigger up to ``wait_s`` and, if it did not arrive, forces it (and says so in
the capture: ``forced``); otherwise it waits ``wait_s`` and reads.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .measurement import MeasurementError, Stopped
from .wavefiles import (
    SAMPLE_BYTES,
    capture_from_reads,
    index_entry,
    save_capture,
    wave_folder,
)
from .was_calls import extract_channel_number, oscilloscope_calls_from_was

DEFAULT_WAIT_S = 2.0
DEFAULT_POINTS = 1_000_000  # assumed in the estimate, before the memory depth is known
WARN_BYTES = 1_000_000_000  # above this the program asks before a run starts
TRIGGERED = ("STOP", "TD", "TRIG", "DONE")  # what a trigger status says once the trigger arrived


def enabled_channels(settings: Dict[str, Any]) -> List[int]:
    """The numbers of the channels a ``.was`` file switches on, in order."""
    channels = settings.get("channels", [])
    items = channels.items() if isinstance(channels, dict) else enumerate(channels)
    found: List[int] = []
    for key, ch in items:
        if not isinstance(ch, dict) or ch.get("enabled") is not True:
            continue
        ref = ch.get("channel_id", key)
        number = extract_channel_number(ref) if isinstance(ref, str) else ref
        if isinstance(number, int) and number not in found:
            found.append(number)
    return found


def capture_steps(steps: int, every: int) -> int:
    """How many of ``steps`` steps are captured when it is done every ``every`` steps (the first
    one included)."""
    return 0 if steps <= 0 else math.ceil(steps / max(1, every))


def estimate(
    steps: int,
    every: int,
    acquisitions: Sequence[Dict[str, Any]],
    channels: Optional[Sequence[int]] = None,
    points: int = DEFAULT_POINTS,
) -> Dict[str, int]:
    """What a run will write: ``captures`` (one per acquisition and captured step), ``waveforms``
    (one per channel) and ``bytes``, with ``points`` samples per waveform."""
    captured = capture_steps(steps, every)
    per_step = sum(len(channels or enabled_channels(a.get("settings") or {})) for a in acquisitions)
    return {
        "captures": captured * len(acquisitions),
        "waveforms": captured * per_step,
        "bytes": captured * per_step * int(points) * SAMPLE_BYTES,
    }


class ScopeCapture:
    """The captures of one run: the oscilloscope, the acquisitions, and where the files go."""

    def __init__(
        self,
        handle: Any,
        acquisitions: Sequence[Dict[str, Any]],
        every: int,
        run_path: Union[str, Path],
        channels: Optional[Sequence[int]] = None,
        bits: int = 8,
        wait_s: float = DEFAULT_WAIT_S,
    ):
        self.handle = handle
        self.acquisitions = list(acquisitions)
        self.every = max(1, int(every))
        self.run_path = Path(run_path)
        self.folder = wave_folder(self.run_path)
        self.channels = list(channels) if channels else None
        self.bits = int(bits)
        self.wait_s = float(wait_s)
        self._refused: set = set()  # calls this model does not have: said once

    @staticmethod
    def from_params(
        params: Dict[str, Any], handles: Sequence[Any], run_path: Optional[Union[str, Path]]
    ) -> Optional["ScopeCapture"]:
        """The capture of the parameters of a measurement, or None if they do not ask for one.
        ``MeasurementError`` if they do and something is missing (no oscilloscope bound, no scope
        settings file that is on, no run file to put the waveforms next to)."""
        raw = params.get("scope_capture")
        if not raw or not raw.get("every"):
            return None
        if len(handles) != 1:
            raise MeasurementError(
                "waveforms are asked for, so the measurement needs one oscilloscope "
                f"(role 'scope'), {len(handles)} bound"
            )
        acquisitions = raw.get("acquisitions") or []
        if not acquisitions:
            raise MeasurementError(
                "waveforms are asked for, but the project has no scope settings file that is on"
            )
        if run_path is None:
            raise MeasurementError(
                "waveforms go in a folder next to the run file: the measurement has none"
            )
        return ScopeCapture(
            handles[0], acquisitions, raw["every"], run_path, raw.get("channels"),
            raw.get("bits", 8), raw.get("wait_s", DEFAULT_WAIT_S),
        )  # fmt: skip

    def due(self, index: int) -> bool:
        """True if the step ``index`` (from 0) is one that is captured."""
        return index % self.every == 0

    def capture(self, ctx: Any, index: int, setpoints: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The captures of the step ``index``, one per acquisition, in order; the rows that went
        to the table ``waves``. Nothing is raised for a failure of the oscilloscope."""
        rows: List[Dict[str, Any]] = []
        for acquisition in self.acquisitions:
            ctx.checkpoint()
            name = str(acquisition["name"])
            try:
                rows.append(self._one(ctx, index, acquisition, setpoints))
            except Stopped:
                raise
            except Exception as exc:  # the oscilloscope failed: a warning, the run goes on
                ctx.log(f"waveform of step {index}, '{name}': {exc}", "warning")
        return rows

    # ----- one acquisition ------------------------------------------------------------------
    def _one(self, ctx: Any, index: int, acquisition: Dict[str, Any], setpoints: Dict[str, Any]):
        settings = acquisition["settings"]
        name = str(acquisition["name"])
        channels = self.channels or enabled_channels(settings)
        if not channels:
            raise MeasurementError("the settings file switches no channel on")
        for call, args in oscilloscope_calls_from_was(settings):
            self._call(ctx, call, **args)
        forced = self._arm_and_wait(ctx, index, name)
        reads = {f"CH{n}": self.handle.read_waveform_full(n, bits=self.bits) for n in channels}
        capture = capture_from_reads(
            index, name, getattr(self.handle, "name", "scope"), reads, forced, setpoints,
            {"file": acquisition.get("file", "")},
        )  # fmt: skip
        path = save_capture(self.folder, capture)
        row = index_entry(capture, path, self.run_path)
        ctx.emit_point(row, "waves")
        if self.handle.supports("run_acquisition"):
            self.handle.call("run_acquisition")  # reading stopped it: the scope runs again
        return row

    def _call(self, ctx: Any, name: str, **args: Any) -> None:
        if not self.handle.supports(name):
            if name not in self._refused:  # a model without the call: said once, not at every step
                self._refused.add(name)
                ctx.log(f"the oscilloscope does not have '{name}': left out", "warning")
            return
        self.handle.call(name, **args)

    def _arm_and_wait(self, ctx: Any, index: int, name: str) -> bool:
        """Arm the acquisition and wait for the trigger; True if it had to be forced."""
        arm = "acquire_single" if self.handle.supports("acquire_single") else "run_acquisition"
        if self.handle.supports(arm):
            self.handle.call(arm)
        if not self.handle.supports("query_trigger_status"):
            ctx.sleep(self.wait_s)  # the model cannot say whether the trigger arrived
            return False
        deadline = time.monotonic() + self.wait_s
        while True:  # the status is asked at least once, even with no time to wait
            status = str(self.handle.call("query_trigger_status")).upper()
            if any(word in status for word in TRIGGERED):
                return False
            if time.monotonic() >= deadline:
                break
            ctx.sleep(0.05)
        if self.handle.supports("force_trigger"):
            self.handle.call("force_trigger")
            ctx.log(f"step {index}, '{name}': the trigger did not arrive, forced", "warning")
            ctx.sleep(0.05)
            return True
        ctx.log(f"step {index}, '{name}': the trigger did not arrive", "warning")
        return False


def default_run_folder(run_path: Union[str, Path]) -> str:
    """Where the waveform files of a run are (``<run>_waves``), as text."""
    return os.fspath(wave_folder(run_path))
