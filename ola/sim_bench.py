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
