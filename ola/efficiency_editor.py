"""The model behind the efficiency editor dialog: no Qt, fully testable.

The dialog shows and edits the ``params`` of an ``.eff`` file (see ``ola/efficiency_spec.py``).
This class owns that dictionary and offers the operations a user does with the mouse:

* add, remove, duplicate and **move** parameters (the order of the list is the order of the sweeps);
* **rename** a parameter or a reading label: formulas, the power order and the checks that use
  the old name are updated, so nothing silently breaks;
* edit any field by its **path** (``variables[1].set.call``, the same paths the validation uses);
* see the **problems** live (``problems()``), the names a formula may use, the values of a sweep
  and the estimated duration.

Every change is a method call, so the dialog is a thin layer and the behaviour is tested here.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Collection, Dict, List, Optional, Sequence, Union

from .efficiency_spec import CallChecker, Problem, parse_params, validate_params
from .project import MeasurementFile
from .sweep import SweepError, axis_values

_SEGMENT = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SWEEP_MODES = ("none", "fixed", "list", "points", "step", "log")


class EditorError(ValueError):
    """An operation of the editor cannot be done (the message says why)."""


# ---- paths -----------------------------------------------------------------------------------


def split_path(path: str) -> List[Union[str, int]]:
    """``"variables[1].set.call"`` -> ``["variables", 1, "set", "call"]``."""
    out: List[Union[str, int]] = []
    for key, index in _SEGMENT.findall(path):
        out.append(int(index) if index != "" else key)
    return out


def get_path(data: Any, path: str, default: Any = None) -> Any:
    """The value at ``path``, or ``default`` if any step is missing."""
    node = data
    for step in split_path(path):
        try:
            node = node[step]
        except (KeyError, IndexError, TypeError):
            return default
    return node


def set_path(data: Any, path: str, value: Any) -> None:
    """Set the value at ``path``, creating missing dictionaries on the way. ``value=None`` removes
    the key (an empty field in the dialog means "not given"). Lists must already be long enough."""
    steps = split_path(path)
    if not steps:
        raise EditorError("empty path")
    node = data
    for step, following in zip(steps[:-1], steps[1:]):
        if isinstance(step, int):
            try:
                node = node[step]
            except (IndexError, TypeError):
                raise EditorError(f"no item {step} in {path}") from None
        else:
            if not isinstance(node, dict):
                raise EditorError(f"cannot set {path}: {step!r} is not inside an object")
            if not isinstance(node.get(step), (dict, list)):
                if value is None:
                    return  # removing something whose parent does not exist: nothing to do
                node[step] = [] if isinstance(following, int) else {}
            node = node[step]
    last = steps[-1]
    if isinstance(last, int):
        raise EditorError("cannot replace a list item by path")
    if not isinstance(node, dict):
        raise EditorError(f"cannot set {path}")
    if value is None:
        node.pop(last, None)
    else:
        node[last] = value


def _replace_name(text: str, old: str, new: str) -> str:
    """Rename ``old`` to ``new`` in a formula (also in ``old@label``), whole names only."""
    return re.sub(rf"(?<![A-Za-z0-9_@]){re.escape(old)}(?![A-Za-z0-9_])", new, text)


def _replace_reading(text: str, parameter: str, old: str, new: str) -> str:
    """Rename the reading label of ``parameter`` in a formula (``parameter@old``)."""
    pattern = rf"(?<![A-Za-z0-9_@]){re.escape(parameter)}@{re.escape(old)}(?![A-Za-z0-9_])"
    return re.sub(pattern, f"{parameter}@{new}", text)


# ---- the editor ------------------------------------------------------------------------------


class EfficiencyEditor:
    """Owns the ``params`` of an efficiency measurement and the operations on them."""

    def __init__(
        self,
        params: Optional[dict] = None,
        instruments: Optional[Collection[str]] = None,
        checker: Optional[CallChecker] = None,
    ):
        self.params: dict = copy.deepcopy(params) if params else {"variables": []}
        self.params.setdefault("variables", [])
        self.instruments = None if instruments is None else sorted(instruments)
        self.checker = checker
        self._problems: Optional[List[Problem]] = None

    # ----- loading and saving ------------------------------------------------------------------
    @staticmethod
    def template(instruments: Sequence[str] = ()) -> dict:
        """A starting point for a converter: input and output voltage and current, efficiency."""
        first = instruments[0] if instruments else ""

        def reading() -> dict:
            return {"daq": {"instrument": first, "call": ""}}

        def setter() -> dict:
            return {"instrument": first, "call": ""}

        return {
            "variables": [
                {
                    "name": "iout",
                    "set": setter(),
                    "sweep": {"start": 0.5, "stop": 2.5, "points": 5},
                },
                {"name": "vin", "set": setter(), "sweep": {"values": [9, 12, 15]}},
                {"name": "iin", "reads": reading()},
                {"name": "vout", "reads": reading()},
            ],
            "timing": {"settle_s": 5, "samples": 3, "interval_s": 2},
            "derived": {
                "pin": "vin * iin@daq",
                "pout": "vout@daq * iout",
                "efficiency": "100 * pout / pin",
            },
        }

    @classmethod
    def from_file(cls, path: str, **kwargs: Any) -> "EfficiencyEditor":
        """Open a ``.eff`` file (a measurement file of type ``efficiency``)."""
        measurement = MeasurementFile.load(path)
        if measurement.type != "efficiency":
            raise EditorError(f"{path} is a '{measurement.type}' file, not an efficiency file")
        return cls(measurement.params, **kwargs)

    def to_measurement_file(self) -> MeasurementFile:
        """The measurement file to save: the params and the instruments they use as role binding."""
        return MeasurementFile(
            type="efficiency",
            module_version="1.0.0",
            role_bindings={"instruments": self.used_instruments()},
            params=copy.deepcopy(self.params),
        )

    def save(self, path: str) -> None:
        """Write the ``.eff`` file."""
        self.to_measurement_file().save(path)

    def used_instruments(self) -> List[str]:
        """The names of all the instruments referenced anywhere in the parameters, sorted."""
        found: set = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                name = node.get("instrument")
                if isinstance(name, str) and name:
                    found.add(name)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(self.params)
        return sorted(found)

    # ----- generic access ----------------------------------------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        """The value of a field by path."""
        return get_path(self.params, path, default)

    def set(self, path: str, value: Any) -> None:
        """Set a field by path; ``None`` removes it."""
        set_path(self.params, path, value)
        self._problems = None

    # ----- parameters --------------------------------------------------------------------------
    @property
    def variables(self) -> List[dict]:
        """The ordered list of parameters (dictionaries)."""
        return self.params["variables"]

    def names(self) -> List[str]:
        """The parameter names, in list order."""
        return [v.get("name", "") for v in self.variables]

    def _unique_name(self, base: str) -> str:
        taken = set(self.names())
        if base not in taken:
            return base
        n = 2
        while f"{base}{n}" in taken:
            n += 1
        return f"{base}{n}"

    def add_parameter(self, name: Optional[str] = None) -> int:
        """Append an empty parameter; returns its position."""
        self.variables.append({"name": self._unique_name(name or "param")})
        self._problems = None
        return len(self.variables) - 1

    def duplicate_parameter(self, index: int) -> int:
        """Copy a parameter right after itself (with a new name); returns the new position."""
        self._check(index)
        clone = copy.deepcopy(self.variables[index])
        clone["name"] = self._unique_name(clone.get("name", "param"))
        self.variables.insert(index + 1, clone)
        self._problems = None
        return index + 1

    def remove_parameter(self, index: int) -> None:
        """Remove a parameter (and its name from the power order). Formulas that used it show up
        in the problems list instead of being silently changed."""
        self._check(index)
        name = self.variables[index].get("name")
        del self.variables[index]
        order = self.params.get("power_order")
        if isinstance(order, list) and name in order:
            order.remove(name)
        self._problems = None

    def move_parameter(self, index: int, delta: int) -> int:
        """Move a parameter up (``delta=-1``) or down (``+1``); returns its new position. The
        first position is the fastest sweep and the first to be set."""
        self._check(index)
        target = index + delta
        if not 0 <= target < len(self.variables):
            return index
        self.variables[index], self.variables[target] = (
            self.variables[target],
            self.variables[index],
        )
        self._problems = None
        return target

    def rename_parameter(self, index: int, new: str) -> List[str]:
        """Rename a parameter. Its uses in the formulas and in ``power_order`` follow. Returns the
        names of the formulas that were changed. ``EditorError`` if the new name is not usable."""
        self._check(index)
        old = self.variables[index].get("name", "")
        if new == old:
            return []
        if not _IDENT.match(new) or "__" in new:
            raise EditorError(
                f"'{new}' is not a valid name (letters, digits, '_'; not starting with a digit)"
            )
        if new in self.names() or new in (self.params.get("derived") or {}):
            raise EditorError(f"the name '{new}' is already used")
        self.variables[index]["name"] = new
        changed = self._rewrite_formulas(lambda text: _replace_name(text, old, new))
        order = self.params.get("power_order")
        if isinstance(order, list):
            self.params["power_order"] = [new if n == old else n for n in order]
        self._problems = None
        return changed

    def _rewrite_formulas(self, function: Any) -> List[str]:
        derived = self.params.get("derived")
        changed: List[str] = []
        if isinstance(derived, dict):
            for name, text in list(derived.items()):
                if isinstance(text, str) and function(text) != text:
                    derived[name] = function(text)
                    changed.append(name)
        return changed

    def _check(self, index: int) -> None:
        if not 0 <= index < len(self.variables):
            raise EditorError(f"there is no parameter at position {index}")

    # ----- readings ----------------------------------------------------------------------------
    def reading_labels(self, index: int) -> List[str]:
        """The labels of the readings of a parameter."""
        self._check(index)
        reads = self.variables[index].get("reads")
        return list(reads) if isinstance(reads, dict) else []

    def add_reading(self, index: int, label: Optional[str] = None) -> str:
        """Add an empty reading to a parameter; returns its label."""
        self._check(index)
        reads = self.variables[index].setdefault("reads", {})
        label = label or "reading"
        unique, n = label, 2
        while unique in reads:
            unique, n = f"{label}{n}", n + 1
        reads[unique] = {}
        self._problems = None
        return unique

    def remove_reading(self, index: int, label: str) -> None:
        """Remove a reading (a ``verify`` that used it is removed too)."""
        self._check(index)
        var = self.variables[index]
        (var.get("reads") or {}).pop(label, None)
        if not var.get("reads"):
            var.pop("reads", None)
        if isinstance(var.get("verify"), dict) and var["verify"].get("read") == label:
            del var["verify"]
        self._problems = None

    def rename_reading(self, index: int, old: str, new: str) -> List[str]:
        """Rename a reading label; formulas and ``verify`` follow. Returns the changed formulas."""
        self._check(index)
        var = self.variables[index]
        reads = var.get("reads") or {}
        if old not in reads:
            raise EditorError(f"there is no reading '{old}'")
        if new == old:
            return []
        if not _IDENT.match(new) or "__" in new:
            raise EditorError(f"'{new}' is not a valid label")
        if new in reads:
            raise EditorError(f"the label '{new}' is already used")
        var["reads"] = {(new if k == old else k): v for k, v in reads.items()}  # keeps the order
        if isinstance(var.get("verify"), dict) and var["verify"].get("read") == old:
            var["verify"]["read"] = new
        name = var.get("name", "")
        changed = self._rewrite_formulas(lambda text: _replace_reading(text, name, old, new))
        self._problems = None
        return changed

    # ----- sweeps ------------------------------------------------------------------------------
    def sweep_mode(self, index: int) -> str:
        """``none`` (not set / nothing), ``fixed``, ``list``, ``points``, ``step`` or ``log``."""
        self._check(index)
        var = self.variables[index]
        if "value" in var:
            return "fixed"
        sweep = var.get("sweep")
        if not isinstance(sweep, dict):
            return "none"
        if "values" in sweep:
            return "list"
        if sweep.get("scale") == "log":
            return "log"
        return "step" if "step" in sweep else "points"

    def set_sweep_mode(self, index: int, mode: str) -> None:
        """Switch how a parameter gets its value, keeping sensible defaults for the new mode."""
        self._check(index)
        if mode not in SWEEP_MODES:
            raise EditorError(f"unknown mode '{mode}'")
        var = self.variables[index]
        previous = self.sweep_values(index) or []
        var.pop("value", None)
        var.pop("sweep", None)
        first = previous[0] if previous else 0.0
        last = previous[-1] if previous else 1.0
        if mode == "fixed":
            var["value"] = first
        elif mode == "list":
            var["sweep"] = {"values": previous or [first]}
        elif mode == "points":
            var["sweep"] = {"start": first, "stop": last, "points": max(2, len(previous) or 5)}
        elif mode == "step":
            var["sweep"] = {"start": first, "stop": last if last != first else first + 1, "step": 1}
        elif mode == "log":
            lo = first if first > 0 else 1.0
            var["sweep"] = {"start": lo, "stop": max(last, lo * 10), "points": 5, "scale": "log"}
        self._problems = None

    def sweep_values(self, index: int) -> Optional[List[float]]:
        """The values the parameter takes (sweep values or the fixed one); ``None`` if not valid."""
        self._check(index)
        var = self.variables[index]
        if "value" in var:
            value = var["value"]
            return (
                [float(value)]
                if isinstance(value, (int, float)) and not isinstance(value, bool)
                else None
            )
        if not isinstance(var.get("sweep"), dict):
            return None
        try:
            return axis_values(var["sweep"])
        except SweepError:
            return None

    def sweep_error(self, index: int) -> Optional[str]:
        """Why the sweep of a parameter is not valid, or ``None``."""
        self._check(index)
        sweep = self.variables[index].get("sweep")
        if not isinstance(sweep, dict):
            return None
        try:
            axis_values(sweep)
        except SweepError as exc:
            return str(exc)
        return None

    # ----- formulas, names ---------------------------------------------------------------------
    def set_formula(self, name: str, text: str) -> None:
        """Add or change a derived quantity."""
        if not _IDENT.match(name) or "__" in name:
            raise EditorError(f"'{name}' is not a valid name")
        if name in self.names():
            raise EditorError(f"'{name}' is already a parameter")
        self.params.setdefault("derived", {})[name] = text
        self._problems = None

    def remove_formula(self, name: str) -> None:
        """Remove a derived quantity."""
        derived = self.params.get("derived")
        if isinstance(derived, dict):
            derived.pop(name, None)
            if not derived:
                del self.params["derived"]
        self._problems = None

    def rename_formula(self, old: str, new: str) -> List[str]:
        """Rename a derived quantity; the other formulas that use it follow. Returns those."""
        derived = self.params.get("derived") or {}
        if old not in derived:
            raise EditorError(f"there is no formula '{old}'")
        if new == old:
            return []
        if not _IDENT.match(new) or "__" in new:
            raise EditorError(f"'{new}' is not a valid name")
        if new in derived or new in self.names():
            raise EditorError(f"the name '{new}' is already used")
        self.params["derived"] = {(new if k == old else k): v for k, v in derived.items()}
        changed = self._rewrite_formulas(lambda text: _replace_name(text, old, new))
        self._problems = None
        return [n for n in changed if n != new] + ([new] if new in changed else [])

    def available_names(self) -> Dict[str, List[str]]:
        """The names a formula may use: ``setpoints`` (``vin``), ``readings`` (``vin@daq``) and
        ``derived`` (the other formulas)."""
        setpoints, readings = [], []
        for var in self.variables:
            name = var.get("name")
            if not isinstance(name, str) or not name:
                continue
            if isinstance(var.get("set"), dict):
                setpoints.append(name)
            for label in var.get("reads") or {}:
                readings.append(f"{name}@{label}")
        derived = list(self.params.get("derived") or {})
        return {"setpoints": setpoints, "readings": readings, "derived": derived}

    # ----- startup and shutdown calls ----------------------------------------------------------
    def calls(self, section: str) -> List[dict]:
        """The extra calls of ``startup`` or ``shutdown``."""
        if section not in ("startup", "shutdown"):
            raise EditorError(f"unknown section '{section}'")
        items = self.params.get(section)
        return items if isinstance(items, list) else []

    def add_call(self, section: str) -> int:
        """Append an empty call to ``startup`` or ``shutdown``; returns its position."""
        items = self.calls(section)
        if section not in self.params:
            self.params[section] = items
        items.append({"instrument": "", "call": ""})
        self._problems = None
        return len(items) - 1

    def remove_call(self, section: str, index: int) -> None:
        """Remove one extra call (the section disappears when it is empty)."""
        items = self.calls(section)
        if not 0 <= index < len(items):
            raise EditorError(f"there is no call {index} in {section}")
        del items[index]
        if not items:
            self.params.pop(section, None)
        self._problems = None

    # ----- power order -------------------------------------------------------------------------
    def managed_outputs(self) -> List[str]:
        """The outputs the program switches (not the always-on ones), in the default order."""
        out = []
        for var in self.variables:
            output = var.get("output")
            if isinstance(output, dict) and output.get("mode") != "always_on" and output.get("on"):
                out.append(var.get("name", ""))
        return out

    def power_order(self) -> List[str]:
        """The switch-on order in use: the explicit ``power_order`` or the default one."""
        explicit = self.params.get("power_order")
        managed = self.managed_outputs()
        if isinstance(explicit, list):
            kept = [n for n in explicit if n in managed]
            return kept + [n for n in managed if n not in kept]
        return managed

    def set_power_order(self, order: Sequence[str]) -> None:
        """Fix the switch-on order explicitly."""
        self.params["power_order"] = list(order)
        self._problems = None

    def move_power(self, position: int, delta: int) -> int:
        """Move one output up or down in the power order; returns its new position."""
        order = self.power_order()
        target = position + delta
        if not (0 <= position < len(order) and 0 <= target < len(order)):
            return position
        order[position], order[target] = order[target], order[position]
        self.set_power_order(order)
        return target

    def reset_power_order(self) -> None:
        """Go back to the default order (the order of the parameter list)."""
        self.params.pop("power_order", None)
        self._problems = None

    # ----- validation and summary --------------------------------------------------------------
    def problems(self) -> List[Problem]:
        """The problems of the parameters now (cached until the next change)."""
        if self._problems is None:
            self._problems = validate_params(self.params, self.instruments, self.checker)
        return self._problems

    def problems_at(self, prefix: str) -> List[Problem]:
        """The problems of a field, or of everything under it (``variables[1]``: all its fields)."""
        return [
            p
            for p in self.problems()
            if p.path == prefix or p.path.startswith((prefix + ".", prefix + "["))
        ]

    def has_errors(self) -> bool:
        """True if the measurement could not start with these parameters."""
        return any(p.severity == "error" for p in self.problems())

    def summary(self) -> Dict[str, Any]:
        """What the measurement would do, when the parameters are valid: points, sweeps,
        cooldowns and the time spent waiting. ``valid`` is False (and the rest empty) otherwise."""
        if self.has_errors():
            return {"valid": False}
        spec = parse_params(self.params, self.instruments, self.checker)
        return {
            "valid": True,
            "points": spec.point_count(),
            "sweeps": spec.point_count() // spec.sweep_length() if spec.sweep_length() else 1,
            "cooldowns": spec.cooldown_count(),
            "seconds": spec.estimated_seconds(),
            "axes": [(name, len(values)) for name, values in spec.axes],
        }

    @staticmethod
    def format_duration(seconds: float) -> str:
        """``3725`` -> ``"1 h 2 min"``."""
        seconds = int(round(seconds))
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return f"{hours} h {minutes} min"
        if minutes:
            return f"{minutes} min {secs} s" if secs else f"{minutes} min"
        return f"{secs} s"
