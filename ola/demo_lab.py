"""A small simulated laboratory to try the measurement windows without any instrument.

``DemoLab`` is a power supply, an electronic load and a data logger around a converter of 90 %
efficiency; ``demo_params()`` is an efficiency file that uses them. Used by
``python -m frontend.ui.RunWindow`` (and handy in scripts)::

    lab = DemoLab()
    handles = [DemoHandle(name, lab) for name in INSTRUMENTS]
    runner = Runner(registry.create("efficiency", demo_params()), {"instruments": handles})

``lab.vin_error`` makes the data logger disagree with the supply (a fraction: 0.05 = 5 %), which
is how to see the "reading does not match" question.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

INSTRUMENTS = ["psu1", "psu2", "daq1", "load1"]
EFFICIENCY = 0.9
VOUT = 5.0


class DemoLab:
    """The simulated instruments and the converter between them."""

    def __init__(self, delay_s: float = 0.0, vin_error: float = 0.0):
        self.vin = self.iout = self.vaux = 0.0
        self.delay_s = delay_s  # time every call takes (to see the window move)
        self.vin_error = vin_error  # the data logger reads vin * (1 + vin_error)
        self.errors_left: int = -1  # -1: always; n: only the next n readings of vin
        self.on = {"psu1": False, "psu2": False, "load1": False}
        self.log: List[Tuple[str, str, Dict[str, Any]]] = []

    def do(self, instrument: str, call: str, args: Dict[str, Any]) -> Any:
        """Run one call of an instrument and return what it answers."""
        if self.delay_s:
            time.sleep(self.delay_s)
        self.log.append((instrument, call, dict(args)))
        if call in ("output_on", "load_on"):
            self.on[instrument] = True
        elif call in ("output_off", "load_off"):
            self.on[instrument] = False
        elif call in ("output_state_query", "query_input_state"):
            return self.on[instrument]
        if (instrument, call) == ("psu1", "set_voltage"):
            self.vin = args["value"]
        elif (instrument, call) == ("psu2", "set_voltage"):
            self.vaux = args["value"]
        elif (instrument, call) == ("load1", "set_current_level"):
            self.iout = args["value"]
        elif (instrument, call) == ("psu1", "read_voltage"):
            return self.vin
        elif (instrument, call) == ("load1", "read_current"):
            return self.iout
        elif (instrument, call) == ("daq1", "read_ch"):
            channel = args["channels"]
            if channel == "101":  # input voltage
                error = self.vin_error if self.errors_left != 0 else 0.0
                if self.errors_left > 0:
                    self.errors_left -= 1
                return self.vin * (1 + error)
            if channel == "102":  # shunt of 0.1 ohm on the input current
                iin = VOUT * self.iout / EFFICIENCY / self.vin if self.vin else 0.0
                return iin / 10
            if channel == "103":  # output voltage
                return VOUT if self.vin else 0.0
        return None


class DemoHandle:
    """What a measurement sees of one instrument: ``handle.call(name, **args)``."""

    def __init__(self, name: str, lab: DemoLab):
        self.name, self.lab = name, lab

    def call(self, name: str, **args: Any) -> Any:
        """Run the call ``name`` of this instrument with the given arguments."""
        return self.lab.do(self.name, name, args)


def demo_params(samples: int = 2, settle_s: float = 0.0, interval_s: float = 0.05) -> dict:
    """An efficiency file for the demo lab: ``vin`` 9-15 V (fastest sweep) for three load
    currents, auxiliary supply fixed, input and output measured by the data logger."""
    return {
        "variables": [
            {
                "name": "vin",
                "set": {"instrument": "psu1", "call": "set_voltage", "args": {"channel_number": 1}},
                "sweep": {"values": [9, 12, 15]},
                "reads": {
                    "psu": {"instrument": "psu1", "call": "read_voltage"},
                    "daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "101"}},
                },
                "verify": {"read": "daq", "tol_rel": 0.01, "tol_abs": 0.02},
            },
            {
                "name": "iout",
                "set": {"instrument": "load1", "call": "set_current_level"},
                "sweep": {"start": 0.5, "stop": 2.5, "points": 3},
                "reads": {"load": {"instrument": "load1", "call": "read_current"}},
            },
            {"name": "vaux", "set": {"instrument": "psu2", "call": "set_voltage"}, "value": 12},
            {
                "name": "iin",
                "reads": {
                    "daq": {
                        "instrument": "daq1",
                        "call": "read_ch",
                        "args": {"channels": "102"},
                        "scale": 10,
                    }
                },
            },
            {
                "name": "vout",
                "reads": {
                    "daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "103"}}
                },
            },
        ],
        "timing": {"settle_s": settle_s, "samples": samples, "interval_s": interval_s},
        "derived": {
            "pin": "vin@daq * iin@daq",
            "pout": "vout@daq * iout@load",
            "efficiency": "100 * pout / pin",
        },
        "startup": [{"instrument": "psu1", "call": "output_on"}],
        "shutdown": [{"instrument": "psu1", "call": "output_off"}],
    }
