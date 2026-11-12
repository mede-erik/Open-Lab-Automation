# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""End-to-end benchmark of the engine on a simulated instrument (no hardware).

    python benchmarks/bench_engine.py                     # 300 iterations, report on screen
    python benchmarks/bench_engine.py --latency-ms 2      # the instrument takes 2 ms to answer
    python benchmarks/bench_engine.py --json new.json     # keep the report ...
    python benchmarks/bench_engine.py --compare old.json  # ... and compare with an earlier one

A real measurement loop is run through everything the software puts between a measurement and an
instrument (library lookup, call planner, instrument lock, steps, simulated link, the runner,
the run writer), using a power supply model of the instrument library. The simulated instrument
answers immediately (plus ``--latency-ms``), so what is measured is the cost of the software;
run it before and after a change to see whether the change made anything slower. On real
hardware use ``OLA_BENCH=1`` instead.
"""

import argparse
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ola import bench  # noqa: E402
from ola.instrument import Instrument  # noqa: E402
from ola.instrument_handle import InstrumentHandle  # noqa: E402
from ola.library import Library  # noqa: E402
from ola.measurement import Measurement, Role  # noqa: E402
from ola.runner import FINAL_STATES, Runner  # noqa: E402
from ola.runs import RunWriter, read_run  # noqa: E402
from ola.sim import SimTransport  # noqa: E402

LIBRARY = os.path.join(ROOT, "Instruments_LIB", "instruments_lib.json")


def find_supply(library):
    """Id of the first library model that has the calls the benchmark uses."""
    wanted = ("set_voltage", "read_voltage", "set_current", "output_on", "output_off")
    for category, series_list in library.categories.items():
        if not isinstance(series_list, list):
            continue
        for series in series_list:
            for model in series.get("models", []) or []:
                commands = library.commands(model.get("id", "")) or {}
                if all(name in commands for name in wanted):
                    return model["id"]
    raise SystemExit("no power supply model with the calls the benchmark needs")


class Loop(Measurement):
    """Sets a voltage, reads it back and records a point, ``n`` times."""

    roles = (Role(name="psu", category="power_supplies_series"),)

    def run(self, ctx):
        psu = ctx.instrument("psu")
        psu.call("set_current", value=1.0, channel_number=1)
        psu.call("output_on")
        for i in range(self.params["n"]):
            ctx.checkpoint()
            psu.call("set_voltage", value=1.0 + i % 10, channel_number=1)
            ctx.sleep(self.params["settle_s"])
            volts = psu.call("read_voltage", channel_number=1)
            ctx.emit_point({"i": i, "volts": volts})

    def teardown(self, ctx):
        ctx.instrument("psu").call("output_off")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--iterations", type=int, default=300)
    ap.add_argument(
        "--latency-ms", type=float, default=0.0, help="simulated instrument answer time"
    )
    ap.add_argument("--settle-ms", type=float, default=0.0, help="ctx.sleep after every set")
    ap.add_argument("--library", default=LIBRARY)
    ap.add_argument("--json", help="write the report to this file")
    ap.add_argument("--compare", help="report of an earlier run to compare with")
    a = ap.parse_args()

    library = Library.load(a.library)
    model = find_supply(library)

    def answer(cmd):
        if a.latency_ms:
            time.sleep(a.latency_ms / 1000.0)
        return "5.0" if cmd.rstrip().endswith("?") else None

    bench.enable(fresh=True)
    cancel = None
    handle = InstrumentHandle(
        "psu", library, model, Instrument("psu", SimTransport(answer)), cancel
    )
    measurement = Loop({"n": a.iterations, "settle_s": a.settle_ms / 1000.0})
    runner = Runner(measurement, {"psu": handle}, collect=False, bench=True)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "bench.jsonl")
        runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
        runner.start()
        runner.join()
        run = read_run(path)
    assert runner.state in FINAL_STATES and runner.state.value == "finished", runner.error
    report = run["bench"]
    print(f"model {model}, {a.iterations} iterations, latency {a.latency_ms} ms\n")
    print(bench.format_report(report))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1)
    if a.compare:
        with open(a.compare, encoding="utf-8") as f:
            old = json.load(f)
        print("\nCompared with", a.compare)
        print(bench.compare_reports(old, report))


if __name__ == "__main__":
    main()
