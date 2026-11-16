# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The fixed texts of the Remote control tab follow the language of the application (they used
to be Italian in any language), and an instrument without a model has no empty brackets in its
title."""

import json
import os
import re

import pytest

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from frontend.core.Translator import Translator  # noqa: E402
from frontend.ui.RemoteControlTab import RemoteControlTab  # noqa: E402
from tests.conftest import LIBRARY_PATH  # noqa: E402

pytestmark = [pytest.mark.gui, pytest.mark.skipif(LIBRARY_PATH is None, reason="no library")]
ITALIAN = re.compile(r"Aggiorna|Aggiornamento|Intervallo|Configura|Ricarica")


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def tab(app):
    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    widget = RemoteControlTab(li)
    yield widget
    timer = getattr(widget, "measurement_timer", None)
    if timer is not None:
        timer.stop()


def translator(lang):
    tr = Translator()
    tr.set_language(lang)
    return tr


def write_inst(tmp_path):
    entries = [
        {"instrument_type": "multimeter", "instance_name": "DMM", "model": "34401A",
         "model_id": "MTR_Agilent_34401A", "visa_address": "GPIB0::22::INSTR",
         "channels": [{"enabled": True, "name": "VIN", "meas_type": "DC_V"}]},
        {"instrument_type": "power_supply", "instance_name": "BENCH", "is_manual": True,
         "num_channels": 1,
         "channels": [{"enabled": True, "name": "CH1", "max_current": 5, "max_voltage": 30}]},
        {"instrument_type": "electronic_load", "instance_name": "LOAD", "model": "EL4913A",
         "model_id": "EL_Keysight_EL4913A", "visa_address": "TCPIP0::127.0.0.1::inst0::INSTR",
         "channels": [{"enabled": True, "name": "CH1", "channel_id": "CH1", "max_current": 10,
                       "max_voltage": 60}]},
    ]
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": entries}), encoding="utf-8")
    return str(path)


def all_texts(tab):
    texts = [tab.label.text(), tab.osc_btn.toolTip(), tab.reload_btn.toolTip(),
             tab.meas_group.title()]
    for name in ("refresh_btn", "auto_refresh_cb", "interval_label"):
        widget = getattr(tab, name, None)
        if widget is not None:
            texts.append(widget.text())
    return texts


def test_the_fixed_texts_are_in_english_without_a_translator(tab):
    assert tab.label.text() == "Remote control of instruments"
    assert tab.osc_btn.toolTip() == "Configure the oscilloscope (.was)"
    assert tab.reload_btn.toolTip() == "Reload the instruments (.inst)"
    assert not any(ITALIAN.search(t) for t in all_texts(tab))


def test_the_measurements_controls_follow_the_language(tab, tmp_path):
    tab.update_translation(translator("en"))
    tab.load_instruments(write_inst(tmp_path))
    assert tab.refresh_btn.text() == "Refresh measurements"
    assert tab.auto_refresh_cb.text() == "Automatic refresh"
    assert tab.interval_label.text() == "Interval (s):"
    assert not any(ITALIAN.search(t) for t in all_texts(tab))
    tab.update_translation(translator("it"))  # the language changes while the tab is open
    assert tab.refresh_btn.text() == "Aggiorna misure"
    assert tab.osc_btn.toolTip() == "Configura l'oscilloscopio (.was)"
    tab.update_translation(translator("de"))
    assert tab.auto_refresh_cb.text() == "Automatische Aktualisierung"
    assert tab.label.text() == translator("de").t("remote_control")


def test_an_instrument_without_a_model_has_no_empty_brackets(tab, tmp_path):
    assert tab._instrument_title({"instance_name": "BENCH"}) == "BENCH"
    assert tab._instrument_title({"instance_name": "BENCH", "model": "  "}) == "BENCH"
    assert tab._instrument_title({"instance_name": "DMM", "model": "34401A"}) == "DMM (34401A)"
    assert tab._instrument_title({"model": "34401A"}) == "34401A"
    tab.update_translation(translator("en"))
    tab.load_instruments(write_inst(tmp_path))
    titles = [g.title() for g in tab.findChildren(QtWidgets.QGroupBox)]
    assert not any("()" in t for t in titles), titles
    assert any(t == "BENCH" for t in titles) and any(t == "LOAD (EL4913A)" for t in titles)
