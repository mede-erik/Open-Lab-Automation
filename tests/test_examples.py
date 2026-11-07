# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Every example project under examples/ must load and reference existing files and models.

tests/test_example_project.py checks the DC-DC project in depth; this file checks that every
example project is at least consistent, so a library change that drops a model used by an
example (or an example edited by hand) is noticed.
"""

import glob
import json
import os

import pytest

from ola.manual_instrument import manual_handle_from_inst
from tests.conftest import REPO, needs_library

EXAMPLES = os.path.join(REPO, "examples")
PROJECTS = sorted(
    p
    for p in glob.glob(os.path.join(EXAMPLES, "*", "*.json"))
    if "project_name" in json.load(open(p, encoding="utf-8"))
)
FILES = sorted(
    p
    for ext in ("json", "inst", "was", "eff")
    for p in glob.glob(os.path.join(EXAMPLES, "*", f"*.{ext}"))
)
# Models referenced by an example but not (yet) in the library. Remove an entry when the
# model is added or the example is updated: the test fails if an entry is no longer needed.
KNOWN_MISSING_MODELS = {
    ("Test_scpi", "PSU_OWON_SPE6103"),
}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _rel(path):
    return os.path.relpath(path, EXAMPLES)


def test_there_are_examples():
    assert PROJECTS and FILES


@pytest.mark.parametrize("path", FILES, ids=_rel)
def test_example_file_is_valid_json(path):
    assert isinstance(_load(path), dict)


@pytest.mark.parametrize("path", PROJECTS, ids=_rel)
def test_project_references_existing_files(path):
    project = _load(path)
    directory = os.path.dirname(path)
    assert project["project_name"]
    referenced = (
        [project["inst_file"]] + project.get("was_files", []) + project.get("eff_files", [])
    )
    for name in referenced:
        assert os.path.isfile(os.path.join(directory, name)), f"{_rel(path)}: {name} missing"


@pytest.mark.parametrize("path", PROJECTS, ids=_rel)
def test_project_instruments_are_well_formed(path):
    project = _load(path)
    inst = _load(os.path.join(os.path.dirname(path), project["inst_file"]))
    names = set()
    for instrument in inst["instruments"]:
        assert instrument.get("instrument_type"), instrument
        name = instrument.get("instance_name")
        assert name and name not in names, f"duplicated instance name {name!r}"
        names.add(name)
        if not instrument.get("is_manual"):
            assert instrument.get("model_id") and instrument.get("visa_address"), name


@needs_library
def test_project_models_are_in_the_library(library):
    found_missing = set()
    for path in PROJECTS:
        project_dir = os.path.basename(os.path.dirname(path))
        project = _load(path)
        inst = _load(os.path.join(os.path.dirname(path), project["inst_file"]))
        for instrument in inst["instruments"]:
            if instrument.get("is_manual"):
                handle = manual_handle_from_inst(instrument, library)
                assert handle is not None
                continue
            ref = library.find_model(instrument["model_id"])
            if ref is None:
                found_missing.add((project_dir, instrument["model_id"]))
                continue
            assert ref.series["series_id"] == instrument.get("series", ref.series["series_id"])
    unexpected = found_missing - KNOWN_MISSING_MODELS
    fixed = KNOWN_MISSING_MODELS - found_missing
    assert unexpected == set(), "example projects use models that are not in the library"
    assert fixed == set(), "these models are now resolved: remove them from KNOWN_MISSING_MODELS"
