# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

# Basic sanity test for core imports

import importlib

def test_frontend_imports():
    """Ensure core modules can be imported without side effects."""
    modules = [
        "frontend.core.tools",
        "frontend.core.validator",
        "frontend.core.errorhandler",
        "frontend.core.ProjectDatabaseManager",
    ]
    for mod in modules:
        importlib.import_module(mod)
