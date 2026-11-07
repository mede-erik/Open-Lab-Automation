#!/usr/bin/env python3
"""Write a placeholder for every connection picture listed in docs/wiring-images.md.

A placeholder is an SVG with the name of the picture, where it is shown and what to draw, so that
the folder of each module already has the file to replace. The program **ignores** a placeholder (it
carries the mark ``OLA-PLACEHOLDER``) and keeps showing its own diagram until you replace the file
with a real drawing: save your drawing over it with the same name (a ``.png`` next to a placeholder
``.svg`` works too).

    python scripts/make_picture_placeholders.py            # write the missing placeholders
    python scripts/make_picture_placeholders.py --check    # only say what is there and what is not

It never overwrites a real drawing. The list is read from ``docs/wiring-images.md``: add a picture
there (and to the ``images`` of the module's ``wiring.json``) and run this again.
"""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path
from typing import Dict, List
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "docs" / "wiring-images.md"
MARK = "OLA-PLACEHOLDER"
WIDTH, HEIGHT = 1600, 800
EXTENSIONS = (".svg", ".png", ".jpg", ".jpeg", ".webp")
FIELDS = {
    "File": "file",
    "Cartella": "folder",
    "Quando si vede": "when",
    "Cosa disegnare": "draw",
    "Dettagli": "details",
}
_SECTION = re.compile(r"^## (\d+)\. (.+)$", re.M)
_FIELD = re.compile(r"^\* \*\*(File|Cartella|Quando si vede|Cosa disegnare|Dettagli)\*\*: (.*)$")


def parse_work_list(text: str) -> List[Dict[str, str]]:
    """The pictures of the work list: ``number``, ``title``, ``file``, ``folder``, ``when`` and
    ``draw`` and ``details``. The text of a field may go on over several lines (indented)."""
    found = list(_SECTION.finditer(text))
    out: List[Dict[str, str]] = []
    for k, match in enumerate(found):
        end = found[k + 1].start() if k + 1 < len(found) else len(text)
        entry = {"number": match.group(1), "title": match.group(2).strip()}
        key = ""
        for line in text[match.end() : end].splitlines():
            field = _FIELD.match(line)
            if field:
                key = FIELDS[field.group(1)]
                entry[key] = field.group(2).strip()
            elif key and line.startswith("  ") and line.strip():
                entry[key] += " " + line.strip()
            elif line.startswith(("---", "# ")):
                break
            else:
                key = ""
        if "file" in entry:
            entry["file"] = entry["file"].strip("`")
            entry["folder"] = entry.get("folder", "").strip("`")
            out.append(entry)
    return out


def plain(text: str) -> str:
    """A text of the work list without its markdown marks (``**``, backticks)."""
    return text.replace("**", "").replace("`", "")


def _lines(label: str, text: str, size: int, y: int, width: int, gap: int, out: List[str]) -> int:
    for chunk in textwrap.wrap(plain(f"{label}{text}" if label else text), width):
        out.append(f'<text x="80" y="{y}" font-size="{size}">{escape(chunk)}</text>')
        y += gap
    return y


def render_placeholder(entry: Dict[str, str]) -> str:
    """The SVG of one placeholder (as tall as its text needs, at least 800)."""
    body: List[str] = []
    body.append(
        '<text x="80" y="110" font-size="44" font-weight="bold" fill="#b00020">'
        "SEGNAPOSTO: sostituiscimi con il tuo disegno</text>"
    )
    body.append(
        f'<text x="80" y="190" font-size="64" font-weight="bold">{escape(entry["file"])}</text>'
    )
    body.append(
        f'<text x="80" y="245" font-size="30" fill="#555">{escape(entry["folder"])}'
        f' - {escape(plain(entry["title"]))}</text>'
    )
    y = _lines("Quando si vede: ", entry.get("when", ""), 30, 330, 95, 42, body)
    y = _lines("Da disegnare: ", entry.get("draw", ""), 30, y + 25, 95, 42, body)
    if entry.get("details"):
        y = _lines("Dettagli: ", entry["details"], 30, y + 25, 95, 42, body)
    height = max(HEIGHT, y + 130)
    body.append(
        f'<text x="80" y="{height - 60}" font-size="26" fill="#555">Salva il tuo disegno con '
        "questo nome (.svg, .png, .jpg o .webp). Finché questo file c'è, il programma usa il suo "
        "schema.</text>"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="Helvetica, Arial, sans-serif">\n'
        f"<!-- {MARK}: not a drawing, the program ignores this file -->\n"
        f'<rect width="{WIDTH}" height="{height}" fill="#f1f1f1"/>\n'
        f'<rect x="20" y="20" width="{WIDTH - 40}" height="{height - 40}" fill="none" '
        'stroke="#999" stroke-width="4" stroke-dasharray="24 14"/>\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )


def is_placeholder(path: Path) -> bool:
    """True if the file carries the placeholder mark."""
    try:
        return MARK.encode() in path.read_bytes()[:4096]
    except OSError:
        return False


def main(argv: List[str]) -> int:
    check = "--check" in argv
    entries = parse_work_list(LIST.read_text(encoding="utf-8"))
    if not entries:
        print(f"no pictures found in {LIST}")
        return 1
    real = placeholders = written = 0
    for entry in entries:
        folder = ROOT / entry["folder"]
        mine = [
            p
            for ext in (".svg", ".png", ".jpg", ".jpeg", ".webp")
            for p in [folder / (entry["file"] + ext)]
            if p.is_file()
        ]
        drawn = [p for p in mine if not is_placeholder(p)]
        if drawn:
            real += 1
            print(f"drawn        {drawn[0].relative_to(ROOT)}")
            continue
        target = folder / (entry["file"] + ".svg")
        if target.is_file():
            placeholders += 1
            print(f"placeholder  {target.relative_to(ROOT)}")
        elif check:
            print(f"missing      {target.relative_to(ROOT)}")
        else:
            target.write_text(render_placeholder(entry), encoding="utf-8")
            written += 1
            print(f"written      {target.relative_to(ROOT)}")
    print(
        f"{len(entries)} pictures: {real} drawn, {placeholders + written} placeholders"
        f" ({written} written now)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
