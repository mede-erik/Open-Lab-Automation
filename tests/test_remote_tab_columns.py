# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The instruments of the remote control tab are in two columns only when the window is wide enough
for two (the widest instrument twice); narrower, one column to scroll down. The columns follow the
width when the window is resized, and the widgets are moved, not built again."""

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


def settle(count=3):
    for _ in range(count):
        QtWidgets.QApplication.processEvents()


def instrument_file(tmp_path, copies=("HC_2", "HC_3")):
    """The supplies and loads of the example, and copies of the 3-channel supply: more than eight
    enabled channels, the case where the old layout made a third column."""
    data = json.load(open(os.path.join(EXAMPLE_DIR, "test_instruments.inst"), encoding="utf-8"))
    data["instruments"] = [i for i in data["instruments"]
                           if i.get("instrument_type") in ("power_supply", "electronic_load")]
    supply = next(i for i in data["instruments"] if i.get("instance_name") == "HC")
    for name in copies:
        extra = json.loads(json.dumps(supply))
        extra["instance_name"] = name
        data["instruments"].append(extra)
    path = tmp_path / "test_instruments.inst"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def make_tab(qtbot, path, width=1600):
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.ui.RemoteControlTab import RemoteControlTab

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    tab = RemoteControlTab(li)
    qtbot.addWidget(tab)
    tab.resize(width, 800)
    tab.show()
    settle()
    tab.load_instruments(path)
    settle()
    return tab


def stop(tab):
    if getattr(tab, "measurement_timer", None):
        tab.measurement_timer.stop()


def placed(tab):
    """The widgets of the instruments in the two columns, in order."""
    out = []
    for column in (tab.left_column, tab.right_column):
        widgets = [column.itemAt(i).widget() for i in range(column.count())]
        out += [w for w in widgets if w is not None]
    return out


def test_wide_window_has_two_columns(qtbot, tmp_path):
    tab = make_tab(qtbot, instrument_file(tmp_path), width=1600)
    try:
        assert tab._column_count == 2
        assert tab.left_column.count() >= 1 and tab.right_column.count() >= 1
        assert not hasattr(tab, "third_column")
        assert tab._scroll.horizontalScrollBar().maximum() == 0  # no scroll sideways
    finally:
        stop(tab)


def test_narrow_window_has_one_column_and_no_sideways_scroll(qtbot, tmp_path):
    tab = make_tab(qtbot, instrument_file(tmp_path), width=700)
    try:
        assert tab._column_count == 1
        assert tab.right_column.count() == 0
        assert tab._scroll.horizontalScrollBar().maximum() == 0  # the measurements wrap too
    finally:
        stop(tab)


def test_the_threshold_is_the_widest_instrument_twice(qtbot, tmp_path):
    tab = make_tab(qtbot, instrument_file(tmp_path), width=1600)
    try:
        needed = tab._two_columns_width()
        assert needed > 2 * max(w.sizeHint().width() for w, _ in tab._instrument_items)
        assert tab._arrange_instruments(width=needed - 1) == 1
        assert tab._arrange_instruments(width=needed) == 2
    finally:
        stop(tab)


def test_resizing_moves_the_widgets_without_building_them_again(qtbot, tmp_path):
    tab = make_tab(qtbot, instrument_file(tmp_path), width=1600)
    try:
        before = {id(w) for w in placed(tab)}
        assert tab._column_count == 2
        tab.resize(700, 800)
        settle()
        assert tab._column_count == 1
        tab.resize(1600, 800)
        settle()
        assert tab._column_count == 2
        assert {id(w) for w in placed(tab)} == before  # the same widgets, placed again
    finally:
        stop(tab)


def test_a_single_instrument_takes_the_whole_width(qtbot, tmp_path):
    path = tmp_path / "one.inst"
    example = json.load(open(os.path.join(EXAMPLE_DIR, "test_instruments.inst"), encoding="utf-8"))
    path.write_text(json.dumps({"instruments": example["instruments"][:1]}), encoding="utf-8")
    tab = make_tab(qtbot, str(path), width=1600)
    try:
        assert tab._column_count == 1 and tab.right_column.count() == 0
    finally:
        stop(tab)
