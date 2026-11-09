# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Transport exceptions. Shared with the native (Rust) module when it is available,
so callers can catch the same classes whichever implementation is in use.

Every exception has a ``code`` property (``"TRN-003"``...) read from the ``[TRN-xxx]``
prefix of its message, see ERROR_CODES.md.
"""

import re

try:  # pragma: no cover - depends on whether the native module is built
    from ola_native import TransportClosed, TransportError, TransportTimeout
except ImportError:

    class TransportError(Exception):
        """Generic transport failure. Message starts with the [TRN-xxx] code."""

    class TransportTimeout(TransportError):
        """[TRN-003] No (complete) answer within the timeout."""

    class TransportClosed(TransportError):
        """[TRN-004] Connection closed, locally or by the peer."""


_CODE = re.compile(r"\[([A-Z]+-\d{3})\]")


def _code(self) -> str:
    m = _CODE.search(str(self))
    return m.group(1) if m else "TRN-002"


# Works for both the pure-Python classes and the native (PyO3) ones.
TransportError.code = property(_code)

__all__ = ["TransportError", "TransportTimeout", "TransportClosed"]
