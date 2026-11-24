# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

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

A parameter can also be a **resistive load** (``"load"``, only in the resistive efficiency,
``.rfe``): the load of the converter is not an instrument but resistors, and the sweep is the list
of the loads: ``{"name": "rload", "load": {"loads": [...], "vout": "vout@daq", "max_vout_v": 12,
"switching": {"mode": "manual" | "mux", ...}, "plan": {...}}}``; ``plan`` only remembers the inputs
the loads were calculated from (``ola/combinations.py``). Its value is the nominal resistance of the
load; the formulas also see ``rload_min`` and ``rload_max`` (the tolerance of the resistors). See
``docs/resistive-efficiency.md``.

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
from .resistors import Load, LoadError, has_refs, parse_loads, refs_problems
from .sweep import SweepError, axis_values, total_points

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOP_KEYS = (
    "variables",
    "timing",
    "derived",
    "startup",
    "shutdown",
    "power_order",
    "golden",
    "device",
    "scope_capture",
)
OUTPUT_MODES = ("keep_on", "off_during_cooldown", "always_on")
MAX_SAMPLES = 10_000
LOAD_MODES = ("manual", "mux")


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
class LoadSpec:
    """A resistive load as a parameter: the ``loads`` it steps through (empty while the references
    to a kit are not resolved, ``count`` is how many there are), how they are connected (``mode``
    ``manual``: the operator is asked, or ``mux``: relays of the ``instrument`` close the channels
    of the resistors), the ``settle_s`` after connecting, the reading ``vout`` (``vout@label``)
    that checks the power in the resistors and ``max_vout_v``, the largest output voltage expected
    (a check made before the run)."""

    loads: Tuple[Load, ...]
    count: int
    mode: str = "manual"
    instrument: str = ""
    settle_s: float = 0.0
    vout: str = "vout"
    max_vout_v: Optional[float] = None
    plan: Optional[Dict[str, Any]] = None  # how the loads were calculated (``ola.combinations``)

    @property
    def learn(self) -> bool:
        """True if the run first measures the output voltage and re-plans the loads (see
        ``docs/resistive-efficiency.md``)."""
        return bool(self.plan and self.plan.get("learn"))

    @property
    def unresolved(self) -> bool:
        """True while a resistor of a kit is still only a reference."""
        return len(self.loads) != self.count


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
    load: Optional[LoadSpec] = None  # a resistive load instead of an instrument (``.rfe``)


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
        allow_load: bool = False,
    ):
        self.params = params
        self.allow_load = allow_load
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
                body,
                ("name", "set", "value", "sweep", "reads", "verify", "limits", "output", "load"),
                path,
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
            if "load" in body:
                variable = self.load_variable(body, name, path)
                if variable is not None:
                    out[name] = variable
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

    def load_variable(self, body: Dict[str, Any], name: str, path: str) -> Optional[Variable]:
        """A parameter that is a resistive load: it replaces 'set', 'value' and 'sweep'."""
        if not self.allow_load:
            self.error(
                f"{path}.load",
                "a resistive load is only in the efficiency with a resistive load (.rfe)",
            )
            return None
        for key in ("set", "value", "sweep", "verify", "limits", "output"):
            if key in body:
                self.error(f"{path}.{key}", f"'{name}' is a load: the loads are its values")
        reads = self.reads(body.get("reads", {}), f"{path}.reads", name)
        spec = self.load_spec(body["load"], f"{path}.load")
        if spec is None:
            return None
        axis = (
            [load.resistance()[0] for load in spec.loads]
            if not spec.unresolved
            else [float(i) for i in range(spec.count)]
        )
        return Variable(name, None, None, reads, None, axis, None, None, spec)

    def load_spec(self, raw: Any, path: str) -> Optional[LoadSpec]:
        if not isinstance(raw, dict):
            self.error(path, 'must be an object like {"loads": [...], "switching": {...}}')
            return None
        self.unknown_keys(raw, ("loads", "switching", "vout", "max_vout_v", "plan"), path)
        plan = raw.get("plan")
        if "plan" in raw:
            if not isinstance(plan, dict):
                self.error(f"{path}.plan", "must be an object (the inputs of the loads' plan)")
                plan = None
            elif plan.get("learn"):
                self.learning_inputs(plan, f"{path}.plan")
        loads_raw = raw.get("loads")
        problems = refs_problems(loads_raw, f"{path}.loads")
        for where, message in problems:
            self.error(where, message)
        loads: Tuple[Load, ...] = ()
        count = len(loads_raw) if isinstance(loads_raw, list) else 0
        if not problems:
            try:
                if has_refs(loads_raw):
                    parse_loads([{"name": f"load{i + 1}", "r_ohm": 1} for i in range(count)])
                else:
                    loads = tuple(parse_loads(loads_raw, f"{path}.loads"))
                    count = len(loads)
            except LoadError as exc:
                self.error(f"{path}.loads", str(exc))
                return None
        else:
            return None
        if not loads_raw:
            self.error(f"{path}.loads", "give at least one load")
            return None
        if loads:
            values = [round(load.resistance()[0], 9) for load in loads]
            if len(set(values)) != len(values):
                self.error(
                    f"{path}.loads", "two loads have the same resistance: every point needs its own"
                )
        switching = raw.get("switching", {})
        mode, instrument, settle = "manual", "", 0.0
        if not isinstance(switching, dict):
            self.error(f"{path}.switching", 'must be an object like {"mode": "manual"}')
        else:
            self.unknown_keys(switching, ("mode", "instrument", "settle_s"), f"{path}.switching")
            mode = switching.get("mode", "manual")
            if mode not in LOAD_MODES:
                self.error(f"{path}.switching.mode", f"must be one of: {', '.join(LOAD_MODES)}")
                mode = "manual"
            if mode == "mux":
                instrument = self.instrument(switching, f"{path}.switching") or ""
                for i, load in enumerate(loads):
                    missing = [r.name for r in load.resistors() if not r.channel]
                    if missing:
                        self.error(
                            f"{path}.loads[{i}]",
                            f"'{load.name}': the multiplexer needs a channel for "
                            f"{', '.join(missing)}",
                        )
            settle = self.number(switching, "settle_s", f"{path}.switching", 0.0, 0.0) or 0.0
        vout = raw.get("vout", "vout")
        if not isinstance(vout, str) or not vout:
            self.error(f"{path}.vout", "must be the name of a reading, like 'vout@daq'")
            vout = "vout"
        vmax = self.number(raw, "max_vout_v", path, None, 0.0)
        if vmax is not None and loads:
            for load in loads:
                resistor, fraction = load.most_loaded(vmax)
                if resistor is not None and fraction > 1:
                    self.error(
                        f"{path}.max_vout_v",
                        f"at {vmax:g} V the resistor {resistor.name} of '{load.name}' dissipates "
                        f"{fraction * 100:.0f} % of its rating",
                    )
        return LoadSpec(loads, count, mode, instrument, settle, vout, vmax, plan)

    def learning_inputs(self, plan: Dict[str, Any], path: str) -> None:
        """The inputs a run that learns the output voltage needs: the kit, the range of currents,
        the voltage the converter is expected to give and the parameter that is its input."""
        if not isinstance(plan.get("kit"), str) or not plan["kit"].strip():
            self.error(f"{path}.kit", "learning needs the kit of resistors the loads come from")
        low = self.number(plan, "i_min", path, None, 0.0)
        high = self.number(plan, "i_max", path, None, 0.0)
        if (
            "i_min" not in plan
            or "i_max" not in plan
            or (low is not None and high is not None and high <= low)
        ):
            self.error(path, "give the smallest and the largest current (the largest above)")
        self.number(plan, "points", path, None, 2, True)
        margin = self.number(plan, "margin_pct", path, 80.0, 1.0, False, 100.0)
        if margin is None:
            return
        self.number(plan, "learn_points", path, None, 2, True)
        if plan.get("kind", "regulated") == "regulated":
            if self.number(plan, "vout_v", path, None, 0.0) in (None, 0.0):
                self.error(f"{path}.vout_v", "give the output voltage the converter should have")
            keys = ("vin_v",)
        else:
            keys = ("ratio", "vin_v")
        for key in keys:  # the input voltage the quick sweep is made at
            if self.number(plan, key, path, None, 0.0) in (None, 0.0):
                self.error(f"{path}.{key}", "give a number above 0")
        if not isinstance(plan.get("vin_param"), str) or not plan["vin_param"]:
            self.error(f"{path}.vin_param", "name the parameter that is the input voltage")

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
            if name in variables or name in load_names(variables):
                self.error(path, f"'{name}' is already a parameter, choose another name")
                continue
            try:
                formulas[name] = Formula(text)
            except FormulaError as exc:
                self.error(path, str(exc))
        usable = [v for v, var in variables.items() if var.set is not None or var.load]
        usable += sorted(load_names(variables))
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
        if used in load_names(variables):
            return None
        var = variables.get(used)
        if var is not None:
            if var.set is None and var.load is None and used not in self.broken_set:
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


