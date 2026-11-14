# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the remote-control panels of an instrument can show (no Qt).

A panel shows only the controls whose logical call the model defines in the library: a
generator without an output switch has no output button, a waveform the model cannot make is
not offered. The values typed in a panel are checked here against the limits the library gives,
before anything is sent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# the logical calls a function-generator panel can use, in the order they are sent by "Apply"
FUNCTION_GENERATOR_CALLS = (
    "set_waveform_shape",
    "set_frequency",
    "set_amplitude",
    "set_offset",
    "set_output_state",
)


@dataclass
class FunctionGeneratorControls:
    """The controls of a function generator: calls it defines, waveforms, channels, limits."""

    calls: List[str] = field(default_factory=list)
    shapes: List[str] = field(default_factory=list)
    channels: int = 1
    frequency_min: Optional[float] = None
    frequency_max: Optional[float] = None

    def has(self, call: str) -> bool:
        """True if the model defines this logical call."""
        return call in self.calls


def accepted_values(
    command: Optional[Dict[str, Any]], arg: str, default: Sequence[str]
) -> List[str]:
    """The values of an enumerated argument a model accepts: the ones its command translates
    (the keys of the ``map`` of a parameter computed from ``arg``), limited to the values it
    lists for ``arg``; ``default`` (the schema's values) when the command says nothing."""
    params = (command or {}).get("parameters") or {}
    listed = list((params.get(arg) or {}).get("values") or default)
    mapped = None
    for spec in params.values():
        if isinstance(spec, dict) and spec.get("from") == arg and isinstance(spec.get("map"), dict):
            mapped = set(spec["map"])
            break
    return [v for v in listed if mapped is None or v in mapped]


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def function_generator_controls(library: Any, model_id: str) -> FunctionGeneratorControls:
    """What the panel of this function-generator model shows (empty if it is not in the
    library)."""
    commands = library.commands(model_id) or {}
    ref = library.find_model(model_id)
    schema = library.schema(ref.category) if ref is not None else None
    default_shapes = (((schema or {}).get("types") or {}).get("waveform_shape") or {}).get(
        "values"
    ) or []
    caps = (ref.model.get("capabilities") or {}) if ref is not None else {}
    channels = caps.get("number_of_channels") or caps.get("channels")
    return FunctionGeneratorControls(
        calls=[c for c in FUNCTION_GENERATOR_CALLS if commands.get(c)],
        shapes=accepted_values(commands.get("set_waveform_shape"), "shape", default_shapes),
        channels=channels if isinstance(channels, int) and channels > 0 else 1,
        frequency_min=_number(caps.get("frequency_min_hz")),
        frequency_max=_number(caps.get("frequency_max_hz")),
    )


def check_function_generator(
    controls: FunctionGeneratorControls,
    frequency: Optional[float] = None,
    amplitude: Optional[float] = None,
) -> List[str]:
    """The problems of the values typed in a panel (empty list: they can be sent). Each
    problem is a key of the translations: ``fg_err_frequency_low``, ``fg_err_frequency_high``,
    ``fg_err_amplitude``."""
    problems = []
    if frequency is not None:
        low = controls.frequency_min
        if frequency < 0 or (low is not None and frequency < low):
            problems.append("fg_err_frequency_low")
        if controls.frequency_max is not None and frequency > controls.frequency_max:
            problems.append("fg_err_frequency_high")
    if amplitude is not None and amplitude < 0:
        problems.append("fg_err_amplitude")
    return problems
