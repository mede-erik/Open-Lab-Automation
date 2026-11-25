# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Every text the GUI asks the translator for must exist in a catalog, and the strings of the
Italian catalogs must not be left in English by mistake."""

import ast
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(ROOT, "frontend", "lang")


def _catalogs():
    """``{name: {lang: {key: text}}}`` for the application catalog and each module catalog."""
    out = {}
    for folder in [LANG] + sorted(glob.glob(os.path.join(LANG, "modules", "*"))):
        name = "app" if folder == LANG else os.path.basename(folder)
        out[name] = {}
        for path in glob.glob(os.path.join(folder, "*.json")):
            with open(path, encoding="utf-8") as f:
                out[name][os.path.basename(path)[:-5]] = json.load(f)
    return out


def test_module_catalogs_have_the_same_keys_in_every_language():
    for name, langs in _catalogs().items():
        reference = set(langs["en"])
        for lang, data in langs.items():
            assert set(data) == reference, f"{name}/{lang}"


def test_every_literal_key_given_to_t_exists_in_a_catalog():
    known = set()
    for langs in _catalogs().values():
        known |= set(langs["en"])
    missing = []
    for path in glob.glob(os.path.join(ROOT, "frontend", "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value not in known
            ):
                where = f"{os.path.relpath(path, ROOT)}:{node.lineno}"
                missing.append(f"{where} {node.args[0].value}")
    assert not missing, missing


# Words that are the same in Italian (technical terms, units, abbreviations).
SAME_IN_ITALIAN = {
    "Datalogger", "Ethernet/LXI", "GPIB", "Timer", "Slot", "Stop", "Timeout (ms)", "Offset (V)",
    "Offset", "Sweep", "Auto", "Auto (>10 GΩ)", "Antenna", "Formula", "Console", "File",
    "Benchmark", "Host", "pyvisa-py (Linux, linux-gpib)", "IVI (Keysight / NI)",
    "Interface Clear (IFC)",
}


def test_italian_catalogs_do_not_keep_english_texts():
    stale = []
    for name, langs in _catalogs().items():
        for key, text in langs["en"].items():
            letters = re.sub(r"\{\w*\}", "", text)
            if (
                langs["it"][key] == text
                and re.search(r"[A-Za-z]{4,}", letters)
                and text not in SAME_IN_ITALIAN
            ):
                stale.append(f"{name}:{key}={text!r}")
    assert not stale, stale
