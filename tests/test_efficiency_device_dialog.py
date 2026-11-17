# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The converter box of the efficiency editor: it writes ``device`` and shows the card."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog  # noqa: E402
from ola.assets import AssetRegistry  # noqa: E402
from tests.efficiency_params import INSTRUMENTS, good  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def registry(tmp_path):
    reg = AssetRegistry(tmp_path / "assets.json")
    reg.create("other", "Buck converter 12 V to 5 V")
    return reg


def make(app, params, registry):
    dialog = EfficiencyEditorDialog(params=params, instruments=INSTRUMENTS, assets=registry)
    dialog.show()
    return dialog


def test_choosing_a_converter_writes_its_code(app, registry):
    d = make(app, good(), registry)
    d.device_box.setCurrentIndex(d.device_box.findData("DUT-0001"))
    assert d.editor.params["device"] == {"asset_id": "DUT-0001"}
    assert d.dirty
    d.dirty = False  # a changed dialog would ask about saving and wait for an answer
    d.close()


def test_an_empty_box_removes_the_converter(app, registry):
    params = good()
    params["device"] = {"asset_id": "DUT-0001"}
    d = make(app, params, registry)
    assert d.device_box.currentText().startswith("DUT-0001 - Buck")  # the card is shown
    d.device_box.setCurrentText("")
    assert "device" not in d.editor.params
    d.dirty = False  # a changed dialog would ask about saving and wait for an answer
    d.close()


def test_a_code_the_registry_does_not_have_is_shown_as_typed(app, registry):
    params = good()
    params["device"] = {"asset_id": "DUT-0099"}
    d = make(app, params, registry)
    assert d.device_box.currentText() == "DUT-0099"
    d.dirty = False  # a changed dialog would ask about saving and wait for an answer
    d.close()
