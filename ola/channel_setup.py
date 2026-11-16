# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""How the channels of a datalogger are read in a measurement (no Qt): range, integration time,
the offset zero with the inputs shorted, and the input impedance.

A channel of the ``.inst`` file (``ola.inst_file``) can carry, besides its function
(``meas_type``), these settings; each is left out when it is the default:

* ``range``: ``"AUTO"`` (the default) or a fixed range in the units of the function (``10`` for the
  10 V range). The model lists the ranges it has.
* ``nplc``: the integration time in power line cycles (``20``, ``100``...; the instrument's own
  default when left out). More cycles give less noise and a slower reading.
* ``zero``: ``true`` to **zero the offset of the channel before the measurement**: the program asks
  you to connect the two terminals of the channel together, takes the reading as the offset to
  subtract (the wiring, the thermal voltages, the offset of the input), then asks you to connect
  them back, and goes on with the next channel. For a shunt of a few milliohms the offset is a
  large part of what is measured.
* ``impedance``: ``"auto"`` (the input resistance is above 10 GOhm on the lowest ranges) or
  ``"10M"`` (fixed at 10 MOhm on every range). Only DC voltage; only for models that have it.

``config_calls`` turns the settings into the logical calls that configure the instrument, and
``ConfiguredHandle`` wraps the handle of a datalogger so that the measurements get them, **without
their having to know**: a ``measure_dc_voltage`` of a configured channel is read from the scan list
the channel was configured for, not with ``MEASure``. That matters: ``CONFigure`` and ``MEASure``
(of the 34970A and the like) put the integration time, the impedance and the offset back to their
defaults, so a reading made that way would lose everything that was set. The wrapper also takes
the zero procedure (``prepare_run``, called by the runner before the measurement starts).

A model that has not the calls a setting needs is **refused with a sentence** when the measurement
starts, never silently read without the setting.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .datalogger_setup import DataloggerSetupError, channel_number

log = logging.getLogger(__name__)

Call = Tuple[str, Dict[str, Any]]
Range = Union[str, float]

ZERO_SETTLE_PLC_SECONDS = 0.04  # one cycle of 50 Hz, twice (the instrument measures twice to zero)
ZERO_SETTLE_MARGIN_S = 1.0
IMPEDANCE_CHOICES = ("auto", "10M")


class ChannelSetupError(ValueError):
    """A channel setting cannot be used; the message says which channel and why."""


@dataclass(frozen=True)
class Function:
    """The logical calls of one function of a datalogger channel."""

    name: str
    configure: str
    measure: str
    nplc: str
    range_call: str
    impedance: Optional[str] = None  # DC voltage only


FUNCTIONS: Dict[str, Function] = {
    "VOLT:DC": Function(
        "VOLT:DC", "configure_dc_voltage", "measure_dc_voltage", "set_voltage_nplc",
        "set_voltage_range", "input_impedance_auto",
    ),
    "CURR:DC": Function(
        "CURR:DC", "configure_dc_current", "measure_dc_current", "set_dc_current_nplc",
        "set_dc_current_range",
    ),
    "RES": Function(
        "RES", "configure_resistance", "measure_resistance", "set_resistance_nplc",
        "set_resistance_range",
    ),
    "FRES": Function(
        "FRES", "configure_fresistance", "measure_fresistance", "set_fresistance_nplc",
        "set_fresistance_range",
    ),
}  # fmt: skip
ALIASES = {"DC_V": "VOLT:DC", "DC_A": "CURR:DC"}
MEASURE_CALLS = {f.measure: f for f in FUNCTIONS.values()}
KEYS = ("range", "nplc", "zero", "impedance")  # the settings a channel of the file can carry


