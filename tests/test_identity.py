"""Identity of an instrument: read from the apparatus, kept in the header of every run."""

import json
import os

import pytest

from ola import identity as ident
from ola import vna_calibration_flow as flow
from ola.connection import ProjectConnector
from ola.library import Library
from ola.manual_instrument import ManualInstrumentHandle
from ola.runs import RunWriter
from ola.sim import SimTransport
from ola.tester import make_handle
from tests.litevna_sim import SimLiteVna

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
needs_library = pytest.mark.skipif(
    LIB is None or "calibration_kinds" not in (open(LIB).read() if LIB else ""),
    reason="library with the VNA models not available",
)


def test_idn_answers():
    got = ident.parse_idn("KEYSIGHT TECHNOLOGIES,E36312A,MY54321234,2.0.1-1.0.0-1.0")
    assert (got.manufacturer, got.model, got.serial_number) == (
        "KEYSIGHT TECHNOLOGIES",
        "E36312A",
        "MY54321234",
    )
    assert got.firmware == "2.0.1-1.0.0-1.0"
    # a comma inside the firmware field stays in it
    assert ident.parse_idn("A,B,C,1.0,beta").firmware == "1.0,beta"


@pytest.mark.parametrize("none", ["0", "", "N/A", "-", "None", " 0 "])
def test_an_instrument_without_a_serial_has_none(none):
    assert ident.parse_idn(f"Brand,Model,{none},1.0").serial_number is None


def test_a_short_or_empty_answer_does_not_fail():
    assert ident.parse_idn("Only,Two").serial_number is None
    assert ident.parse_idn(None) == ident.Identity()


def test_the_usb_descriptor_is_used_only_for_serial_ports(monkeypatch):
    class Port:
        device = "/dev/ttyACM0"
        serial_number = "ABC123"

    from serial.tools import list_ports

    monkeypatch.setattr(list_ports, "comports", lambda: [Port()])
    assert ident.usb_serial_number("ASRL/dev/ttyACM0::INSTR") == "ABC123"
    assert ident.usb_serial_number("ASRL/dev/ttyUSB9::INSTR") is None
    assert ident.usb_serial_number("TCPIP0::1.2.3.4::inst0::INSTR") is None


class Handle:
    def __init__(self, answer=None, fails=False):
        self.name, self._answer, self._fails = "X", answer, fails

    def supports(self, call):
        return call == "identification_query"

    def call(self, name):
        if self._fails:
            raise TimeoutError("no answer")
        return self._answer


def test_read_identity_never_raises():
    assert ident.read_identity(Handle("B,M,S1,F")).serial_number == "S1"
    assert ident.read_identity(Handle(fails=True)) == ident.Identity()


def test_snapshots():
    class Real:
        name, model_id = "VNA", "VNA_X"
        identity = ident.parse_idn("Z,L,SN9,1.0")
        calibration = {"file": "calibrations/a.cal.json"}

    got = ident.snapshot(Real())
    assert got["serial_number"] == "SN9" and got["model_id"] == "VNA_X"
    assert got["calibration"] == {"file": "calibrations/a.cal.json"}

    class Simulated:
        name = "demo"

    assert ident.snapshot(Simulated()) == {"name": "demo"}

    class Manual:
        name, is_manual, instrument_type = "VIN", True, "power_supply"

    assert ident.snapshot(Manual()) == {"name": "VIN", "manual": True, "type": "power_supply"}


