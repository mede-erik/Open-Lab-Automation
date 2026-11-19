# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A simulated datalogger that does what the Keysight 34970A does where it matters for the
settings of a channel, to try the zero procedure, the integration time and the input impedance
without hardware.

``SimDatalogger`` has the call names of the datalogger category and answers like the real one:

* each channel has its function, range, integration time (``nplc``), input impedance, and a
  scaling (gain, offset, on / off);
* **``configure_*`` and ``measure_*`` put the channel back to the defaults**: integration time 1,
  impedance 10 MOhm, scaling off, gain 1, offset 0 (the manual of the 34970A says so). A reading
  made with ``measure_*`` therefore never keeps a zero or an integration time;
* ``null_offset`` takes the present reading and stores the offset that makes it zero;
  ``set_scale_state`` turns the scaling on, and ``read_scan`` gives the scaled readings of the scan
  list (``select_channels``), not touching the configuration;
* what a channel reads is the voltage on its terminals (``signals``) plus what is there even
  with the terminals shorted (``wiring_offset``: thermal voltages, the offset of the input), less
  the loading of the source resistance (``source_ohm``) by the input resistance (10 GOhm with the
  automatic impedance on a range of 10 V or less, otherwise 10 MOhm). ``short(channel)`` and
  ``connect(channel)`` are what the operator does with the terminals.

``log`` records every call in order; ``without`` lists calls the simulated model does not have.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

KNOWN = (
    "configure_dc_voltage", "measure_dc_voltage", "configure_dc_current", "measure_dc_current",
    "configure_resistance", "measure_resistance", "set_voltage_nplc", "set_dc_current_nplc",
    "set_resistance_nplc", "input_impedance_auto", "set_zero_auto", "null_offset",
    "set_scale_state", "set_scale_offset", "select_channels", "read_scan",
)  # fmt: skip
DEFAULT_NPLC = 1.0


def parse_channels(text: str) -> List[int]:
    """``"101,103"`` or ``"101:103"`` or ``"(@101:103,105)"`` -> the channel numbers, in order."""
    numbers: List[int] = []
    for part in re.sub(r"[()@ ]", "", str(text)).split(","):
        if not part:
            continue
        if ":" in part:
            low, high = (int(x) for x in part.split(":"))
            numbers += list(range(low, high + 1))
        else:
            numbers.append(int(part))
    return numbers


class SimDatalogger:
    """A datalogger with the behaviour of the 34970A that matters here (see the module doc)."""

    def __init__(
        self,
        name: str = "dlog",
        signals: Optional[Dict[int, float]] = None,
        wiring_offset: Optional[Dict[int, float]] = None,
        source_ohm: Optional[Dict[int, float]] = None,
        without: Iterable[str] = (),
    ):
        self.name = name
        self.model_id = "SIM_DATALOGGER"
        self.signals = dict(signals or {})
        self.wiring_offset = dict(wiring_offset or {})
        self.source_ohm = dict(source_ohm or {})
        self.shorted: set = set()
        self.known = tuple(k for k in KNOWN if k not in set(without))
        self.channels: Dict[int, Dict[str, Any]] = {}
        self.scan: List[int] = []
        self.log: List[Tuple[str, Dict[str, Any]]] = []
        self.events: List[str] = []  # what happened to the channels: "configure 101", "null 101"...

    # ----- the operator ------------------------------------------------------------------------
    def short(self, channel: int) -> None:
        """The operator connects the two terminals of the channel together."""
        self.shorted.add(int(channel))

    def connect(self, channel: int) -> None:
        """The operator connects the terminals back to the signal."""
        self.shorted.discard(int(channel))

    # ----- what the channels read --------------------------------------------------------------
    def state(self, number: int) -> Dict[str, Any]:
        """The configuration of a channel now (the defaults of a channel never configured)."""
        return self.channels.setdefault(number, self._defaults("VOLT:DC", "AUTO"))

    @staticmethod
    def _defaults(function: str, range_: Any) -> Dict[str, Any]:
        return {
            "function": function, "range": range_, "nplc": DEFAULT_NPLC, "impedance_auto": False,
            "zero_auto": True, "gain": 1.0, "offset": 0.0, "scale": False,
        }  # fmt: skip

    def raw(self, number: int) -> float:
        """The voltage the input sees: the signal (nothing if shorted) and the offset of the
        wiring, loaded by the input resistance."""
        v = 0.0 if number in self.shorted else self.signals.get(number, 0.0)
        state = self.state(number)
        rng = state["range"]
        high_z = state["impedance_auto"] and (rng == "AUTO" or float(rng) <= 10.0)
        r_in = 10e9 if high_z else 10e6
        r_source = self.source_ohm.get(number, 0.0)
        return v * r_in / (r_in + r_source) + self.wiring_offset.get(number, 0.0)

    def value(self, number: int) -> float:
        """The reading of a channel as the instrument gives it: scaled if the scaling is on."""
        state = self.state(number)
        raw = self.raw(number)
        return state["gain"] * raw + state["offset"] if state["scale"] else raw

    # ----- the instrument ----------------------------------------------------------------------
    def supports(self, name: str) -> bool:
        """True for the calls this simulated model has."""
        return name in self.known

    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call (the interface of an ``InstrumentHandle``)."""
        if name not in self.known:
            raise ValueError(f"{self.name}: unknown call {name!r}")
        self.log.append((name, dict(args)))
        function = {"dc_voltage": "VOLT:DC", "dc_current": "CURR:DC", "resistance": "RES"}
        if name.startswith(("configure_", "measure_")):
            numbers = parse_channels(args["channels"])
            for n in numbers:  # CONFigure and MEASure put everything back to the defaults
                self.channels[n] = self._defaults(
                    function.get(name.split("_", 1)[1], "VOLT:DC"), args.get("range", "AUTO")
                )
                self.events.append(f"configure {n}")
            if name.startswith("measure_"):
                return self.value(numbers[0])
            return None
        if name.endswith("_nplc"):
            for n in parse_channels(args["channels"]):
                self.state(n)["nplc"] = float(args["plcs"])
                self.events.append(f"nplc {n}")
        elif name == "input_impedance_auto":
            for n in parse_channels(args["channels"]):
                self.state(n)["impedance_auto"] = str(args["state"]).upper() in ("ON", "1")
                self.events.append(f"impedance {n}")
        elif name == "set_zero_auto":
            for n in parse_channels(args["channels"]):
                self.state(n)["zero_auto"] = str(args["mode"]).upper() == "ON"
        elif name == "null_offset":
            for n in parse_channels(args["channels"]):
                self.state(n)["offset"] = -self.raw(n) * self.state(n)["gain"]
                self.events.append(f"null {n}")
        elif name == "set_scale_state":
            for n in parse_channels(args["channels"]):
                self.state(n)["scale"] = str(args["state"]).upper() in ("ON", "1")
                self.events.append(f"scale {n}")
        elif name == "set_scale_offset":
            for n in parse_channels(args["channels"]):
                self.state(n)["offset"] = float(args["offset"])
        elif name == "select_channels":
            self.scan = parse_channels(args["channels"])
            self.events.append(f"scan {args['channels']}")
        elif name == "read_scan":
            return [self.value(n) for n in self.scan]
        return None

    def readback(self, name: str, **args: Any) -> Any:
        """The value of a ``set`` call, read back (only the scaling offset here)."""
        if name != "set_scale_offset":
            raise ValueError(f"{self.name}: no readback of {name!r}")
        return self.state(parse_channels(args["channels"])[0])["offset"]

    def __repr__(self) -> str:
        return f"SimDatalogger({self.name!r})"