def load_names(variables: Mapping[str, Variable]) -> set:
    """The extra names a resistive load gives to the formulas: ``rload_min`` and ``rload_max``,
    the resistance with the tolerances of the resistors at their worst."""
    return {f"{n}{s}" for n, var in variables.items() if var.load for s in ("_min", "_max")}


def _check_learning(c: "_Checker", variables: Mapping[str, Variable]) -> None:
    """A learning run needs an input parameter the program sets, and only one load learns."""
    learners = [v for v in variables.values() if v.load is not None and v.load.learn]
    if len(learners) > 1:
        c.error("variables", "only one load can learn the output voltage of the converter")
    for index, (name, var) in enumerate(variables.items()):
        if var.load is None or not var.load.learn:
            continue
        owner = variables.get(var.load.plan.get("vin_param"))
        if owner is None or owner.set is None:
            c.error(
                f"variables[{index}].load.plan.vin_param",
                "this is not a parameter that the program sets (the input voltage)",
            )


def _check_vout(c: "_Checker", variables: Mapping[str, Variable]) -> None:
    """The reading that checks the power in the resistors must exist."""
    for index, (name, var) in enumerate(variables.items()):
        if var.load is None:
            continue
        label = var.load.vout
        where = f"variables[{index}].load.vout"
        if "@" in label:
            owner, _, reading = label.partition("@")
            holder = variables.get(owner)
            if holder is None or (
                reading not in holder.reads and (owner, reading) not in c.broken_reads
            ):
                c.error(where, f"there is no reading '{label}': add it to the parameter '{owner}'")
        elif label not in variables or not variables[label].reads:
            c.error(where, f"'{label}' is not a parameter that is read; write it like 'vout@daq'")
        elif len(variables[label].reads) != 1:
            c.error(where, f"'{label}' has more readings: write which, like '{label}@daq'")