def function_of(meas_type: Any) -> Optional[Function]:
    """The ``Function`` of a ``meas_type`` of the file (``VOLT:DC``, ``DC_V``...), or None for a
    function that has none of these settings (AC, frequency, temperature...)."""
    key = str(meas_type or "VOLT:DC").strip().upper()
    return FUNCTIONS.get(ALIASES.get(key, key))


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_range(value: Any) -> Range:
    """``"AUTO"`` or a fixed range: ``None``, ``""`` and ``"auto"`` are ``"AUTO"``; a number or a
    number written as text (``"10"``, ``"0,1"``) is that number; ``MIN`` and ``MAX`` are kept.
    ``ChannelSetupError`` for anything else."""
    if value is None or (isinstance(value, str) and value.strip().upper() in ("", "AUTO")):
        return "AUTO"
    if isinstance(value, str):
        text = value.strip().upper()
        if text in ("MIN", "MAX", "DEF"):
            return text
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            raise ChannelSetupError(f"the range {value!r} is not AUTO or a number") from None
    if not _number(value) or value <= 0:
        raise ChannelSetupError(f"the range must be AUTO or a number above 0, not {value!r}")
    return float(value)


def parse_nplc(value: Any) -> Optional[Union[float, str]]:
    """The integration time in cycles: None for the instrument's own, a number above 0, or
    ``MIN`` / ``MAX``. ``ChannelSetupError`` for anything else."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        text = value.strip().upper()
        if text in ("MIN", "MAX"):
            return text
        try:
            value = float(text.replace(",", "."))
        except ValueError:
            raise ChannelSetupError(f"the integration time {value!r} is not a number") from None
    if not _number(value) or value <= 0:
        raise ChannelSetupError(
            f"the integration time must be a number of cycles above 0: {value!r}"
        )
    return float(value)


def parse_impedance(value: Any) -> str:
    """``""`` (not set), ``"auto"`` or ``"10M"``; ``ChannelSetupError`` for anything else."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    text = str(value).strip()
    for choice in IMPEDANCE_CHOICES:
        if text.lower() == choice.lower():
            return choice
    raise ChannelSetupError(
        f"the input impedance {value!r} is not one of {', '.join(IMPEDANCE_CHOICES)}"
    )


@dataclass
class ChannelSettings:
    """What a channel of the file asks for, parsed and checked."""

    number: int
    name: str
    function: Function
    range: Range = "AUTO"
    nplc: Optional[Union[float, str]] = None
    zero: bool = False
    impedance: str = ""

    @property
    def configured(self) -> bool:
        """True if the channel asks for anything beyond the defaults (the others are read as
        before, by the measurement's own call)."""
        return self.range != "AUTO" or self.nplc is not None or self.zero or bool(self.impedance)

    @property
    def label(self) -> str:
        """``103`` or ``103 (shunt in)``: how a message names the channel."""
        named = self.name and self.name != str(self.number)
        return f"{self.number} ({self.name})" if named else str(self.number)


def settings_of(channel: Mapping[str, Any]) -> Optional[ChannelSettings]:
    """The settings of one channel of the file, or None if its function has none of them. A
    value that cannot be used is a ``ChannelSetupError`` that names the channel; a channel whose
    number cannot be told is a ``DataloggerSetupError``."""
    function = function_of(channel.get("meas_type", "VOLT:DC"))
    if function is None:
        return None
    number = channel_number(dict(channel))
    name = str(channel.get("name") or number)
    try:
        return ChannelSettings(
            number,
            name,
            function,
            parse_range(channel.get("range")),
            parse_nplc(channel.get("nplc")),
            bool(channel.get("zero", False)),
            parse_impedance(channel.get("impedance")),
        )
    except ChannelSetupError as exc:
        raise ChannelSetupError(f"channel {number} ({name}): {exc}") from None


def channel_problems(channel: Mapping[str, Any]) -> List[str]:
    """What is wrong with the settings of one channel of the file, as sentences (without the name of
    the channel): a value that cannot be used, a zero that is not true or false, an input impedance
    on a function that has none. Empty if there is nothing wrong."""
    found: List[str] = []
    for key, parse in (
        ("range", parse_range),
        ("nplc", parse_nplc),
        ("impedance", parse_impedance),
    ):
        try:
            parse(channel.get(key))
        except ChannelSetupError as exc:
            found.append(str(exc))
    if "zero" in channel and not isinstance(channel["zero"], bool):
        found.append(f"the zero must be true or false, not {channel['zero']!r}")
    function = function_of(channel.get("meas_type", "VOLT:DC"))
    if function is None:
        if any(channel.get(k) not in (None, "", False) for k in ("nplc", "zero", "impedance")):
            found.append("this function has no integration time, zero or input impedance setting")
    elif channel.get("impedance") not in (None, "") and function.impedance is None:
        found.append("the input impedance is only for DC voltage")
    return found


