# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The instrument file (``.inst``): reading, writing and checking its entries. No Qt.

An ``.inst`` file lists the instruments of a project. Every entry has an ``instrument_type``,
a unique ``instance_name`` (the name measurements use), and either a ``model_id`` and a
``visa_address`` (an instrument with remote control) or ``is_manual: true`` (the operator sets
the values by hand). Besides that an entry may carry:

* ``channels`` (and ``slots`` with channels for a datalogger): ``enabled``, ``name`` and the
  limits ``max_voltage``, ``max_current`` and ``max_power`` of a supply or a load;
* ``serial``: the RS-232 settings that differ from the ones of the library (``baud``,
  ``data_bits``, ``parity``, ``stop_bits``, ``flow_control``), for an ``ASRL`` address;
* ``timeout_ms``: how long to wait for an answer;
* a network analyzer: ``num_ports``, ``ports`` (``port``, ``enabled``, ``name``) and ``sweep`` (the
  usual sweep: ``start_hz``, ``stop_hz``, ``points``, optional ``if_bandwidth_hz`` and
  ``power_dbm``).

``save_inst`` keeps every other key of the file as it is. ``check_entry`` returns the problems of
one entry as ``(code, values)`` pairs, so a window can say them in its own language with the key
``inst_problem_<code>``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .fileio import atomic_write_json

Problem = Tuple[str, Dict[str, Any]]

DEFAULT_TIMEOUT_MS = 5000
MIN_TIMEOUT_MS = 100
MAX_TIMEOUT_MS = 600_000
DEFAULT_SWEEP_POINTS = 201

