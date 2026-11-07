# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The function generator type in the instrument lists and the DWF address of its editor."""

import json
import os

import pytest

from frontend.core.LoadInstruments import LoadInstruments

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.AddressEditorDialog import AddressEditorDialog  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANG = os.path.join(HERE, "frontend", "lang")

SERIES = {
    "series_id": "Digilent_AnalogDiscovery_Series",
    "series_name": "Digilent Analog Discovery",
    "models": [
        {
            "id": "FGEN_Digilent_AnalogDiscovery2",
            "name": "Digilent Analog Discovery 2",
            "interface": {
                "supported_connection_types": [
                    {
                        "type": "WAVEFORMS",
                        "address_format_example": "DWF::<serial number>",
                        "transports": [{"kind": "dwf"}],
                    }
                ]
            },
        }
    ],
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def library(tmp_path):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps({"function_generators_series": [SERIES]}), encoding="utf-8")
    li = LoadInstruments()
    assert li.load_instruments(str(path))
    return li


def test_the_type_is_in_the_lists(library):
    assert LoadInstruments.get_series_key("function_generator") == "function_generators_series"
    assert "function_generator" in library.get_all_types()
    assert [s["series_id"] for s in library.get_series("function_generator")] == [
        "Digilent_AnalogDiscovery_Series"
    ]
    models = library.get_models("function_generator", "Digilent_AnalogDiscovery_Series")
    assert [m["id"] for m in models] == ["FGEN_Digilent_AnalogDiscovery2"]


def test_the_type_has_a_name_in_every_language():
    import glob

    paths = glob.glob(os.path.join(LANG, "*.json"))
    assert len(paths) == 5
    for path in paths:
        catalog = json.load(open(path, encoding="utf-8"))
        assert catalog.get("function_generator"), os.path.basename(path)


def entry(address=""):
    return {
        "instrument_type": "function_generator",
        "instance_name": "GEN",
        "series": "Digilent_AnalogDiscovery_Series",
        "model_id": "FGEN_Digilent_AnalogDiscovery2",
        "visa_address": address,
    }


def test_the_editor_builds_a_dwf_address(app, library):
    dialog = AddressEditorDialog(entry(), library)
    assert dialog.conn_combo.currentText() == "WAVEFORMS"
    dialog.fields["serial"].setText("SN:210321A1B2C3")  # the prefix of the SDK is dropped
    assert dialog.get_address() == "DWF::210321A1B2C3"
    dialog.fields["serial"].setText("")  # empty: the first device found
    assert dialog.get_address() == "DWF"


def test_the_editor_shows_the_serial_of_an_existing_address(app, library):
    dialog = AddressEditorDialog(entry("DWF::210321A1B2C3"), library)
    assert dialog.fields["serial"].text() == "210321A1B2C3"
    first = AddressEditorDialog(entry("DWF"), library)  # kept: its widgets live as long as it does
    assert first.fields["serial"].text() == ""


def test_an_existing_address_of_any_kind_is_shown_when_the_editor_opens(app, tmp_path):
    """The .inst file keeps the address as ``visa_address``; the editor used to look for
    ``address`` and always opened empty."""
    path = tmp_path / "lib.json"
    path.write_text(json.dumps({"function_generators_series": []}), encoding="utf-8")
    li = LoadInstruments()
    li.load_instruments(str(path))  # no model: the default templates
    lan = {"instrument_type": "power_supply", "visa_address": "TCPIP0::192.168.1.201::inst0::INSTR"}
    dialog = AddressEditorDialog(lan, li)
    assert dialog.conn_combo.currentText() == "LXI (VXI-11)"
    assert dialog.fields["ip"].text() == "192.168.1.201"
