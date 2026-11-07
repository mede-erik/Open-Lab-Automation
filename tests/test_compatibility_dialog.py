# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The pop-up of the differences between instruments (no screen needed, see conftest.py)."""

import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.CompatibilityDialog import CompatibilityDialog  # noqa: E402
from ola.compat import Finding  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def finding(**over):
    values = dict(
        role="dmm",
        instrument="NEW",
        characteristic="max_voltage",
        value=100.0,
        previous=200.0,
        previous_name="OLD",
        need=39.6,
    )
    values.update(over)
    return Finding(**values)


def cells(dialog, row):
    return [dialog.table.item(row, c).text() for c in range(dialog.table.columnCount())]


def test_the_three_values_are_shown(app):
    dialog = CompatibilityDialog([finding()])
    assert cells(dialog, 0) == [
        "dmm",
        "NEW",
        "Maximum voltage",
        "100 V",
        "200 V (OLD)",
        "39.6 V",
    ]
    assert not dialog.blocking and dialog.continue_button.isVisible() is False  # not shown yet


def test_continue_accepts_and_cancel_refuses(app):
    dialog = CompatibilityDialog([finding()])
    dialog.continue_button.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    other = CompatibilityDialog([finding()])
    other.reject()
    assert other.result() == other.DialogCode.Rejected


def test_a_difference_that_makes_the_measurement_impossible_cannot_be_overridden(app):
    dialog = CompatibilityDialog([finding(blocking=True)])
    assert dialog.blocking and not hasattr(dialog, "continue_button")


def test_missing_values_are_dashes(app):
    dialog = CompatibilityDialog([finding(previous=None, previous_name="", need=None)])
    assert cells(dialog, 0)[4:] == ["-", "-"]


def test_every_text_exists_in_all_languages():
    import glob
    import json
    import re

    source = open(os.path.join(HERE, "frontend", "ui", "CompatibilityDialog.py")).read()
    keys = set(re.findall(r'"(compat_[a-z_]+)"', source))
    from ola.compat import UNITS

    keys |= {f"compat_char_{c}" for c in UNITS}
    keys = {k for k in keys if not k.endswith("_")}
    assert len(keys) > 20
    for path in glob.glob(os.path.join(HERE, "frontend", "lang", "*.json")):
        catalog = json.load(open(path, encoding="utf-8"))
        missing = sorted(k for k in keys if k not in catalog)
        assert not missing, f"{os.path.basename(path)} lacks {missing}"
