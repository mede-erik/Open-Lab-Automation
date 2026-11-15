# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Benchmark of a real instrument: how long it takes to answer and what the software adds.

    python benchmarks/bench_hardware.py --model PSU_OWON_ODP3033 \
        --address TCPIP0::192.168.1.50::inst0::INSTR --arg channel_number=1
    python benchmarks/bench_hardware.py --model PSU_OWON_ODP3033 --address ASRL/dev/ttyUSB0::INSTR \
        --arg channel_number=1 --repeat 100 --calls read_voltage,read_current --json owon.json \
        --compare owon_before.json

Safe by default: only **queries** of the library are run (nothing is set, switched or changed),
and only those that need no argument. The default calls are ``identification_query``,
``error_query``, ``read_voltage``, ``read_current`` and ``output_state_query``, those of them the
model has; ``--calls`` chooses others (a call that is not a query is refused, and so are
``self_test`` and ``reset`` calls: they are slow or change the instrument).

For every call you get the time of a call as the measurement sees it, how much of it is the
instrument (``io``) and how much is the software (``plan`` + ``interp`` + ``overhead``). The same
question is also sent straight to the link, without planner and lock (``--raw``, default
``*IDN?``; ``--raw ""`` skips it): that is the best the link can do, and the difference with the
call is what the software costs on this instrument. The first calls are a warm-up and are not
counted. Send the output (or the ``--json`` file) to compare instruments and transports.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ola import bench  # noqa: E402
from ola.instrument import Instrument  # noqa: E402
from ola.instrument_handle import InstrumentHandle  # noqa: E402
from ola.library import Library  # noqa: E402

LIBRARY = os.path.join(ROOT, "Instruments_LIB", "instruments_lib.json")
DEFAULT_CALLS = (
    "identification_query",
    "error_query",
    "read_voltage",
    "read_current",
    "output_state_query",
)
FORBIDDEN = ("self_test", "reset", "calibrat", "clear", "factory")
WARMUP = 3


def safe_calls(library, model_id, names):
    """Split ``names`` into (calls that can be run, [(name, reason)] that cannot)."""
    ref = library.find_model(model_id)
    schema = library.schema(ref.category) or {}
    calls = schema.get("calls", {})
    commands = library.commands(model_id) or {}
    ok, refused = [], []
    for name in names:
        if name not in commands:
            refused.append((name, "the model does not define it"))
        elif any(word in name for word in FORBIDDEN):
            refused.append((name, "slow or changes the instrument"))
        elif calls.get(name, {}).get("kind") != "query":
            refused.append((name, "not a query"))
        elif any(a.get("required", True) for a in (calls[name].get("args") or {}).values()):
            refused.append((name, "needs an argument"))
        else:
            ok.append(name)
    return ok, refused


def call_args(library, model_id, name, extra):
    """The ``--arg`` values the schema of call ``name`` declares (the others are not passed)."""
    schema = library.schema(library.find_model(model_id).category) or {}
    declared = (schema.get("calls", {}).get(name, {}).get("args") or {}).keys()
    return {k: v for k, v in extra.items() if k in declared}


def parse_args_option(items):
    """``["channel_number=1", "x=a"]`` -> ``{"channel_number": 1, "x": "a"}``."""
    out = {}
    for item in items:
        key, _, value = item.partition("=")
        try:
            out[key] = json.loads(value)
        except ValueError:
            out[key] = value
    return out


def summary_lines(report):
    """One line per call: mean total, instrument part and software part."""
    lines = [
        f"{'call':34s} {'n':>5s} {'total':>9s} {'instrument':>11s} {'software':>9s} {'%sw':>6s}"
    ]
    for row in bench.rows_of(report, "call"):
        parts = row.get("parts_ms") or {}
        software = parts.get("plan", 0) + parts.get("interp", 0) + parts.get("overhead", 0)
        software += parts.get("lock", 0)
        pct = 100 * software / row["mean_ms"] if row["mean_ms"] else 0.0
        io = parts.get("io", 0)
        lines.append(
            f"{row['name'][:34]:34s} {row['n']:5d} {row['mean_ms']:9.3f} {io:11.3f} "
            f"{software:9.3f} {pct:5.1f}%"
        )
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True, help="library model id")
    ap.add_argument("--address", required=True, help="VISA address, as in the instrument file")
    ap.add_argument("--repeat", type=int, default=50, help="measured repetitions of each call")
    ap.add_argument("--calls", help="comma separated calls (default: the safe set above)")
    ap.add_argument(
        "--arg",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="argument passed to every call whose schema has it, e.g. channel_number=1 "
        "(some models need it although the schema says it is optional)",
    )
    ap.add_argument("--raw", default="*IDN?", help='query sent straight to the link ("" = skip)')
    ap.add_argument("--timeout-ms", type=int, default=5000)
    ap.add_argument("--library", default=LIBRARY)
    ap.add_argument("--json", help="write the report to this file")
    ap.add_argument("--compare", help="report of an earlier measurement to compare with")
    a = ap.parse_args()

    library = Library.load(a.library)
    if library.find_model(a.model) is None:
        sys.exit(f"model {a.model!r} is not in the library")
    names = [n.strip() for n in a.calls.split(",")] if a.calls else list(DEFAULT_CALLS)
    calls, refused = safe_calls(library, a.model, names)
    for name, why in refused:
        print(f"skipped {name}: {why}")
    if not calls:
        sys.exit("no call to measure")

    from ola import tester

    extra = parse_args_option(a.arg)
    args = {name: call_args(library, a.model, name, extra) for name in calls}
    bench.enable(fresh=True)
    with bench.span("connect", "open"):
        link = tester.open_visa(a.address, library, a.model, timeout_ms=a.timeout_ms)
    handle = InstrumentHandle("dut", library, a.model, Instrument("dut", link))
    try:
        working = []
        for name in calls:  # warm-up: first use wakes the link; a call that fails is left out
            try:
                for _ in range(WARMUP):
                    handle.call(name, **args[name])
                working.append(name)
            except Exception as exc:
                print(f"skipped {name}: {exc}")
        if not working:
            sys.exit("no call could be run (is the address right? does it need --arg?)")
        bench.enable(fresh=True)  # forget the warm-up
        for name in working:
            for _ in range(a.repeat):
                handle.call(name, **args[name])
        if a.raw:
            try:
                for _ in range(WARMUP):
                    link.query(a.raw)
                for _ in range(a.repeat):
                    with bench.span("raw", f"link: {a.raw}"):
                        link.query(a.raw)
            except Exception as exc:
                print(f"the raw query {a.raw!r} was not answered ({exc}): skipped")
        report = bench.current().report()
    finally:
        bench.disable()
        try:
            link.close()
        except Exception:
            pass

    print(f"\n{a.model} at {a.address}, {a.repeat} repetitions\n")
    print("\n".join(summary_lines(report)))
    raw = bench.rows_of(report, "raw")
    if raw:
        r = raw[0]
        print(
            f"\nStraight to the link ({a.raw}): mean {r['mean_ms']:.3f} ms, median "
            f"{r['median_ms']:.3f}, p95 {r['p95_ms']:.3f}, max {r['max_ms']:.3f}"
        )
    print("\n" + bench.format_report(report))
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
