"""The efficiency measurement: description of the parameters, and their validation.

This module has two jobs and no I/O, no Qt:

* ``validate_params(params, bound_instruments, checker)`` returns the list of ``Problem`` found in
  the parameters. It is fast and meant to be called **while the user fills in the dialog** (every
  edit), so every problem carries the ``path`` of the field it is about (``variables.vin.set.call``,
  ``derived.pin``, ``sweeps[1]``...) and a message that says what to do. The measurement calls it
  again before starting, for files edited by hand.
* ``parse_params(...)`` turns valid parameters into an ``EfficiencySpec`` the measurement runs.

The parameters (the ``params`` of an ``.eff`` file), in short::

    variables   an ORDERED LIST of parameters; each one is
                {"name": ..., "set": how to set it (optional), "value": fixed value or
                 "sweep": axis (one of them, if it is set), "reads": {label: how to read it},
                 "verify": check against a reading, "limits": {"min", "max"},
                 "output": {"on", "off", "mode"}: how its output is switched (see below)}
    timing      {"settle_s", "samples", "interval_s"}: what to do at every point
    derived     name -> formula over the names below
    startup / shutdown   extra calls made once, after the outputs are on / before they go off

The order of the list is chosen by the user and means two things: it is the order in which the
parameters are set, and it is the nesting of the sweeps. The **first** parameter changes first and
fastest (innermost sweep); the second advances one step only when the first has done its whole
sweep; and so on.

The ``output`` of a parameter says what the program may do with the output of its instrument:
``keep_on`` (default) switches it on at the start and off at the end, also after an error or a stop;
``off_during_cooldown`` also switches it off during the cooldown (see below) and on again after it;
``always_on`` switches it on at the start if an ``on`` call is given and **never switches it off**,
not even at the end, after an error or after a stop (an auxiliary supply that keeps a
microcontroller without non-volatile memory alive). Outputs go on in the order of the list and
off in the reverse order.

The **cooldown** (``timing.cooldown_s``) is a rest for the converter between two sweeps: every
time the innermost sweep (the first swept parameter of the list) has done its whole run and an
outer parameter advances, the outputs marked ``off_during_cooldown`` are switched off, the
measurement waits ``cooldown_s`` and everything is switched on again. Between the points of the
innermost sweep nothing is switched off. There is no cooldown after the last sweep.

The **power order** (``power_order``, a list of parameter names) is the order in which the outputs
are switched on; they go off in the reverse order. Outputs marked ``always_on`` are not in this
list: they are handled before it. If an output has a ``state`` call, the program asks whether it is
already on: an output that is on is left alone, one that is off is switched on (and, if it is
``always_on``, never switched off).

Names in formulas: ``vin`` is the value that was **set**, ``vin@daq`` is the **reading** labelled
``daq`` of ``vin``, ``pin`` is another derived quantity. See ``docs/efficiency.md``.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Collection, Dict, List, Mapping, Optional, Protocol, Tuple

from .formula import FUNCTIONS, Formula, FormulaError
from .sweep import SweepError, axis_values, total_points

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOP_KEYS = ("variables", "timing", "derived", "startup", "shutdown", "power_order")
OUTPUT_MODES = ("keep_on", "off_during_cooldown", "always_on")
MAX_SAMPLES = 10_000


@dataclass(frozen=True)
class Problem:
    """One thing wrong (or suspicious) in the parameters.

    ``path`` points at the field (for example ``variables.vin.set.call``), ``severity`` is
    ``"error"`` (the measurement cannot start) or ``"warning"`` (it can, but check)."""

    path: str
    message: str
    severity: str = "error"

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


class CallChecker(Protocol):
    """Optional second level of validation, supplied by the application: does this instrument
    support the call, and are the arguments (and the value) acceptable for its model and limits?"""

    def check(self, instrument: str, call: str, args: Mapping[str, Any]) -> List[str]:
        """Return the problems as readable messages (empty list if the call would be accepted)."""


class SpecError(ValueError):
    """``parse_params`` was given parameters with errors; ``problems`` lists them."""

    def __init__(self, problems: List[Problem]):
        self.problems = problems
        super().__init__("; ".join(str(p) for p in problems if p.severity == "error"))


# ---- the parsed form ------------------------------------------------------------


@dataclass(frozen=True)
class SetSpec:
    """How a parameter is set: ``call(**args, <value_arg>=value)`` on ``instrument``."""

    instrument: str
    call: str
    args: Dict[str, Any]
    value_arg: str = "value"


@dataclass(frozen=True)
class ReadSpec:
    """How a parameter is read: ``call(**args)`` on ``instrument``; result * scale + offset."""

    label: str
    instrument: str
    call: str
    args: Dict[str, Any]
    scale: float = 1.0
    offset: float = 0.0


@dataclass(frozen=True)
class VerifySpec:
    """Check that the reading ``read`` agrees with the setpoint: |reading - set| <= tol_abs +
    tol_rel * |set|. ``on_fail``: ``"ask"`` (default) stops and asks the user to retry, skip or
    abort; ``"warn"`` only writes a warning; ``"stop"`` fails the measurement without asking."""

    read: str
    tol_abs: float
    tol_rel: float
    on_fail: str


@dataclass(frozen=True)
class Variable:
    """A parameter chosen by the user (``vin``, ``vaux``, ``iin``...)."""

    name: str
    set: Optional[SetSpec]
    value: Optional[float]
    reads: Dict[str, ReadSpec]
    verify: Optional[VerifySpec]
    axis: Optional[List[float]] = None  # the values of its sweep, if it is swept
    limits: Optional[Tuple[Optional[float], Optional[float]]] = None  # allowed (min, max)
    output: Optional["OutputSpec"] = None  # how its output is switched on and off


@dataclass(frozen=True)
class Timing:
    """What happens at every point: wait ``settle_s`` after setting, then ``samples`` readings
    ``interval_s`` apart; the point is their average. ``cooldown_s`` is the rest between two
    sweeps of the innermost parameter (0: none)."""

    settle_s: float = 0.0
    samples: int = 1
    interval_s: float = 0.0
    cooldown_s: float = 0.0


@dataclass(frozen=True)
class CallSpec:
    """A call made at the start or at the end (outputs on / off)."""

    instrument: str
    call: str
    args: Dict[str, Any]


@dataclass(frozen=True)
class OutputSpec:
    """The output of the instrument that sets a parameter: ``on`` / ``off`` calls (either may be
    missing), the ``mode`` (``keep_on``, ``off_during_cooldown`` or ``always_on``) and an optional
    ``state`` call that tells whether the output is on."""

    on: Optional[CallSpec]
    off: Optional[CallSpec]
    mode: str = "keep_on"
    state: Optional[CallSpec] = None


@dataclass
class EfficiencySpec:
    """Valid parameters, ready to run."""

    variables: Dict[str, Variable]  # in the order chosen by the user
    axes: List[Tuple[str, List[float]]]  # swept parameters, innermost (fastest) first
    derived: Dict[str, Formula]  # in an order where every formula only needs earlier ones
    timing: Timing
    startup: List[CallSpec] = field(default_factory=list)
    shutdown: List[CallSpec] = field(default_factory=list)
    power_order: List[str] = field(default_factory=list)  # outputs, in switch-on order

    def point_count(self) -> int:
        """Number of points of the sweep."""
        return total_points(self.axes)

    def estimated_seconds(self) -> float:
        """Time spent waiting for the whole sweep (settling + sample intervals); the time the
        instruments need to answer is not included."""
        t = self.timing
        total = self.point_count() * (t.settle_s + (t.samples - 1) * t.interval_s)
        return total + self.cooldown_count() * t.cooldown_s

    def sweep_length(self) -> int:
        """Points in one run of the innermost sweep (0 if nothing is swept)."""
        return len(self.axes[0][1]) if self.axes else 0

    def cooldown_count(self) -> int:
        """How many cooldowns the measurement makes: one between every two runs of the innermost
        sweep (none if there is only one sweep, or if ``cooldown_s`` is 0)."""
        if self.timing.cooldown_s <= 0 or len(self.axes) < 2:
            return 0
        return self.point_count() // self.sweep_length() - 1


# ---- validation -----------------------------------------------------------------


class _Checker:
    """Collects the problems while reading the parameters (and builds the spec on the way)."""

    def __init__(
        self,
        params: Any,
        bound: Optional[Collection[str]],
        checker: Optional[CallChecker],
    ):
        self.params = params
        self.bound = None if bound is None else sorted(bound)
        self.checker = checker
        self.problems: List[Problem] = []
        self.broken_set: set = set()  # parameters whose 'set' was given but is invalid
        self.broken_reads: set = set()  # (parameter, label) of readings given but invalid

    # -- small helpers --
    def error(self, path: str, message: str) -> None:
        self.problems.append(Problem(path, message))

    def warn(self, path: str, message: str) -> None:
        self.problems.append(Problem(path, message, "warning"))

    @staticmethod
    def hint(name: str, candidates: Collection[str]) -> str:
        close = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
        return f" (did you mean '{close[0]}'?)" if close else ""

    def unknown_keys(self, obj: Mapping[str, Any], allowed: Collection[str], path: str) -> None:
        for key in obj:
            if key not in allowed:
                self.error(
                    f"{path}.{key}" if path else key,
                    f"unknown field{self.hint(str(key), allowed)}; allowed: {', '.join(allowed)}",
                )

    def number(
        self,
        obj: Mapping[str, Any],
        key: str,
        path: str,
        default: Optional[float] = None,
        minimum: Optional[float] = None,
        integer: bool = False,
        maximum: Optional[float] = None,
    ) -> Optional[float]:
        if key not in obj:
            return default
        value = obj[key]
        where = f"{path}.{key}"
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            self.error(where, f"must be a number, got {value!r}")
            return None
        if integer and (isinstance(value, float) and not value.is_integer()):
            self.error(where, f"must be a whole number, got {value!r}")
            return None
        if minimum is not None and value < minimum:
            self.error(where, f"must be at least {minimum:g}, got {value:g}")
            return None
        if maximum is not None and value > maximum:
            self.error(where, f"must be at most {maximum:g}, got {value:g}")
            return None
        return int(value) if integer else float(value)

    def identifier(self, name: Any, path: str, what: str) -> bool:
        if not isinstance(name, str) or not _IDENT.match(name):
            self.error(
                path,
                f"{what} {name!r} is not valid: letters, digits and '_', not starting with a digit",
            )
            return False
        if "__" in name:
            self.error(path, f"{what} {name!r} must not contain two underscores in a row")
            return False
        if name in FUNCTIONS:
            self.error(path, f"{what} {name!r} is the name of a function, choose another")
            return False
        return True

    def instrument(self, obj: Mapping[str, Any], path: str) -> Optional[str]:
        name = obj.get("instrument")
        if not isinstance(name, str) or not name:
            self.error(f"{path}.instrument", "the instrument is missing")
            return None
        if self.bound is not None and name not in self.bound:
            known = ", ".join(self.bound) or "none"
            self.error(
                f"{path}.instrument",
                f"instrument '{name}' is not in the project{self.hint(name, self.bound)}; "
                f"available: {known}",
            )
        return name

    def call_and_args(
        self, obj: Mapping[str, Any], path: str
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        call = obj.get("call")
        if not isinstance(call, str) or not call:
            self.error(
                f"{path}.call", "the call is missing (a call name of the instrument library)"
            )
            call = None
        args = obj.get("args", {})
        if not isinstance(args, dict):
            self.error(f"{path}.args", 'must be an object like {"channel_number": 1}')
            args = {}
        return call, dict(args)

    def library_check(
        self, instrument: Optional[str], call: Optional[str], args: Mapping[str, Any], path: str
    ) -> None:
        if self.checker is None or not instrument or not call:
            return
        for message in dict.fromkeys(self.checker.check(instrument, call, args)):
            self.error(path, message)

    # -- the sections of the parameters --
    def variables(self, raw: Any) -> Dict[str, Variable]:
        out: Dict[str, Variable] = {}
        if not isinstance(raw, list) or not raw:
            self.error("variables", 'give a list of parameters, like [{"name": "vin", ...}]')
            return out
        for i, body in enumerate(raw):
            path = f"variables[{i}]"
            if not isinstance(body, dict):
                self.error(path, "must be an object with 'name' and 'set' and/or 'reads'")
                continue
            self.unknown_keys(
                body, ("name", "set", "value", "sweep", "reads", "verify", "limits", "output"), path
            )
            name = body.get("name")
            if "name" not in body:
                self.error(f"{path}.name", "the name of the parameter is missing")
                continue
            if not self.identifier(name, f"{path}.name", "parameter name"):
                continue
            if name in out:
                self.error(f"{path}.name", f"there is already a parameter called '{name}'")
                continue
            has_set = "set" in body
            setter = self.setter(body.get("set"), f"{path}.set") if has_set else None
            if has_set and setter is None:
                self.broken_set.add(name)  # already reported: do not complain about it again
            reads = self.reads(body.get("reads", {}), f"{path}.reads", name)
            if "set" not in body and "reads" not in body:
                self.error(
                    path, f"'{name}': give 'set' (how to set it) and/or 'reads' (how to read it)"
                )
            value, axis = None, None
            if "value" in body and "sweep" in body:
                self.error(path, f"'{name}' has a fixed 'value' and a 'sweep': keep only one")
            elif "value" in body or "sweep" in body:
                key = "value" if "value" in body else "sweep"
                if not has_set:
                    self.error(
                        f"{path}.{key}", f"'{name}' needs 'set' (how to set it) to have a {key}"
                    )
                elif setter is None:
                    pass  # the invalid 'set' is already reported
                elif key == "value":
                    value = self.number(body, "value", path)
                else:
                    try:
                        axis = axis_values(body["sweep"])
                    except SweepError as exc:
                        self.error(f"{path}.sweep", str(exc))
            elif setter is not None:
                self.error(path, f"'{name}' has no value: give 'value' (fixed) or 'sweep'")
            verify = (
                self.verify(body.get("verify"), reads, has_set, f"{path}.verify", name)
                if "verify" in body
                else None
            )
            limits = self.limits(body.get("limits"), name, has_set, value, axis, f"{path}.limits")
            output = (
                self.output(body.get("output"), has_set, name, f"{path}.output")
                if "output" in body
                else None
            )
            out[name] = Variable(name, setter, value, reads, verify, axis, limits, output)
        return out

    def setter(self, raw: Any, path: str) -> Optional[SetSpec]:
        if not isinstance(raw, dict):
            self.error(path, "must be an object with 'instrument' and 'call'")
            return None
        self.unknown_keys(raw, ("instrument", "call", "args", "value_arg"), path)
        instrument = self.instrument(raw, path)
        call, args = self.call_and_args(raw, path)
        value_arg = raw.get("value_arg", "value")
        if not isinstance(value_arg, str) or not value_arg:
            self.error(
                f"{path}.value_arg",
                "must be the name of the call's value argument (default 'value')",
            )
            value_arg = "value"
        if instrument and call:
            return SetSpec(instrument, call, args, value_arg)
        return None

    def reads(self, raw: Any, path: str, owner: str) -> Dict[str, ReadSpec]:
        out: Dict[str, ReadSpec] = {}
        if not isinstance(raw, dict):
            self.error(path, 'must be an object {label: how to read}, like {"daq": {...}}')
            return out
        for label, body in raw.items():
            where = f"{path}.{label}"
            if not self.identifier(label, where, "reading label"):
                continue
            self.broken_reads.add((owner, label))  # until the reading is accepted below
            if not isinstance(body, dict):
                self.error(where, "must be an object with 'instrument' and 'call'")
                continue
            self.unknown_keys(body, ("instrument", "call", "args", "scale", "offset"), where)
            instrument = self.instrument(body, where)
            call, args = self.call_and_args(body, where)
            scale = self.number(body, "scale", where, default=1.0)
            offset = self.number(body, "offset", where, default=0.0)
            if scale == 0:
                self.error(f"{where}.scale", "must not be 0 (every reading would be the offset)")
            self.library_check(instrument, call, args, where)
            if instrument and call and scale is not None and offset is not None:
                out[label] = ReadSpec(label, instrument, call, args, scale, offset)
                self.broken_reads.discard((owner, label))
        return out

    def verify(
        self, raw: Any, reads: Mapping[str, ReadSpec], has_set: bool, path: str, owner: str
    ) -> Optional[VerifySpec]:
        if not isinstance(raw, dict):
            self.error(path, 'must be an object like {"read": "daq", "tol_rel": 0.01}')
            return None
        self.unknown_keys(raw, ("read", "tol_abs", "tol_rel", "on_fail"), path)
        if not has_set:
            self.error(
                path,
                "only a parameter that is set can be verified (there is no setpoint to compare)",
            )
        label = raw.get("read")
        if label not in reads and (owner, label) not in self.broken_reads:
            self.error(
                f"{path}.read",
                f"unknown reading {label!r}{self.hint(str(label), reads)}; "
                f"readings: {', '.join(reads) or 'none'}",
            )
        tol_abs = self.number(raw, "tol_abs", path, default=0.0, minimum=0.0)
        tol_rel = self.number(raw, "tol_rel", path, default=0.0, minimum=0.0)
        if tol_abs == 0 and tol_rel == 0:
            self.error(
                path,
                "give 'tol_abs' and/or 'tol_rel' greater than 0 (zero tolerance can never pass)",
            )
        on_fail = raw.get("on_fail", "ask")
        if on_fail not in ("ask", "warn", "stop"):
            self.error(
                f"{path}.on_fail",
                "must be 'ask' (ask the user), 'warn' (write a warning) or 'stop' (fail)",
            )
        if (
            label in reads
            and tol_abs is not None
            and tol_rel is not None
            and on_fail in ("ask", "warn", "stop")
        ):
            return VerifySpec(label, tol_abs, tol_rel, on_fail)
        return None

    def timing(self, raw: Any) -> Timing:
        if raw is None:
            return Timing()
        if not isinstance(raw, dict):
            self.error(
                "timing", 'must be an object like {"settle_s": 8, "samples": 5, "interval_s": 10}'
            )
            return Timing()
        self.unknown_keys(raw, ("settle_s", "samples", "interval_s", "cooldown_s"), "timing")
        settle = self.number(raw, "settle_s", "timing", default=0.0, minimum=0.0)
        samples = self.number(
            raw, "samples", "timing", default=1, minimum=1, maximum=MAX_SAMPLES, integer=True
        )
        interval = self.number(raw, "interval_s", "timing", default=0.0, minimum=0.0)
        cooldown = self.number(raw, "cooldown_s", "timing", default=0.0, minimum=0.0)
        if samples == 1 and interval:
            self.warn("timing.interval_s", "with a single sample the interval is not used")
        return Timing(settle or 0.0, samples or 1, interval or 0.0, cooldown or 0.0)

    def limits(
        self,
        raw: Any,
        name: str,
        has_set: bool,
        value: Optional[float],
        axis: Optional[List[float]],
        path: str,
    ) -> Optional[Tuple[Optional[float], Optional[float]]]:
        if raw is None:
            return None
        if not has_set:
            self.error(path, f"'{name}' is not set by the program, it cannot have limits")
            return None
        if not isinstance(raw, dict) or not raw:
            self.error(path, 'must be an object like {"min": 0, "max": 15}')
            return None
        self.unknown_keys(raw, ("min", "max"), path)
        low, high = self.number(raw, "min", path), self.number(raw, "max", path)
        if low is not None and high is not None and low > high:
            self.error(path, f"min ({low:g}) is greater than max ({high:g})")
            return None
        used = [value] if value is not None else (axis or [])
        outside = [
            v for v in used if (low is not None and v < low) or (high is not None and v > high)
        ]
        if outside:
            lo_text = "-inf" if low is None else f"{low:g}"
            hi_text = "+inf" if high is None else f"{high:g}"
            shown = ", ".join(f"{v:g}" for v in outside[:3]) + (" ..." if len(outside) > 3 else "")
            self.error(
                path, f"{len(outside)} value(s) of '{name}' outside [{lo_text}, {hi_text}]: {shown}"
            )
        return (low, high)

    def call_list(self, raw: Any, path: str) -> List[CallSpec]:
        out: List[CallSpec] = []
        if raw is None:
            return out
        if not isinstance(raw, list):
            self.error(path, 'must be a list of {"instrument": .., "call": ..}')
            return out
        for i, item in enumerate(raw):
            spec = self.call_spec(item, f"{path}[{i}]")
            if spec is not None:
                out.append(spec)
        return out

    def call_spec(self, item: Any, where: str) -> Optional[CallSpec]:
        if not isinstance(item, dict):
            self.error(where, "must be an object with 'instrument' and 'call'")
            return None
        self.unknown_keys(item, ("instrument", "call", "args"), where)
        instrument = self.instrument(item, where)
        call, args = self.call_and_args(item, where)
        self.library_check(instrument, call, args, where)
        if instrument and call:
            return CallSpec(instrument, call, args)
        return None

    def output(self, raw: Any, has_set: bool, name: str, path: str) -> Optional[OutputSpec]:
        if not has_set:
            self.error(path, f"'{name}' is not set by the program, so it has no output to switch")
            return None
        if not isinstance(raw, dict):
            self.error(
                path, 'must be an object like {"on": {...}, "off": {...}, "mode": "keep_on"}'
            )
            return None
        self.unknown_keys(raw, ("on", "off", "mode", "state"), path)
        mode = raw.get("mode", "keep_on")
        if mode not in OUTPUT_MODES:
            self.error(f"{path}.mode", f"must be one of: {', '.join(OUTPUT_MODES)}")
            mode = "keep_on"
        on = self.call_spec(raw["on"], f"{path}.on") if "on" in raw else None
        off = self.call_spec(raw["off"], f"{path}.off") if "off" in raw else None
        state = self.call_spec(raw["state"], f"{path}.state") if "state" in raw else None
        if any(k in raw and v is None for k, v in (("on", on), ("off", off), ("state", state))):
            return None  # already reported
        if mode == "off_during_cooldown" and (on is None or off is None):
            self.error(path, "to switch it off during the cooldown give both 'on' and 'off' calls")
        if mode == "always_on":
            if off is not None:
                self.warn(
                    f"{path}.off", "ignored: an output that is always on is never switched off"
                )
            self.warn(
                path,
                f"'{name}' is always on: the program never switches it off, so it stays ON when "
                "the measurement ends, also after an error or a stop",
            )
        elif off is None:
            self.warn(path, f"no 'off' call: the output of '{name}' stays on at the end")
        elif state is None:
            self.warn(
                path,
                f"no 'state' call: if the output of '{name}' is already on when the measurement "
                "starts, the program cannot warn you that it will be switched off at the end",
            )
        if mode == "always_on" and on is not None and state is None:
            self.warn(
                path,
                f"no 'state' call: 'on' is sent without checking whether '{name}' is already on",
            )
        return OutputSpec(on, off, mode, state)

    def power_order(self, raw: Any, variables: Mapping[str, Variable]) -> List[str]:
        """The switch-on order of the outputs the program manages (not the always-on ones).

        Without ``power_order`` it is the order of the parameter list."""
        managed = [
            name
            for name, var in variables.items()
            if var.output and var.output.mode != "always_on" and var.output.on
        ]
        if raw is None:
            return managed
        if not isinstance(raw, list) or not all(isinstance(n, str) for n in raw):
            self.error("power_order", 'must be a list of parameter names, like ["vin", "iout"]')
            return managed
        seen: List[str] = []
        for i, name in enumerate(raw):
            where = f"power_order[{i}]"
            var = variables.get(name)
            if var is None:
                self.error(where, f"unknown parameter '{name}'{self.hint(name, variables)}")
            elif var.output and var.output.mode == "always_on":
                self.error(
                    where,
                    f"'{name}' is always on: it is switched on before this list, not part of it",
                )
            elif name not in managed:
                self.error(where, f"'{name}' has no output with an 'on' call to switch on")
            elif name in seen:
                self.error(where, f"'{name}' appears twice")
            else:
                seen.append(name)
        missing = [n for n in managed if n not in seen and n not in raw]
        if missing:
            self.error("power_order", f"these outputs are not in the list: {', '.join(missing)}")
        return seen if not self.problems_in("power_order") else managed

    def problems_in(self, prefix: str) -> bool:
        return any(p.severity == "error" and p.path.startswith(prefix) for p in self.problems)

    def cooldown_warnings(
        self, variables: Mapping[str, Variable], axes: List[Tuple[str, List[float]]], timing: Timing
    ) -> None:
        """Say so when the cooldown settings do not fit together (nothing would happen)."""
        cooled = [
            v for v in variables.values() if v.output and v.output.mode == "off_during_cooldown"
        ]
        if cooled and timing.cooldown_s <= 0:
            self.warn(
                "timing.cooldown_s",
                "some outputs are set to switch off during the cooldown, but cooldown_s is 0: "
                "there is no cooldown, so they are never switched off before the end",
            )
        if timing.cooldown_s > 0 and not cooled:
            self.warn(
                "timing.cooldown_s",
                "no output is set to switch off during the cooldown: the converter keeps "
                "running while the measurement waits",
            )
        if (timing.cooldown_s > 0 or cooled) and len(axes) < 2:
            self.warn(
                "timing.cooldown_s",
                "the cooldown happens between two sweeps, and there is only one (or none): "
                "it is never used",
            )

    def derived(self, raw: Any, variables: Mapping[str, Variable]) -> Dict[str, Formula]:
        formulas: Dict[str, Formula] = {}
        if raw is None:
            return formulas
        if not isinstance(raw, dict):
            self.error(
                "derived", 'must be an object {name: formula}, like {"pin": "vin@daq * iin@daq"}'
            )
            return formulas
        for name, text in raw.items():
            path = f"derived.{name}"
            if not self.identifier(name, path, "name"):
                continue
            if name in variables:
                self.error(path, f"'{name}' is already a parameter, choose another name")
                continue
            try:
                formulas[name] = Formula(text)
            except FormulaError as exc:
                self.error(path, str(exc))
        usable = [v for v, var in variables.items() if var.set is not None]
        for name, formula in list(formulas.items()):
            for used in sorted(formula.names):
                message = self.name_problem(used, variables, formulas, usable)
                if message:
                    self.error(f"derived.{name}", message)
        return self.dependency_order(formulas)

    def name_problem(
        self,
        used: str,
        variables: Mapping[str, Variable],
        formulas: Mapping[str, Formula],
        usable: List[str],
    ) -> Optional[str]:
        if "@" in used:
            var_name, label = used.split("@", 1)
            var = variables.get(var_name)
            if var is None:
                return f"unknown parameter '{var_name}' in '{used}'{self.hint(var_name, variables)}"
            if label not in var.reads and (var_name, label) not in self.broken_reads:
                return (
                    f"'{var_name}' has no reading '{label}'{self.hint(label, var.reads)}; "
                    f"readings: {', '.join(var.reads) or 'none'}"
                )
            return None
        var = variables.get(used)
        if var is not None:
            if var.set is None and used not in self.broken_set:
                readings = ", ".join(f"{used}@{lab}" for lab in var.reads)
                return f"'{used}' has no setpoint (it is only read): use {readings or 'a reading'}"
            return None
        if used in formulas:
            return None
        candidates = usable + list(formulas)
        return f"unknown name '{used}'{self.hint(used, candidates)}"

    def dependency_order(self, formulas: Dict[str, Formula]) -> Dict[str, Formula]:
        order: Dict[str, Formula] = {}
        state: Dict[str, int] = {}

        def visit(name: str, trail: List[str]) -> None:
            if state.get(name) == 2:
                return
            if state.get(name) == 1:
                start = trail.index(name)
                loop = trail[start:] + [name]
                self.error(
                    f"derived.{name}",
                    "the formulas depend on each other in a loop: " + " -> ".join(loop),
                )
                return
            state[name] = 1
            for used in sorted(formulas[name].names):
                if used in formulas:
                    visit(used, trail + [name])
            state[name] = 2
            order[name] = formulas[name]

        for name in formulas:
            visit(name, [])
        return order


def _analyse(
    params: Any, bound: Optional[Collection[str]], checker: Optional[CallChecker]
) -> Tuple[Optional[EfficiencySpec], List[Problem]]:
    c = _Checker(params, bound, checker)
    if not isinstance(params, dict):
        c.error("", "the parameters must be an object with 'variables', 'sweeps', 'timing'...")
        return None, c.problems
    c.unknown_keys(params, TOP_KEYS, "")
    variables = c.variables(params.get("variables"))
    timing = c.timing(params.get("timing"))
    if c.checker is not None:
        for index, var in enumerate(variables.values()):
            values = [var.value] if var.value is not None else (var.axis or [])
            if var.set is None or not values:
                continue
            for v in dict.fromkeys((min(values), max(values))):
                args = {**var.set.args, var.set.value_arg: v}
                c.library_check(var.set.instrument, var.set.call, args, f"variables[{index}].set")
    if variables and not any(v.reads for v in variables.values()):
        c.error(
            "variables", "nothing is read: give at least one 'reads' to have something to measure"
        )
    axes = [(name, var.axis) for name, var in variables.items() if var.axis]
    derived = c.derived(params.get("derived"), variables)
    startup = c.call_list(params.get("startup"), "startup")
    shutdown = c.call_list(params.get("shutdown"), "shutdown")
    protected = {
        (var.output.off.instrument, var.output.off.call, repr(var.output.off.args)): var.name
        for var in variables.values()
        if var.output and var.output.mode == "always_on" and var.output.off
    }
    for i, call in enumerate(shutdown):
        owner = protected.get((call.instrument, call.call, repr(call.args)))
        if owner:
            c.error(
                f"shutdown[{i}]", f"this switches off the output of '{owner}', which is always on"
            )
    c.cooldown_warnings(variables, axes, timing)
    power_order = c.power_order(params.get("power_order"), variables)
    if not any(p.severity == "error" for p in c.problems):
        spec = EfficiencySpec(variables, axes, derived, timing, startup, shutdown, power_order)
        return spec, c.problems
    return None, c.problems


def validate_params(
    params: Any,
    bound_instruments: Optional[Collection[str]] = None,
    checker: Optional[CallChecker] = None,
) -> List[Problem]:
    """All the problems of ``params`` (empty list: nothing wrong). No I/O, safe on every edit.

    ``bound_instruments`` are the names of the instruments of the project; if given, an unknown
    instrument is a problem (with a "did you mean"). ``checker`` is the optional second level that
    asks the instrument library whether each call exists and accepts its arguments and values."""
    return _analyse(params, bound_instruments, checker)[1]


def parse_params(
    params: Any,
    bound_instruments: Optional[Collection[str]] = None,
    checker: Optional[CallChecker] = None,
) -> EfficiencySpec:
    """The ``EfficiencySpec`` for valid ``params``; ``SpecError`` (with ``.problems``) otherwise."""
    spec, problems = _analyse(params, bound_instruments, checker)
    if spec is None:
        raise SpecError(problems)
    return spec
