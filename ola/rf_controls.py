# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the remote-control panel of an RF signal generator shows, and the calls it sends (no Qt).

The panel offers the carrier (frequency, power, RF output) and, for each modulation the model
defines in the library (AM, FM, PM, pulse), its on/off state, the source of the modulating signal,
the rate of an internal generator, the depth or deviation, the waveform and the coupling of the
external input. Only what the model translates is offered: the formats of its
``set_modulation_state``, the sources of its ``set_modulation_source``... A value is checked against
the limits the library gives (the frequency and power ranges of the model) before anything is sent;
the depth and deviation ranges are in the data sheets, so the instrument has the last word and its
error is shown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

KINDS = ("AM", "FM", "PM", "PULSE")
SOURCES = ("INTERNAL", "INTERNAL_2", "EXTERNAL")
INTERNAL_SOURCES = ("INTERNAL", "INTERNAL_2")
SHAPES = ("SINE", "TRIANGLE", "SQUARE")
COUPLINGS = ("AC", "DC")
# the call that sets the depth (AM) or the deviation (FM, PM) of a format, and its unit
DEPTH = {
    "AM": ("set_am_depth", "%"),
    "FM": ("set_fm_deviation", "Hz"),
    "PM": ("set_pm_deviation", "rad"),
}

Call = Tuple[str, Dict[str, Any]]


@dataclass
class ModulationKind:
    """What a model can do for one modulation format."""

    kind: str
    sources: List[str] = field(default_factory=list)
    rate_sources: List[str] = field(default_factory=list)
    shapes: List[str] = field(default_factory=list)
    couplings: List[str] = field(default_factory=list)
    depth_call: str = ""
    depth_unit: str = ""


@dataclass
class RfControls:
    """The controls of an RF signal generator model."""

    calls: List[str] = field(default_factory=list)
    kinds: List[ModulationKind] = field(default_factory=list)
    frequency_min: Optional[float] = None
    frequency_max: Optional[float] = None
    power_min: Optional[float] = None
    power_max: Optional[float] = None

    def has(self, call: str) -> bool:
        """True if the model defines this logical call."""
        return call in self.calls

    @property
    def usable(self) -> bool:
        """True if the panel can drive the carrier (the three mandatory calls)."""
        return all(self.has(c) for c in ("set_frequency", "set_power_level", "set_output_state"))

    def kind(self, name: str) -> Optional[ModulationKind]:
        """The description of a modulation format, or None if the model has not got it."""
        return next((k for k in self.kinds if k.kind == name), None)


def _map_keys(command: Optional[Dict[str, Any]], arg: str) -> Optional[List[str]]:
    """The values of ``arg`` the command translates: the keys of the ``map`` of ``arg`` itself or
    of a parameter computed from it (``from: arg``). None if the command has no such map."""
    params = (command or {}).get("parameters") or {}
    for name, spec in params.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("map"), dict):
            continue
        if name == arg or spec.get("from") == arg:
            return list(spec["map"])
    return None


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _of_kind(command: Optional[Dict[str, Any]], kind: str, arg: str, values: Sequence[str]):
    """The ``values`` of ``arg`` the command accepts for this modulation format (none if the
    command is missing or does not translate the format)."""
    if not command:
        return []
    kinds = _map_keys(command, "kind")
    if kinds is not None and kind not in kinds:
        return []
    keys = _map_keys(command, arg)
    return [v for v in values if keys is None or v in keys]


def rf_controls(library: Any, model_id: str) -> RfControls:
    """What the panel of this RF generator model shows (empty if it is not in the library)."""
    commands = library.commands(model_id) or {}
    ref = library.find_model(model_id)
    caps = (ref.model.get("capabilities") or {}) if ref is not None else {}
    kinds: List[ModulationKind] = []
    state = commands.get("set_modulation_state")
    if state:
        translated = _map_keys(state, "kind")
        for name in KINDS:
            if translated is not None and name not in translated:
                continue
            depth_call, unit = DEPTH.get(name, ("", ""))
            kinds.append(
                ModulationKind(
                    name,
                    sources=_of_kind(
                        commands.get("set_modulation_source"), name, "source", SOURCES
                    ),
                    rate_sources=_of_kind(
                        commands.get("set_modulation_rate"), name, "source", INTERNAL_SOURCES
                    ),
                    shapes=_of_kind(commands.get("set_modulation_waveform"), name, "shape", SHAPES),
                    couplings=_of_kind(
                        commands.get("set_modulation_external_coupling"),
                        name,
                        "coupling",
                        COUPLINGS,
                    ),
                    depth_call=depth_call if commands.get(depth_call) else "",
                    depth_unit=unit,
                )
            )
    return RfControls(
        calls=[name for name, spec in commands.items() if spec],
        kinds=kinds,
        frequency_min=_number(caps.get("frequency_min_hz")),
        frequency_max=_number(caps.get("frequency_max_hz")),
        power_min=_number(caps.get("power_min_dbm")),
        power_max=_number(caps.get("power_max_dbm")),
    )


