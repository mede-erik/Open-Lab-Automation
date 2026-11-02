"""The unit of work of a call: one step (write, query or delay).

Shape agreed with the library/planner session (PLAN.md 7.2):

    {"op": "write"|"query"|"delay", "text": "...", "ms": 100,
     "timeout_ms": 5000, "returns": "float"|"int"|"string"|"binary"}

``text`` is the final string (placeholders already substituted, no terminator).
Unknown fields are rejected so typos fail loudly when the plan is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

OPS = ("write", "query", "delay")
RETURNS = ("string", "float", "int", "binary")
_FIELDS = {"op", "text", "ms", "timeout_ms", "returns"}


@dataclass(frozen=True)
class Step:
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
        if self.op == "delay":
            if self.ms is None or self.ms < 0:
                raise ValueError("'delay' step needs 'ms' >= 0")
            if self.text is not None or self.timeout_ms is not None:
                raise ValueError("'delay' step accepts only 'ms'")
        if self.returns not in RETURNS:
            raise ValueError(f"'returns' must be one of {RETURNS}, got {self.returns!r}")
        if self.op != "query" and self.returns != "string":
            raise ValueError("'returns' is only valid for 'query' steps")
        if self.timeout_ms is not None and self.timeout_ms <= 0:
            raise ValueError("'timeout_ms' must be > 0")

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "Step":
        unknown = set(d) - _FIELDS
        if unknown:
            raise ValueError(f"unknown step field(s): {sorted(unknown)}")
        if "op" not in d:
            raise ValueError("step without 'op'")
        return Step(**d)

    @staticmethod
    def coerce(step) -> "Step":
        return step if isinstance(step, Step) else Step.from_dict(step)
