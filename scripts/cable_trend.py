#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The aging of a cable: its loss against the date (see docs/trend.md).

    python scripts/cable_trend.py CBL-0042 runs --figure loss_868MHz_db --limit 3 \
        --max-rate 0.5 --warn-days 90
    python scripts/cable_trend.py CBL-0042 runs --list-figures
    python scripts/cable_trend.py CBL-0042 runs --csv trend.csv

The exit code is 0 for PASS, 1 for WARNING, FAIL or NOT ENOUGH DATA, 2 for a request that cannot
be used.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ola.trend import (  # noqa: E402
    DEFAULT_FIGURE,
    TrendError,
    assess,
    export_csv,
    figures,
    format_trend,
    series,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("code", help="the code of the cable, for example CBL-0042")
    parser.add_argument("runs", nargs="+", help="the folder(s) with the run files")
    parser.add_argument("--figure", default=DEFAULT_FIGURE, help="the figure to follow")
    parser.add_argument("--measurement", default="cable", help="the kind of measurement")
    parser.add_argument("--limit", type=float, help="the value that must not be reached")
    parser.add_argument("--max-rate", type=float, help="the fastest change for the worse, a year")
    parser.add_argument("--warn-days", type=float, help="warn if the limit is this near")
    parser.add_argument("--lower-is-worse", action="store_true", help="for a return loss")
    parser.add_argument("--csv", help="also write the series to this file")
    parser.add_argument("--list-figures", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.list_figures:
            print("\n".join(figures(args.code, args.runs, args.measurement)) or "no figure")
            return 0
        points = series(args.code, args.runs, args.figure, args.measurement)
        if args.csv:
            export_csv(points, args.csv)
        trend = assess(
            points,
            figure=args.figure,
            limit=args.limit,
            max_rate_per_year=args.max_rate,
            warn_within_days=args.warn_days,
            higher_is_worse=not args.lower_is_worse,
        )
    except (TrendError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(format_trend(trend))
    return 0 if trend.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
