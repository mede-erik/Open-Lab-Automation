# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the remote-control panel of a vector network analyzer shows, and the sweep it runs
(no Qt).

The panel offers the S-parameters the model measures (``measurable_sparameters`` of the library,
or those of its number of ports), the sweep within its frequency and point limits, the IF
bandwidth, the source power and a logarithmic sweep only when the model has those calls. A sweep
goes through the same helpers as the VNA measurements (``ola.vna_common``), so a LiteVNA (driver)
and an analyzer with SCPI behave the same way. The curves are the magnitude in dB of each
S-parameter, or the impedance (R and X) seen at a port for the reflection parameters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import rf
from .vna_common import _library_sweep, set_sweep, sweep_frequencies, uses_library_calls

ALL_SPARAMETERS = ("S11", "S21", "S12", "S22")
REFLECTIONS = ("S11", "S22")
FORMAT_DB, FORMAT_IMPEDANCE = "db", "impedance"
Z0 = 50.0

Curve = Tuple[str, List[float], List[float]]


@dataclass
class VnaControls:
    """The controls of a VNA model."""

    calls: List[str] = field(default_factory=list)
    sparameters: List[str] = field(default_factory=list)
    frequency_min: Optional[float] = None
    frequency_max: Optional[float] = None
    max_points: Optional[int] = None

    def has(self, call: str) -> bool:
        """True if the model defines this logical call."""
        return call in self.calls

    @property
    def usable(self) -> bool:
        """True if the panel can sweep with this model."""
        return bool(self.sparameters) and self.has("set_frequency_sweep") and self.has(
            "read_sparameters"
        )


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def vna_controls(library: Any, model_id: str) -> VnaControls:
    """What the panel of this VNA model shows (not ``usable`` if it is not in the library)."""
    commands = library.commands(model_id) or {}
    ref = library.find_model(model_id)
    caps = (ref.model.get("capabilities") or {}) if ref is not None else {}
    measurable = caps.get("measurable_sparameters")
    if isinstance(measurable, list) and measurable:
        sparameters = [s for s in ALL_SPARAMETERS if s in measurable]
    else:
        ports = caps.get("number_of_ports")
        ports = max(ports) if isinstance(ports, list) and ports else ports
        sparameters = list(ALL_SPARAMETERS) if (ports or 2) >= 2 else ["S11"]
    points = caps.get("max_sweep_points")
    return VnaControls(
        calls=[name for name, spec in commands.items() if spec],
        sparameters=sparameters,
        frequency_min=_number(caps.get("frequency_min_hz")),
        frequency_max=_number(caps.get("frequency_max_hz")),
        max_points=points if isinstance(points, int) and points > 1 else None,
    )


_SI = {"k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}


def parse_frequency(text: str) -> float:
    """A frequency typed in the panel, in Hz: ``2400000``, ``2.4G``, ``100 k``, ``1,5M``
    (``ValueError`` if it is not one)."""
    raw = (text or "").strip().replace(",", ".").replace(" ", "")
    if raw.lower().endswith("hz"):
        raw = raw[:-2]
    scale = 1.0
    if raw and raw[-1] in _SI:
        scale, raw = _SI[raw[-1]], raw[:-1]
    return float(raw) * scale


def check_sweep(controls: VnaControls, start: float, stop: float, points: int) -> List[str]:
    """Problems of a sweep (translation keys; empty: it can be sent)."""
    problems = []
    if start <= 0 or stop <= start:
        problems.append("vna_err_order")
    if controls.frequency_min is not None and start < controls.frequency_min:
        problems.append("vna_err_low")
    if controls.frequency_max is not None and stop > controls.frequency_max:
        problems.append("vna_err_high")
    if points < 2 or (controls.max_points is not None and points > controls.max_points):
        problems.append("vna_err_points")
    return problems


def sweep_settings(
    start: float,
    stop: float,
    points: int,
    log: bool = False,
    if_bandwidth: Optional[float] = None,
    power: Optional[float] = None,
) -> Dict[str, Any]:
    """The sweep in the form of the VNA measurements (``ola.vna_common.set_sweep``)."""
    sweep: Dict[str, Any] = {
        "start_hz": float(start),
        "stop_hz": float(stop),
        "points": int(points),
        "scale": "log" if log else "linear",
    }
    if if_bandwidth is not None:
        sweep["if_bandwidth_hz"] = float(if_bandwidth)
    if power is not None:
        sweep["power_dbm"] = float(power)
    return sweep


def run_one_sweep(
    handle: Any, sweep: Mapping[str, Any], sparameters: Sequence[str], configure: bool = True
) -> Tuple[List[float], Dict[str, List[complex]], List[str]]:
    """Set the sweep (``configure``: only when it changed) and read the S-parameters of one
    sweep: ``(frequencies, {name: complex values}, notes)``. ``notes`` say what the instrument
    could not do (a logarithmic sweep on a LiteVNA...)."""
    notes = set_sweep(handle, sweep) if configure else []
    if not uses_library_calls(handle):
        raise ValueError("this VNA has no run_sweep / read_sparameters calls")
    freq, values, calibrated = _library_sweep(handle, list(sparameters), sweep_frequencies(sweep))
    if not calibrated:
        notes.append("not_calibrated")
    return freq, values, notes


def curves(
    freq: Sequence[float], data: Mapping[str, Sequence[complex]], fmt: str
) -> List[Curve]:
    """What to draw: ``(label, x, y)`` for each S-parameter in dB, or R and X (Ω) of each
    reflection parameter for the impedance view (transmission has no port impedance)."""
    x = [float(f) for f in freq]
    out: List[Curve] = []
    for name in ALL_SPARAMETERS:
        if name not in data:
            continue
        if fmt == FORMAT_IMPEDANCE:
            if name not in REFLECTIONS:
                continue
            z = rf.gamma_to_z(data[name], Z0)
            out.append((f"R ({name})", x, [v.real for v in z]))
            out.append((f"X ({name})", x, [v.imag for v in z]))
        else:
            out.append((f"{name} dB", x, rf.magnitude_db(data[name])))
    return out


def markers(curve: Curve) -> Dict[str, Tuple[float, float]]:
    """The minimum and the maximum of a curve: ``{"min": (f, y), "max": (f, y)}`` (empty for an
    empty curve; points that are not finite are skipped)."""
    _, xs, ys = curve
    points = [(x, y) for x, y in zip(xs, ys) if y == y and abs(y) != float("inf")]
    if not points:
        return {}
    return {
        "min": min(points, key=lambda p: p[1]),
        "max": max(points, key=lambda p: p[1]),
    }


def export_touchstone(path: str, freq: Sequence[float], data: Mapping[str, Sequence[complex]]):
    """Save the last sweep as ``.s1p`` (S11 only) or ``.s2p`` (``ola.rf.write_touchstone``)."""
    rf.write_touchstone(
        path, freq, dict(data), z0=Z0, comment="Open Lab Automation - remote control"
    )


def touchstone_suffix(data: Mapping[str, Any]) -> str:
    """``.s1p`` when only S11 was measured, otherwise ``.s2p``."""
    return ".s1p" if set(data) <= {"S11"} else ".s2p"
