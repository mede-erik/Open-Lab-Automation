"""What an instrument can do, what a measurement has asked of it, and how they compare. No Qt.

**Characteristics** are the numbers the library gives for a model (or the limits of a manual
instrument): ``max_voltage``, ``max_current``, ``max_power``, ``bandwidth_mhz``,
``frequency_max_hz``... ``characteristics(library, model_id)`` returns only what the library
really says; a model whose entry has no number for something has no entry for it.

**The need of a role is learned, modules declare nothing.** The handle of an instrument remembers
the largest value of every quantity it was asked for or gave back during a run (``observe``: the
values set with ``set_voltage``..., the values read with ``read_voltage``,
``measure_dc_voltage``...). At the end of the run this goes into the ``end`` record of the run file
(``observed``). The need of a role is the largest value observed in the runs of that measurement
plus 20 % (``NEED_MARGIN``): the capability an instrument must have to do again what was done.
Before any run there is no need.

Only quantities that are both observable and given by the library can be compared: voltage,
current and power. Other characteristics (bandwidth, number of ports...) are compared with those of
the instrument that made the previous run (``ola.identity.snapshot`` keeps them).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

NEED_MARGIN = 1.2  # the need is the largest value observed plus 20 %

VOLTAGE, CURRENT, POWER = "max_voltage", "max_current", "max_power"

# logical call -> (quantity, where the value is: an argument or the result)
OBSERVED_CALLS: Dict[str, tuple] = {
    "set_voltage": (VOLTAGE, "value"),
    "read_voltage": (VOLTAGE, None),
    "set_voltage_level": (VOLTAGE, "value"),
    "measure_dc_voltage": (VOLTAGE, None),
    "measure_ac_voltage": (VOLTAGE, None),
    "set_current": (CURRENT, "value"),
    "read_current": (CURRENT, None),
    "set_current_level": (CURRENT, "value"),
    "measure_dc_current": (CURRENT, None),
    "measure_ac_current": (CURRENT, None),
    "set_power_level": (POWER, "value"),
    "read_power": (POWER, None),
}

# characteristics where a smaller number is better (the lowest frequency of a VNA)
LOWER_IS_BETTER = {"frequency_min_hz"}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def observe(store: Dict[str, float], call: str, args: Dict[str, Any], result: Any) -> None:
    """Remember in ``store`` the largest absolute value of the quantity of ``call`` (if it has
    one): a value that was set, or the value that was read."""
    spec = OBSERVED_CALLS.get(call)
    if spec is None:
        return
    quantity, argument = spec
    value = _number(args.get(argument) if argument else result)
    if value is None or value != value:  # not a number, or NaN
        return
    store[quantity] = max(store.get(quantity, 0.0), abs(value))


def observed_of(runner: Any) -> Dict[str, List[Dict[str, Any]]]:
    """What the instruments of a runner gave and were asked, per role, for the end of a run file:
    ``{role: [{"name": ..., "observed": {"max_voltage": 12.0}}]}`` (instruments with nothing
    observed are left out)."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for role, handles in runner.bindings.items():
        rows = []
        for handle in handles:
            seen = dict(getattr(handle, "observed", None) or {})
            if seen:
                rows.append({"name": getattr(handle, "name", "?"), "observed": seen})
        if rows:
            out[role] = rows
    return out


# ====================================================================== characteristics
def _max(values: Iterable[Any]) -> Optional[float]:
    numbers = [n for n in (_number(v) for v in values) if n is not None]
    return max(numbers) if numbers else None


def _put(out: Dict[str, float], key: str, value: Any) -> None:
    number = _number(value)
    if number is not None:
        out[key] = number


