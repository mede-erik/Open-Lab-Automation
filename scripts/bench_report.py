#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Show the benchmark report of a run (made with ``OLA_BENCH=1``), or compare two of them.

    python scripts/bench_report.py runs/efficiency_20261112_101500.jsonl
    python scripts/bench_report.py new.jsonl --compare old.jsonl     # median of every row
    python scripts/bench_report.py report.json --top 30              # a report saved as JSON

A file can be a run file (JSON Lines with a ``bench`` line) or a report saved by
``benchmarks/bench_engine.py --json``.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ola import bench  # noqa: E402
from ola.runs import read_run  # noqa: E402


def load_report(path):
    """The report in a run file or in a JSON file; exits with a message if there is none."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)  # a saved report is one JSON document
        if isinstance(data, dict) and "rows" in data:
            return data
    except ValueError:
        pass  # a run file is JSON Lines
    report = read_run(path).get("bench")
    if not report:
        sys.exit(f"{path}: no benchmark in this run (start the program with OLA_BENCH=1)")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--compare", help="an earlier run or report to compare with")
    ap.add_argument("--top", type=int, default=15, help="rows per table")
    a = ap.parse_args()
    report = load_report(a.file)
    print(bench.format_report(report, top=a.top))
    if a.compare:
        print("\nCompared with", a.compare)
        print(bench.compare_reports(load_report(a.compare), report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
