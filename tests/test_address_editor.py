# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The address editor: the WaveForms device list, picking an instrument from the GPIB bus,
choosing the adapter of an existing address, and the errors of building an address (no screen
needed). The other parts are in ``test_gpib_adapter_dialog.py`` and
``test_function_generator_type.py``."""

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from frontend.core import gpib_settings  # noqa: E402
from frontend.core.LoadInstruments import LoadInstruments  # noqa: E402
from frontend.ui import GpibDevicePickerDialog as picker_module  # noqa: E402
from frontend.ui.AddressEditorDialog import AddressEditorDialog  # noqa: E402
from ola.gpib_adapter import BusDevice, GpibAdapterConfig, GpibError  # noqa: E402


class NoLibrary:
    def find_instrument(self, **kwargs):
        return None


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def adapters(tmp_path):
    """Three adapters (GPIB0, GPIB1, a Prologix on COM5) in temporary settings."""
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(tmp_path / "app"))
    settings = QSettings("LabAutomation", "App")
    settings.clear()
    gpib_settings.save_adapters(
        [
            GpibAdapterConfig(name="Main", board=0),
            GpibAdapterConfig(name="Second", board=1),
            GpibAdapterConfig(name="Prologix", profile="prologix_usb", port="COM5"),
        ],
        settings,
    )
    yield settings
    settings.clear()


@pytest.fixture
def warnings(monkeypatch):
    seen = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda parent, title, text: seen.append(text))
    )
    return seen


def editor(address="", library=None, kind="x"):
    entry = {"visa_address": address, "instrument_type": kind}
    return AddressEditorDialog(entry, library or NoLibrary())


def gpib_editor(address=""):
    dialog = editor(address)
    dialog.conn_combo.setCurrentText("GPIB")
    return dialog


# ---------------------------------------------------------------- WaveForms
SERIES = {
    "series_id": "Digilent_AnalogDiscovery_Series",
    "models": [
        {
            "id": "FGEN_Digilent_AnalogDiscovery2",
            "interface": {
                "supported_connection_types": [
                    {"type": "WAVEFORMS", "address_format_example": "DWF::<serial number>"}
                ]
            },
        }
    ],
}


def dwf_library(tmp_path):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps({"function_generators_series": [SERIES]}), encoding="utf-8")
    library = LoadInstruments()
    assert library.load_instruments(str(path))
    return library


def dwf_entry():
    return {
        "instrument_type": "function_generator",
        "series": "Digilent_AnalogDiscovery_Series",
        "model_id": "FGEN_Digilent_AnalogDiscovery2",
    }


def test_the_connected_waveforms_devices_are_suggested_for_the_serial(app, tmp_path, monkeypatch):
    from ola.drivers import waveforms

    class Api:
        def __init__(self, library):
            pass

        def enumerate(self):
            return [{"serial": "SN:210321A1B2C3"}, {"serial": "210321FFFF"}]

    monkeypatch.setattr(waveforms, "load_library", lambda: object())
    monkeypatch.setattr(waveforms, "DwfApi", Api)
    dialog = AddressEditorDialog(dwf_entry(), dwf_library(tmp_path))
    completer = dialog.fields["serial"].completer()
    assert completer is not None
    assert completer.model().stringList() == ["210321A1B2C3", "210321FFFF"]  # without "SN:"


def test_without_the_waveforms_runtime_the_serial_is_just_typed(app, tmp_path, monkeypatch):
    from ola.drivers import waveforms

    def missing():
        raise OSError("libdwf not found")

    monkeypatch.setattr(waveforms, "load_library", missing)
    dialog = AddressEditorDialog(dwf_entry(), dwf_library(tmp_path))
    assert dialog.fields["serial"].completer() is None
    dialog.fields["serial"].setText("ABC")
    assert dialog.get_address() == "DWF::ABC"


# ---------------------------------------------------------------- GPIB bus picker
class FakePicker:
    chosen = None
    answer = 1
    adapter = None

    def __init__(self, adapter, translator, parent):
        type(self).adapter = adapter

    def exec(self):
        return type(self).answer


@pytest.fixture
def picker(monkeypatch):
    FakePicker.chosen = BusDevice(address=7, resource="GPIB1::7::INSTR")
    FakePicker.answer = 1
    FakePicker.adapter = None
    monkeypatch.setattr(picker_module, "GpibDevicePickerDialog", FakePicker)
    return FakePicker


def test_picking_from_the_bus_fills_the_address_of_the_selected_adapter(app, picker):
    dialog = gpib_editor()
    dialog.adapter_combo.setCurrentIndex(1)
    dialog.pick_from_bus()
    assert picker.adapter is dialog.gpib_adapters[1] and picker.adapter.board == 1
    assert dialog.fields["gpib_addr"].text() == "7"


@pytest.mark.parametrize("answer,chosen", [(0, "device"), (1, None)])
def test_cancelling_the_bus_picker_keeps_the_address(app, picker, answer, chosen):
    dialog = gpib_editor()
    dialog.fields["gpib_addr"].setText("3")
    picker.answer = answer
    picker.chosen = BusDevice(address=9, resource="GPIB0::9::INSTR") if chosen else None
    dialog.pick_from_bus()
    assert dialog.fields["gpib_addr"].text() == "3"


# ---------------------------------------------------------------- adapter of an address
def test_a_type_that_is_not_gpib_has_no_adapter(app):
    dialog = editor("TCPIP0::192.168.1.5::inst0::INSTR")
    assert dialog.adapter_combo is None and dialog.gpib_adapter is None
    dialog.select_gpib_adapter("GPIB1::5::INSTR")  # nothing to select: no error


@pytest.mark.parametrize(
    "address",
    [
        "GPIB5::7::INSTR",  # no adapter has board 5: the selection stays
        "GPIB1::INSTR",  # no instrument address
        "PROLOGIX::COM9::7::INSTR",  # no Prologix on COM9
        "PROLOGIX::broken",  # not a valid Prologix address
    ],
)
def test_an_address_no_adapter_matches_leaves_the_selection(app, address):
    dialog = gpib_editor()
    dialog.adapter_combo.setCurrentIndex(1)
    dialog.select_gpib_adapter(address)
    assert dialog.adapter_combo.currentIndex() == 1


def test_the_adapter_of_a_prologix_address_is_found_by_its_port(app):
    dialog = gpib_editor()
    dialog.select_gpib_adapter("prologix::com5::3::INSTR")  # the port is compared ignoring case
    assert dialog.adapter_combo.currentIndex() == 2


# ---------------------------------------------------------------- errors of the address
@pytest.mark.parametrize("value", ["", "0", "31", "abc", "-4"])
def test_a_gpib_address_must_be_between_1_and_30(app, warnings, value):
    dialog = gpib_editor()
    dialog.fields["gpib_addr"].setText(value)
    assert dialog.get_address() is None
    assert warnings and "1 e 30" in warnings[0]


def test_an_adapter_that_cannot_make_the_address_is_reported(app, warnings):
    dialog = gpib_editor()
    dialog.fields["gpib_addr"].setText("5")

    def refuse(pad):
        raise GpibError("[GPIB-006] bad adapter")

    dialog.gpib_adapters[0] = SimpleNamespace(name="Main", address=refuse)
    dialog.adapter_combo.setCurrentIndex(0)
    assert dialog.get_address() is None
    assert warnings == ["[GPIB-006] bad adapter"]


def test_a_template_with_an_unknown_field_is_reported(app, warnings):
    dialog = editor("")
    dialog.conn_combo.setCurrentText("LXI (VXI-11)")
    dialog.templates["LXI (VXI-11)"] = "TCPIP0::{ip}::{no_such_field}::INSTR"
    assert dialog.get_address() is None
    assert warnings and "no_such_field" in warnings[0]


def test_a_serial_port_that_is_not_a_port_is_reported(app, warnings):
    dialog = editor("")
    dialog.conn_combo.setCurrentText("SERIAL")
    dialog.fields["com_port"].setText("not a port!")
    assert dialog.get_address() is None
    assert warnings and "Porta seriale" in warnings[0]