def check_carrier(
    controls: RfControls, frequency: Optional[float] = None, power: Optional[float] = None
) -> List[str]:
    """Problems of the carrier values (translation keys; empty: they can be sent)."""
    problems = []
    if frequency is not None:
        if frequency <= 0 or (
            controls.frequency_min is not None and frequency < controls.frequency_min
        ):
            problems.append("rf_err_frequency_low")
        if controls.frequency_max is not None and frequency > controls.frequency_max:
            problems.append("rf_err_frequency_high")
    if power is not None:
        if controls.power_min is not None and power < controls.power_min:
            problems.append("rf_err_power_low")
        if controls.power_max is not None and power > controls.power_max:
            problems.append("rf_err_power_high")
    return problems


def carrier_calls(
    controls: RfControls, frequency: Optional[float], power: Optional[float]
) -> List[Call]:
    """The calls that set the frequency and the power (only the values given)."""
    calls: List[Call] = []
    if frequency is not None:
        calls.append(("set_frequency", {"value": float(frequency)}))
    if power is not None:
        calls.append(("set_power_level", {"value": float(power)}))
    return calls


def output_calls(on: bool) -> List[Call]:
    """The call that switches the RF output on or off."""
    return [("set_output_state", {"state": bool(on)})]


def master_calls(controls: RfControls, on: bool) -> List[Call]:
    """The call that switches all the modulation of the RF output (if the model has it)."""
    if not controls.has("set_modulation_output_state"):
        return []
    return [("set_modulation_output_state", {"state": bool(on)})]


def shape_applies(info: ModulationKind, source: Optional[str]) -> bool:
    """True if the waveform call sets the modulating signal that ``source`` uses. The library
    documents it for the second internal generator (the first one is a sine); on a model with a
    single internal generator it is that one."""
    if not info.shapes:
        return False
    if source == "INTERNAL_2":
        return True
    return source in INTERNAL_SOURCES and "INTERNAL_2" not in info.rate_sources


def modulation_calls(
    controls: RfControls,
    kind: str,
    enabled: bool,
    source: Optional[str] = None,
    rate: Optional[float] = None,
    depth: Optional[float] = None,
    shape: Optional[str] = None,
    coupling: Optional[str] = None,
) -> List[Call]:
    """The calls that set a modulation format: when it is enabled its source, the rate of an
    internal source, the depth or deviation, the waveform and the coupling of the external input
    (only what the model has and the source makes useful), then its on state; when it is disabled
    only its off state. ``[]`` if the model has not got this format."""
    info = controls.kind(kind)
    if info is None:
        return []
    calls: List[Call] = []
    if enabled:
        if source and source in info.sources:
            calls.append(("set_modulation_source", {"kind": kind, "source": source}))
        internal = source in INTERNAL_SOURCES if source else bool(info.rate_sources)
        if rate is not None and internal and (source or info.rate_sources[0]) in info.rate_sources:
            calls.append(
                (
                    "set_modulation_rate",
                    {"kind": kind, "value": float(rate), "source": source or info.rate_sources[0]},
                )
            )
        if depth is not None and info.depth_call:
            calls.append((info.depth_call, {"value": float(depth)}))
        if shape and shape in info.shapes and shape_applies(info, source):
            calls.append(("set_modulation_waveform", {"kind": kind, "shape": shape}))
        if coupling and coupling in info.couplings and source == "EXTERNAL":
            calls.append(("set_modulation_external_coupling", {"kind": kind, "coupling": coupling}))
    calls.append(("set_modulation_state", {"kind": kind, "state": bool(enabled)}))
    return calls


def check_modulation(
    rate: Optional[float] = None, depth: Optional[float] = None
) -> List[str]:
    """Problems of the modulation values (translation keys): they cannot be negative."""
    problems = []
    if rate is not None and rate < 0:
        problems.append("rf_err_negative")
    if depth is not None and depth < 0 and "rf_err_negative" not in problems:
        problems.append("rf_err_negative")
    return problems
