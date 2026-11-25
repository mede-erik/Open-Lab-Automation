# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Efficiency with a **resistive load**: the efficiency measurement (``ola/modules/efficiency``)
whose load is a parameter made of real resistors instead of an instrument.

It is the same measurement, with the same file format and the same editor: the parameter that has
a ``load`` steps through the loads you wrote (single resistors, or series and parallel groups, from
a kit of resistors or typed in), connecting each one by hand or through the relays of a
multiplexer, with the converter switched off while the load changes. The output voltage read at
every point checks the power in the resistors. See ``docs/resistive-efficiency.md``.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict


def _efficiency_class():
    """The ``Efficiency`` class of the sibling module (modules are loaded by file path)."""
    name = "ola_modules.efficiency"
    module = sys.modules.get(name)
    if module is None:
        path = Path(__file__).resolve().parent.parent / "efficiency" / "measurement.py"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module.Efficiency


class ResistiveEfficiency(_efficiency_class()):
    """Efficiency whose load is a set of resistors (a ``load`` parameter)."""

    allow_load = True


def default_params() -> Dict[str, Any]:
    """A starting point: the template of the efficiency editor with a resistive load."""
    from ola.efficiency_editor import EfficiencyEditor

    return EfficiencyEditor.template(load=True)