def settings_of_entry(entry: Mapping[str, Any]) -> List[ChannelSettings]:
    """The settings of every enabled channel of a datalogger entry (flat ``channels``; the
    channels of the ``slots`` if the entry has no flat list), by channel number."""
    channels = [c for c in entry.get("channels") or [] if isinstance(c, dict)]
    if not channels:
        for slot in entry.get("slots") or []:
            if not isinstance(slot, dict) or not slot.get("module_id"):
                continue
            for index, ch in enumerate(slot.get("channels") or []):
                if isinstance(ch, dict):
                    ch = dict(ch)
                    ch.setdefault("slot_number", slot.get("slot_number"))
                    ch.setdefault(
                        "channel_id", str(int(slot.get("slot_number") or 0) * 100 + index + 1)
                    )
                    channels.append(ch)
    found = []
    for ch in channels:
        if not ch.get("enabled", True):
            continue
        parsed = settings_of(ch)
        if parsed is not None:
            found.append(parsed)
    return sorted(found, key=lambda s: s.number)


def check_settings(
    settings: Sequence[ChannelSettings], supports: Callable[[str], bool]
) -> List[str]:
    """The problems of what the channels ask for, given what the model can do: a sentence for each
    setting the model has no call for. Empty: it can all be done."""
    problems: List[str] = []
    for s in settings:
        if s.nplc is not None and not supports(s.function.nplc):
            problems.append(
                f"channel {s.label}: this model has no integration time ({s.function.nplc})"
            )
        if s.impedance:
            if s.function.impedance is None:
                problems.append(f"channel {s.label}: the input impedance is only for DC voltage")
            elif not supports(s.function.impedance):
                problems.append(f"channel {s.label}: this model has no input impedance setting")
        if s.zero:
            for call in ("null_offset", "set_scale_state"):
                if not supports(call):
                    problems.append(f"channel {s.label}: this model cannot zero a channel ({call})")
                    break
    return problems


def _group(settings: Sequence[ChannelSettings]) -> Dict[tuple, List[int]]:
    groups: Dict[tuple, List[int]] = {}
    for s in settings:
        key = (s.function.name, s.range, s.nplc, s.impedance)
        groups.setdefault(key, []).append(s.number)
    return groups


def _extras(function: Function, nplc: Any, impedance: str, channels: str) -> List[Call]:
    calls: List[Call] = []
    if nplc is not None:
        calls.append((function.nplc, {"plcs": nplc, "channels": channels}))
    if impedance and function.impedance:
        state = "ON" if impedance == "auto" else "OFF"
        calls.append((function.impedance, {"state": state, "channels": channels}))
    return calls


def config_calls(settings: Sequence[ChannelSettings]) -> List[Call]:
    """The logical calls that configure the channels, in order: for each group of channels with
    the same function and settings, ``configure_*`` (the range; ``configure`` puts everything else
    back to the default, so it comes first), then the integration time and the input impedance."""
    calls: List[Call] = []
    for (name, rng, nplc, impedance), numbers in _group(settings).items():
        function = FUNCTIONS[name]
        text = ",".join(str(n) for n in sorted(numbers))
        calls.append((function.configure, {"range": rng, "resolution": "DEF", "channels": text}))
        calls += _extras(function, nplc, impedance, text)
    return calls


def extra_calls(
    settings: Sequence[ChannelSettings], supports: Optional[Callable[[str], bool]] = None
) -> List[Call]:
    """Only the integration time and the input impedance calls of the channels, for a caller that
    sends the ``configure_*`` itself (the remote control). With ``supports``, a call the model has
    not is left out."""
    calls: List[Call] = []
    for (name, _rng, nplc, impedance), numbers in _group(settings).items():
        text = ",".join(str(n) for n in sorted(numbers))
        for call in _extras(FUNCTIONS[name], nplc, impedance, text):
            if supports is None or supports(call[0]):
                calls.append(call)
    return calls


def zero_wait_s(s: ChannelSettings) -> float:
    """How long to wait for the null measurement of a channel: it takes the integration time (twice,
    with the instrument's own autozero), 50 Hz being the slower line, and a margin."""
    cycles = s.nplc if _number(s.nplc) else 1.0
    return max(ZERO_SETTLE_MARGIN_S, cycles * ZERO_SETTLE_PLC_SECONDS + ZERO_SETTLE_MARGIN_S)