SCOPE_CAPTURE_KEYS = (
    "instruments", "every", "when", "max", "channels", "bits", "wait_s", "points", "acquisitions",
)  # fmt: skip


def _check_scope_capture(
    c: "_Checker", raw: Any, variables: Mapping[str, Variable], formulas: Mapping[str, Formula]
) -> None:
    """The waveforms taken during the measurement (``ola.scope_capture``): the oscilloscopes, and
    *when* (``every`` N steps and/or ``when`` a quantity of the step goes beyond a value). The files
    of scope settings come from the project, which writes them in ``acquisitions`` when the run
    starts. Missing or ``{}``: no waveforms."""
    if raw is None or raw == {}:
        return
    path = "scope_capture"
    if not isinstance(raw, dict):
        c.error(path, 'must be an object like {"instruments": ["osc1"], "every": 2}')
        return
    c.unknown_keys(raw, SCOPE_CAPTURE_KEYS, path)
    names = raw.get("instruments")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
        c.error(f"{path}.instruments", 'give the oscilloscopes, like ["osc1"]')
    else:
        if len(set(names)) != len(names):
            c.error(f"{path}.instruments", "an oscilloscope is named twice")
        for i, name in enumerate(names):
            if c.bound is not None and name not in c.bound:
                known = ", ".join(c.bound) or "none"
                c.error(
                    f"{path}.instruments[{i}]",
                    f"instrument '{name}' is not in the project{c.hint(name, c.bound)}; "
                    f"available: {known}",
                )
    if "every" not in raw and "when" not in raw:
        c.error(path, "say when: 'every' (every how many steps, 1 = every step) and/or 'when'")
    if "every" in raw:
        c.number(raw, "every", path, None, 1, True)
    if "max" in raw:
        c.number(raw, "max", path, None, 1, True)
    if "when" in raw:
        _check_when(c, raw["when"], variables, formulas, f"{path}.when")
    channels = raw.get("channels")
    if channels is not None and (
        not isinstance(channels, list)
        or not channels
        or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 1 for n in channels)
    ):
        c.error(f"{path}.channels", "must be a list of channel numbers, like [1, 2]")
    if raw.get("bits", 8) not in (8, 16):
        c.error(f"{path}.bits", "must be 8 or 16")
    c.number(raw, "wait_s", path, None, 0.0)
    c.number(raw, "points", path, None, 1, True)
    acquisitions = raw.get("acquisitions")
    if acquisitions is not None and not (
        isinstance(acquisitions, list)
        and all(isinstance(a, dict) and a.get("name") and "settings" in a for a in acquisitions)
    ):
        c.error(f"{path}.acquisitions", "must be a list of {name, file, settings}")


