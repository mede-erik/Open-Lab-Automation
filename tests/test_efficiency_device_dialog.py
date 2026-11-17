# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The converter box of the efficiency editor: a name written by hand, optional."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog  # noqa: E402
from tests.efficiency_params import INSTRUMENTS, good  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make(params):
    dialog = EfficiencyEditorDialog(params=params, instruments=INSTRUMENTS)
    dialog.show()
    return dialog


def close_clean(dialog):
    dialog.dirty = False  # a changed dialog would ask about saving and wait for an answer
    dialog.close()


def test_typing_a_converter_writes_its_name(app):
    d = make(good())
    d.device_box.setText("Boost 12 V-5 V")
    d.device_box.editingFinished.emit()
    assert d.editor.params["device"] == {"name": "Boost 12 V-5 V"}
    assert d.dirty
    close_clean(d)


def test_an_empty_box_removes_the_converter(app):
    params = good()
    params["device"] = {"name": "Boost"}
    d = make(params)
    assert d.device_box.text() == "Boost"
    d.device_box.setText("")
    d.device_box.editingFinished.emit()
    assert "device" not in d.editor.params
    close_clean(d)