class ConfiguredHandle:
    """The handle of a datalogger with the settings of its channels (see the module docstring).

    It is the handle it wraps for everything but the readings of a configured channel:
    ``name``, ``supports``, ``readback``... and the calls that are not a ``measure_*`` of a
    configured channel go straight through. ``prepare_run(ctx)`` configures the channels and does
    the zero procedure; if nobody called it (a script) the first reading configures them, and a
    channel that asks for the zero is read without it, with a warning in the log."""

    def __init__(self, handle: Any, settings: Sequence[ChannelSettings]):
        self._handle = handle
        self.settings = {s.number: s for s in settings if s.configured}
        self._configured = False
        self._scan: Optional[str] = None  # the scan list the instrument has now
        self._zeroed: Dict[int, Optional[float]] = {}

    def __getattr__(self, attribute: str) -> Any:
        return getattr(self._handle, attribute)

    @property
    def wrapped(self) -> Any:
        """The plain handle."""
        return self._handle

    def supports(self, name: str) -> bool:
        """True if the model defines the call."""
        return bool(self._handle.supports(name))

    def problems(self) -> List[str]:
        """What the channels ask for and the model cannot do (``check_settings``)."""
        return check_settings(list(self.settings.values()), self.supports)

    # ----- the calls --------------------------------------------------------------------------
    def call(self, name: str, **args: Any) -> Any:
        """A logical call. The ``measure_*`` of a configured channel is a reading of that channel as
        configured; anything else is the call of the plain handle."""
        s = self._configured_channel(name, args)
        if s is not None:
            return self._read(s)
        result = self._handle.call(name, **args)
        if name == "select_channels":
            self._scan = str(args.get("channels", "")).replace(" ", "")
        return result

    def _configured_channel(self, name: str, args: Mapping[str, Any]) -> Optional[ChannelSettings]:
        function = MEASURE_CALLS.get(name)
        text = str(args.get("channels", "")).strip()
        if function is None or not re.fullmatch(r"\d{3,4}", text):
            return None
        s = self.settings.get(int(text))
        return s if s is not None and s.function is function else None

    def _read(self, s: ChannelSettings) -> float:
        self._configure()
        if s.zero and s.number not in self._zeroed:
            log.warning("channel %s asks for the zero but the run did not do it", s.label)
            self._zeroed[s.number] = None
        wanted = str(s.number)
        if self._scan != wanted:
            self._handle.call("select_channels", channels=wanted)
            self._scan = wanted
        values = self._handle.call("read_scan")
        value = values[0] if isinstance(values, (list, tuple)) else values
        return float(value)

    # ----- before the measurement -------------------------------------------------------------
    def _configure(self) -> None:
        if self._configured:
            return
        problems = self.problems()
        if problems:
            raise ChannelSetupError("; ".join(problems))
        for name, args in config_calls(list(self.settings.values())):
            self._handle.call(name, **args)
        self._configured = True
        self._scan = None  # CONFigure does not touch the scan list, but do not rely on it

    def prepare_run(self, ctx: Any) -> None:
        """Called by the runner, in its thread, before the measurement: configure the channels, then
        zero the ones that ask for it, one at a time, asking the operator to short and to reconnect.
        """
        problems = self.problems()
        if problems:
            raise ChannelSetupError("; ".join(problems))
        self._configured = False
        self._configure()
        zero = [s for s in self.settings.values() if s.zero]
        for s in sorted(zero, key=lambda item: item.number):
            self.zero_channel(ctx, s)

    def zero_channel(self, ctx: Any, s: ChannelSettings) -> Optional[float]:
        """The zero procedure of one channel: ask to short its terminals, take the offset, ask to
        connect them back. Returns the offset the instrument stored (None if it cannot say); the
        operator can skip the channel (it is then read without the zero) or abort the run."""
        from .measurement import Stopped

        data = {"kind": "zero", "channel": s.number, "name": s.name}
        answer = ctx.ask(
            f"Zero of channel {s.label}: connect the two input terminals of the channel together "
            "(a short), then continue.",
            ["continue", "skip_zero", "abort"],
            default="abort",
            data={**data, "step": "short"},
        )
        if answer == "abort":
            raise Stopped()
        if answer == "skip_zero":
            self._zeroed[s.number] = None
            ctx.log(f"channel {s.label}: not zeroed (skipped)", "warning")
            return None
        channel = str(s.number)
        self._handle.call("null_offset", channels=channel)
        ctx.sleep(zero_wait_s(s))
        self._handle.call("set_scale_state", state="ON", channels=channel)
        offset = self._offset(channel)
        self._zeroed[s.number] = offset
        shown = f" (offset {offset:+.6g})" if offset is not None else ""
        ctx.log(f"channel {s.label} zeroed{shown}")
        answer = ctx.ask(
            f"Zero of channel {s.label} done{shown}: connect its terminals back where they were, "
            "then continue.",
            ["continue", "abort"],
            default="abort",
            data={**data, "step": "reconnect", "offset": offset},
        )
        if answer == "abort":
            raise Stopped()
        return offset

    def _offset(self, channel: str) -> Optional[float]:
        """The offset the instrument keeps for the channel, if the model can tell."""
        try:
            value = self._handle.readback("set_scale_offset", channels=channel)
            value = value[0] if isinstance(value, (list, tuple)) else value
            return float(value)
        except Exception:  # not every model reads it back, and it is only for the log
            return None

    def __repr__(self) -> str:
        return f"ConfiguredHandle({self._handle!r}, channels {sorted(self.settings)})"


