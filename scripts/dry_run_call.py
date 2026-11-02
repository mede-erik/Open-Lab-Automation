#!/usr/bin/env python3
"""Show the commands a logical call (or a whole .was file) would send to a model, without hardware.

Examples:
    python3 scripts/dry_run_call.py --model OSC_Siglent_SDS824X_HD --call set_channel_scale \\
        --arg channel_number=1 --arg value=0.5
    python3 scripts/dry_run_call.py --model OSC_Tek_MSO54 \\
        --call query_trigger_status --answer TRIGGER
    python3 scripts/dry_run_call.py --model OSC_Rigol_DS1054Z --was project.was

The library is read from --library (default: Instruments_LIB/instruments_lib.json, or a sibling
Instruments_LIB folder); the call schemas from the 'schema' folder next to it.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ola.call_errors import CallError  # noqa: E402
from ola.call_planner import plan_call  # noqa: E402
from ola.instrument import Instrument  # noqa: E402
from ola.library import Library  # noqa: E402
from ola.sim import SimTransport  # noqa: E402
from ola.was_calls import oscilloscope_calls_from_was  # noqa: E402


def default_library():
    for p in (
        os.path.join(ROOT, "Instruments_LIB", "instruments_lib.json"),
        os.path.join(os.path.dirname(ROOT), "Instruments_LIB", "instruments_lib.json"),
    ):
        if os.path.isfile(p):
            return p
    return os.path.join(ROOT, "Instruments_LIB", "instruments_lib.json")


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def run_call(library, model, call, args, answer):
    try:
        plan = plan_call(library, model, call, args)
    except CallError as exc:
        print(f"  {call:30} -> {exc}")
        return False
    sim = SimTransport(lambda cmd: answer if answer is not None else "0")
    instrument = Instrument("dry-run", sim)
    if plan.access == "driver":
        print(f"  {call:30} -> driver {plan.driver}")
        return True
    try:
        raw = instrument.run(plan)
        logical = plan.interpret(raw)
    except CallError as exc:
        print(f"  {call:30} -> {exc}")
        return False
    sent = " ; ".join(sim.log) if sim.log else "(nothing)"
    suffix = (
        f"   answer {answer!r} -> {logical!r}" if plan.result.get("from_step") is not None else ""
    )
    print(f"  {call:30} -> {sent}{suffix}")
    return True


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--library", default=default_library())
    ap.add_argument("--model", required=True, help="model id, e.g. OSC_Siglent_SDS824X_HD")
    ap.add_argument("--call", help="logical call name")
    ap.add_argument("--arg", action="append", default=[], metavar="NAME=VALUE")
    ap.add_argument("--answer", help="simulated instrument answer for query steps")
    ap.add_argument("--was", help="oscilloscope .was file: show every call it produces")
    a = ap.parse_args()

    library = Library.load(a.library)
    if library.find_model(a.model) is None:
        sys.exit(f"model {a.model!r} is not in the library")
    print(f"model {a.model}")
    ok = True
    if a.was:
        with open(a.was, encoding="utf-8") as f:
            for name, args in oscilloscope_calls_from_was(json.load(f)):
                ok &= run_call(library, a.model, name, args, a.answer)
    if a.call:
        args = {}
        for item in a.arg:
            name, _, value = item.partition("=")
            args[name] = parse_value(value)
        ok &= run_call(library, a.model, a.call, args, a.answer)
    if not a.was and not a.call:
        sys.exit("give --call or --was")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
