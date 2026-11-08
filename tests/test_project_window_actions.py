# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The project window: calibration of the analyzers, mapping of the user's own instruments and
the decision to stop a run before it starts (no screen needed).

The window is the one of ``tests/test_project_window.py`` (simulated lab); the nested windows are
replaced by recorders so that every answer of the user can be given and the effect checked.
"""

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from frontend.ui.ProjectWindow import ProjectWindow, demo_project  # noqa: E402
from ola.demo_lab import DemoHandle, DemoLab  # noqa: E402
from ola.library import Library  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from tests.conftest import LIBRARY_PATH  # noqa: E402

VNA = {
    "instrument_type": "network_analyzer",
    "instance_name": "VNA",
    "series": "Zenko_LiteVNA_Series",
    "model": "LiteVNA 62",
    "model_id": "VNA_Zenko_LiteVNA62",
    "visa_address": "ASRL/dev/ttyACM0::INSTR",
}
PSU = {
    "instrument_type": "power_supply",
    "instance_name": "PSU",
    "series": "Keysight_E36300_Series",
    "model_id": "PSU_Keysight_E36312A",
    "visa_address": "TCPIP0::192.168.1.201::inst0::INSTR",
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def popups(monkeypatch):
    """Every pop-up is recorded as ``(kind, title, text)``; none blocks."""
    shown = []
    for kind in ("critical", "warning", "information", "question"):

        def record(parent, title, text="", *args, _kind=kind, **kwargs):
            shown.append((_kind, title, text))
            return QMessageBox.StandardButton.Yes

        monkeypatch.setattr(QMessageBox, kind, staticmethod(record))
    return shown


@pytest.fixture
def window(app, tmp_path, popups):
    w = ProjectWindow(
        demo_project(str(tmp_path)),
        connect=lambda name, cancel=None: DemoHandle(name, DemoLab()),
        registry=default_registry(user_dir="/nonexistent"),
    )
    w._mapping_timer.stop()
    yield w
    for r in w.run_windows:
        r.runner.stop()
        r.runner.join(5)
        r._timer.stop()
        r.model.state = "finished"
        r.close()
    w._timer.stop()
    w.run_windows.clear()
    w.close()


@pytest.fixture
def library():
    if LIBRARY_PATH is None:
        pytest.skip("instrument library not available")
    return Library.load(LIBRARY_PATH)


def use_inst_file(window, library, entries, name="lab.inst"):
    """Give the project an instrument file and a connector that has the library."""
    project = window.session.project
    (project.directory / name).write_text(json.dumps({"instruments": entries}), encoding="utf-8")
    project.inst_file = name
    window.connector = SimpleNamespace(library=library)


# ---------------------------------------------------------------- calibration
def test_calibration_needs_an_instrument_file(window, library, popups):
    window.connector = SimpleNamespace(library=library)
    window.session.project.inst_file = None
    window.calibrate_analyzer()
    assert len(popups) == 1 and popups[0][0] == "warning"
    assert "instrument file" in popups[0][2]


def test_calibration_says_when_the_instrument_file_cannot_be_read(window, library, popups):
    use_inst_file(window, library, [])
    (window.session.project.directory / "lab.inst").write_text("{ broken", encoding="utf-8")
    window.calibrate_analyzer()
    assert [p[0] for p in popups] == ["warning"] and "cannot read" in popups[0][2]


def test_calibration_says_when_there_is_no_network_analyzer(window, library, popups):
    use_inst_file(window, library, [PSU])
    window.calibrate_analyzer()
    assert [p[0] for p in popups] == ["information"]
    assert "analyzer" in popups[0][2].lower() or "vna" in popups[0][2].lower()


def test_calibration_opens_its_window_for_the_analyzers_of_the_project(
    window, library, popups, monkeypatch
):
    use_inst_file(window, library, [PSU, VNA])
    seen = {}

    class FakeCalibration:
        def __init__(self, analyzers, lib, connector, project_path, translator, **kwargs):
            seen.update(analyzers=analyzers, lib=lib, connector=connector, path=project_path)
            seen.update(kwargs)

        def exec(self):
            seen["executed"] = True
            return QDialog.DialogCode.Rejected

    import frontend.ui.CalibrationDialog as calibration_module

    monkeypatch.setattr(calibration_module, "CalibrationDialog", FakeCalibration)
    window.calibrate_analyzer()
    assert popups == [] and seen["executed"] is True
    assert seen["analyzers"] == {"VNA": "VNA_Zenko_LiteVNA62"}  # the supply is not an analyzer
    assert seen["lib"] is library and seen["connector"] is window.connector
    assert seen["path"] == window.session.project.path
    assert set(seen["entries"]) == {"PSU", "VNA"} and seen["parent"] is window


# ---------------------------------------------------------------- mapping instruments
class FakeRoles:
    answer = QDialog.DialogCode.Accepted
    gaps = ["a gap"]
    opened = 0

    def __init__(self, session, characteristics, abilities, translator, parent):
        type(self).opened += 1

    def exec(self):
        return type(self).answer


@pytest.fixture
def roles(monkeypatch):
    import frontend.ui.RolesDialog as roles_module

    FakeRoles.answer = QDialog.DialogCode.Accepted
    FakeRoles.gaps = ["a gap"]
    FakeRoles.opened = 0
    monkeypatch.setattr(roles_module, "RolesDialog", FakeRoles)
    return FakeRoles


def test_mapping_does_nothing_without_a_project(window, roles):
    window.session = None
    window.map_instruments()
    assert roles.opened == 0


def test_the_list_is_refreshed_after_the_user_maps_instruments(window, roles, monkeypatch):
    refreshed = []
    monkeypatch.setattr(window, "_refresh", lambda: refreshed.append(True))
    window.map_instruments()
    assert roles.opened == 1 and refreshed == [True]


def test_cancelling_the_mapping_changes_nothing(window, roles, monkeypatch):
    roles.answer = QDialog.DialogCode.Rejected
    refreshed = []
    monkeypatch.setattr(window, "_refresh", lambda: refreshed.append(True))
    window.map_instruments()
    assert roles.opened == 1 and refreshed == []


def test_nothing_to_map_shows_no_window_and_is_silent_when_quiet(window, roles, popups):
    roles.gaps = []
    window.map_instruments(quiet=True)
    assert popups == []
    window.map_instruments()
    assert [p[0] for p in popups] == ["information"]


# ---------------------------------------------------------------- stopping a run
def test_declining_the_compatibility_question_starts_nothing(window, monkeypatch):
    window.table.selectRow(0)
    window.wiring_before_run = False
    monkeypatch.setattr(window, "_check_compatibility", lambda ref: (False, None))
    built = []
    monkeypatch.setattr(
        window.session, "build_runner", lambda *a, **k: built.append(True) or (None, None)
    )
    window.run_measurement()
    assert built == [] and window.run_windows == []


def test_declining_the_wiring_diagram_starts_nothing(window, monkeypatch):
    window.table.selectRow(0)
    monkeypatch.setattr(window, "_confirm_wiring", lambda ref: False)
    asked = []
    monkeypatch.setattr(window, "_check_compatibility", lambda ref: asked.append(True))
    window.run_measurement()
    assert asked == [] and window.run_windows == []


def test_without_a_selection_nothing_runs(window, monkeypatch):
    window.table.clearSelection()
    monkeypatch.setattr(
        window, "_confirm_wiring", lambda ref: (_ for _ in ()).throw(AssertionError("asked"))
    )
    window.run_measurement()
    assert window.run_windows == []