def wrap_if_configured(handle: Any, entry: Mapping[str, Any]) -> Any:
    """``handle`` itself, or a ``ConfiguredHandle`` when a channel of the datalogger ``entry`` asks
    for something beyond the defaults and the model reads channels through a scan list. A file with
    no such setting is not touched, so a project that does not use them behaves as before.
    ``ChannelSetupError`` / ``DataloggerSetupError`` for a setting that cannot be used."""
    settings = settings_of_entry(entry)
    if not any(s.configured for s in settings):
        return handle
    if not (handle.supports("select_channels") and handle.supports("read_scan")):
        raise ChannelSetupError(
            "this instrument reads no scan list, so the settings of its channels (range, "
            "integration time, zero, input impedance) cannot be applied"
        )
    wrapped = ConfiguredHandle(handle, settings)
    problems = wrapped.problems()
    if problems:
        raise ChannelSetupError("; ".join(problems))
    return wrapped


@dataclass
class ModelOptions:
    """What the settings of a channel can be for a model (for the editor)."""

    nplc: List[str] = field(default_factory=list)  # the integration times the model lists
    ranges: Dict[str, List[str]] = field(default_factory=dict)  # function -> fixed ranges
    zero: bool = False  # the model can zero a channel (null_offset and scaling)
    impedance: bool = False  # the model has the input impedance setting


def _values(commands: Mapping[str, Any], call: str, parameter: str) -> List[str]:
    spec = ((commands.get(call) or {}).get("parameters") or {}).get(parameter) or {}
    return [str(v) for v in spec.get("values") or [] if str(v).upper() not in ("MIN", "MAX")]


def options_of(commands: Optional[Mapping[str, Any]]) -> ModelOptions:
    """The options of a model from its commands (``Library.commands(model_id)``): the integration
    times and ranges it lists, and whether it can zero a channel and set the input impedance. An
    empty ``ModelOptions`` for a model that has none."""
    commands = commands or {}
    options = ModelOptions()
    options.nplc = _values(commands, "set_voltage_nplc", "plcs")
    for function in FUNCTIONS.values():
        found = _values(commands, function.range_call, "range")
        if found:
            options.ranges[function.name] = found
    options.zero = all(call in commands for call in ("null_offset", "set_scale_state"))
    options.impedance = "input_impedance_auto" in commands
    return options


__all__ = [
    "ChannelSettings", "ChannelSetupError", "ConfiguredHandle", "FUNCTIONS", "Function", "KEYS",
    "ModelOptions", "channel_problems", "check_settings", "config_calls", "extra_calls",
    "function_of", "options_of",
    "parse_impedance", "parse_nplc", "parse_range", "settings_of", "settings_of_entry",
    "wrap_if_configured", "zero_wait_s", "DataloggerSetupError",
]  # fmt: skip