SERIAL_BAUDS = (300, 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
SERIAL_CHOICES: Dict[str, Tuple[Any, ...]] = {
    "data_bits": (5, 6, 7, 8),
    "parity": ("N", "E", "O"),
    "stop_bits": (1, 1.5, 2),
    "flow_control": ("none", "xon_xoff", "rts_cts", "dtr_dsr"),
}
SERIAL_KEYS = ("baud",) + tuple(SERIAL_CHOICES)
# what a serial resource has when neither the library nor the entry says anything (9600 8N1)
SERIAL_FALLBACK: Dict[str, Any] = {
    "baud": 9600,
    "data_bits": 8,
    "parity": "N",
    "stop_bits": 1,
    "flow_control": "none",
}

POWER_TYPES = ("power_supply", "electronic_load")
TYPE_ALIASES = {
    "power_supplies": "power_supply",
    "alimentatore": "power_supply",
    "alimentatori": "power_supply",
    "electronic_loads": "electronic_load",
    "carico_elettronico": "electronic_load",
    "carichi_elettronici": "electronic_load",
    "dataloggers": "datalogger",
    "multimeters": "multimeter",
    "multimetro": "multimeter",
    "multimetri": "multimeter",
    "oscilloscopes": "oscilloscope",
    "oscilloscopio": "oscilloscope",
    "oscilloscopi": "oscilloscope",
    "switch_units": "switch_unit",
    "network_analyzers": "network_analyzer",
}


def entry_type(entry: Dict[str, Any]) -> str:
    """The type of an entry in its canonical form (``power_supply``, ``network_analyzer``...)."""
    raw = str(entry.get("instrument_type", entry.get("type", ""))).strip().lower()
    return TYPE_ALIASES.get(raw, raw)


# ====================================================================== the file
def load_inst(path) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The entries of an ``.inst`` file and its other top-level keys (kept for ``save_inst``).

    A missing file is an empty list; a file that is not valid raises ``ValueError``."""
    path = Path(path)
    if not path.exists():
        return [], {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not an instrument file")
    entries = [e for e in data.get("instruments", []) if isinstance(e, dict)]
    extra = {k: v for k, v in data.items() if k != "instruments"}
    return entries, extra


def save_inst(path, entries: Sequence[Dict[str, Any]], extra: Optional[Dict[str, Any]] = None):
    """Write the entries (and the other keys that were in the file) to ``path``."""
    data = dict(extra or {})
    data["instruments"] = list(entries)
    atomic_write_json(path, data)


def unique_name(base: str, taken: Sequence[str], suffix: str = "_copy") -> str:
    """``base`` + suffix (and a number) that is not in ``taken``."""
    name, counter = f"{base}{suffix}", 1
    while name in taken:
        name = f"{base}{suffix}{counter}"
        counter += 1
    return name


# ====================================================================== channels and limits
def enabled_channels(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The enabled channels of an entry, also those inside the slots of a datalogger."""
    channels = list(entry.get("channels") or [])
    for slot in entry.get("slots") or []:
        if isinstance(slot, dict):
            channels += list(slot.get("channels") or [])
    return [c for c in channels if isinstance(c, dict) and c.get("enabled")]


def number(text: Any, default: Optional[float] = None) -> Optional[float]:
    """A float from what a person typed (a comma is accepted); ``default`` if it is not one."""
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError:
        return default


# ====================================================================== network analyzers
def port_options(caps: Optional[Dict[str, Any]]) -> List[int]:
    """The numbers of ports a model can have (``number_of_ports`` is a number or a list)."""
    value = (caps or {}).get("number_of_ports")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return [value]
    if isinstance(value, list):
        options = sorted({v for v in value if isinstance(v, int) and v > 0})
        if options:
            return options
    return [2]


def default_sweep(caps: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """A sweep that fits the model: its whole frequency range, 201 points (fewer if the model
    allows fewer)."""
    caps = caps or {}
    start = float(caps.get("frequency_min_hz") or 1e6)
    stop = float(caps.get("frequency_max_hz") or 100e6)
    if stop <= start:
        stop = start * 10
    points = DEFAULT_SWEEP_POINTS
    if caps.get("max_sweep_points"):
        points = min(points, int(caps["max_sweep_points"]))
    return {"start_hz": start, "stop_hz": stop, "points": points}


def format_frequency(hz: float) -> str:
    """``50000`` -> ``50k``, ``6.3e9`` -> ``6.3G`` (what ``parse_frequency`` reads back)."""
    for unit, divisor in (("G", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(hz) >= divisor:
            return f"{hz / divisor:g}{unit}"
    return f"{hz:g}"


def resize_ports(entry: Dict[str, Any], count: int) -> None:
    """Give the entry ``count`` ports (``P1``..): existing ports keep their settings."""
    old = {p.get("port"): p for p in entry.get("ports") or [] if isinstance(p, dict)}
    entry["num_ports"] = count
    entry["ports"] = [
        old.get(n) or {"port": n, "enabled": True, "name": f"P{n}"} for n in range(1, count + 1)
    ]


def check_sweep(sweep: Dict[str, Any], caps: Optional[Dict[str, Any]] = None) -> List[Problem]:
    """Problems of a sweep of a network analyzer against what the model can do."""
    caps = caps or {}
    problems: List[Problem] = []
    start, stop = number(sweep.get("start_hz")), number(sweep.get("stop_hz"))
    points = number(sweep.get("points"))
    if start is None or stop is None or start <= 0 or stop <= start:
        problems.append(("sweep_order", {}))
    else:
        low, high = caps.get("frequency_min_hz"), caps.get("frequency_max_hz")
        if (low and start < low) or (high and stop > high):
            problems.append(
                ("sweep_range", {"low": low if low else 0, "high": high if high else 0})
            )
    maximum = caps.get("max_sweep_points")
    if points is None or points < 2 or int(points) != points:
        problems.append(("sweep_points", {"max": maximum or "-"}))
    elif maximum and points > maximum:
        problems.append(("sweep_points", {"max": maximum}))
    for key, code in (("if_bandwidth_hz", "sweep_if_bandwidth"),):
        value = sweep.get(key)
        if value is not None and (number(value) is None or number(value) <= 0):
            problems.append((code, {}))
    power = sweep.get("power_dbm")
    if power is not None and number(power) is None:
        problems.append(("sweep_power", {}))
    return problems


# ====================================================================== serial settings
def serial_changes(chosen: Dict[str, Any], library_defaults: Dict[str, Any]) -> Dict[str, Any]:
    """The serial settings that differ from the ones of the library (what the entry stores)."""
    changes = {}
    for key in SERIAL_KEYS:
        if key in chosen and chosen[key] != library_defaults.get(key):
            changes[key] = chosen[key]
    return changes


def check_serial(cfg: Dict[str, Any]) -> List[Problem]:
    """Problems of the serial settings of an entry."""
    problems: List[Problem] = []
    for key in cfg:
        if key not in SERIAL_KEYS:
            problems.append(("serial_unknown", {"key": key}))
    if "baud" in cfg and (not isinstance(cfg["baud"], int) or cfg["baud"] <= 0):
        problems.append(("serial_value", {"key": "baud", "value": cfg["baud"]}))
    for key, choices in SERIAL_CHOICES.items():
        if key in cfg and str(cfg[key]).upper() not in {str(c).upper() for c in choices}:
            problems.append(("serial_value", {"key": key, "value": cfg[key]}))
    return problems


# ====================================================================== checking an entry
def check_entry(
    entry: Dict[str, Any],
    *,
    caps: Optional[Dict[str, Any]] = None,
    model_found: bool = True,
    other_names: Sequence[str] = (),
) -> List[Problem]:
    """What is wrong or missing in one entry (empty list: it can be used).

    ``caps``: the capabilities the library gives for its model (None if it gives none);
    ``model_found``: False if the model is not in the library; ``other_names``: the names of the
    other entries."""
    problems: List[Problem] = []
    name = str(entry.get("instance_name", "")).strip()
    kind = entry_type(entry)
    manual = bool(entry.get("is_manual"))
    if not name:
        problems.append(("name_empty", {}))
    elif name in other_names:
        problems.append(("name_duplicate", {"name": name}))
    if not manual:
        if not (entry.get("visa_address") or entry.get("address")):
            problems.append(("no_address", {}))
        if not (entry.get("model_id") or entry.get("model")):
            problems.append(("no_model", {}))
        elif not model_found:
            problems.append(
                ("model_unknown", {"model": entry.get("model_id") or entry.get("model")})
            )
    timeout = entry.get("timeout_ms")
    if timeout is not None and not (
        isinstance(timeout, (int, float)) and MIN_TIMEOUT_MS <= timeout <= MAX_TIMEOUT_MS
    ):
        problems.append(("timeout", {"min": MIN_TIMEOUT_MS, "max": MAX_TIMEOUT_MS}))
    if entry.get("serial"):
        problems += check_serial(entry["serial"])

    if kind in POWER_TYPES:
        enabled = enabled_channels(entry)
        if not enabled:
            problems.append(("no_channel", {}))
        for ch in enabled:
            label = ch.get("name", "?")
            for key in ("max_voltage", "max_current"):
                value = number(ch.get(key), 0.0)
                if not value or value <= 0:
                    problems.append(("limit_missing", {"channel": label, "limit": key}))
            if manual or not caps:
                continue
            for key, cap_key in (
                ("max_voltage", "max_voltage_v"),
                ("max_current", "max_current_a"),
            ):
                limit = (caps or {}).get(cap_key)
                value = number(ch.get(key), 0.0) or 0.0
                if limit and value > limit:
                    problems.append(
                        ("limit_above_model", {"channel": label, "limit": key, "model": limit})
                    )
    elif kind in ("oscilloscope", "datalogger", "multimeter"):
        if not enabled_channels(entry):
            problems.append(("no_channel", {}))
    elif kind == "network_analyzer":
        if not [p for p in entry.get("ports") or [] if isinstance(p, dict) and p.get("enabled")]:
            problems.append(("no_port", {}))
        if entry.get("sweep"):
            problems += check_sweep(entry["sweep"], caps)
    return problems
