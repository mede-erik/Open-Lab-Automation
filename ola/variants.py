# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The variants of a run: what changed in the device between two runs of the same DUT. No Qt.

The same device under test, in the same version, is often measured more than once with a small
change in between: a component changed in the bill of materials (``R100 = 100 ohm``), a fan
switched on or off. That is a **variant** of the run, not a new version of the DUT. It is a few
named values written with the measurement, in the ``device`` group of its file (``filter`` for the
filter measurement)::

    {"device": {"dut_id": "DUT-0001", "version": "rev A",
                "variant": {"R100": "100 ohm", "fan": "on"}}}

The header of a run keeps the parameters of the file, so the variant stays with its results; the
comparison and the history of a DUT show it next to each run. In the editors it is written as one
``name = value`` per line (``parse_lines`` and ``format_lines``).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

VARIANT_GROUPS = ("device", "filter")  # where a measurement file names its DUT and its variant


def variant_of(params: Mapping[str, Any]) -> Dict[str, str]:
    """The variant a measurement file names (``device.variant`` or ``filter.variant``), as
    ``{name: text}``. Empty if it has none, or if it is not valid (see ``problem``)."""
    for group in VARIANT_GROUPS:
        item = params.get(group)
        value = item.get("variant") if isinstance(item, Mapping) else None
        if value and problem(value) is None:
            return {str(k).strip(): str(v).strip() for k, v in value.items()}
    return {}


def variant_text(variant: Mapping[str, Any]) -> str:
    """The variant on one line, for a list or a label: ``R100=100 ohm, fan=on``."""
    return ", ".join(f"{name}={value}" for name, value in variant.items())


def problem(value: Any) -> Optional[str]:
    """What is wrong with a variant (a sentence), or None if it can be used: an object of names
    and values, the names text and not empty, the values text or numbers."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return "the variant is a list of name = value"
    for name, item in value.items():
        if not isinstance(name, str) or not name.strip():
            return "a name of the variant cannot be empty"
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            return f"the value of {name!r} must be text or a number"
    return None


def parse_lines(text: str) -> Dict[str, str]:
    """``name = value`` lines to a variant. ``ValueError`` with the number of the first line that
    is not one, has no name or value, or repeats a name."""
    out: Dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or not name or not value or name in out:
            raise ValueError(str(number))
        out[name] = value
    return out


def format_lines(variant: Mapping[str, Any]) -> str:
    """A variant as ``name = value`` lines, one per line."""
    return "\n".join(f"{name} = {value}" for name, value in variant.items())


__all__ = ["VARIANT_GROUPS", "format_lines", "parse_lines", "problem", "variant_of", "variant_text"]
