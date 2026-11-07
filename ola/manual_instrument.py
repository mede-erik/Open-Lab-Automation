# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Manual instruments: instruments without remote control, operated by the person at the bench.

A manual instrument is a **generic** instrument defined in the project (``.inst`` entry with
``is_manual: true``): a type, a name and the limits of its single channel. It is not a model of
the instrument library. A bench supply with two outputs is two manual instruments.

The handle has the interface of ``InstrumentHandle`` (``call``, ``readback``, ``supports``,
``name``) so a measurement does not care. A call that changes the instrument (a setpoint, the
output on or off) is shown to the operator through a ``prompt`` function; the call returns when
the operator confirms, and raises ``CALL-006`` when they cancel. Values are checked against the
call schema and the limits of the instrument (``CALL-003``). Manual instruments cannot be read:
every query is ``CALL-001`` (reading values by hand is a possible future feature).

No Qt here: the application passes a ``prompt`` that shows a dialog, a test passes a stub.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .call_errors import (
    CallNotSupportedError,
    InvalidArgumentError,
    ManualActionCancelledError,
)
from .call_planner import _logical_value
from .compat import observe
from .library import Library

# manual instrument type of the .inst file -> category of the library schemas
CATEGORIES = {
    "power_supply": "power_supplies_series",
    "electronic_load": "electronic_loads_series",
}

# calls the operator can carry out by hand, and the limit that bounds each value
# (unit, name of the limit in the instrument, argument that carries the value)
OPERATOR_CALLS: Dict[str, Dict[str, Optional[tuple]]] = {
    "power_supply": {
        "set_voltage": ("V", "max_voltage", "value"),
        "set_current": ("A", "max_current", "value"),
        "output_on": None,
        "output_off": None,
    },
    "electronic_load": {
        "load_on": None,
        "load_off": None,
        "set_mode": None,
        "set_current_level": ("A", "max_current", "value"),
        "set_voltage_level": ("V", "max_voltage", "value"),
        "set_resistance_level": ("ohm", None, "value"),
        "set_power_level": ("W", "max_power", "value"),
    },
}


@dataclass
class ManualRequest:
    """What the operator is asked to do. ``text`` is an English sentence; a user interface can
    translate it with the key ``manual_<call>_prompt`` and the fields of ``args``."""

    instrument: str
    call: str
    args: Dict[str, Any] = field(default_factory=dict)
    text: str = ""

    @property
    def key(self) -> str:
        """Translation key of the sentence."""
        return f"manual_{self.call}_prompt"


def _describe(name: str, call: str, args: Dict[str, Any], unit: Optional[str]) -> str:
    if call in ("output_on", "load_on"):
        return f"Switch ON '{name}'"
    if call in ("output_off", "load_off"):
        return f"Switch OFF '{name}'"
    if call == "set_mode":
        return f"Set the mode of '{name}' to {args.get('mode')}"
    what = {
        "set_voltage": "",
        "set_current": "",
        "set_current_level": "to a constant current of ",
        "set_voltage_level": "to a constant voltage of ",
        "set_resistance_level": "to a constant resistance of ",
        "set_power_level": "to a constant power of ",
    }.get(call, "")
    return f"Set '{name}' {what}{args.get('value')} {unit or ''}".replace("  ", " ").strip()


class ManualInstrumentHandle:
    """A manual instrument, seen by a measurement like any other instrument handle."""

    is_manual = True

    def __init__(
        self,
        name: str,
        library: Library,
        instrument_type: str,
        limits: Optional[Dict[str, Any]] = None,
        prompt: Optional[Callable[[ManualRequest], bool]] = None,
        cancel: Optional[threading.Event] = None,
    ):
        if instrument_type not in CATEGORIES:
            raise CallNotSupportedError(
                f"manual instruments of type {instrument_type!r} are not available "
                f"(only {sorted(CATEGORIES)})"
            )
        self.name = name
        self.instrument_type = instrument_type
        self.limits = dict(limits or {})
        self._schema = library.schema(CATEGORIES[instrument_type]) or {"calls": {}, "types": {}}
        self._prompt = prompt
        self._cancel = cancel
        self.observed: Dict[str, float] = {}  # the largest value the operator was asked to set

    def supports(self, name: str) -> bool:
        """True for the calls the operator can carry out by hand."""
        return name in OPERATOR_CALLS[self.instrument_type]

    def call(self, name: str, **args: Any) -> None:
        """Ask the operator to carry out the call; returns when they confirm."""
        if not self.supports(name):
            raise CallNotSupportedError(
                f"call '{name}' is not available on the manual instrument {self.name!r}", call=name
            )
        spec = self._schema["calls"].get(name, {})
        types = self._schema.get("types", {})
        checked: Dict[str, Any] = {}
        for arg_name, arg_spec in spec.get("args", {}).items():
            if arg_name in args and args[arg_name] is not None:
                checked[arg_name] = _logical_value(arg_name, arg_spec, args[arg_name], types, name)
            elif arg_spec.get("required", True):
                raise InvalidArgumentError(
                    f"call '{name}' needs the argument '{arg_name}'", call=name
                )
        bound = OPERATOR_CALLS[self.instrument_type][name]
        unit = None
        if bound:
            unit, limit_name, arg_name = bound
            limit = self.limits.get(limit_name) if limit_name else None
            if limit and checked[arg_name] > float(limit):
                raise InvalidArgumentError(
                    f"{checked[arg_name]} {unit} exceeds the maximum {limit} {unit} of "
                    f"{self.name!r} (call '{name}')",
                    call=name,
                )
        visible = {k: v for k, v in checked.items() if k != "channel_number"}
        request = ManualRequest(self.name, name, visible, _describe(self.name, name, visible, unit))
        self._ask(request)
        observe(self.observed, name, checked, None)  # confirmed: it was set

    def readback(self, name: str, **args: Any) -> Any:
        """Manual instruments cannot be read back."""
        raise CallNotSupportedError(
            f"manual instrument {self.name!r} cannot be read back (call '{name}')", call=name
        )

    def _ask(self, request: ManualRequest) -> None:
        if self._cancel is not None and self._cancel.is_set():
            raise ManualActionCancelledError("the measurement was cancelled", call=request.call)
        if self._prompt is None or not self._prompt(request):
            raise ManualActionCancelledError(
                f"the operator cancelled: {request.text}", call=request.call
            )

    def __repr__(self) -> str:
        return f"ManualInstrumentHandle({self.name!r}, {self.instrument_type!r})"


def manual_handle_from_inst(
    inst: Dict[str, Any],
    library: Library,
    prompt: Optional[Callable[[ManualRequest], bool]] = None,
    cancel: Optional[threading.Event] = None,
) -> ManualInstrumentHandle:
    """Build the handle of a manual ``.inst`` entry (its first channel gives the limits)."""
    channels = inst.get("channels") or [{}]
    channel = channels[0]
    limits = {k: channel.get(k) for k in ("max_voltage", "max_current", "max_power")}
    kind = str(inst.get("instrument_type", "")).strip().lower()
    kind = {"power_supplies": "power_supply", "electronic_loads": "electronic_load"}.get(kind, kind)
    return ManualInstrumentHandle(
        inst.get("instance_name", "manual instrument"), library, kind, limits, prompt, cancel
    )
