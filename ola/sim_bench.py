# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A simulated bench for a converter: a supply, an electronic load and a voltmeter, to try
measurements without hardware.

``SimBench`` is the converter under test and the three instruments around it::

    bench = SimBench(vout_v=5.0, line_mv_per_v=2.0, output_mohm=40.0)
    bench.supply.call("set_voltage", value=12.0, channel_number=1)
    bench.supply.call("output_on")
    bench.load.call("set_current_level", value=1.0)
    bench.load.call("load_on")
    bench.meter.call("measure_dc_voltage", channels="103")      # the output: 5.0 - 0.040 V ...

The output voltage is ``vout_v + line_mv_per_v * (vin - vin_nominal_v) / 1000 - output_mohm * i /
1000``: it follows the input by ``line_mv_per_v`` millivolts per volt and drops by ``output_mohm``
milliohms with the load current. With the supply or the load off, or with the input below
``dropout_v``, the output is 0 (and the load draws nothing). The meter reads the **output** on
channel ``103``, the **input at the converter** on ``101`` (the supply voltage less the drop in the
cables, ``cable_mohm`` milliohms at the load current) and 0 on any other. ``supply.read_voltage``
gives the supply's own setpoint. ``noise_mv`` adds random error to every reading; ``calls`` records
what was asked of each instrument, in ``bench.log`` in order.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Tuple


