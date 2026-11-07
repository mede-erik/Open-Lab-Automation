# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A measurement whose sweep a VNA cannot do is stopped before it starts, with both ranges shown."""

import json
import os

import pytest

from ola.connection import ProjectConnector
from ola.library import Library
from ola.project import Project
from ola.project_session import ProjectSession
from ola.registry import default_registry

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


def setup(tmp_path, model_id, params):
    library = Library.load(LIB)
    inst = tmp_path / "lab.inst"
    inst.write_text(
        json.dumps(
            {
                "instruments": [
                    {
                        "instrument_type": "network_analyzer",
                        "instance_name": "VNA",
                        "model_id": model_id,
                        "visa_address": "ASRL3::INSTR",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    connector = ProjectConnector(library, lambda: inst, opener=lambda *a, **k: None)
    session = ProjectSession(
        Project.new("P", tmp_path, inst_file="lab.inst"),
        default_registry(user_dir="/nonexistent"),
        connect=connector,
    )
    ref = session.create("sparameters", "S")
    raw = json.loads(session.path(ref).read_text(encoding="utf-8"))
    raw["params"] = params
    raw["role_bindings"] = {"vna": ["VNA"]}
    session.path(ref).write_text(json.dumps(raw), encoding="utf-8")
    return session, connector, ref


def test_what_a_vna_can_measure_is_known_without_connecting(tmp_path):
    session, connector, _ = setup(tmp_path, "VNA_Zenko_LiteVNA62", {})
    assert connector.abilities("VNA") == {"sparameters": ["S11", "S21"], "source_power": False}
    assert connector.characteristics("VNA")["frequency_max_hz"] == 6.3e9
    assert connector.abilities("nobody") == {}


def test_a_sweep_above_the_range_stops_the_measurement_with_both_values(tmp_path):
    params = {"start_hz": 1e6, "stop_hz": 8e9, "points": 201, "sparameters": ["S11"]}
    session, connector, ref = setup(tmp_path, "VNA_Zenko_LiteVNA62", params)
    found = session.compatibility(ref, connector.characteristics, connector.abilities)
    assert [(f.characteristic, f.blocking) for f in found] == [("frequency_max_hz", True)]
    assert found[0].value == 6.3e9 and found[0].need == 8e9 and found[0].instrument == "VNA"


def test_the_same_sweep_is_fine_on_a_vna_with_a_wider_range(tmp_path):
    params = {"start_hz": 1e6, "stop_hz": 4e9, "points": 201, "sparameters": ["S11"]}
    session, connector, ref = setup(tmp_path, "VNA_Siglent_SNA5002A", params)
    assert session.compatibility(ref, connector.characteristics, connector.abilities) == []


def test_a_sweep_inside_the_range_is_fine(tmp_path):
    params = {"start_hz": 1e6, "stop_hz": 1e9, "points": 201, "sparameters": ["S11"]}
    session, connector, ref = setup(tmp_path, "VNA_Zenko_LiteVNA62", params)
    assert session.compatibility(ref, connector.characteristics, connector.abilities) == []
