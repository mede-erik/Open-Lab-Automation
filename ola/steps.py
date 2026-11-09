# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The unit of work of a call: one step (write, query or delay).

Shape agreed with the library/planner session (PLAN.md 7.2):

    {"op": "write"|"query"|"read"|"delay", "text": "...", "ms": 100,
     "timeout_ms": 5000, "returns": "float"|"int"|"string"|"binary"}

``text`` is the final string (placeholders already substituted, no terminator).
``read`` reads an answer WITHOUT sending anything first, for instruments that talk when
addressed (e.g. the HP 3478A over GPIB); it takes ``returns`` and ``timeout_ms`` like ``query``.
Unknown fields are rejected so typos fail loudly when the plan is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

OPS = ("write", "query", "read", "delay")
RETURNS = ("string", "float", "int", "binary")
_FIELDS = {"op", "text", "ms", "timeout_ms", "returns"}


@dataclass(frozen=True)
class Step:
    """One unit of work of a call; immutable and validated when created."""

    op: str
    text: Optional[str] = None
    ms: Optional[float] = None
    timeout_ms: Optional[int] = None
    returns: str = "string"

    def __post_init__(self):
        if self.op not in OPS:
            raise ValueError(f"step op must be one of {OPS}, got {self.op!r}")
        if self.op in ("write", "query"):
            if not isinstance(self.text, str) or not self.text:
                raise ValueError(f"'{self.op}' step needs a non-empty 'text'")
            if self.ms is not None:
                raise ValueError(f"'{self.op}' step must not have 'ms'")
        if self.op == "read":
            if self.text is not None or self.ms is not None:
                raise ValueError("'read' step takes no 'text' and no 'ms' (it sends nothing)")
        if self.op == "delay":
            if self.ms is None or self.ms < 0:
                raise ValueError("'delay' step needs 'ms' >= 0")
            if self.text is not None or self.timeout_ms is not None:
                raise ValueError("'delay' step accepts only 'ms'")
        if self.returns not in RETURNS:
            raise ValueError(f"'returns' must be one of {RETURNS}, got {self.returns!r}")
        if self.op not in ("query", "read") and self.returns != "string":
            raise ValueError("'returns' is only valid for 'query' and 'read' steps")
        if self.timeout_ms is not None and self.timeout_ms <= 0:
            raise ValueError("'timeout_ms' must be > 0")

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "Step":
        """Build a step from a dict; unknown fields are rejected."""
        unknown = set(d) - _FIELDS
        if unknown:
            raise ValueError(f"unknown step field(s): {sorted(unknown)}")
        if "op" not in d:
            raise ValueError("step without 'op'")
        return Step(**d)

    @staticmethod
    def coerce(step) -> "Step":
        """Return ``step`` as a ``Step`` (accepts a ``Step`` or a dict)."""
        return step if isinstance(step, Step) else Step.from_dict(step)
