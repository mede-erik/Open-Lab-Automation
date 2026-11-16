# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The readings an instrument has inside (no Qt): what a log or a panel can ask it for.

Every instrument of the library has calls that give a number (the voltage a supply is
delivering, the current of an electronic load, the value of a multimeter...). ``readable_calls``
lists them for a model, with the unit and what the call needs besides: a **channel** (a supply with
several outputs wants ``channel_number``; a load or a meter has none, and a multichannel load
selects the channel first with ``select_channel``) and any other required argument. The status
and calibration queries of the library are not readings and are left out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

READING_PREFIXES = ("read_", "measure_")
NUMERIC_RESULTS = ("float", "int")


@dataclass(frozen=True)
class Readable:
    """One reading a model can give."""

    name: str
    unit: str = ""
    channel: bool = False
    """The call takes ``channel_number``."""
    needs: List[str] = field(default_factory=list)
    """Other arguments it needs and has no default for (``channels`` of a datalogger...)."""


def call_arguments(library: Any, model_id: str, call: str) -> Dict[str, bool]:
    """The arguments the logical call takes, ``{name: required}`` (empty if the model or the
    call is not in the library)."""
    ref = library.find_model(model_id)
    schema = (library.schema(ref.category) or {}) if ref is not None else {}
    spec = (schema.get("calls") or {}).get(call) or {}
    out: Dict[str, bool] = {}
    for arg, detail in (spec.get("args") or {}).items():
        detail = detail or {}
        out[arg] = detail.get("required", True) is not False and "default" not in detail
    return out


def readable_calls(library: Any, model_id: str) -> List[Readable]:
    """The readings of this model (``read_...`` and ``measure_...`` calls that give a number),
    sorted by name; empty if the model is not in the library."""
    commands = library.commands(model_id) or {}
    ref = library.find_model(model_id)
    schema = (library.schema(ref.category) or {}) if ref is not None else {}
    calls = schema.get("calls") or {}
    out: List[Readable] = []
    for name in sorted(commands):
        if not name.startswith(READING_PREFIXES) or not commands.get(name):
            continue
        result = (calls.get(name) or {}).get("result") or {}
        if result.get("type") not in NUMERIC_RESULTS:
            continue
        arguments = call_arguments(library, model_id, name)
        out.append(
            Readable(
                name,
                str(result.get("unit", "")),
                "channel_number" in arguments,
                [a for a, required in arguments.items() if required and a != "channel_number"],
            )
        )
    return out
