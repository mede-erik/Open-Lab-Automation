# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the calibration window relies on: the VNAs of a project, the connection of a driver
instrument, and the saving of a finished calibration in the project."""

import json
import os

import pytest

from ola import vna_calibration_flow as flow
from ola.connection import ProjectConnector, read_inst_entries
from ola.library import Library
from tests.litevna_sim import SimLiteVna

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

INSTRUMENTS = [
    {"instance_name": "VNA", "model_id": "VNA_Zenko_LiteVNA67", "visa_address": "ASRL3::INSTR"},
    {"instance_name": "Siglent", "model_id": "VNA_Siglent_SNA5002A", "visa_address": "TCPIP::x"},
    {"instance_name": "Supply", "model_id": "PS_Rigol_DP832", "visa_address": "TCPIP::y"},
    {"instance_name": "Hand", "is_manual": True, "manual_type": "power_supply"},
]


def write_inst(tmp_path):
    path = tmp_path / "lab.inst"
    path.write_text(json.dumps({"instruments": INSTRUMENTS}), encoding="utf-8")
    return path


def test_the_vnas_of_an_instrument_file(tmp_path):
    library = Library.load(LIB)
    found = flow.network_analyzers(library, read_inst_entries(write_inst(tmp_path)))
    assert found == {
        "VNA": "VNA_Zenko_LiteVNA67",
        "Siglent": "VNA_Siglent_SNA5002A",
    }


def test_a_driver_instrument_is_connected_with_its_driver(tmp_path):
    library = Library.load(LIB)
    path = write_inst(tmp_path)
    sims = []

    def opener(address, lib, model_id, timeout_ms):
        sims.append(SimLiteVna())
        return sims[-1]

    connector = ProjectConnector(library, lambda: path, opener=opener)
    handle = connector("VNA")
    handle.call("set_frequency_sweep", start_frequency=1e6, stop_frequency=2e6, points=11)
    session = flow.CalibrationSession(handle, "ONE_PORT", 1, None, None)
    session.start()  # reaches the driver (calibration_begin)


def test_save_and_attach_writes_next_to_the_project(tmp_path):
    project = tmp_path / "p.json"
    project.write_text(json.dumps({"project_name": "p", "other": 1}), encoding="utf-8")
    record = flow.CalibrationRecord(
        instrument="VNA",
        model_id="VNA_Zenko_LiteVNA67",
        kind="ONE_PORT",
        port=1,
        port2=None,
        sweep=None,
        standards=["OPEN@1"],
    )
    path = flow.save_and_attach(record, project)
    assert path.parent == tmp_path / "calibrations" and path.exists()
    raw = json.loads(project.read_text(encoding="utf-8"))
    assert raw["other"] == 1 and raw["calibrations"][0]["instrument"] == "VNA"
    assert raw["calibrations"][0]["file"] == "calibrations/" + path.name


def test_the_sweep_typed_by_the_user():
    assert flow.parse_sweep("1M", "2.4G", "201") == {"start": 1e6, "stop": 2.4e9, "points": 201}
    for start, stop, points in (
        ("x", "1G", 10),
        ("2G", "1G", 10),
        ("1M", "1G", 1),
        ("1M", "1G", "many"),
        ("0", "1G", 10),
    ):
        with pytest.raises(flow.InvalidArgumentError):
            flow.parse_sweep(start, stop, points)


def test_which_models_take_a_calibration_kit():
    library = Library.load(LIB)
    assert flow.supports_kit(library, "VNA_Zenko_LiteVNA67") is True
    assert flow.supports_kit(library, "VNA_Siglent_SNA5002A") is False
