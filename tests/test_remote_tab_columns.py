# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The remote control tab shows the instruments in two columns (one half of the window each), and
the settings of an RF modulation are shown only when the modulation is enabled: the room of the
window is for the instruments."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
QtCore = pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("pytestqt")

from tests.conftest import LIBRARY_PATH, REPO  # noqa: E402

EXAMPLE_DIR = os.path.join(REPO, "examples", "test-dcdc-project")

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available"),
]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(home))
    settings = QtCore.QSettings
    for fmt in (settings.Format.NativeFormat, settings.Format.IniFormat):
        settings.setPath(fmt, settings.Scope.UserScope, str(home / "settings"))
    settings("LabAutomation", "App").clear()
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", staticmethod(lambda *a, **k: 0))
    yield


def settle():
    for _ in range(3):
        QtWidgets.QApplication.processEvents()


def instrument_file(tmp_path):
    """The supplies and loads of the example, and two more copies of the 3-channel supply: nine
    enabled channels, the case where the old layout made a third column."""
    data = json.load(open(os.path.join(EXAMPLE_DIR, "test_instruments.inst"), encoding="utf-8"))
    data["instruments"] = [i for i in data["instruments"] if i.get("instrument_type") in
                           ("power_supply", "electronic_load")]
    supply = next(i for i in data["instruments"] if i.get("instance_name") == "HC")
    for copy in ("HC_2", "HC_3"):
        extra = json.loads(json.dumps(supply))
        extra["instance_name"] = copy
        data["instruments"].append(extra)
    path = tmp_path / "test_instruments.inst"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def make_tab(qtbot, path):
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.RemoteControlTab import RemoteControlTab

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    tab = RemoteControlTab(li)
    qtbot.addWidget(tab)
    tab.load_instruments(path)
    settle()
    return tab


def test_several_instruments_are_in_two_columns(qtbot, tmp_path):
    tab = make_tab(qtbot, instrument_file(tmp_path))
    try:
        assert not hasattr(tab, "third_column")
        assert tab.left_column.count() >= 1
        assert tab.right_column.count() >= 1  # the second half of the window has instruments too
        assert tab.right_column.count() + tab.left_column.count() >= 4
    finally:
        if getattr(tab, "measurement_timer", None):
            tab.measurement_timer.stop()


def test_a_single_instrument_takes_the_whole_width(qtbot, tmp_path):
    path = tmp_path / "one.inst"
    example = json.load(open(os.path.join(EXAMPLE_DIR, "test_instruments.inst"), encoding="utf-8"))
    data = {"instruments": example["instruments"][:1]}
    path.write_text(json.dumps(data), encoding="utf-8")
    tab = make_tab(qtbot, str(path))
    try:
        assert tab.right_column.count() == 0  # the one instrument is not in the second half
    finally:
        if getattr(tab, "measurement_timer", None):
            tab.measurement_timer.stop()
