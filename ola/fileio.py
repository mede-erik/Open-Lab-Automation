# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Writing files so that a crash or a second program never sees half a file. No Qt.

``atomic_write_text`` writes to a temporary file in the same folder and then renames it over the
target (``os.replace`` is atomic on the same file system, also on a network share): a reader gets
the old file or the new one, never a mix, and a crash while writing leaves the old file in place.
Used for every file a person may edit or share: project, measurements, instruments, registry.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Union


def atomic_write_text(path: Union[str, Path], text: str, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically (the folder must exist). The temporary file is removed
    if anything fails."""
    path = Path(path)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Union[str, Path], data: Any, indent: int = 2) -> None:
    """``atomic_write_text`` of ``data`` as JSON (UTF-8, not escaped, final newline)."""
    atomic_write_text(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")


__all__ = ["atomic_write_json", "atomic_write_text"]
