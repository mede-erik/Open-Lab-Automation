#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Check a run against a golden sample, or keep a golden sample (see docs/golden.md).

    python scripts/golden_check.py RUN GOLDEN --curve S21:loss_db:0.5 --figure loss_868MHz_db:0.3
    python scripts/golden_check.py RUN GOLDEN --spec tolerances.json
    python scripts/golden_check.py --set PROJECT NAME RUN       # RUN becomes the golden sample
    python scripts/golden_check.py --list PROJECT

``--curve TRACE:VIEW:TOLERANCE`` and ``--figure KEY:TOLERANCE`` (an absolute tolerance, or ``5%``
for a relative one) can be repeated; ``--spec`` is a JSON file with the same form as in the guide.
The exit code is 0 for PASS, 1 for FAIL or NO DATA, 2 for a request that cannot be used.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ola.compare import CompareError, load_run  # noqa: E402
from ola.golden import (  # noqa: E402
    GoldenError,
    check_against_golden,
    find_golden,
    format_result,
    list_golden,
    set_golden,
)


def _tolerance(text):
    if text.endswith("%"):
        return {"rel": float(text[:-1]) / 100.0}
    return float(text)


def build_spec(args):
    """The tolerances of the command line (or of the file) as the spec of ``ola.golden``."""
    spec = {}
    if args.spec:
        with open(args.spec, encoding="utf-8") as f:
            spec = json.load(f)
    for item in args.curve or []:
        trace, view, tolerance = item.split(":")
        spec.setdefault("curves", []).append(
            {"trace": trace, "view": view, "tolerance": float(tolerance)}
        )
    for item in args.figure or []:
        key, tolerance = item.rsplit(":", 1)
        spec.setdefault("summary", {})[key] = _tolerance(tolerance)
    return spec


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("run", nargs="?", help="the run file to check")
    parser.add_argument("golden", nargs="?", help="the golden run file, or its name with --project")
    parser.add_argument("--project", help="the project folder: GOLDEN is a name kept in it")
    parser.add_argument("--curve", action="append", help="TRACE:VIEW:TOLERANCE")
    parser.add_argument("--figure", action="append", help="KEY:TOLERANCE (5%% for relative)")
    parser.add_argument("--spec", help="a JSON file with the tolerances")
    parser.add_argument("--set", nargs=3, metavar=("PROJECT", "NAME", "RUN"))
    parser.add_argument("--list", metavar="PROJECT")
    args = parser.parse_args(argv)
    try:
        if args.list:
            names = list_golden(args.list)
            print("\n".join(names) if names else "no golden sample")
            return 0
        if args.set:
            print(f"golden sample written: {set_golden(*args.set)}")
            return 0
        if not args.run or not args.golden:
            parser.error("give the run and the golden sample")
        golden = find_golden(args.project, args.golden) if args.project else load_run(args.golden)
        if golden is None:
            raise GoldenError(f"no golden sample called {args.golden!r} in {args.project}")
        result = check_against_golden(load_run(args.run), golden, build_spec(args))
    except (GoldenError, CompareError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_result(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
