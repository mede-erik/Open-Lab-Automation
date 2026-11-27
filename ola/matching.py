# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Matching networks: the two-component L networks that make a measured load look like ``z0`` at
one frequency (no Qt, no I/O).

A load ``Z = R + jX`` (an antenna, the input of an amplifier) is matched to ``z0`` with one
series and one shunt reactance. Two shapes, each with up to two solutions:

* ``shunt_load`` (*shunt next to the load, series towards the source*): possible when the load is
  outside the circle ``R^2 + X^2 >= z0 R`` (for example a resistance above ``z0``).
* ``series_load`` (*series next to the load, shunt towards the source*): possible when ``R <= z0``.

Each reactance is turned into the component that gives it at that frequency: a positive series
reactance is an inductor, a negative one a capacitor; a positive shunt susceptance is a
capacitor, a negative one an inductor. ``networks`` returns every solution with the input
impedance it gives (``z_in``, which is ``z0`` up to rounding: the test of the formulas) and the
bandwidth hint ``q``: the loaded Q of the network, a lower Q is a wider match. ``summary_at`` is
what the antenna and the return loss measurements report at their ``match_frequencies_hz``.

The components are ideal: a real inductor or capacitor has losses and its own resonance (measure
it with the component measurement), and the pads of the board add their own reactance.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple


class MatchingError(ValueError):
    """No network can be computed (a load with no resistance, a wrong frequency)."""


def component(reactance: float, f: float, shunt: bool) -> Dict[str, Any]:
    """The part that gives ``reactance`` (series, ohm) or susceptance (``shunt``: siemens) at
    ``f``: ``{"kind": "L" | "C", "value": henry or farad, "where": "series" | "shunt"}``."""
    w = 2 * math.pi * f
    if shunt:  # a susceptance B: C = B / w, or L = -1 / (w B)
        kind, value = ("C", reactance / w) if reactance > 0 else ("L", -1 / (w * reactance))
    else:  # a reactance X: L = X / w, or C = -1 / (w X)
        kind, value = ("L", reactance / w) if reactance > 0 else ("C", -1 / (w * reactance))
    return {"kind": kind, "value": value, "where": "shunt" if shunt else "series"}


def _input(z_load: complex, x: float, b: float, shape: str) -> complex:
    """The impedance seen from the source through the network."""
    if shape == "shunt_load":
        y = 1 / z_load + 1j * b
        return 1 / y + 1j * x
    z = z_load + 1j * x
    return 1 / (1 / z + 1j * b)


def networks(z_load: complex, f: float, z0: float = 50.0) -> List[Dict[str, Any]]:
    """Every L network that matches ``z_load`` to ``z0`` at ``f``: ``[{"shape", "series",
    "shunt", "x_ohm", "b_s", "z_in", "q"}]`` (``series`` and ``shunt`` as ``component`` gives
    them). Empty if the load is already ``z0``. ``MatchingError`` for a load with no resistance
    (a pure reactance cannot be matched without losses) or a frequency that is not above 0."""
    if f <= 0:
        raise MatchingError("the frequency must be above 0")
    r, xl = z_load.real, z_load.imag
    if not math.isfinite(r) or not math.isfinite(xl) or r <= 0:
        raise MatchingError(
            "the load has no resistance (an open, a short or a pure reactance): it cannot be "
            "matched with two reactances"
        )
    if abs(z_load - z0) < 1e-9 * z0:
        return []
    found: List[Dict[str, Any]] = []
    under = r * r + xl * xl - z0 * r
    if under >= 0:  # shunt next to the load
        root = math.sqrt(r / z0) * math.sqrt(under)
        for sign in (1, -1):
            b = (xl + sign * root) / (r * r + xl * xl)
            if b == 0:
                continue
            x = 1 / b + xl * z0 / r - z0 / (b * r)
            found.append({"shape": "shunt_load", "x_ohm": x, "b_s": b})
    if r <= z0:  # series next to the load
        root_x = math.sqrt(r * (z0 - r))
        root_b = math.sqrt((z0 - r) / r) / z0
        for sign in (1, -1):
            found.append(
                {"shape": "series_load", "x_ohm": sign * root_x - xl, "b_s": sign * root_b}
            )
    out = []
    for net in found:
        x, b = net["x_ohm"], net["b_s"]
        if abs(x) < 1e-12 or abs(b) < 1e-15:
            continue  # one element only: kept in the list of the other shape
        z_in = _input(z_load, x, b, net["shape"])
        out.append(
            dict(
                net,
                series=component(x, f, shunt=False),
                shunt=component(b, f, shunt=True),
                z_in=z_in,
                q=max(abs(x) / z0, abs(b) * z0),
            )
        )
    return sorted(out, key=lambda n: n["q"])


