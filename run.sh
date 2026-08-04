#!/bin/bash
# Open Lab Automation - test runner
# Builds the C backend (if needed) and launches the application.

set -e
cd "$(dirname "$0")"

echo "=== Open Lab Automation - Test Runner ==="

# 1. Build C backend if missing or newer sources
needs_build=0
if [ ! -f backend/libbackend.so ]; then
    needs_build=1
elif find backend -maxdepth 1 -name '*.c' -newer backend/libbackend.so | grep -q .; then
    needs_build=1
fi
if [ "$needs_build" = 1 ]; then
    echo "[1/3] Building C backend..."
    ( cd backend && ./build.sh )
else
    echo "[1/3] C backend up to date."
fi

# 2. Quick sanity check: translations
if [ -f scripts/check_translations.py ]; then
    echo "[2/3] Checking translations..."
    python3 scripts/check_translations.py
fi

# 3. Launch the app
echo "[3/3] Launching Open Lab Automation..."
exec python3 frontend/launcher.py "$@"
