# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Waveforms taken during a converter measurement (no Qt).

The efficiency measurements (``.eff``, ``.rfe``) can take the waveforms of one or more
oscilloscopes during the sweep (``scope_capture`` in the parameters)::

    "scope_capture": {"instruments": ["osc1", "osc2"], "every": 2,
                      "when": [{"name": "efficiency", "below": 85}], "max": 20,
                      "channels": [1, 2], "bits": 8, "wait_s": 2.0}        # the last ones optional

**When** (after the readings of a step, so at steady state): ``every`` (every *N* steps, the first
one included) and/or ``when``, a list of conditions ``{"name", "above", "below"}`` on a quantity of
the step (a parameter, a reading ``vout@daq`` or a ``derived`` one): the waveforms are also taken
at a step where **any** of them holds, so that an anomaly is caught without filling the disk with
the steps that are fine. ``max`` is the most steps that are captured (a condition that always holds
must not fill the disk). The reason of each capture (``every`` or the condition and its value) is
in the row of the run file.

**Which oscilloscopes**: the ones bound to the role ``scope`` (``instruments``; several when the
circuit is probed at points that one oscilloscope has no channels for). **Which settings**: the
scope settings files of the project that are switched on (``Project.scope_settings``: a long view,
a rising edge, a falling edge...), made **one after another, in the order of the list**; a file that
names an oscilloscope applies to it only, one that names none applies to all. For each file and
each oscilloscope it applies to the oscilloscope is set as the file says (``ola.was_calls``), all of
them are armed, the trigger of each is waited for and the whole memory of every channel the file
enables (or ``channels``) is read, the channels of one capture together so that they share one
trigger and one time base. Each capture is a binary file in the folder of the run
(``ola.wavefiles``) and the run file gets one row of the table ``waves``. The project writes the
files in ``acquisitions`` when the run starts.

A failure of one oscilloscope at a step is a warning in the log: the measurement goes on, and the
other oscilloscopes, acquisitions and steps are still captured. If the model can tell the trigger
status the program waits for the trigger up to ``wait_s`` and, if it did not arrive, forces it (and
says so in the capture: ``forced``); otherwise it waits ``wait_s`` and reads.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

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
    return list(channel_names(settings))


def channel_names(settings: Dict[str, Any]) -> Dict[int, str]:
    """The channels a ``.was`` file switches on, ``{number: name of the signal}`` in order (the
    name is what the channel measures, ``VGS_Q1``; empty if the file does not say)."""
    channels = settings.get("channels", [])
    items = channels.items() if isinstance(channels, dict) else enumerate(channels)
    found: Dict[int, str] = {}
    for key, ch in items:
        if not isinstance(ch, dict) or ch.get("enabled") is not True:
            continue
        ref = ch.get("channel_id", key)
        number = extract_channel_number(ref) if isinstance(ref, str) else ref
        if isinstance(number, int) and number not in found:
            found[number] = str(ch.get("name") or "")
    return found


def capture_steps(steps: int, every: int) -> int:
    """How many of ``steps`` steps are captured when it is done every ``every`` steps (the first
    one included)."""
    return 0 if steps <= 0 else math.ceil(steps / max(1, every))


def estimate(
    steps: int,
    every: Optional[int],
    acquisitions: Sequence[Dict[str, Any]],
    channels: Optional[Sequence[int]] = None,
    points: int = DEFAULT_POINTS,
    scopes: Sequence[str] = ("",),
    maximum: Optional[int] = None,
) -> Dict[str, int]:
    """What a run will write at most: ``captures`` (one per acquisition, oscilloscope and captured
    step), ``waveforms`` (one per channel) and ``bytes``, with ``points`` samples per waveform.
    Without ``every`` only the steps a condition picks are captured: the estimate then takes all of
    them, up to ``maximum``."""
    captured = capture_steps(steps, every) if every else steps
    if maximum is not None:
        captured = min(captured, int(maximum))
    captures = per_step = 0
    for a in acquisitions:
        target = a.get("scope", "")
        n = len([s for s in scopes if target in ("", s)]) or 1
        captures += n
        per_step += n * len(channels or enabled_channels(a.get("settings") or {}))
    return {
        "captures": captured * captures,
        "waveforms": captured * per_step,
        "bytes": captured * per_step * int(points) * SAMPLE_BYTES,
    }