def describe(net: Dict[str, Any]) -> str:
    """One line for the log and the summary, from the source to the load, for example
    ``series 2.99 pF, then shunt (to ground) 31.6 nH next to the load``."""
    from .run_view import format_si

    def part(p: Dict[str, Any]) -> str:
        where = "shunt (to ground)" if p["where"] == "shunt" else "series"
        value = float(f"{p['value']:.3g}")  # three digits: what a real part is chosen by
        return f"{where} {format_si(value, 'H' if p['kind'] == 'L' else 'F')}"

    if net["shape"] == "shunt_load":
        return f"{part(net['series'])}, then {part(net['shunt'])} next to the load"
    return f"{part(net['shunt'])}, then {part(net['series'])} next to the load"


def summary_at(
    freq: Sequence[float],
    resistance: Sequence[float],
    reactance: Sequence[float],
    frequencies: Sequence[float],
    z0: float = 50.0,
) -> Tuple[Dict[str, Any], List[str]]:
    """What a measurement reports about matching its load at each of ``frequencies``: the
    summary entries (``match_<f>_count``, ``match_<f>_1`` and ``match_<f>_2``, the networks of
    lowest Q, and ``match_<f>_q``) and the lines for the log, with every network."""
    from . import rf
    from .run_view import format_si

    summary: Dict[str, Any] = {}
    lines: List[str] = []
    for f in frequencies:
        name = format_si(f, "Hz").replace(" ", "")
        z = complex(rf.value_at(freq, list(resistance), f), rf.value_at(freq, list(reactance), f))
        try:
            found = networks(z, f, z0)
        except MatchingError as exc:
            summary[f"match_{name}_count"] = 0
            lines.append(f"matching at {format_si(f, 'Hz')}: {exc}")
            continue
        summary[f"match_{name}_count"] = len(found)
        if not found:
            lines.append(f"matching at {format_si(f, 'Hz')}: the load is already {z0:g} ohm")
            continue
        for index, net in enumerate(found[:2], 1):
            summary[f"match_{name}_{index}"] = describe(net)
        summary[f"match_{name}_q"] = found[0]["q"]
        head = f"matching {z.real:.3g}{z.imag:+.3g}j ohm at {format_si(f, 'Hz')} to {z0:g} ohm"
        lines.append(head + ": " + "; or ".join(describe(n) for n in found))
    return summary, lines


def check_frequencies(
    params: Dict[str, Any], out: List[Any], problem: Any, start: Any, stop: Any
) -> None:
    """Check ``params["match_frequencies_hz"]`` (optional): a list of frequencies above 0, inside
    the sweep ``start`` to ``stop`` when they are known; ``problem(path, message)`` for each
    wrong thing."""
    wanted = params.get("match_frequencies_hz")
    if wanted is None:
        return
    numbers = isinstance(wanted, list) and all(
        isinstance(f, (int, float)) and not isinstance(f, bool) and f > 0 for f in wanted
    )
    if not numbers:
        out.append(problem("match_frequencies_hz", "must be a list of frequencies above 0 (Hz)"))
    elif start is not None and stop is not None and any(not start <= f <= stop for f in wanted):
        out.append(problem("match_frequencies_hz", "every frequency must be inside the sweep"))
