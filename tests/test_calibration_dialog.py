# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The calibration window on a simulated LiteVNA (no screen needed, see conftest.py)."""

import json
import os
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.CalibrationDialog import (  # noqa: E402
    PAGE_DONE,
    PAGE_SETTINGS,
    PAGE_STEPS,
    CalibrationDialog,
)
from ola.library import Library  # noqa: E402
from ola.tester import make_handle  # noqa: E402
from tests.litevna_sim import SimLiteVna  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
pytestmark = pytest.mark.skipif(
    LIB is None or "calibration_kinds" not in (open(LIB).read() if LIB else ""),
    reason="library with the VNA models not available",
)
MODEL = "VNA_Zenko_LiteVNA67"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def pump(app, condition, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def setup(tmp_path):
    library = Library.load(LIB)
    sim = SimLiteVna()
    project = tmp_path / "p.json"
    project.write_text(json.dumps({"project_name": "p"}), encoding="utf-8")
    connect = lambda name, cancel=None: make_handle(library, MODEL, sim, name)  # noqa: E731
    dialog = CalibrationDialog({"VNA": MODEL}, library, connect, project)
    return dialog, sim, project


def test_a_one_port_calibration_goes_through_the_steps_and_is_saved(app, setup):
    dialog, sim, project = setup
    assert dialog.kind.count() == 2  # the LiteVNA has no full two-port calibration
    assert not dialog.port2.isEnabled()
    dialog.start.setText("1M")
    dialog.stop.setText("2M")
    dialog.points.setValue(21)
    dialog.begin_button.click()
    assert pump(app, lambda: dialog.session is not None)
    assert dialog.pages.currentIndex() == PAGE_STEPS
    assert dialog.step_list.count() == 3
    for gamma in (1, -1, 0):
        sim.connect(gamma)
        assert pump(app, lambda: dialog.measure_button.isEnabled())
        dialog.measure_button.click()
        assert pump(
            app,
            lambda: dialog.measure_button.isEnabled() or dialog.pages.currentIndex() == PAGE_DONE,
        )
    assert pump(app, lambda: dialog.pages.currentIndex() == PAGE_DONE)
    assert dialog.saved_path is not None and dialog.saved_path.exists()
    assert json.loads(project.read_text(encoding="utf-8"))["calibrations"][0]["instrument"] == "VNA"


def test_a_wrong_sweep_stays_on_the_settings_page(app, setup):
    dialog, _sim, _project = setup
    dialog.stop.setText("not a frequency")
    dialog.begin_button.click()
    assert dialog.pages.currentIndex() == PAGE_SETTINGS
    assert dialog.settings_error.text()
    assert dialog.session is None


def test_the_kit_is_offered_to_a_model_that_takes_it(app, setup):
    dialog, _sim, _project = setup
    assert dialog.kit_group.isEnabled()
    assert dialog._kit_values() is None  # ideal standards until the box is ticked
    dialog.kit_group.setChecked(True)
    dialog.kit_fields["open_c0"].setValue(49.4)
    assert dialog._kit_values()["open_c0"] == 49.4


def test_the_advanced_kit_values_are_sent_only_when_asked(app, setup):
    dialog, _sim, _project = setup
    dialog.kit_group.setChecked(True)
    dialog.kit_fields["open_loss"].setValue(2.0)
    assert "open_loss" not in dialog._kit_values()
    assert dialog.kit_fields["open_z0"].value() == 50.0  # the ideal impedance, not zero
    dialog.kit_advanced.setChecked(True)
    assert dialog._kit_values()["open_loss"] == 2.0


def test_a_kit_with_values_reaches_the_driver(app, setup):
    dialog, sim, _project = setup
    dialog.kit_group.setChecked(True)
    dialog.kit_fields["open_c0"].setValue(49.4)
    dialog.stop.setText("2M")
    dialog.points.setValue(21)
    dialog.begin_button.click()
    assert pump(app, lambda: dialog.session is not None)
    assert dialog.session.kit["open_c0"] == 49.4
