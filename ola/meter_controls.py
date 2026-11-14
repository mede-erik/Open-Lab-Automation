# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the remote-control panel of a multimeter or a datalogger shows, and the calls it sends
(no Qt).

Both show one row per enabled channel of the ``.inst`` file with its measurement function, its
range (automatic or a value) and the value read. Only the functions the model defines in the
library are offered:

* a **multimeter** is set with ``set_function`` and ``set_auto_range`` / ``set_range`` (the
  functions its ``set_function`` translates), then read with ``read_measurement``; a meter with
  several channels in the file is switched to the function of each row before reading it;
* a **datalogger** is configured with the ``configure_...`` calls of ``ola.datalogger_setup``
  (one per group of channels, then the scan list) and read with ``read_scan``, one value per
  channel in channel-number order.

A reading is divided by the attenuation of its channel, as in the ``.inst`` file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .datalogger_setup import MEAS_TYPE_CALLS, datalogger_calls, scan_order

Call = Tuple[str, Dict[str, Any]]

# multimeter functions (schema enum) and the unit of their reading
METER_UNITS = {
    "DC_VOLTAGE": "V",
    "DC_VOLTAGE_RATIO": "",
    "AC_VOLTAGE": "V",
    "DC_CURRENT": "A",
    "AC_CURRENT": "A",
    "RESISTANCE_2W": "Ω",
    "RESISTANCE_4W": "Ω",
    "EXTENDED_RESISTANCE": "Ω",
    "FREQUENCY": "Hz",
    "PERIOD": "s",
    "CONTINUITY": "Ω",
    "DIODE": "V",
}
# measurement type written by the .inst editors -> multimeter function
MEAS_TYPE_FUNCTION = {
    "VOLT:DC": "DC_VOLTAGE",
    "DC_V": "DC_VOLTAGE",
    "VOLT:AC": "AC_VOLTAGE",
    "AC_V": "AC_VOLTAGE",
    "CURR:DC": "DC_CURRENT",
    "DC_A": "DC_CURRENT",
    "CURR:AC": "AC_CURRENT",
    "AC_A": "AC_CURRENT",
    "RES": "RESISTANCE_2W",
    "FRES": "RESISTANCE_4W",
    "FREQ": "FREQUENCY",
    "PER": "PERIOD",
}
# datalogger measurement types (keys of the .inst file) and the unit of their reading
DATALOGGER_TYPES = {
    "VOLT:DC": "V",
    "VOLT:AC": "V",
    "CURR:DC": "A",
    "CURR:AC": "A",
    "RES": "Ω",
    "FRES": "Ω",
    "FREQ": "Hz",
    "PER": "s",
    "TEMP": "°C",
}

MULTIMETER, DATALOGGER = "multimeter", "datalogger"


@dataclass
class MeterControls:
    """The controls of a multimeter or datalogger model."""

    kind: str = ""
    """``multimeter``, ``datalogger``, or empty when the model cannot be controlled."""
    calls: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    """Multimeter: the functions of the schema enum; datalogger: the measurement types."""
    range_functions: List[str] = field(default_factory=list)
    """Multimeter: the functions ``set_range`` accepts (a ratio, a continuity test... have no
    range on some models)."""
    auto_range_functions: List[str] = field(default_factory=list)
    """Multimeter: the functions ``set_auto_range`` accepts."""

    def has(self, call: str) -> bool:
        """True if the model defines this logical call."""
        return call in self.calls


class RangeError(ValueError):
    """A range typed in the panel is not a number (or ``AUTO``)."""


def _mapped_values(command: Optional[Dict[str, Any]], arg: str, values: Sequence[str]) -> List[str]:
    """The values of ``arg`` the command translates (keys of its map), in the order of
    ``values``; all of them when the command has no map."""
    spec = ((command or {}).get("parameters") or {}).get(arg) or {}
    mapped = spec.get("map") if isinstance(spec.get("map"), dict) else None
    return [v for v in values if mapped is None or v in mapped]


