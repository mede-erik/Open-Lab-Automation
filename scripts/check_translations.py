#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Check that every locale file in frontend/lang has the same keys and placeholders.

The reference locale is en.json. For every other locale the script reports:
  * keys missing or extra compared to the reference;
  * values that are not text, or empty;
  * different {placeholders} (a message formatted with .format(...) would fail or lose data).

Exit code 1 if anything is reported. Usage:
    python scripts/check_translations.py [--lang-dir frontend/lang] [--reference en]
"""

import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACEHOLDER = re.compile(r"\{(\w*)\}")


def load_locales(lang_dir):
    locales = {}
    problems = []
    for path in sorted(glob.glob(os.path.join(lang_dir, "*.json"))):
        name = os.path.basename(path)[: -len(".json")]
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            problems.append(f"{name}: cannot read the file: {exc}")
            continue
        if not isinstance(data, dict):
            problems.append(f"{name}: the file must contain a JSON object")
            continue
        locales[name] = data
    return locales, problems


def check(locales, reference):
    problems = []
    if reference not in locales:
        return [f"reference locale '{reference}' not found"]
    ref = locales[reference]
    for name, data in locales.items():
        for key, value in data.items():
            if not isinstance(value, str):
                problems.append(f"{name}: '{key}' is not text")
            elif not value.strip():
                problems.append(f"{name}: '{key}' is empty")
        if name == reference:
            continue
        for key in sorted(set(ref) - set(data)):
            problems.append(f"{name}: missing key '{key}'")
        for key in sorted(set(data) - set(ref)):
            problems.append(f"{name}: extra key '{key}' (not in {reference})")
        for key in sorted(set(ref) & set(data)):
            if not (isinstance(ref[key], str) and isinstance(data[key], str)):
                continue
            a = sorted(PLACEHOLDER.findall(ref[key]))
            b = sorted(PLACEHOLDER.findall(data[key]))
            if a != b:
                problems.append(f"{name}: '{key}' has placeholders {b}, {reference} has {a}")
    return problems


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--lang-dir", default=os.path.join(ROOT, "frontend", "lang"))
    ap.add_argument("--reference", default="en")
    args = ap.parse_args()

    locales, problems = load_locales(args.lang_dir)
    problems += check(locales, args.reference)
    for p in problems:
        print(f"ERROR {p}")
    keys = len(locales.get(args.reference, {}))
    print(f"{len(locales)} locales, {keys} keys in '{args.reference}': {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
