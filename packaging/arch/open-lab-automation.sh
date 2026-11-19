#!/bin/sh
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

# Starts Open Lab Automation installed by the Arch package (sources in /usr/lib/open-lab-automation).
export PYTHONPATH="/usr/lib/open-lab-automation${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python -m frontend.main "$@"
