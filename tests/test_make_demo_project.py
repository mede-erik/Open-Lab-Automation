# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The demo project script: a project with a finished run that has waveforms."""

import importlib.util
from pathlib import Path

from ola.project import Project
from ola.wave_view import WaveIndex

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_demo_project.py"


def test_the_demo_project_has_a_run_with_waveforms(tmp_path):
    spec = importlib.util.spec_from_file_location("make_demo_project", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = module.make(tmp_path / "demo", depth=200, every=3)
    index = WaveIndex(run)
    assert index.steps() and index.acquisitions() == ["long", "rise"]
    project = Project.load(tmp_path / "demo" / "demo.json")
    assert project.scope_file_names() == ["long.was", "rise.was"]
