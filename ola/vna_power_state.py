# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Is the calibration kept by a network analyzer still valid? (No Qt.)

A VNA that keeps its own calibration (Siglent, Rohde & Schwarz: no ``calibration_import``) loses it
when it is switched off. The software cannot see that, so it keeps, per apparatus, the state
**"calibrated in this power session"** and finds a power cut with a **presence probe**
(``ola.identity.probe_presence``) made at the start of a measurement and when the VNA panel
sweeps:

* a calibration made here (``mark_calibrated``) sets the state;
* the probe gets no answer: the instrument is off, the state is cleared;
* the probe answers after an earlier "no answer": the instrument was switched on again and the
  state **stays cleared** until the next calibration;
* nothing is known about an apparatus (the program just started): it counts as not calibrated.

A switch-off and switch-on between two probes is not seen (accepted). A measurement without a valid
calibration is **reported**, never blocked: the operator decides.

A **software calibration** (the LiteVNA, ``calibration_import``) follows the same rule: it is
forgotten when the program is closed or the VNA is switched off. Its record stays in the project
(it says when and how it was made), but it is put back only for an apparatus calibrated in this
run of the program that has not been off since (``allows_restore``).
"""

from __future__ import annotations

import threading
from typing import Any, Optional, Set

from .identity import probe_presence

MISSING = "missing"  # nothing says it was calibrated in this session
LOST = "lost"  # the instrument was off since it was calibrated
CALIBRATED = "calibrated"


def keeps_own_calibration(handle: Any) -> bool:
    """True for a VNA whose calibration lives in the instrument (it cannot import one)."""
    try:
        return not handle.supports("calibration_import")
    except Exception:  # a handle that cannot say
        return False


def key_of(handle: Any) -> str:
    """The apparatus: its serial number when the instrument gives one, else the name."""
    serial = getattr(getattr(handle, "identity", None), "serial_number", None)
    return f"sn:{serial}" if serial else f"name:{getattr(handle, 'name', '?')}"


class PowerState:
    """The state of the calibration of every apparatus in this run of the program."""

    def __init__(self) -> None:
        self._calibrated: Set[str] = set()
        self._off: Set[str] = set()  # seen without an answer since it was calibrated
        self._lock = threading.Lock()

    def mark_calibrated(self, handle: Any) -> None:
        """A calibration was just made on this VNA."""
        key = key_of(handle)
        with self._lock:
            self._calibrated.add(key)
            self._off.discard(key)

    def observe(self, handle: Any, answered: bool) -> None:
        """What the presence probe found: no answer clears the state."""
        key = key_of(handle)
        with self._lock:
            if not answered:
                self._calibrated.discard(key)
                self._off.add(key)

    def status(self, handle: Any) -> str:
        """``CALIBRATED``, ``LOST`` (it was off since) or ``MISSING`` (no calibration seen)."""
        key = key_of(handle)
        with self._lock:
            if key in self._calibrated:
                return CALIBRATED
            return LOST if key in self._off else MISSING

    def allows_restore(self, handle: Any) -> bool:
        """May the saved software calibration of this apparatus be put back? Only if it was made
        in this run of the program and the instrument was not switched off since: a calibration
        is forgotten when the program is closed or the VNA is switched off."""
        return self.status(handle) == CALIBRATED

    def check(self, handle: Any) -> Optional[str]:
        """Probe the VNA and say what is wrong with its calibration, or None when it is fine.

        An instrument that keeps its own calibration loses it when it is switched off. A software
        calibration (the LiteVNA) lives in the program: it is forgotten when the VNA does not
        answer (``forget_software_calibration``) and is never taken from a previous run of the
        program."""
        software = not keeps_own_calibration(handle)
        self.observe(handle, probe_presence(handle))
        state = self.status(handle)
        if state == LOST and software:
            forget_software_calibration(handle)
        if state == CALIBRATED:
            return None
        name = getattr(handle, "name", "the VNA")
        if state == LOST:
            return (
                f"{name} was switched off since it was calibrated: the calibration is lost. "
                "Calibrate it again before measuring; the data of this run are not calibrated."
            )
        if software:
            return (
                f"{name} was not calibrated in this session of the program: a calibration is "
                "forgotten when the program is closed or the VNA is switched off. Calibrate it "
                "before measuring; the data of this run are not calibrated."
            )
        return (
            f"{name} was not calibrated since the program started (an instrument that keeps its "
            "own calibration loses it when it is switched off). Calibrate it before measuring "
            "if it was off; the data of this run are not known to be calibrated."
        )


def forget_software_calibration(handle: Any) -> None:
    """Drop the software calibration applied to a connection (the driver's and the application's
    snapshot of it). Never raises: an instrument that has none has nothing to drop."""
    try:
        if handle.supports("calibration_clear"):
            handle.call("calibration_clear")
    except Exception:
        pass
    try:
        handle.set_calibration(None)
    except Exception:
        pass


POWER_STATE = PowerState()  # the one of the program