def meter_controls(library: Any, model_id: str, instrument_type: str) -> MeterControls:
    """What the panel of this model shows (``kind`` empty if the model is not in the library or
    has none of the calls needed)."""
    commands = library.commands(model_id) or {}
    calls = [name for name, spec in commands.items() if spec]
    kind = DATALOGGER if "datalogger" in str(instrument_type).lower() else MULTIMETER
    if kind == MULTIMETER:
        if "set_function" not in calls or "read_measurement" not in calls:
            return MeterControls(calls=calls)
        functions = _mapped_values(commands.get("set_function"), "function", list(METER_UNITS))
        ranged = [
            _mapped_values(commands.get(c), "function", functions) if c in calls else []
            for c in ("set_range", "set_auto_range")
        ]
        return MeterControls(MULTIMETER, calls, functions, ranged[0], ranged[1])
    if "read_scan" not in calls or "select_channels" not in calls:
        return MeterControls(calls=calls)
    functions = [t for t in DATALOGGER_TYPES if MEAS_TYPE_CALLS.get(t) in calls]
    return MeterControls(DATALOGGER, calls, functions)


def parse_range(text: str) -> Union[str, float]:
    """``AUTO`` for an empty field (or ``auto``), otherwise the number typed (``RangeError``)."""
    text = (text or "").strip().replace(",", ".")
    if not text or text.upper() == "AUTO":
        return "AUTO"
    try:
        value = float(text)
    except ValueError as exc:
        raise RangeError(text) from exc
    if value <= 0:
        raise RangeError(text)
    return value


def default_function(controls: MeterControls, channel: Mapping[str, Any]) -> str:
    """The function a row starts with: the one of the channel in the ``.inst`` file, if the
    model has it, otherwise the first the model has."""
    meas = str(channel.get("meas_type", "") or "").strip().upper()
    wanted = meas if controls.kind == DATALOGGER else MEAS_TYPE_FUNCTION.get(meas, meas)
    if wanted in controls.functions:
        return wanted
    return controls.functions[0] if controls.functions else ""


def unit_of(controls: MeterControls, function: str) -> str:
    """The unit of a reading of this function."""
    table = DATALOGGER_TYPES if controls.kind == DATALOGGER else METER_UNITS
    return table.get(function, "")


def multimeter_calls(
    controls: MeterControls, function: str, range_: Union[str, float]
) -> List[Call]:
    """The calls that set the function and the range of a multimeter."""
    calls: List[Call] = [("set_function", {"function": function})]
    if range_ == "AUTO":
        if function in controls.auto_range_functions:
            calls.append(("set_auto_range", {"function": function, "state": True}))
    elif function in controls.range_functions:
        calls.append(("set_range", {"function": function, "range": float(range_)}))
    return calls


def datalogger_rows(
    channels: Sequence[Mapping[str, Any]], settings: Mapping[int, Tuple[str, Union[str, float]]]
) -> List[Dict[str, Any]]:
    """The channels of the ``.inst`` entry with the function and range chosen in the panel
    (``settings``: index of the channel among ``channels`` -> (measurement type, range))."""
    rows = []
    for index, channel in enumerate(channels):
        row = dict(channel)
        if index in settings:
            meas, range_ = settings[index]
            row["meas_type"] = meas
            row["range"] = range_
        rows.append(row)
    return rows


def datalogger_setup(rows: Sequence[Mapping[str, Any]]) -> List[Call]:
    """The calls that configure the datalogger for these rows (``ola.datalogger_setup``)."""
    return datalogger_calls([dict(r) for r in rows])


def datalogger_values(
    rows: Sequence[Mapping[str, Any]], readings: Sequence[Any]
) -> List[Optional[Any]]:
    """The value of each row (in the order of ``rows``) from the answer of ``read_scan``, which
    gives the enabled channels in channel-number order; None for a row without a reading."""
    ordered = scan_order([dict(r) for r in rows])
    by_id = {}
    for position, row in enumerate(ordered):
        if position < len(readings):
            by_id[id_key(row)] = readings[position]
    return [by_id.get(id_key(dict(r))) for r in rows]


def id_key(row: Mapping[str, Any]) -> Tuple[Any, Any, Any]:
    """What tells two channels of the same entry apart."""
    return (row.get("slot_number"), row.get("channel_id"), row.get("name"))


def scaled(value: Any, channel: Mapping[str, Any]) -> Optional[float]:
    """A reading divided by the attenuation of its channel (1 if none); None if not a number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    try:
        attenuation = float(channel.get("attenuation", 1.0) or 1.0)
    except (TypeError, ValueError):
        attenuation = 1.0
    return number / attenuation if attenuation else number
