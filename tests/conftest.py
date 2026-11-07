"""Shared fixtures of the test suite.

* ``library_path`` / ``library``: the instrument library of the ``Instruments_LIB`` submodule
  (or of a sibling checkout). Tests that use them are skipped when the library is missing, so
  the engine tests still run in a checkout without the submodule.
* ``REPO``: the repository root.

The Qt tests run without a screen (``QT_QPA_PLATFORM=offscreen``).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_LIBRARY_CANDIDATES = [
    os.environ.get("OLA_LIBRARY", ""),
    os.path.join(REPO, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(REPO), "Instruments_LIB", "instruments_lib.json"),
]
LIBRARY_PATH = next((p for p in _LIBRARY_CANDIDATES if p and os.path.isfile(p)), None)

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")


@pytest.fixture(scope="session")
def library_path():
    if LIBRARY_PATH is None:
        pytest.skip("instrument library not available (git submodule update --init)")
    return LIBRARY_PATH


@pytest.fixture(scope="session")
def library(library_path):
    from ola.library import Library

    return Library.load(library_path)
