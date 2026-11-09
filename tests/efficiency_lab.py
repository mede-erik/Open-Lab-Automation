# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A simulated laboratory for the efficiency tests: a power supply, an electronic load, a data
logger and an ideal converter of efficiency 90 % between them."""

import threading
import time

from ola.registry import default_registry
from ola.runner import Runner
from tests.efficiency_params import good
from tests.measurement_helpers import wait_for

EFF = 0.9  # efficiency of the simulated converter
VOUT = 5.0


class Lab:
    """Psu + electronic load + data logger around an ideal converter of efficiency 90 %."""

    def __init__(self):
        self.vin = self.iout = self.vaux = 0.0
        self.log = []  # every call, in order: (instrument, call, args)
        self.daq_vin_error = 0.0  # the logger sees vin * (1 + error)
        self.daq_errors_left = None  # None: always; n: only the next n reads of channel 101
        self.fail = {}  # (instrument, call) -> exception to raise
        self.vin_noise = []  # values added to the logger's vin, one per read
        self.on = {"psu1": False, "psu2": False, "load1": False}  # state of the outputs
        self.state_answer = lambda on: on  # how the instruments answer "is the output on?"
        self.stamps = []  # time of every call, parallel to ``log``

    # converter
    @property
    def pout(self):
        return VOUT * self.iout

    @property
    def iin(self):
        return self.pout / EFF / self.vin if self.vin else 0.0

    # instruments
    def do(self, instrument, call, args):
        self.log.append((instrument, call, dict(args)))
        self.stamps.append(time.monotonic())
        if (instrument, call) in self.fail:
            raise self.fail[(instrument, call)]
        if call in ("output_on", "load_on"):
            self.on[instrument] = True
        elif call in ("output_off", "load_off"):
            self.on[instrument] = False
        elif call in ("output_state_query", "query_input_state"):
            return self.state_answer(self.on[instrument])
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
            ch = args["channels"]
            if ch == "101":
                error = self.daq_vin_error
                if self.daq_errors_left is not None:
                    error = error if self.daq_errors_left > 0 else 0.0
                    self.daq_errors_left -= 1
                noise = self.vin_noise.pop(0) if self.vin_noise else 0.0
                return self.vin * (1 + error) + noise
            if ch == "102":
                return self.iin / 10  # shunt: 0.1 ohm -> scale 10 gives amperes
            if ch == "103":
                return VOUT if self.vin else 0.0
        return None


class Handle:
    def __init__(self, name, lab):
        self.name, self.lab = name, lab

    def call(self, name, **args):
        return self.lab.do(self.name, name, args)


def params(**timing):
    p = good()
    p["timing"] = {"settle_s": 0, "samples": 2, "interval_s": 0.01, **timing}
    return p


def build(p, lab=None, **runner_kw):
    lab = lab or Lab()
    registry = default_registry(user_dir="/nonexistent")
    m = registry.create("efficiency", p)
    handles = [Handle(n, lab) for n in ("psu1", "psu2", "daq1", "load1")]
    return Runner(m, {"instruments": handles}, **runner_kw), lab


def rows(runner, table="points"):
    return [e.data for e in runner.drain() if e.kind == "point" and e.data["table"] == table]


def calls(lab, instrument=None, call=None):
    return [
        c
        for c in lab.log
        if (instrument is None or c[0] == instrument) and (call is None or c[1] == call)
    ]


def answer_questions(runner, choices):
    """A stand-in for the pop-up: answers the questions with the given choices, in order."""
    given = []

    def worker():
        for choice in choices:
            if not wait_for(lambda: runner.pending_questions, timeout=5):
                return
            q = runner.pending_questions[0]
            given.append((q["data"].get("variable"), q["choices"], choice))
            runner.answer(q["id"], choice)
            wait_for(lambda: not runner.pending_questions, timeout=2)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return given, t
