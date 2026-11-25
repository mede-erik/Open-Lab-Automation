# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The VNA panel of the Remote control tab uses the calibration saved in the project.

The software calibration of a driver (the LiteVNA) lives in the connection that measured it, and the
panel has its own connection: before a sweep it puts back the calibration saved for this apparatus
and this sweep, and for another sweep it bypasses the calibration (the driver would refuse the
sweep otherwise)."""

import json

import pytest

from ola import identity as ident
from ola import vna_calibration_flow as flow
from ola import vna_controls as vc
from ola.library import Library
from ola.tester import make_handle
from tests.conftest import LIBRARY_PATH
from tests.litevna_sim import SimLiteVna

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")

SWEEP = {"start": 1e6, "stop": 2e6, "points": 21}
ASKED = {"start_hz": 1e6, "stop_hz": 2e6, "points": 21}
OTHER = {"start_hz": 1e6, "stop_hz": 3e6, "points": 21}


def handle_for(library, sim, serial="SN42"):
    handle = make_handle(library, "VNA_Zenko_LiteVNA67", sim, "VNA")
    handle._instrument.identity = ident.parse_idn(f"Zenko,LiteVNA,{serial},1.0")
    return handle


def calibrated_project(tmp_path):
    """A LiteVNA simulation calibrated (ideal standards) and saved in a project. Returns
    (library, sim, project file)."""
    library = Library.load(LIBRARY_PATH)
    sim = SimLiteVna()
    handle = handle_for(library, sim)
    session = flow.CalibrationSession(handle, "ONE_PORT", 1, None, SWEEP)
    session.start()
    for step, gamma in zip(session.steps, (1, -1, 0)):
        sim.connect(gamma)
        session.measure(step)
    session.finish()
    project = tmp_path / "p.json"
    project.write_text(json.dumps({"project_name": "p"}), encoding="utf-8")
    flow.save_and_attach(session.record("VNA", "VNA_Zenko_LiteVNA67"), project)
    return library, sim, project


def read(handle, sweep):
    handle.call(
        "set_frequency_sweep",
        start_frequency=sweep["start_hz"],
        stop_frequency=sweep["stop_hz"],
        points=sweep["points"],
    )
    return handle.call("read_sparameters", sparameters=["S11"])


@needs_library
def test_a_new_connection_gets_the_saved_calibration_for_the_same_sweep(tmp_path):
    library, sim, project = calibrated_project(tmp_path)
    panel_handle = handle_for(library, sim)  # the connection of the panel: nothing calibrated
    sim.connect(lambda f: 0.3)
    assert read(panel_handle, ASKED)["calibrated"] is False  # what the panel showed before
    info = vc.restore_saved_calibration(panel_handle, project, ASKED)
    assert info and info["restored"]
    assert read(panel_handle, ASKED)["calibrated"] is True


@needs_library
def test_the_next_sweeps_on_the_same_connection_stay_calibrated(tmp_path):
    # a continuous run (or a second click) asks again before every sweep: the calibration that
    # is already applied must not be switched off
    library, sim, project = calibrated_project(tmp_path)
    handle = handle_for(library, sim)
    assert vc.restore_saved_calibration(handle, project, ASKED)
    sim.connect(lambda f: 0.3)
    for _ in range(3):
        assert vc.restore_saved_calibration(handle, project, ASKED) is None  # nothing to do
        assert read(handle, ASKED)["calibrated"] is True


@needs_library
def test_another_sweep_is_read_uncalibrated_and_the_calibration_comes_back(tmp_path):
    library, sim, project = calibrated_project(tmp_path)
    handle = handle_for(library, sim)
    assert vc.restore_saved_calibration(handle, project, ASKED)
    sim.connect(lambda f: 0.3)
    # the user changes the sweep: the calibration no longer fits and the driver would refuse it
    assert vc.restore_saved_calibration(handle, project, OTHER) is None
    assert handle.calibration is None  # forgotten
    assert read(handle, OTHER)["calibrated"] is False  # read, not refused
    # back to the calibrated sweep: the saved calibration is put back
    assert vc.restore_saved_calibration(handle, project, ASKED)
    assert read(handle, ASKED)["calibrated"] is True


@needs_library
def test_the_calibration_of_another_apparatus_is_not_used(tmp_path):
    library, sim, project = calibrated_project(tmp_path)
    other = handle_for(library, sim, serial="SN99")
    assert vc.restore_saved_calibration(other, project, ASKED) is None
    sim.connect(lambda f: 0.3)
    assert read(other, ASKED)["calibrated"] is False


@needs_library
def test_no_project_means_no_restore_but_the_sweep_still_works(tmp_path):
    library, sim, _ = calibrated_project(tmp_path)
    handle = handle_for(library, sim)
    assert vc.restore_saved_calibration(handle, None, ASKED) is None
    sim.connect(lambda f: 0.3)
    assert read(handle, ASKED)["calibrated"] is False


class OwnCalibration:
    """An analyzer that keeps its own calibration: no calibration_import, nothing to restore."""

    def __init__(self):
        self.calls = []

    def supports(self, name):
        return name != "calibration_import"

    def call(self, name, **args):
        self.calls.append(name)


def test_an_instrument_with_its_own_calibration_is_left_as_it_is(tmp_path):
    handle = OwnCalibration()
    assert vc.restore_saved_calibration(handle, tmp_path / "p.json", ASKED) is None
    assert handle.calls == []  # its front-panel calibration is never switched off


@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PyQt6")
    from PyQt6 import QtWidgets

    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.gui
def test_the_panel_restores_before_the_sweep_and_a_failure_does_not_stop_it(app):
    from frontend.core.Translator import Translator
    from frontend.ui.VnaPanel import VnaPanel
    from ola.sim_vna import SimVna

    vna = SimVna(library_calls=True, library_extras=False, library_sweep_type=True,
                 library_linear_only=True, termination="open")
    seen = []

    def restore(handle, sweep):
        seen.append((handle, sweep["points"]))
        raise RuntimeError("no calibration file")  # it must not stop the sweep

    controls = vc.VnaControls(
        calls=["set_frequency_sweep", "run_sweep", "read_sparameters"],
        sparameters=["S11", "S21"],
        frequency_min=50e3,
        frequency_max=6.3e9,
        max_points=65535,
    )
    panel = VnaPanel("VNA", controls, lambda: vna, Translator().t, asynchronous=False,
                     restore=restore)
    assert panel.sweep_once()
    assert seen and seen[0][0] is vna  # asked with the handle of the sweep, before the reading
    assert panel.freq  # the sweep ran anyway


@needs_library
def test_the_sweep_of_a_saved_calibration_that_does_not_fit_is_reported(tmp_path):
    library, sim, project = calibrated_project(tmp_path)
    handle = handle_for(library, sim)
    saved = vc.calibration_for_another_sweep(handle, project, OTHER)
    assert saved == SWEEP  # the sweep the calibration was made for
    assert vc.calibration_for_another_sweep(handle, project, ASKED) is None  # it fits: nothing
    assert vc.calibration_for_another_sweep(handle, None, OTHER) is None  # no project
    other = handle_for(library, sim, serial="SN99")  # another apparatus: its calibration only
    assert vc.calibration_for_another_sweep(other, project, OTHER) is None


def make_panel(app, calibration_sweep, calibrated=False):
    from frontend.core.Translator import Translator
    from frontend.ui.VnaPanel import VnaPanel
    from ola.sim_vna import SimVna

    vna = SimVna(library_calls=True, library_extras=False, library_sweep_type=True,
                 library_linear_only=True, termination="open")
    vna.calibrated = calibrated
    controls = vc.VnaControls(
        calls=["set_frequency_sweep", "run_sweep", "read_sparameters"],
        sparameters=["S11", "S21"],
        frequency_min=50e3,
        frequency_max=6.3e9,
        max_points=65535,
    )
    return VnaPanel("VNA", controls, lambda: vna, Translator().t, asynchronous=False,
                    calibration_sweep=calibration_sweep)


@pytest.mark.gui
def test_the_panel_says_which_sweep_the_saved_calibration_is_for(app):
    saved = {"start": 50e3, "stop": 6.3e9, "points": 5000}
    panel = make_panel(app, lambda handle, sweep: saved)
    assert panel.sweep_once()
    text = panel.status.text()
    assert "50" in text and "6.3" in text and "5000" in text  # the calibrated sweep, in the note
    assert panel.use_calibration_button.isVisibleTo(panel)
    panel.use_calibration_button.click()  # the form gets the sweep of the calibration
    assert (panel.start.text(), panel.stop.text(), panel.points.value()) == ("50k", "6.3G", 5000)
    assert not panel.use_calibration_button.isVisibleTo(panel)


@pytest.mark.gui
def test_no_hint_when_there_is_no_saved_calibration_or_the_data_are_calibrated(app):
    panel = make_panel(app, lambda handle, sweep: None)
    assert panel.sweep_once()
    assert not panel.use_calibration_button.isVisibleTo(panel)
    called = []
    panel = make_panel(app, lambda handle, sweep: called.append(1), calibrated=True)
    assert panel.sweep_once()
    assert not called and not panel.use_calibration_button.isVisibleTo(panel)  # not even asked
