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
comparison and the history of a DUT show it next to each run. In the editors it is a table of
names and values (``parse_lines`` and ``format_lines`` read and write the same as text lines).

The measurements listed in ``ASK_FOR_VARIANT`` that name a DUT ask for the variant every time they
start: ``previous_variants`` gives the variants of the earlier runs of that DUT (the newest is
proposed, the names are suggested) and ``with_variant`` gives the parameters of the run with the
answer, so that the file of the measurement is not changed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

VARIANT_GROUPS = ("device", "filter")  # where a measurement file names its DUT and its variant
# the measurements that ask for the variant when they start (those that name a DUT and whose device
# changes between runs: a part of the bill of materials, a fan on or off)
ASK_FOR_VARIANT = ("efficiency", "resistive_efficiency", "regulation", "ripple")


def variant_of(params: Mapping[str, Any]) -> Dict[str, str]:
    """The variant a measurement file names (``device.variant`` or ``filter.variant``), as
    ``{name: text}``. Empty if it has none, or if it is not valid (see ``problem``)."""
    for group in VARIANT_GROUPS:
        item = params.get(group)
        value = item.get("variant") if isinstance(item, Mapping) else None
        if value and problem(value) is None:
            return {str(k).strip(): str(v).strip() for k, v in value.items()}
    return {}


def dut_group(params: Mapping[str, Any]) -> Optional[str]:
    """The group of the parameters that names a DUT (``device`` or ``filter``), or None."""
    for group in VARIANT_GROUPS:
        item = params.get(group)
        if isinstance(item, Mapping) and item.get("dut_id"):
            return group
    return None


def with_variant(params: Mapping[str, Any], variant: Mapping[str, Any]) -> Dict[str, Any]:
    """A copy of the parameters with ``variant`` as the variant of the DUT they name (an empty
    variant removes it). The parameters themselves, and so the file, are not changed."""
    out = copy.deepcopy(dict(params))
    group = dut_group(out)
    if group is None:
        raise ValueError("the measurement does not name a DUT")
    clean = {str(k).strip(): str(v).strip() for k, v in variant.items() if str(k).strip()}
    if clean:
        out[group]["variant"] = clean
    else:
        out[group].pop("variant", None)
    return out


def previous_variants(run_dir: Union[str, Path], dut_id: str) -> List[Dict[str, str]]:
    """The variants of the earlier runs of a DUT in a folder of run files, the newest run first
    (a run without a variant gives ``{}``). Only the first line of each file is read."""
    found: List[Tuple[float, Dict[str, str]]] = []
    folder = Path(run_dir)
    if not folder.is_dir():
        return []
    for path in folder.glob("*.jsonl"):
        try:
            with open(path, encoding="utf-8") as f:
                header = json.loads(f.readline())
            params = header.get("params") if header.get("kind") == "run" else None
            if not isinstance(params, Mapping):
                continue
            group = dut_group(params)
            if group is None or params[group].get("dut_id") != dut_id:
                continue
            found.append((path.stat().st_mtime, variant_of(params)))
        except (OSError, ValueError, AttributeError):
            continue  # a file that is not a run, or cannot be read: not a source of suggestions
    return [variant for _t, variant in sorted(found, key=lambda item: -item[0])]


def variant_names(variants: Iterable[Mapping[str, Any]]) -> List[str]:
    """The names used in these variants, the most used first (to suggest them again)."""
    count: Dict[str, int] = {}
    for variant in variants:
        for name in variant:
            count[name] = count.get(name, 0) + 1
    return sorted(count, key=lambda n: (-count[n], n))


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


__all__ = [
    "ASK_FOR_VARIANT", "VARIANT_GROUPS", "dut_group", "format_lines", "parse_lines",
    "previous_variants", "problem", "variant_names", "variant_of", "variant_text", "with_variant",
]  # fmt: skip