def why_captured(
    index: int, every: Optional[int], when: Sequence[Mapping[str, Any]], env: Mapping[str, Any]
) -> str:
    """Why the step ``index`` is captured, as a short text (``every 2``, ``efficiency = 83.2 below
    85``), or '' if it is not."""
    if every and index % every == 0:
        return f"every {every}"
    for condition in when:
        value = env.get(condition["name"])
        if not isinstance(value, (int, float)) or isinstance(value, bool) or math.isnan(value):
            continue
        if "below" in condition and value < condition["below"]:
            return f"{condition['name']} = {value:.4g} below {condition['below']:g}"
        if "above" in condition and value > condition["above"]:
            return f"{condition['name']} = {value:.4g} above {condition['above']:g}"
    return ""


class _Scope:
    """One oscilloscope of the capture: its handle and the calls its model does not have."""

    def __init__(self, handle: Any):
        self.handle = handle
        self.name = str(getattr(handle, "name", "scope"))
        self.refused: set = set()


class ScopeCapture:
    """The captures of one run: the oscilloscopes, the acquisitions, when, and where files go."""

    def __init__(
        self,
        handles: Sequence[Any],
        acquisitions: Sequence[Dict[str, Any]],
        run_path: Union[str, Path],
        every: Optional[int] = None,
        when: Optional[Sequence[Mapping[str, Any]]] = None,
        maximum: Optional[int] = None,
        channels: Optional[Sequence[int]] = None,
        bits: int = 8,
        wait_s: float = DEFAULT_WAIT_S,
    ):
        self.scopes = [_Scope(h) for h in handles]
        self.acquisitions = list(acquisitions)
        self.every = int(every) if every else None
        self.when = list(when or [])
        self.maximum = int(maximum) if maximum else None
        self.run_path = Path(run_path)
        self.folder = wave_folder(self.run_path)
        self.channels = list(channels) if channels else None
        self.bits = int(bits)
        self.wait_s = float(wait_s)
        self.steps_captured = 0

    @staticmethod
    def from_params(
        params: Dict[str, Any], handles: Sequence[Any], run_path: Optional[Union[str, Path]]
    ) -> Optional["ScopeCapture"]:
        """The capture of the parameters of a measurement, or None if they do not ask for one.
        ``MeasurementError`` if they do and something is missing (no oscilloscope bound, no scope
        settings file that is on for one of them, no run file to put the waveforms next to)."""
        raw = params.get("scope_capture")
        if not raw or not (raw.get("every") or raw.get("when")):
            return None
        wanted = raw.get("instruments") or []
        bound = {str(getattr(h, "name", "")): h for h in handles}
        chosen = [bound[n] for n in wanted if n in bound]
        if not chosen or len(chosen) != len(wanted):
            missing = [n for n in wanted if n not in bound]
            raise MeasurementError(
                "waveforms are asked for, so the measurement needs its oscilloscope"
                + (f" ({', '.join(missing)} not bound to the role 'scope')" if missing else "")
            )
        acquisitions = raw.get("acquisitions") or []
        if not acquisitions:
            raise MeasurementError(
                "waveforms are asked for, but the project has no scope settings file that is on"
            )
        for handle in chosen:
            name = str(getattr(handle, "name", ""))
            if not any(a.get("scope", "") in ("", name) for a in acquisitions):
                raise MeasurementError(
                    f"the oscilloscope {name} has no scope settings file that is on for it"
                )
        if run_path is None:
            raise MeasurementError(
                "waveforms go in a folder next to the run file: the measurement has none"
            )
        return ScopeCapture(
            chosen, acquisitions, run_path, raw.get("every"), raw.get("when"), raw.get("max"),
            raw.get("channels"), raw.get("bits", 8), raw.get("wait_s", DEFAULT_WAIT_S),
        )  # fmt: skip

    def due(self, index: int, env: Optional[Mapping[str, Any]] = None) -> str:
        """Why the step ``index`` is captured (``every 2``, ``efficiency = 83 below 85``), or ''
        if it is not (also when ``max`` steps were already captured). ``env`` has the values of
        the step, for the conditions of ``when``."""
        if self.maximum is not None and self.steps_captured >= self.maximum:
            return ""
        return why_captured(index, self.every, self.when, env or {})

    def capture(
        self, ctx: Any, index: int, setpoints: Dict[str, Any], why: str = ""
    ) -> List[Dict[str, Any]]:
        """The captures of the step ``index``: for each acquisition, in order, one per
        oscilloscope it applies to; the rows that went to the table ``waves``. Nothing is raised
        for a failure of an oscilloscope."""
        self.steps_captured += 1
        rows: List[Dict[str, Any]] = []
        for acquisition in self.acquisitions:
            ctx.checkpoint()
            target = acquisition.get("scope", "")
            scopes = [s for s in self.scopes if target in ("", s.name)]
            rows += self._acquire(ctx, index, acquisition, scopes, setpoints, why)
        return rows

    # ----- one acquisition, on one or more oscilloscopes ------------------------------------
    def _acquire(self, ctx, index, acquisition, scopes, setpoints, why) -> List[Dict[str, Any]]:
        name = str(acquisition["name"])
        settings = acquisition["settings"]
        numbers = self.channels or enabled_channels(settings)
        if not numbers:
            ctx.log(f"step {index}, '{name}': the settings file switches no channel on", "warning")
            return []
        ready: List[_Scope] = []
        for scope in scopes:  # every oscilloscope is set and armed before the first is waited for
            try:
                for call, args in oscilloscope_calls_from_was(settings):
                    self._call(ctx, scope, call, **args)
                self._arm(scope)
                ready.append(scope)
            except Stopped:
                raise
            except Exception as exc:
                ctx.log(f"waveform of step {index}, '{name}', {scope.name}: {exc}", "warning")
        rows: List[Dict[str, Any]] = []
        for scope in ready:
            try:
                forced = self._wait_trigger(ctx, scope, index, name)
                rows.append(
                    self._read(ctx, index, acquisition, scope, numbers, forced, setpoints, why)
                )
            except Stopped:
                raise
            except Exception as exc:  # the oscilloscope failed: a warning, the run goes on
                ctx.log(f"waveform of step {index}, '{name}', {scope.name}: {exc}", "warning")
        return rows

    def _read(self, ctx, index, acquisition, scope, numbers, forced, setpoints, why):
        handle = scope.handle
        names = channel_names(acquisition["settings"])
        reads = {}
        for n in numbers:
            got = dict(handle.read_waveform_full(n, bits=self.bits))
            if names.get(n):
                got["signal"] = names[n]  # what the channel measures, to find a shared signal
            reads[f"CH{n}"] = got
        capture = capture_from_reads(
            index, str(acquisition["name"]), scope.name, reads, forced, setpoints,
            {"file": acquisition.get("file", "")},
        )  # fmt: skip
        path = save_capture(self.folder, capture)
        row = index_entry(capture, path, self.run_path)
        if why:
            row["why"] = why
        ctx.emit_point(row, "waves")
        if handle.supports("run_acquisition"):
            handle.call("run_acquisition")  # reading stopped it: the scope runs again
        return row

    def _call(self, ctx: Any, scope: _Scope, name: str, **args: Any) -> None:
        if not scope.handle.supports(name):
            if name not in scope.refused:  # a model without the call: said once, not at every step
                scope.refused.add(name)
                ctx.log(f"{scope.name} does not have '{name}': left out", "warning")
            return
        scope.handle.call(name, **args)

    def _arm(self, scope: _Scope) -> None:
        handle = scope.handle
        arm = "acquire_single" if handle.supports("acquire_single") else "run_acquisition"
        if handle.supports(arm):
            handle.call(arm)

    def _wait_trigger(self, ctx: Any, scope: _Scope, index: int, name: str) -> bool:
        """Wait for the trigger of one oscilloscope; True if it had to be forced."""
        handle = scope.handle
        if not handle.supports("query_trigger_status"):
            ctx.sleep(self.wait_s)  # the model cannot say whether the trigger arrived
            return False
        deadline = time.monotonic() + self.wait_s
        while True:  # the status is asked at least once, even with no time to wait
            status = str(handle.call("query_trigger_status")).upper()
            if any(word in status for word in TRIGGERED):
                return False
            if time.monotonic() >= deadline:
                break
            ctx.sleep(0.05)
        if handle.supports("force_trigger"):
            handle.call("force_trigger")
            ctx.log(
                f"step {index}, '{name}', {scope.name}: the trigger did not arrive, forced",
                "warning",
            )
            ctx.sleep(0.05)
            return True
        ctx.log(f"step {index}, '{name}', {scope.name}: the trigger did not arrive", "warning")
        return False


def default_run_folder(run_path: Union[str, Path]) -> str:
    """Where the waveform files of a run are (``<run>_waves``), as text."""
    return os.fspath(wave_folder(run_path))
