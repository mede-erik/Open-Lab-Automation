#!/bin/bash
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

# Open Lab Automation - test runner
# Checks the translations and launches the application.

set -e
cd "$(dirname "$0")"

echo "=== Open Lab Automation - Test Runner ==="

# 1. Quick sanity check: translations
if [ -f scripts/check_translations.py ]; then
    echo "[1/2] Checking translations..."
    python3 scripts/check_translations.py
fi

# 2. Launch the app
echo "[2/2] Launching Open Lab Automation..."
exec python3 frontend/launcher.py "$@"