class _Instrument:
    """What a measurement sees of one instrument: ``call`` and ``supports``."""

    def __init__(self, bench: "SimBench", name: str, known: Tuple[str, ...]):
        self.bench, self.name, self.known = bench, name, known
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def supports(self, name: str) -> bool:
        """True for the calls this simulated instrument knows."""
        return name in self.known

    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call (the same interface as an ``InstrumentHandle``)."""
        if name not in self.known:
            raise ValueError(f"{self.name}: unknown call {name!r}")
        self.calls.append((name, dict(args)))
        self.bench.log.append((self.name, name, dict(args)))
        return self.bench.do(self.name, name, args)


class SimBench:
    """A converter with a supply, a load and a meter (see the module docstring)."""

    def __init__(
        self,
        vout_v: float = 5.0,
        vin_nominal_v: float = 12.0,
        line_mv_per_v: float = 2.0,
        output_mohm: float = 40.0,
        cable_mohm: float = 100.0,
        dropout_v: float = 6.0,
        noise_mv: float = 0.0,
        seed: int = 5,
    ):
        self.vout_v, self.vin_nominal_v = vout_v, vin_nominal_v
        self.line_mv_per_v, self.output_mohm = line_mv_per_v, output_mohm
        self.cable_mohm, self.dropout_v, self.noise_mv = cable_mohm, dropout_v, noise_mv
        self.setpoint_v = 0.0
        self.current_a = 0.0
        self.supply_on = False
        self.load_on = False
        self.mode = ""
        self.log: List[Tuple[str, str, Dict[str, Any]]] = []
        self._random = random.Random(seed)
        self.supply = _Instrument(
            self, "supply", ("set_voltage", "output_on", "output_off", "read_voltage")
        )
        self.load = _Instrument(
            self, "load", ("set_mode", "set_current_level", "load_on", "load_off")
        )
        self.meter = _Instrument(self, "meter", ("measure_dc_voltage",))

    # ----- the converter -----------------------------------------------------------------------
    def load_current(self) -> float:
        """The current the load draws now (0 if it is off or the converter is not running)."""
        return self.current_a if self.load_on and self.running() else 0.0

    def running(self) -> bool:
        """True if the supply is on and its voltage is high enough for the converter."""
        return self.supply_on and self.setpoint_v >= self.dropout_v

    def vin_at_converter(self) -> float:
        """The input voltage at the converter pins: the supply less the drop in the cables."""
        if not self.supply_on:
            return 0.0
        iin = self.load_current() * self.vout_v / max(self.setpoint_v, 1e-9)  # roughly
        return self.setpoint_v - iin * self.cable_mohm / 1000.0

    def vout(self) -> float:
        """The output voltage now."""
        if not self.running():
            return 0.0
        vin = self.vin_at_converter()
        return (
            self.vout_v
            + self.line_mv_per_v * (vin - self.vin_nominal_v) / 1000.0
            - self.output_mohm * self.load_current() / 1000.0
        )

    def _noisy(self, value: float) -> float:
        return value + self._random.gauss(0, self.noise_mv / 1000.0) if self.noise_mv else value

    # ----- the instruments ---------------------------------------------------------------------
    def do(self, instrument: str, call: str, args: Dict[str, Any]) -> Any:
        """Run one call of an instrument."""
        if instrument == "supply":
            if call == "set_voltage":
                self.setpoint_v = float(args["value"])
            elif call == "output_on":
                self.supply_on = True
            elif call == "output_off":
                self.supply_on = False
            elif call == "read_voltage":
                return self._noisy(self.setpoint_v if self.supply_on else 0.0)
        elif instrument == "load":
            if call == "set_current_level":
                self.current_a = float(args["value"])
            elif call == "load_on":
                self.load_on = True
            elif call == "load_off":
                self.load_on = False
            elif call == "set_mode":
                self.mode = args["mode"]
        elif instrument == "meter":
            channel = str(args.get("channels", ""))
            if channel in ("103", ""):
                return self._noisy(self.vout())
            if channel == "101":
                return self._noisy(self.vin_at_converter())
            return 0.0
        return None


class SimResistiveBench:
    """A converter that feeds a **resistive load** made of resistors, with a supply, a voltmeter
    and a multiplexer, to try the resistive-efficiency measurement without hardware::

        bench = SimResistiveBench(channel_ohms={"201": 10.0, "202": 22.0})
        bench.switch.call("close_channel", channels="201,202")     # 10 || 22 ohm
        bench.supply.call("set_voltage", value=12.0)
        bench.supply.call("output_on")
        bench.meter.call("measure_dc_voltage", channels="103")     # the output
        bench.meter.call("measure_dc_voltage", channels="102")     # a 0.1 ohm shunt on the input

    The converter regulates its output to ``vout_v`` while its input is at least ``dropout_v`` and
    the power ``vout_v**2 / R`` does not exceed ``pmax_w`` (above it the output sags, so the power
    stays at ``pmax_w``). Its efficiency is ``eta_peak`` less ``vin_droop`` per volt above
    ``dropout_v`` and ``load_droop`` times the fraction of ``pmax_w`` it delivers; with the supply
    off it draws nothing, and with no load connected only ``quiescent_a``. The load is the closed
    relays of the multiplexer, combined by ``combine`` (a function of the closed channels that gives
    ohms: all in parallel by default), or ``manual_ohms`` for a measurement where the user connects
    the resistors by hand. ``r_error`` is how far the real resistance is from the nominal one
    (a fraction: +0.01 is 1 % more). Channel ``101`` of the meter is the input voltage, ``102`` the
    shunt voltage (``shunt_ohm`` times the input current) and ``103`` the output. ``log`` records
    every call in order, and ``events`` what happened to the circuit (``"supply off"``, ``"close
    201"`` ...) so that a test can check the order.
    """

    def __init__(
        self,
        channel_ohms: Dict[str, float] = None,
        combine: Any = None,
        vout_v: float = 5.0,
        dropout_v: float = 6.0,
        eta_peak: float = 0.95,
        vin_droop: float = 0.004,
        load_droop: float = 0.05,
        pmax_w: float = 25.0,
        quiescent_a: float = 0.005,
        shunt_ohm: float = 0.1,
        r_error: float = 0.0,
        seed: int = 5,
    ):
        self.channel_ohms = dict(channel_ohms or {})
        self.combine = combine
        self.vout_v, self.dropout_v, self.eta_peak = vout_v, dropout_v, eta_peak
        self.vin_droop, self.load_droop, self.pmax_w = vin_droop, load_droop, pmax_w
        self.quiescent_a, self.shunt_ohm, self.r_error = quiescent_a, shunt_ohm, r_error
        self.setpoint_v = 0.0
        self.supply_on = False
        self.closed: List[str] = []
        self.manual_ohms: Any = None
        self.log: List[Tuple[str, str, Dict[str, Any]]] = []
        self.events: List[str] = []
        self.supply = _Instrument(
            self, "supply",
            ("set_voltage", "output_on", "output_off", "read_voltage", "read_current"),
        )  # fmt: skip
        self.meter = _Instrument(self, "meter", ("measure_dc_voltage",))
        self.switch = _Instrument(
            self, "switch", ("close_channel", "open_channels", "query_channel_closed_state")
        )

    # ----- the circuit -------------------------------------------------------------------------
    def resistance(self) -> float:
        """The real resistance of the load now (``inf`` if nothing is connected)."""
        if self.closed:
            channels = frozenset(self.closed)
            if self.combine is not None:
                nominal = float(self.combine(channels))
            else:
                nominal = 1.0 / sum(1.0 / self.channel_ohms[c] for c in channels)
        elif self.manual_ohms is not None:
            nominal = float(self.manual_ohms)
        else:
            return float("inf")
        return nominal * (1 + self.r_error)

    def running(self) -> bool:
        """True if the supply is on and its voltage is high enough for the converter."""
        return self.supply_on and self.setpoint_v >= self.dropout_v

    def vout(self) -> float:
        """The output voltage now: ``vout_v``, or less if the power would exceed ``pmax_w``."""
        if not self.running():
            return 0.0
        r = self.resistance()
        if math.isinf(r):
            return self.vout_v
        return min(self.vout_v, math.sqrt(self.pmax_w * r))

    def pout(self) -> float:
        """The power in the load now, watts."""
        r = self.resistance()
        return 0.0 if math.isinf(r) else self.vout() ** 2 / r

    def efficiency(self) -> float:
        """The efficiency now (a fraction)."""
        eta = (
            self.eta_peak
            - self.vin_droop * (self.setpoint_v - self.dropout_v)
            - self.load_droop * self.pout() / self.pmax_w
        )
        return max(0.2, min(0.99, eta))

    def iin(self) -> float:
        """The input current now, amps."""
        if not self.supply_on:
            return 0.0
        if not self.running():
            return 0.0
        return self.quiescent_a + self.pout() / self.efficiency() / self.setpoint_v

    # ----- the instruments ---------------------------------------------------------------------
    def do(self, instrument: str, call: str, args: Dict[str, Any]) -> Any:
        """Run one call of an instrument."""
        if instrument == "supply":
            if call == "set_voltage":
                self.setpoint_v = float(args["value"])
            elif call == "output_on":
                self.supply_on = True
                self.events.append("supply on")
            elif call == "output_off":
                self.supply_on = False
                self.events.append("supply off")
            elif call == "read_voltage":
                return self.setpoint_v if self.supply_on else 0.0
            elif call == "read_current":
                return self.iin()
        elif instrument == "meter":
            channel = str(args.get("channels", ""))
            if channel == "101":
                return self.setpoint_v if self.supply_on else 0.0
            if channel == "102":
                return self.iin() * self.shunt_ohm
            if channel in ("103", ""):
                return self.vout()
            return 0.0
        elif instrument == "switch":
            wanted = [c.strip() for c in str(args.get("channels", "")).split(",") if c.strip()]
            for channel in wanted:
                if call == "close_channel":
                    if channel not in self.channel_ohms and self.combine is None:
                        raise ValueError(f"no relay {channel}")
                    if channel not in self.closed:
                        self.closed.append(channel)
                    self.events.append(f"close {channel}")
                elif call == "open_channels":
                    if channel in self.closed:
                        self.closed.remove(channel)
                    self.events.append(f"open {channel}")
            if call == "query_channel_closed_state":
                return ",".join("1" if c in self.closed else "0" for c in wanted)
        return None