@needs_library
def test_the_connector_reads_the_serial_once_and_the_snapshot_keeps_it(tmp_path):
    library = Library.load(LIB)
    inst = tmp_path / "lab.inst"
    inst.write_text(
        json.dumps(
            {
                "instruments": [
                    {
                        "instrument_type": "power_supply",
                        "instance_name": "PSU",
                        "model_id": "PSU_Keysight_E36312A",
                        "visa_address": "TCPIP0::1.2.3.4::inst0::INSTR",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    asked = []

    def answer(cmd):
        asked.append(cmd)
        return "KEYSIGHT,E36312A,MY54321234,2.0" if cmd == "*IDN?" else None

    connector = ProjectConnector(library, lambda: inst, opener=lambda *a, **k: SimTransport(answer))
    first = connector("PSU")
    second = connector("PSU")
    assert first.identity.serial_number == "MY54321234"
    assert second.identity is first.identity and asked.count("*IDN?") == 1
    assert ident.snapshot(first)["serial_number"] == "MY54321234"


@needs_library
def test_a_litevna_has_no_serial_and_says_so():
    library = Library.load(LIB)
    handle = make_handle(library, "VNA_Zenko_LiteVNA62", SimLiteVna(), "VNA")
    got = ident.read_identity(handle)
    assert (got.manufacturer, got.model, got.serial_number) == ("Zenko", "LiteVNA", None)
    assert "firmware" in got.firmware


@needs_library
def test_a_calibration_belongs_to_its_apparatus_and_is_in_the_snapshot(tmp_path):
    library = Library.load(LIB)
    sim = SimLiteVna()
    handle = make_handle(library, "VNA_Zenko_LiteVNA62", sim, "VNA")
    handle._instrument.identity = ident.parse_idn("Zenko,LiteVNA,SN42,1.0")
    session = flow.CalibrationSession(
        handle, "ONE_PORT", 1, None, {"start": 1e6, "stop": 2e6, "points": 21}
    )
    session.start()
    assert handle.calibration is None
    for step, gamma in zip(session.steps, (1, -1, 0)):
        sim.connect(gamma)
        session.measure(step)
    session.finish()
    project = tmp_path / "p.json"
    project.write_text(json.dumps({"project_name": "p"}), encoding="utf-8")
    record = session.record("VNA", "VNA_Zenko_LiteVNA62")
    assert record.serial_number == "SN42"
    path = flow.save_and_attach(record, project)
    handle.set_calibration(flow.calibration_info(record, path, project))
    assert json.loads(path.read_text())["serial_number"] == "SN42"
    got = ident.snapshot(handle)
    assert got["calibration"]["serial_number"] == "SN42"
    assert got["calibration"]["file"] == f"calibrations/{path.name}"
    handle.call("calibration_clear")  # the calibration is gone: the snapshot says none
    assert handle.calibration is None and "calibration" not in ident.snapshot(handle)


def test_an_old_calibration_file_without_a_serial_still_loads(tmp_path):
    record = flow.CalibrationRecord("V", "M", "ONE_PORT", 1, None, None, ["OPEN@1"])
    path = flow.save_record(record, tmp_path)
    raw = json.loads(path.read_text())
    del raw["serial_number"]
    path.write_text(json.dumps(raw))
    assert flow.load_record(path).serial_number is None


def test_the_header_of_a_run_keeps_the_apparatus(tmp_path):
    class Info:
        id, version = "demo", "1"

    class Measurement:
        info, params = Info(), {"a": 1}

    class Real:
        name, model_id = "DMM", "DMM_X"
        identity = ident.parse_idn("B,M,SER7,1")

    manual = ManualInstrumentHandle.__new__(ManualInstrumentHandle)
    manual.name, manual.instrument_type = "VIN", "power_supply"

    class Runner:
        measurement, run_id = Measurement(), "r1"
        bindings = {"dmm": [Real()], "supply": [manual]}

    header = RunWriter.header_for(Runner())
    assert header["bindings"] == {"dmm": ["DMM"], "supply": ["VIN"]}
    assert header["instruments"]["dmm"][0]["serial_number"] == "SER7"
    assert header["instruments"]["supply"][0] == {
        "name": "VIN",
        "manual": True,
        "type": "power_supply",
    }
    json.dumps(header)  # it goes into the run file


# ---- a calibration belongs to one apparatus ----------------------------------------------------
SWEEP = {"start": 1e6, "stop": 2e6, "points": 21}


def calibrated(tmp_path, serial):
    """A LiteVNA simulation calibrated (ideal standards) and saved in a project, as made for
    ``serial``. Returns (library, sim, project path)."""
    library = Library.load(LIB)
    sim = SimLiteVna()
    handle = make_handle(library, "VNA_Zenko_LiteVNA62", sim, "VNA")
    handle._instrument.identity = ident.parse_idn(f"Zenko,LiteVNA,{serial},1.0")
    session = flow.CalibrationSession(handle, "ONE_PORT", 1, None, SWEEP)
    session.start()
    for step, gamma in zip(session.steps, (1, -1, 0)):
        sim.connect(gamma)
        session.measure(step)
    session.finish()
    project = tmp_path / "p.json"
    if not project.exists():  # a second apparatus calibrated for the same project
        project.write_text(json.dumps({"project_name": "p"}), encoding="utf-8")
    flow.save_and_attach(session.record("VNA", "VNA_Zenko_LiteVNA62"), project)
    return library, sim, project


def fresh_handle(library, sim, serial):
    handle = make_handle(library, "VNA_Zenko_LiteVNA62", sim, "VNA")
    if serial is not None:
        handle._instrument.identity = ident.parse_idn(f"Zenko,LiteVNA,{serial},1.0")
    return handle


ASKED = {"start_hz": 1e6, "stop_hz": 2e6, "points": 21}


@needs_library
def test_the_calibration_of_this_apparatus_is_restored_for_the_same_sweep(tmp_path):
    library, sim, project = calibrated(tmp_path, "SN42")
    handle = fresh_handle(library, sim, "SN42")
    info = flow.auto_restore(handle, project, ASKED)
    assert info["restored"] and info["serial_number"] == "SN42"
    assert handle.calibration == info  # the snapshot of the run will say so
    sim.connect(lambda f: 0.3)
    assert handle.call("read_sparameters", sparameters=["S11"])["calibrated"] is True


@needs_library
def test_a_calibration_is_never_used_with_another_apparatus(tmp_path):
    library, sim, project = calibrated(tmp_path, "SN42")
    for serial in ("SN99", None):  # another serial, or one that gives none
        handle = fresh_handle(library, sim, serial)
        assert flow.auto_restore(handle, project, ASKED) is None
        assert handle.calibration is None
    assert flow.find_record(project, "SN99") is None and flow.find_record(project, None) is None
    assert flow.find_record(project, "SN42") is not None


@needs_library
def test_another_sweep_or_an_already_calibrated_instrument_is_left_alone(tmp_path):
    library, sim, project = calibrated(tmp_path, "SN42")
    handle = fresh_handle(library, sim, "SN42")
    assert flow.auto_restore(handle, project, {**ASKED, "points": 101}) is None
    assert flow.auto_restore(handle, project, None) is None
    handle.set_calibration({"file": "x"})
    assert flow.auto_restore(handle, project, ASKED) is None  # one is applied already


@needs_library
def test_calibrations_of_two_apparatus_with_the_same_name_are_kept_apart(tmp_path):
    library, sim, project = calibrated(tmp_path, "SN42")
    calibrated(tmp_path, "SN43")
    entries = json.loads(project.read_text(encoding="utf-8"))["calibrations"]
    assert sorted(e["serial_number"] for e in entries) == ["SN42", "SN43"]
    assert flow.find_record(project, "SN43")[0].serial_number == "SN43"
    assert flow.find_record(project, "SN42")[0].serial_number == "SN42"


@needs_library
def test_a_run_restores_the_calibration_of_its_vna_and_the_header_says_so(tmp_path):
    from ola.project import Project
    from ola.project_session import ProjectSession
    from ola.registry import default_registry
    from ola.runs import read_run

    library, sim, project_path = calibrated(tmp_path, "SN42")
    project = Project.new("p", tmp_path)
    project.path = project_path  # the project file the calibration was listed in
    session = ProjectSession(
        project,
        default_registry(user_dir="/nonexistent"),
        connect=lambda name, cancel=None: fresh_handle(library, sim, "SN42"),
        instruments=["VNA"],
    )
    ref = session.create("sparameters", "S")
    raw = json.loads(session.path(ref).read_text(encoding="utf-8"))
    raw["params"] = {"start_hz": 1e6, "stop_hz": 2e6, "points": 21, "sparameters": ["S11"]}
    raw["role_bindings"] = {"vna": ["VNA"]}
    session.path(ref).write_text(json.dumps(raw), encoding="utf-8")
    sim.connect(lambda f: 0.3)
    runner, path = session.build_runner(ref)
    runner.start()
    runner.join(30)
    header = read_run(path)["header"]
    calibration = header["instruments"]["vna"][0]["calibration"]
    assert calibration["restored"] is True and calibration["serial_number"] == "SN42"
    assert calibration["file"].startswith("calibrations/VNA_SN42_")
