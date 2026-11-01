"""Validate locale files against en.json and against keys used in the code.

Exit code is non-zero if a locale misses/has extra keys relative to ``en.json`` or
if the code calls ``translator.t('<key>')`` with a key that is not defined in en.json.
"""

import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG_DIR = os.path.join(ROOT, "frontend", "lang")
KEY_RE = re.compile(r"""\.t\(\s*['"]([^'"]+)['"]\s*\)""")


def main() -> int:
    langs = {}
    for path in sorted(glob.glob(os.path.join(LANG_DIR, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            langs[os.path.basename(path)[:-5]] = json.load(fh)

    if "en" not in langs:
        print("ERROR: en.json not found")
        return 1

    errors = 0
    reference = set(langs["en"])
    for lang, data in langs.items():
        missing = sorted(reference - set(data))
        extra = sorted(set(data) - reference)
        if missing:
            errors += 1
            print(f"ERROR [{lang}] missing keys: {', '.join(missing)}")
        if extra:
            errors += 1
            print(f"ERROR [{lang}] keys not in en.json: {', '.join(extra)}")

    used = set()
    for path in glob.glob(os.path.join(ROOT, "frontend", "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            used |= set(KEY_RE.findall(fh.read()))
    undefined = sorted(used - reference)
    if undefined:
        errors += 1
        print(f"ERROR keys used in code but not in en.json: {', '.join(undefined)}")

    if errors:
        return 1
    print(f"Translations OK ({len(langs)} locales, {len(reference)} keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
