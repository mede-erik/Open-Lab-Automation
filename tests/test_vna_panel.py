# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The network-analyzer panel of the Remote control tab.

Sweep settings within the model's limits, the S-parameters it measures, a single or continuous
sweep through the helpers of the VNA measurements (so a LiteVNA, a driver, works), curves in dB or
as impedance, min/max markers and the Touchstone export. ``ola.sim_vna.SimVna`` with the library
calls stands for the instrument (``library_linear_only``: like the LiteVNA).
"""

import json
import os

import pytest

from ola import rf
from ola import vna_controls as vc
from ola.sim_vna import SimVna
from tests.conftest import LIBRARY_PATH

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")


def lite():
    return SimVna(library_calls=True, library_extras=False, library_sweep_type=True,
                  library_linear_only=True, termination="open")


# ----- what the panel shows and runs (no Qt) ----------------------------------------------------
@needs_library
def test_the_litevna_67_controls():
    from ola.library import Library

    c = vc.vna_controls(Library.load(LIBRARY_PATH), "VNA_Zenko_LiteVNA67")
    assert c.usable and c.sparameters == ["S11", "S21"]
    assert (c.frequency_min, c.frequency_max, c.max_points) == (50e3, 6.3e9, 65535)
    assert not c.has("set_if_bandwidth") and not c.has("set_source_power")


def test_frequencies_are_typed_with_prefixes():
    assert vc.parse_frequency("2.4G") == 2.4e9
    assert vc.parse_frequency("100 k") == 100e3
    assert vc.parse_frequency("1,5MHz") == 1.5e6
    assert vc.parse_frequency("1500000") == 1.5e6
    with pytest.raises(ValueError):
        vc.parse_frequency("abc")


def test_the_sweep_is_checked_against_the_model():
    c = vc.VnaControls(frequency_min=50e3, frequency_max=6.3e9, max_points=65535)
    assert vc.check_sweep(c, 1e6, 1e9, 201) == []
    assert vc.check_sweep(c, 1e9, 1e6, 201) == ["vna_err_order"]
    assert vc.check_sweep(c, 10e3, 1e9, 201) == ["vna_err_low"]
    assert vc.check_sweep(c, 1e6, 7e9, 201) == ["vna_err_high"]
    assert vc.check_sweep(c, 1e6, 1e9, 70000) == ["vna_err_points"]


def test_one_sweep_with_a_litevna_like_analyzer():
    vna = lite()
    sweep = vc.sweep_settings(1e6, 1e9, 51, log=True)
    freq, data, notes = vc.run_one_sweep(vna, sweep, ["S11", "S21"])
    assert len(freq) == 51 and set(data) == {"S11", "S21"}
    assert any("linear" in n for n in notes)  # it cannot sweep logarithmically: said, not hidden
    asked = [c[0] for c in vna.calls]
    assert asked.count("set_frequency_sweep") == 1
    vc.run_one_sweep(vna, sweep, ["S11"], configure=False)  # a continuous sweep: not set again
    assert [c[0] for c in vna.calls].count("set_frequency_sweep") == 1


def test_curves_in_db_and_as_impedance():
    freq = [1e6, 2e6]
    data = {"S11": [0j, 0.5 + 0j], "S21": [1 + 0j, 0.1 + 0j]}
    db = vc.curves(freq, data, vc.FORMAT_DB)
    assert [c[0] for c in db] == ["S11 dB", "S21 dB"] and db[1][2][0] == pytest.approx(0.0)
    z = vc.curves(freq, data, vc.FORMAT_IMPEDANCE)
    assert [c[0] for c in z] == ["R (S11)", "X (S11)"]  # transmission has no port impedance
    assert z[0][2] == pytest.approx([50.0, 150.0]) and z[1][2] == pytest.approx([0.0, 0.0])


def test_markers_skip_points_that_are_not_finite():
    curve = ("S11 dB", [1.0, 2.0, 3.0], [-3.0, float("-inf"), -20.0])
    assert vc.markers(curve) == {"min": (3.0, -20.0), "max": (1.0, -3.0)}
    assert vc.markers(("x", [], [])) == {}


def test_touchstone_export(tmp_path):
    freq = [1e6, 2e6]
    one = {"S11": [0.1 + 0.2j, 0.3j]}
    assert vc.touchstone_suffix(one) == ".s1p"
    path = tmp_path / "a.s1p"
    vc.export_touchstone(str(path), freq, one)
    back = rf.read_touchstone(str(path))
    assert back[0] == pytest.approx(freq)
    two = {"S11": [0j, 0j], "S21": [1 + 0j, 1 + 0j]}
    assert vc.touchstone_suffix(two) == ".s2p"


# ----- the panel ---------------------------------------------------------------------------------
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LITE = vc.VnaControls(
    calls=["set_frequency_sweep", "run_sweep", "read_sparameters", "set_sweep_type"],
    sparameters=["S11", "S21"], frequency_min=50e3, frequency_max=6.3e9, max_points=65535,
)


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def make(controls=LITE, vna=None):
    from frontend.core.Translator import Translator
    from frontend.ui.VnaPanel import VnaPanel

    vna = vna or lite()
    panel = VnaPanel("VNA", controls, lambda: vna, Translator().t, asynchronous=False)
    return panel, vna


@pytest.mark.gui
def test_only_the_controls_of_the_model_are_shown(app):
    panel, _ = make()
    assert list(panel.sparameter_checks) == ["S11", "S21"]
    assert panel.points.maximum() == 65535
    assert not panel.if_bandwidth.isVisibleTo(panel) and not panel.power.isVisibleTo(panel)
    assert panel.start.text() == "1M" and panel.stop.text() == "1G"
    panel, _ = make(vc.VnaControls())
    assert panel.plot is None  # not in the library: a message, no control


@pytest.mark.gui
def test_a_sweep_draws_the_curves_and_the_markers(app):
    panel, vna = make()
    panel.points.setValue(51)
    assert panel.sweep_once()
    assert [c[0] for c in panel.plot.curves] == ["S11 dB", "S21 dB"]
    assert "S11 dB: min" in panel.markers.text()
    assert panel.export_button.isEnabled()
    panel.format.setCurrentIndex(panel.format.findData(vc.FORMAT_IMPEDANCE))
    assert [c[0] for c in panel.plot.curves] == ["R (S11)", "X (S11)"]
    panel.sparameter_checks["S11"].setChecked(False)
    assert panel.plot.curves == [] and "S11, S22" in panel.markers.text()


@pytest.mark.gui
def test_a_bad_sweep_is_not_sent(app):
    panel, vna = make()
    panel.stop.setText("7G")
    assert not panel.sweep_once()
    assert vna.calls == [] and "maximum" in panel.status.text()
    panel.stop.setText("1G")
    for check in panel.sparameter_checks.values():
        check.setChecked(False)
    assert not panel.sweep_once() and "at least one trace" in panel.status.text()


@pytest.mark.gui
def test_an_error_is_shown_and_stops_the_continuous_sweep(app):
    from frontend.core.Translator import Translator
    from frontend.ui.VnaPanel import VnaPanel

    def broken():
        raise RuntimeError("'VNA' has no address (visa_address) in the instrument file")

    panel = VnaPanel("VNA", LITE, broken, Translator().t, asynchronous=False)
    panel.continuous.setChecked(True)
    assert not panel.continuous.isChecked()
    assert "no address" in panel.status.text() and panel.sweep_button.isEnabled()


@pytest.mark.gui
def test_the_continuous_sweep_does_not_set_the_sweep_again(app, monkeypatch):
    panel, vna = make()
    panel.points.setValue(21)
    from PyQt6.QtCore import QTimer

    runs = []
    monkeypatch.setattr(QTimer, "singleShot", lambda ms, fn: runs.append(fn))
    panel.continuous.setChecked(True)
    assert len(runs) == 1  # the next sweep is queued after the first one
    runs.pop()()
    assert [c[0] for c in vna.calls].count("set_frequency_sweep") == 1
    assert [c[0] for c in vna.calls].count("run_sweep") == 2
    panel.stop_reading()
    assert not panel.continuous.isChecked()


@pytest.mark.gui
def test_export_writes_the_last_sweep(app, tmp_path):
    panel, _ = make()
    panel.points.setValue(11)
    assert not panel.export(str(tmp_path / "x"))  # nothing measured yet
    panel.sweep_once()
    assert panel.export(str(tmp_path / "x"))
    assert (tmp_path / "x.s2p").exists()


@pytest.mark.gui
@needs_library
def test_the_remote_control_tab_shows_a_panel_for_a_litevna(app, tmp_path):
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.RemoteControlTab import RemoteControlTab
    from frontend.ui.VnaPanel import VnaPanel

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    vna = {"instrument_type": "network_analyzer", "instance_name": "LITE", "model": "LiteVNA 67",
           "model_id": "VNA_Zenko_LiteVNA67", "visa_address": "ASRL99::INSTR", "channels": []}
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": [vna]}), encoding="utf-8")
    tab = RemoteControlTab(li)
    tab.load_instruments(str(path))
    panels = tab.findChildren(VnaPanel)
    assert len(panels) == 1 and list(panels[0].sparameter_checks) == ["S11", "S21"]
    assert tab._vna_connector is not None and tab._vna_connector.names() == ["LITE"]
    tab.close()
    assert tab._vna_connector is None
