"""A project received from someone else: using it with your own instruments."""

import json
import os

import pytest

from ola import role_mapping as rm
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

MINE = [
    {
        "instrument_type": "network_analyzer",
        "instance_name": "MY_LITE",
        "model_id": "VNA_Zenko_LiteVNA62",
        "visa_address": "ASRL3::INSTR",
    },
    {
        "instrument_type": "network_analyzer",
        "instance_name": "MY_SNA",
        "model_id": "VNA_Siglent_SNA5002A",
        "visa_address": "TCPIP0::1.2.3.4::inst0::INSTR",
    },
    {
        "instrument_type": "power_supply",
        "instance_name": "MY_PSU",
        "is_manual": True,
        "channels": [{"enabled": True, "name": "CH1", "max_voltage": 30, "max_current": 3}],
    },
]


def received(tmp_path, params=None, binding="OWNER_VNA"):
    """A project whose only measurement names the sender's VNA."""
    (tmp_path / "lab.inst").write_text(json.dumps({"instruments": MINE}), encoding="utf-8")
    library = Library.load(LIB)
    connector = ProjectConnector(
        library, lambda: tmp_path / "lab.inst", opener=lambda *a, **k: None
    )
    session = ProjectSession(
        Project.new("P", tmp_path, inst_file="lab.inst"),
        default_registry(user_dir="/nonexistent"),
        connect=connector,
    )
    ref = session.create("sparameters", "Sweep")
    raw = json.loads(session.path(ref).read_text(encoding="utf-8"))
    raw["params"] = params or {"start_hz": 1e6, "stop_hz": 4e9, "points": 201}
    raw["role_bindings"] = {"vna": [binding]}
    session.path(ref).write_text(json.dumps(raw), encoding="utf-8")
    return session, connector, ref


def test_the_names_you_do_not_have_are_found_with_the_kind_the_role_asks(tmp_path):
    session, _, _ = received(tmp_path)
    gaps = rm.find_gaps(session)
    assert [(g.name, g.category, g.measurements, g.roles) for g in gaps] == [
        ("OWNER_VNA", "network_analyzer", ("Sweep",), ("vna",))
    ]


def test_a_project_that_uses_your_instruments_has_no_gaps(tmp_path):
    session, _, _ = received(tmp_path, binding="MY_LITE")
    assert rm.find_gaps(session) == []


def test_without_an_instrument_file_nothing_is_reported(tmp_path):
    session, _, _ = received(tmp_path)
    session.project.inst_file = None
    assert rm.find_gaps(session) == []


def test_only_your_instruments_of_that_kind_are_offered(tmp_path):
    session, _, _ = received(tmp_path)
    gap = rm.find_gaps(session)[0]
    assert rm.candidates_for(session, gap) == ["MY_LITE", "MY_SNA"]  # not the power supply


def test_the_preview_says_which_candidate_cannot_do_the_sweep(tmp_path):
    session, connector, _ = received(tmp_path)  # a sweep up to 4 GHz
    gap = rm.find_gaps(session)[0]
    lite = rm.preview(session, gap, "MY_LITE", connector.characteristics, connector.abilities)
    sna = rm.preview(session, gap, "MY_SNA", connector.characteristics, connector.abilities)
    assert lite == [] and sna == []  # 4 GHz is inside both (LiteVNA 6.3 GHz, SNA 4.5 GHz)
    wide, connector, _ = received(tmp_path, params={"start_hz": 1e6, "stop_hz": 5e9, "points": 201})
    gap = rm.find_gaps(wide)[0]
    sna = rm.preview(wide, gap, "MY_SNA", connector.characteristics, connector.abilities)
    assert [(f.characteristic, f.blocking, f.value) for f in sna] == [
        ("frequency_max_hz", True, 4.5e9)
    ]


def test_mapping_names_your_instrument_in_the_measurements_only(tmp_path):
    session, _, ref = received(tmp_path)
    run = tmp_path / "runs" / "sweep_20260101_000000.jsonl"
    run.parent.mkdir()
    run.write_text('{"kind": "run", "bindings": {"vna": ["OWNER_VNA"]}}\n', encoding="utf-8")
    before = run.read_text(encoding="utf-8")
    changed = rm.map_instrument(session, "OWNER_VNA", "MY_LITE")
    assert [c.role for c in changed] == ["vna"]
    assert json.loads(session.path(ref).read_text(encoding="utf-8"))["role_bindings"] == {
        "vna": ["MY_LITE"]
    }
    assert run.read_text(encoding="utf-8") == before  # the runs keep the sender's instrument
    assert rm.find_gaps(session) == []
