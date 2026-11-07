#!/usr/bin/env python3
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Add (or check) the copyright header of the source files of the repository.

    python scripts/add_copyright_headers.py            # add the header where it is missing
    python scripts/add_copyright_headers.py --check    # list the files without it (exit 1)
    python scripts/add_copyright_headers.py FILE ...   # only these files

Without file arguments it works on the files tracked by git with the extensions below. The
header goes after a shebang, a Python coding line or a batch '@echo off'; the line endings
(LF or CRLF) and a UTF-8 BOM of each file are kept. Files that already have it are skipped.
"""

import argparse
import os
import re
import subprocess
import sys

LINES = [
    "Copyright (C) 2025-2026 Erik Medeossi",
    "This file is part of Open Lab Automation.",
    "Licensed under the GNU General Public License v3.0; see the LICENSE file.",
]
# extension -> line prefix, or (block start, block end) for block comments
STYLE = {
    ".py": "# ",
    ".sh": "# ",
    ".rs": "// ",
    ".c": "// ",
    ".h": "// ",
    ".bat": "REM ",
    ".qss": ("/*", " */"),
}
CODING = re.compile(r"^[ \t\f]*#.*?coding[:=]")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def header(ext, nl):
    style = STYLE[ext]
    if isinstance(style, tuple):
        body = [style[0]] + [" * " + text for text in LINES] + [style[1]]
    else:
        body = [style + text for text in LINES]
    return nl.join(body) + nl


def has_header(text):
    return LINES[0] in text[:800]


def add_header(path):
    """Add the header to one file. Returns True if the file was changed."""
    ext = os.path.splitext(path)[1]
    with open(path, "rb") as fh:
        data = fh.read()
    bom = b""
    if data.startswith(b"\xef\xbb\xbf"):
        bom, data = data[:3], data[3:]
    text = data.decode("utf-8")
    if has_header(text):
        return False
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    keep = 0
    if ext in (".py", ".sh") and lines and lines[0].startswith("#!"):
        keep = 1
    if ext == ".py" and len(lines) > keep and CODING.match(lines[keep]):
        keep += 1
    if ext == ".bat" and lines and lines[0].strip().lower() == "@echo off":
        keep = 1
    pre = "".join(lines[:keep])
    if pre and not pre.endswith("\n"):
        pre += nl
    rest = "".join(lines[keep:])
    sep = nl if rest and not rest.startswith(("\r\n", "\n")) else ""
    with open(path, "wb") as fh:
        fh.write(bom + (pre + header(ext, nl) + sep + rest).encode("utf-8"))
    return True


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [
        os.path.join(ROOT, name)
        for name in out.splitlines()
        if os.path.splitext(name)[1] in STYLE and os.path.isfile(os.path.join(ROOT, name))
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only list the files without it")
    parser.add_argument("files", nargs="*", help="files to process (default: tracked files)")
    args = parser.parse_args(argv)
    files = [f for f in (args.files or tracked_files()) if os.path.splitext(f)[1] in STYLE]
    if args.check:
        missing = []
        for path in files:
            with open(path, "rb") as fh:
                if not has_header(fh.read().decode("utf-8", errors="replace")):
                    missing.append(os.path.relpath(path, ROOT))
        for name in missing:
            print(f"missing copyright header: {name}")
        print(f"{len(files) - len(missing)} of {len(files)} files have the header")
        return 1 if missing else 0
    changed = [path for path in files if add_header(path)]
    for path in changed:
        print(f"added: {os.path.relpath(path, ROOT)}")
    print(f"{len(changed)} file(s) changed, {len(files) - len(changed)} already had it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
