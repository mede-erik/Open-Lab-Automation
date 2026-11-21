# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A manual instrument (set by hand, no remote control) is not shown in the Remote control tab:
no box with its name, no voltage or current controls, no measurement."""

import json

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QGroupBox  # noqa: E402

from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from tests.conftest import LIBRARY_PATH  # noqa: E402

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def manual_supply(name="TTI"):
    return {
        "instrument_type": "power_supply",
        "instance_name": name,
        "is_manual": True,
        "num_channels": 1,
        "channels": [{"enabled": True, "name": "CH1", "max_voltage": 30.0, "max_current": 3.0}],
    }


@needs_library
def test_a_manual_supply_has_no_box_and_no_controls(app, tmp_path):
    from frontend.ui.RemoteControlTab import RemoteControlTab

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": [manual_supply()]}), encoding="utf-8")
    tab = RemoteControlTab(li)
    tab.load_instruments(str(path))
    titles = [g.title() for g in tab.findChildren(QGroupBox)]
    assert not any("TTI" in title for title in titles), titles
    assert tab.current_channel_widgets == []
    assert getattr(tab, "meas_vars", []) == []  # nothing to measure on a manual supply
    tab.close()


def test_the_manual_instruments_are_left_out_of_the_tab():
    from frontend.ui.RemoteControlTab import RemoteControlTab

    supply = {"instance_name": "PSU", "instrument_type": "power_supply"}
    shown = RemoteControlTab._connected_instruments({"instruments": [manual_supply(), supply]})
    assert [i["instance_name"] for i in shown] == ["PSU"]