def characteristics_of_caps(category: str, caps: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """The comparable numbers in the capabilities of a model of ``category``."""
    caps = caps or {}
    out: Dict[str, float] = {}
    if category in ("power_supplies_series", "electronic_loads_series"):
        channels = [c for c in caps.get("channels") or [] if isinstance(c, dict)]
        voltage = _max((c.get("voltage_output") or {}).get("max") for c in channels)
        current = _max((c.get("current_output") or {}).get("max") for c in channels)
        _put(out, VOLTAGE, voltage if voltage is not None else caps.get("max_voltage_v"))
        _put(out, CURRENT, current if current is not None else caps.get("max_current_a"))
        _put(out, POWER, caps.get("max_power_w"))
        count = caps.get("number_of_channels")
        _put(out, "number_of_channels", count if count is not None else len(channels) or None)
    elif category == "oscilloscopes_series":
        bandwidth = caps.get("bandwidth_mhz", caps.get("bandwidth_mhz_max"))
        for key, value in (
            ("bandwidth_mhz", bandwidth),
            ("sample_rate_gsa_s", caps.get("sample_rate_gsa_s")),
            ("memory_depth_mpts", caps.get("memory_depth_mpts")),
            ("number_of_channels", caps.get("number_of_channels")),
            ("vertical_resolution_bits", caps.get("vertical_resolution_bits")),
        ):
            _put(out, key, value)
    elif category == "network_analyzers_series":
        ports = caps.get("number_of_ports")
        for key, value in (
            ("frequency_min_hz", caps.get("frequency_min_hz")),
            ("frequency_max_hz", caps.get("frequency_max_hz")),
            ("number_of_ports", _max(ports) if isinstance(ports, list) else ports),
            ("max_sweep_points", caps.get("max_sweep_points")),
        ):
            _put(out, key, value)
    elif category == "multimeters_series":
        for key, section in ((VOLTAGE, "voltage_ranges"), (CURRENT, "current_ranges")):
            ranges = caps.get(section)
            if isinstance(ranges, dict):
                _put(out, key, _max(v for k, v in ranges.items() if isinstance(v, list) for v in v))
    elif category == "dataloggers_series":
        _put(out, "number_of_channels", caps.get("max_scan_channels"))
    return out


def characteristics(library: Any, model_id: str) -> Dict[str, float]:
    """The comparable numbers the library gives for a model (empty if it gives none)."""
    ref = library.find_model(model_id) if library is not None else None
    if ref is None:
        return {}
    return characteristics_of_caps(ref.category, ref.model.get("capabilities"))


def handle_characteristics(handle: Any) -> Dict[str, float]:
    """The characteristics of the instrument behind a handle: the limits of a manual instrument,
    the numbers of the library for any other."""
    if getattr(handle, "is_manual", False):
        limits = getattr(handle, "limits", None) or {}
        return {k: float(v) for k, v in limits.items() if _number(v)}
    library = getattr(handle, "library", None)
    model_id = getattr(handle, "model_id", None)
    return characteristics(library, model_id) if library is not None and model_id else {}


# ====================================================================== the need of a role
def role_need(runs: Iterable[Dict[str, Any]], role: str) -> Dict[str, float]:
    """The need of a role: for each quantity the largest value observed in the ``runs`` (read runs,
    see ``ola.runs.read_run``) times ``NEED_MARGIN``. Empty if no run observed anything."""
    largest: Dict[str, float] = {}
    for run in runs:
        for row in ((run.get("end") or {}).get("observed") or {}).get(role, []):
            for quantity, value in (row.get("observed") or {}).items():
                number = _number(value)
                if number is not None:
                    largest[quantity] = max(largest.get(quantity, 0.0), number)
    return {quantity: value * NEED_MARGIN for quantity, value in largest.items()}


def previous_instruments(runs: Iterable[Dict[str, Any]], role: str) -> List[Dict[str, Any]]:
    """The snapshots of the instruments of ``role`` in the newest run that has them (``runs`` newest
    first, as ``ProjectSession.runs`` gives them)."""
    for run in runs:
        rows = ((run.get("header") or {}).get("instruments") or {}).get(role)
        if rows:
            return list(rows)
    return []
