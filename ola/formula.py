# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Safe arithmetic formulas for derived quantities (efficiency, power, loss...).

A formula is plain arithmetic over *names*: ``100 * pout / pin``. A name is a parameter
(``vin``), a reading of a parameter (``vin@daq``) or another derived quantity (``pin``).
Numbers, ``+ - * / **``, parentheses and the functions ``abs min max sqrt log log10 exp`` are the
whole language: it is parsed with ``ast`` and evaluated by this module, **never with ``eval``**,
so a formula coming from a project file cannot run code.

A formula that cannot be computed for a given point (division by zero, a missing value, the
square root of a negative number) gives ``None`` for that point instead of stopping the
measurement.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Any, Callable, Dict, FrozenSet, Mapping, Optional

MAX_LENGTH = 500
_AT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)@([A-Za-z_][A-Za-z0-9_]*)\b")
_SEP = "__at__"

FUNCTIONS: Dict[str, Callable[..., float]] = {
    "abs": abs,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
}
_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}


class FormulaError(ValueError):
    """The formula is not valid (the message says why, in words a user can act on)."""


class Formula:
    """A parsed formula. ``Formula("100 * pout / pin").names`` is ``{"pout", "pin"}``."""

    def __init__(self, text: str):
        if not isinstance(text, str) or not text.strip():
            raise FormulaError("the formula is empty")
        if len(text) > MAX_LENGTH:
            raise FormulaError(f"the formula is too long (more than {MAX_LENGTH} characters)")
        self.text = text.strip()
        mangled = _AT.sub(lambda m: f"{m.group(1)}{_SEP}{m.group(2)}", self.text)
        if "@" in mangled:
            raise FormulaError("'@' must join a parameter and a reading, like vin@daq")
        if "__" in self.text:
            raise FormulaError("names cannot contain two underscores in a row")
        try:
            tree = ast.parse(mangled, mode="eval")
        except SyntaxError as exc:
            raise FormulaError(f"syntax error in the formula: {exc.msg}") from None
        self._tree = tree.body
        names = set()
        self._check(self._tree, names)
        self.names: FrozenSet[str] = frozenset(names)

    # ----- checking ---------------------------------------------------------------------
    def _check(self, node: ast.AST, names: set) -> None:
        if isinstance(node, ast.BinOp):
            if type(node.op) not in _BINARY:
                raise FormulaError("only + - * / and ** are allowed")
            self._check(node.left, names)
            self._check(node.right, names)
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.UAdd, ast.USub)):
                raise FormulaError("only the signs + and - are allowed before a value")
            self._check(node.operand, names)
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise FormulaError(f"only numbers are allowed, not {node.value!r}")
        elif isinstance(node, ast.Name):
            if node.id in FUNCTIONS:
                raise FormulaError(f"'{node.id}' is a function: write {node.id}(...)")
            names.add(node.id.replace(_SEP, "@"))
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                allowed = ", ".join(sorted(FUNCTIONS))
                raise FormulaError(f"unknown function; the functions are: {allowed}")
            if node.keywords or not node.args:
                raise FormulaError(f"{node.func.id}() takes plain values")
            for arg in node.args:
                self._check(arg, names)
        else:
            raise FormulaError("only arithmetic is allowed in a formula")

    # ----- evaluation ----------------------------------------------------------------------
    def evaluate(self, values: Mapping[str, Any]) -> Optional[float]:
        """Value of the formula for ``values`` (name to number), or ``None`` if it cannot be
        computed (missing/``None`` value, division by zero, overflow, out-of-domain function)."""
        try:
            result = self._eval(self._tree, values)
        except (ZeroDivisionError, OverflowError, ValueError):
            return None
        if result is None or isinstance(result, complex) or not math.isfinite(result):
            return None
        return float(result)

    def _eval(self, node: ast.AST, values: Mapping[str, Any]) -> Optional[float]:
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            value = values.get(node.id.replace(_SEP, "@"))
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return float(value)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, values)
            if operand is None:
                return None
            return -operand if isinstance(node.op, ast.USub) else operand
        if isinstance(node, ast.BinOp):
            left, right = self._eval(node.left, values), self._eval(node.right, values)
            if left is None or right is None:
                return None
            return _BINARY[type(node.op)](left, right)
        args = [self._eval(a, values) for a in node.args]  # ast.Call (checked at parse time)
        if any(a is None for a in args):
            return None
        return FUNCTIONS[node.func.id](*args)
