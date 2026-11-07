# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Shared pytest setup: the Qt tests run without a screen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
