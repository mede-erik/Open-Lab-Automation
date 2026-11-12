# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Who made a measurement, on which computer, with which version of the program. No Qt.

The header of every run keeps these three values (see ``ola.runs``), so that results taken
from a shared archive say where they come from. Nothing here is a login: the author is the name
the person declares (the environment variable ``OLA_AUTHOR``) or, without it, the user name of the
operating system. A value that cannot be found is written as ``"unknown"``, never left out.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
from pathlib import Path
from typing import Dict

ENV_AUTHOR = "OLA_AUTHOR"
UNKNOWN = "unknown"


def author() -> str:
    """The declared author (``$OLA_AUTHOR``), else the operating-system user name."""
    declared = os.environ.get(ENV_AUTHOR, "").strip()
    if declared:
        return declared
    try:
        return getpass.getuser() or UNKNOWN
    except Exception:  # no user in the environment (some containers)
        return UNKNOWN


def host() -> str:
    """The name of this computer."""
    try:
        return socket.gethostname() or UNKNOWN
    except OSError:
        return UNKNOWN


def software_version() -> str:
    """The version of the program: the installed package, else ``frontend/appinfo.json`` (a copy
    of the sources), else ``"unknown"``."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("open-lab-automation")
        except PackageNotFoundError:
            pass
    except ImportError:  # pragma: no cover - Python < 3.8
        pass
    info = Path(__file__).resolve().parent.parent / "frontend" / "appinfo.json"
    try:
        return str(json.loads(info.read_text(encoding="utf-8")).get("version") or UNKNOWN)
    except (OSError, ValueError, AttributeError):
        return UNKNOWN


def provenance() -> Dict[str, str]:
    """``{"author", "host", "software_version"}`` for the header of a run."""
    return {"author": author(), "host": host(), "software_version": software_version()}


__all__ = ["author", "host", "provenance", "software_version"]
