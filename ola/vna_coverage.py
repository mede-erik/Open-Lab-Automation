# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What a calibration corrects: which S-parameters, and how well (no Qt).

A VNA measurement reads some S-parameters (``S21`` is received at port 2 and driven from port 1, the
numbers are the analyzer's); the calibration applied to the analyzer corrects some of them.
``coverage`` says, for a calibration kind and its ports, the level of correction of each
S-parameter; ``problems`` compares it with the parameters a measurement reads and returns the
sentences for the log. The measurements read the parameters they need, so no module has to say what
calibration it wants: ``ola.vna_common.acquire`` does the check.

The levels follow the error model: a **normalisation** (one standard) corrects the tracking only; a
full **one-port** calibration corrects directivity, source match and tracking of the reflection; the
**enhanced response** adds a transmission corrected for the source match; the two-port kinds
(SOLT, TOSM, UOSM, TOM, TSM, TRM, TRL, TNA) correct all four parameters. Nothing here stops a run:
the operator may know better (a normalisation is common practice for a cable loss).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

NONE, NORMALIZED, PARTIAL, FULL = 0, 1, 2, 3

# the kinds that correct all four S-parameters of a pair of ports
TWO_PORT_KINDS = (
    "TWO_PORT",
    "TWO_PORT_UNKNOWN_THRU",
    "TOM",
    "TSM",
    "TRM",
    "TRL",
    "TNA",
)

_PARAMETER = re.compile(r"^S([1-9])([1-9])$")

# what to make when a parameter is not corrected: the kind that does it
_REMEDY = {
    "reflection": "a one-port calibration (open, short, load)",
    "forward": "a transmission response (thru) or, better, an enhanced response",
    "reverse": "a two-port calibration (the analyzer must measure in both directions)",
}


def coverage(kind: str, port: int = 1, port2: Optional[int] = None) -> Dict[Tuple[int, int], int]:
    """``{(receiving port, driven port): level}`` of the parameters the calibration corrects, in
    the port numbers of the analyzer. A parameter that is missing is not corrected.

    ``port`` is the source port (and the only port of a one-port kind), ``port2`` the other one."""
    p, q = port, port2
    if kind == "ONE_PORT":
        return {(p, p): FULL}
    if kind in ("REFLECTION_OPEN", "REFLECTION_SHORT"):
        return {(p, p): NORMALIZED}
    if q is None or q == p:
        return {}
    if kind == "TRANSMISSION_RESPONSE":
        return {(q, p): NORMALIZED}
    if kind == "TRANSMISSION_RESPONSE_BOTH":
        return {(q, p): NORMALIZED, (p, q): NORMALIZED}
    if kind == "ENHANCED_RESPONSE":
        return {(p, p): FULL, (q, p): PARTIAL}
    if kind in TWO_PORT_KINDS:
        return {(p, p): FULL, (q, p): FULL, (p, q): FULL, (q, q): FULL}
    return {}


def levels(
    kind: str, parameters: Sequence[str], port: int = 1, port2: Optional[int] = None
) -> Dict[str, int]:
    """``{parameter: level}`` for the parameters a measurement reads. ``S21`` is the analyzer's
    own: received at port 2, driven from port 1; ``port`` and ``port2`` are the analyzer ports the
    calibration was made on."""
    cover = coverage(kind, port, port2)
    out = {}
    for name in parameters:
        match = _PARAMETER.match(name)
        out[name] = cover.get((int(match.group(1)), int(match.group(2))), NONE) if match else NONE
    return out


def _role(parameter: str) -> str:
    receiving, driven = parameter[1], parameter[2]
    if receiving == driven:
        return "reflection"
    return "forward" if (receiving, driven) == ("2", "1") else "reverse"


def problems(info: Mapping[str, Any], parameters: Sequence[str]) -> List[str]:
    """The warnings for the log when a measurement reads ``parameters`` with the calibration
    ``info`` (the ``handle.calibration`` of the connection: its ``kind`` and ports). Empty when
    nothing is known about the calibration or everything is corrected well enough."""
    kind = (info or {}).get("kind")
    if not kind:
        return []
    port = int(info.get("port") or 1)
    port2 = info.get("port2")
    port2 = int(port2) if port2 else None
    out = []
    for name, level in levels(kind, parameters, port, port2).items():
        if not _PARAMETER.match(name):
            continue
        role = _role(name)
        if level == NONE:
            out.append(
                f"{name} is not corrected by the calibration made with the program ({kind}): "
                f"it needs {_REMEDY[role]}. The values of {name} are not calibrated."
            )
        elif level == NORMALIZED and role == "reflection":
            out.append(
                f"{name} is corrected only in tracking by the calibration made with the program "
                f"({kind}): directivity and source match are not corrected, so the reflection of a "
                "good device can be wrong by several dB. A one-port calibration (open, short, "
                "load) is better."
            )
    return out