def _check_when(
    c: "_Checker", raw: Any, variables: Mapping[str, Variable], formulas: Mapping[str, Formula],
    path: str,
) -> None:  # fmt: skip
    """The conditions that make the waveforms be taken at a step: ``[{"name": "efficiency",
    "below": 85}]``, a quantity of the step (a parameter, a reading ``vout@daq``, a ``derived``
    one) and a limit; any condition that holds is enough."""
    if not isinstance(raw, list) or not raw:
        c.error(path, 'must be a list like [{"name": "efficiency", "below": 85}]')
        return
    usable = [v for v, var in variables.items() if var.set is not None or var.load]
    usable += sorted(load_names(variables)) + list(formulas)
    for i, item in enumerate(raw):
        where = f"{path}[{i}]"
        if not isinstance(item, dict):
            c.error(where, 'must be an object like {"name": "efficiency", "below": 85}')
            continue
        c.unknown_keys(item, ("name", "above", "below"), where)
        name = item.get("name")
        if not isinstance(name, str) or not name:
            c.error(
                f"{where}.name", "the quantity of the step is missing (vin, vout@daq, efficiency)"
            )
        else:
            message = c.name_problem(name, variables, formulas, usable)
            if message:
                c.error(f"{where}.name", message)
        if "above" not in item and "below" not in item:
            c.error(where, "give 'above' and/or 'below'")
        for key in ("above", "below"):
            if key in item:
                c.number(item, key, where)


def _check_device(c: "_Checker", device: Any) -> None:
    """The converter under test, if the file names one (all optional): a ``name`` written by hand,
    a ``dut_id`` of the archive of the devices under test (``DUT-0001``) with its ``version``
    (free text), and a ``variant``, a few named values that changed since the last run (a part
    of the bill of materials, a fan on or off: ``ola.variants``)."""
    if device is None:
        return
    from .assets import normalize_code
    from .variants import problem as variant_problem

    allowed = {"name", "dut_id", "version", "variant"}
    if not isinstance(device, dict) or set(device) - allowed:
        c.error("device", "the device has: " + ", ".join(sorted(allowed)))
        return
    for key in ("name", "version"):
        if not isinstance(device.get(key, ""), str):
            c.error(f"device.{key}", f"the {key} must be text")
    code = device.get("dut_id")
    if code not in (None, "") and not (isinstance(code, str) and normalize_code(code)):
        c.error("device.dut_id", "not a code (it looks like DUT-0001)")
    message = variant_problem(device.get("variant"))
    if message:
        c.error("device.variant", message)


def _analyse(
    params: Any,
    bound: Optional[Collection[str]],
    checker: Optional[CallChecker],
    allow_load: bool = False,
) -> Tuple[Optional[EfficiencySpec], List[Problem]]:
    c = _Checker(params, bound, checker, allow_load)
    if not isinstance(params, dict):
        c.error("", "the parameters must be an object with 'variables', 'sweeps', 'timing'...")
        return None, c.problems
    c.unknown_keys(params, TOP_KEYS, "")
    _check_device(c, params.get("device"))
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
    _check_vout(c, variables)
    _check_learning(c, variables)
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
    _check_scope_capture(c, params.get("scope_capture"), variables, derived)
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
    allow_load: bool = False,
) -> List[Problem]:
    """All the problems of ``params`` (empty list: nothing wrong). No I/O, safe on every edit.

    ``bound_instruments`` are the names of the instruments of the project; if given, an unknown
    instrument is a problem (with a "did you mean"). ``checker`` is the optional second level that
    asks the instrument library whether each call exists and accepts its arguments and values.
    ``allow_load`` allows a resistive load as a parameter (the ``.rfe`` measurement)."""
    problems = _analyse(params, bound_instruments, checker, allow_load)[1]
    if isinstance(params, dict):
        from .golden import check_golden_param  # the check against a golden sample

        check_golden_param(params, problems)
    return problems


def parse_params(
    params: Any,
    bound_instruments: Optional[Collection[str]] = None,
    checker: Optional[CallChecker] = None,
    allow_load: bool = False,
) -> EfficiencySpec:
    """The ``EfficiencySpec`` for valid ``params``; ``SpecError`` (with ``.problems``) otherwise."""
    spec, problems = _analyse(params, bound_instruments, checker, allow_load)
    if spec is None:
        raise SpecError(problems)
    return spec
