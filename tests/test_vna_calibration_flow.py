# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Guided VNA calibration: the steps, the session on a real driver (simulated LiteVNA) and on an
SCPI VNA (simulated transport), the saved record and the terminal tool."""

import json
import os
import sys

import pytest

from ola import vna_calibration_flow as flow
from ola.call_errors import CallNotSupportedError, InvalidArgumentError
from ola.library import Library
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
    reason="library with the calibration kinds not available",
)
SWEEP = {"start": 1e6, "stop": 2e6, "points": 21}


def test_frequencies():
    assert flow.parse_frequency("1e6") == 1e6 and flow.parse_frequency("100k") == 1e5
    assert flow.parse_frequency("2.4G") == 2.4e9 and flow.parse_frequency("6 GHz") == 6e9
    assert flow.parse_frequency("50MHz") == 5e7
    for bad in ("fast", "", "1T"):
        with pytest.raises(ValueError):
            flow.parse_frequency(bad)


def test_steps_of_each_kind():
    one = flow.plan_steps("ONE_PORT", 2)
    assert [(s.standard, s.port) for s in one] == [("OPEN", 2), ("SHORT", 2), ("LOAD", 2)]
    assert one[0].text == "Connect the OPEN to port 2"
    assert one[2].text == "Connect the 50 ohm LOAD to port 2"
    thru = flow.plan_steps("TRANSMISSION_RESPONSE", 1, 2)
    assert [(s.standard, s.port, s.port2) for s in thru] == [("THRU", 1, 2)]
    assert thru[0].text == "Connect a THRU (cable) between port 1 and port 2"
    two = flow.plan_steps("TWO_PORT", 1, 2)
    assert [(s.standard, s.port) for s in two] == [
        ("OPEN", 1),
        ("SHORT", 1),
        ("LOAD", 1),
        ("OPEN", 2),
        ("SHORT", 2),
        ("LOAD", 2),
        ("THRU", 1),
    ]
    for kind, ports in (("TWO_PORT", (1, None)), ("TRANSMISSION_RESPONSE", (1, 1))):
        with pytest.raises(InvalidArgumentError):
            flow.plan_steps(kind, *ports)
    with pytest.raises(InvalidArgumentError):
        flow.plan_steps("THREE_PORT", 1)


@needs_library
def test_kinds_of_the_models():
    library = Library.load(LIB)
    assert flow.supported_kinds(library, "VNA_Zenko_LiteVNA67") == [
        "ONE_PORT",
        "TRANSMISSION_RESPONSE",
    ]
    assert flow.supported_kinds(library, "VNA_Siglent_SNA5002A") == [
        "ONE_PORT",
        "TRANSMISSION_RESPONSE",
        "TWO_PORT",
        "REFLECTION_OPEN",
        "REFLECTION_SHORT",
        "ENHANCED_RESPONSE",
        "TRL",
    ]
    znb = flow.supported_kinds(library, "VNA_RS_ZNB8")
    assert set(znb) == set(flow.KINDS)  # the ZNB does all of them
    assert "TNA" in znb and "TNA" not in flow.supported_kinds(library, "VNA_RS_ZNL6")
    assert flow.supported_kinds(library, "VNA_RS_ZVL6") == [
        "ONE_PORT",
        "TRANSMISSION_RESPONSE",
        "TWO_PORT",
        "TRANSMISSION_RESPONSE_BOTH",
        "ENHANCED_RESPONSE",
    ]
    assert flow.ecal_kinds(library, "VNA_Zenko_LiteVNA67") == []
    assert flow.ecal_kinds(library, "VNA_RS_ZVL6") == []
    assert "TWO_PORT" in flow.ecal_kinds(library, "VNA_Siglent_SNA5002A")
    assert "TRL" not in flow.ecal_kinds(library, "VNA_Siglent_SNA5002A")


def test_steps_of_the_other_kinds():
    def plan(kind):
        return [(s.standard, s.port, s.port2) for s in flow.plan_steps(kind, 1, 2)]

    assert plan("REFLECTION_OPEN") == [("OPEN", 1, None)]
    assert plan("REFLECTION_SHORT") == [("SHORT", 1, None)]
    assert plan("TRANSMISSION_RESPONSE_BOTH") == [("THRU", 1, 2)]
    assert plan("ENHANCED_RESPONSE") == [
        ("OPEN", 1, None),
        ("SHORT", 1, None),
        ("LOAD", 1, None),
        ("THRU", 1, 2),
    ]
    assert plan("TWO_PORT_UNKNOWN_THRU")[-1] == ("UNKNOWN_THRU", 1, 2)
    assert plan("TOM") == [
        ("OPEN", 1, None),
        ("LOAD", 1, None),
        ("OPEN", 2, None),
        ("LOAD", 2, None),
        ("THRU", 1, 2),
    ]
    assert [s[0] for s in plan("TSM")] == ["SHORT", "LOAD", "SHORT", "LOAD", "THRU"]
    assert [s[0] for s in plan("TRM")] == ["REFLECT", "LOAD", "REFLECT", "LOAD", "THRU"]
    assert plan("TRL") == [
        ("REFLECT", 1, None),
        ("REFLECT", 2, None),
        ("TRL_THRU", 1, 2),
        ("LINE", 1, 2),
    ]
    assert plan("TNA") == [("THRU", 1, 2), ("ATTENUATION", 1, 2), ("NETWORK", 1, 2)]
    for kind in flow.KINDS:  # every step can be read by the operator
        assert all(s.text.startswith("Connect") for s in flow.plan_steps(kind, 1, 2))
    # one-port kinds take no second port, every other kind needs two different ports
    assert not flow.needs_second_port("REFLECTION_SHORT") and flow.needs_second_port("TRL")
    for kind in flow.KINDS:
        if flow.needs_second_port(kind):
            with pytest.raises(InvalidArgumentError):
                flow.plan_steps(kind, 2, 2)
    assert set(flow.KIND_PLAN) == set(flow.KINDS) == set(flow.KIND_TEXT)


@needs_library
def test_every_kind_of_every_vna_can_be_planned():
    """Every kind a model lists is turned into commands by the library, for the begin call, for
    every standard of the kind and (when listed) for the electronic calibration unit."""
    from ola.tester import describe_plan

    library = Library.load(LIB)
    checked = 0
    models = [
        m["id"]
        for s in json.load(open(LIB))["instrument_library"]["network_analyzers_series"]
        for m in s["models"]
        if m["capabilities"].get("calibration") == "instrument"
    ]
    assert models
    for model_id in models:
        for kind in flow.supported_kinds(library, model_id):
            args = {"kind": kind, "port": 1}
            if flow.needs_second_port(kind):
                args["port2"] = 2
            assert describe_plan(library, model_id, "calibration_begin", args), (model_id, kind)
            for step in flow.plan_steps(kind, 1, 2):
                margs = {"standard": step.standard, "port": step.port}
                if step.port2:
                    margs["port2"] = step.port2
                assert describe_plan(library, model_id, "calibration_measure", margs), (
                    model_id,
                    kind,
                    step.standard,
                )
                checked += 1
        for kind in flow.ecal_kinds(library, model_id):
            args = {"kind": kind, "port": 1}
            if flow.needs_second_port(kind):
                args["port2"] = 2
            assert describe_plan(library, model_id, "calibration_ecal", args), (model_id, kind)
    assert checked > 100


@needs_library
def test_trl_and_ecal_commands_of_the_instruments():
    from ola.tester import describe_plan

    library = Library.load(LIB)
    sig, znb = "VNA_Siglent_SNA5002A", "VNA_RS_ZNB8"
    assert describe_plan(
        library, sig, "calibration_begin", {"kind": "TRL", "port": 1, "port2": 2}
    ) == [":SENSe1:CORRection:COLLect:METHod:TRL2 1,2"]
    commands = [
        describe_plan(library, sig, "calibration_measure", dict(standard=st, port=1, port2=2))[0]
        for st in ("TRL_THRU", "LINE")
    ]
    assert commands == [
        ":SENSe1:CORRection:COLLect:ACQuire:TRLThru 2,1",
        ":SENSe1:CORRection:COLLect:ACQuire:TRLLine 2,1",
    ]
    assert describe_plan(
        library, sig, "calibration_begin", {"kind": "ENHANCED_RESPONSE", "port": 1, "port2": 2}
    ) == [":SENSe1:CORRection:COLLect:METHod:ERESponse 2,1"]
    assert describe_plan(
        library, znb, "calibration_begin", {"kind": "TWO_PORT_UNKNOWN_THRU", "port": 1, "port2": 2}
    ) == ["SENSe1:CORRection:COLLect:METHod:DEFine 'OLA', UOSM, 1,2"]
    assert (
        describe_plan(
            library, znb, "calibration_measure", {"standard": "UNKNOWN_THRU", "port": 1, "port2": 2}
        )[0]
        == "SENSe1:CORRection:COLLect:ACQuire:SELected UTHRough,1,2"
    )
    assert describe_plan(library, znb, "calibration_ecal", {"kind": "ONE_PORT", "port": 2})[0] == (
        "SENSe1:CORRection:COLLect:AUTO:TYPE FOPort, '', 2"
    )


@needs_library
def test_trl_session_on_an_scpi_vna():
    library = Library.load(LIB)
    sim = SimTransport(lambda cmd: "1" if cmd == "*OPC?" else None)
    handle = make_handle(library, "VNA_Siglent_SNA5002A", sim, "vna")
    session = flow.CalibrationSession(handle, "TRL", 1, 2, SWEEP)
    session.start()
    assert [s.standard for s in session.steps] == ["REFLECT", "REFLECT", "TRL_THRU", "LINE"]
    for step in session.steps:
        session.measure(step)
    session.finish()
    assert ":SENSe1:CORRection:COLLect:METHod:TRL2 1,2" in sim.log
    assert ":SENSe1:CORRection:COLLect:ACQuire:TRLReflect 2" in sim.log
    assert ":SENSe1:CORRection:COLLect:SAVE" in sim.log


@needs_library
def test_ecal_session_measures_nothing_and_applies_nothing():
    library = Library.load(LIB)
    sim = SimTransport(lambda cmd: "1" if cmd == "*OPC?" else None)
    handle = make_handle(library, "VNA_Siglent_SNA5002A", sim, "vna")
    session = flow.CalibrationSession(handle, "TWO_PORT", 1, 2, SWEEP, ecal=True)
    assert session.steps == [] and session.complete
    session.start()
    session.finish()
    assert ":SENSe1:CORRection:COLLect:ECal:SOLT2 1,2" in sim.log
    assert not any("COLLect:SAVE" in c or "ACQuire" in c for c in sim.log)
    assert ":SENSe1:CORRection:STATe ON" in sim.log
    assert session.record("sna", "VNA_Siglent_SNA5002A").standards == ["ECAL"]
    # a kind the unit cannot do is refused by the library, before anything is sent
    other = flow.CalibrationSession(handle, "TRL", 1, 2, SWEEP, ecal=True)
    from ola.call_errors import CallError

    with pytest.raises(CallError):
        other.start()


def gamma(f):
    return 0.3 * (1 + (f - 1e6) / 1e6) * (0.8 - 0.4j)


@needs_library
def test_software_calibration_session_save_and_restore(tmp_path):
    library = Library.load(LIB)
    sim = SimLiteVna()
    handle = make_handle(library, "VNA_Zenko_LiteVNA67", sim, "vna")
    session = flow.CalibrationSession(handle, "ONE_PORT", 1, None, SWEEP)
    session.start()
    for step, g in zip(session.steps, (1, -1, 0)):
        sim.connect(g)
        session.measure(step)
    assert session.complete
    session.finish()
    sim.connect(gamma)
    read = handle.call("read_sparameters", sparameters=["S11"])
    assert read["calibrated"] is True
    assert (
        abs(
            complex(read["parameters"]["S11"]["real"][5], read["parameters"]["S11"]["imaginary"][5])
            - gamma(1.25e6)
        )
        < 1e-4
    )

    record = session.record("DAQ-vna", "VNA_Zenko_LiteVNA67")
    assert record.data is not None and record.standards == ["OPEN@1", "SHORT@1", "LOAD@1"]
    path = flow.save_record(record, tmp_path / "calibrations")
    assert path.name.startswith("DAQ-vna_") and path.name.endswith(".cal.json")

    # a new session of the application: the calibration is restored for the same sweep
    fresh = make_handle(library, "VNA_Zenko_LiteVNA67", sim, "vna")
    flow.restore(fresh, flow.load_record(path))
    again = fresh.call("read_sparameters", sparameters=["S11"])
    assert again["calibrated"] is True
    assert (
        abs(
            complex(
                again["parameters"]["S11"]["real"][5], again["parameters"]["S11"]["imaginary"][5]
            )
            - gamma(1.25e6)
        )
        < 1e-4
    )


def test_unfinished_calibration_cannot_be_applied():
    sim = SimLiteVna()
    from ola.drivers.litevna import LiteVnaDriver

    class Handle:
        def __init__(self):
            self.driver = LiteVnaDriver(sim)

        def call(self, name, **args):
            return self.driver.call(name, args)

        def supports(self, name):
            return hasattr(self.driver, f"fn_{name}")

    session = flow.CalibrationSession(Handle(), "ONE_PORT", 1, None, SWEEP)
    session.start()
    session.measure(session.steps[0])
    with pytest.raises(InvalidArgumentError):
        session.finish()


@needs_library
def test_scpi_vna_session_sends_the_commands_and_keeps_no_data(tmp_path):
    library = Library.load(LIB)
    sim = SimTransport(lambda cmd: "1" if cmd == "*OPC?" else None)
    handle = make_handle(library, "VNA_Siglent_SNA5002A", sim, "vna")
    session = flow.CalibrationSession(handle, "TWO_PORT", 1, 2, SWEEP)
    session.start()
    for step in session.steps:
        session.measure(step)
    session.finish()
    assert ":SENSe1:CORRection:COLLect:METHod:SOLT2 1,2" in sim.log
    assert ":SENSe1:CORRection:COLLect:ACQuire:OPEN 2" in sim.log
    assert ":SENSe1:CORRection:COLLect:ACQuire:THRU 2,1" in sim.log
    assert sim.log[-2:] == [":SENSe1:CORRection:COLLect:SAVE", ":SENSe1:CORRection:STATe ON"] or (
        ":SENSe1:CORRection:STATe ON" in sim.log
    )
    record = session.record("sna", "VNA_Siglent_SNA5002A")
    assert record.data is None
    with pytest.raises(CallNotSupportedError):
        flow.restore(handle, record)


def test_record_is_listed_in_the_project(tmp_path):
    project = tmp_path / "p.json"
    project.write_text(json.dumps({"format_version": 2, "project_name": "p", "x": 1}))
    record = flow.CalibrationRecord("v", "m", "ONE_PORT", 1, None, SWEEP, ["OPEN@1"])
    path = flow.save_record(record, tmp_path / "calibrations")
    flow.attach_to_project(project, path, record)
    newer = flow.CalibrationRecord(
        "v", "m", "ONE_PORT", 1, None, SWEEP, ["OPEN@1"], date="2099-01-01T00:00:00"
    )
    flow.attach_to_project(project, flow.save_record(newer, tmp_path / "calibrations"), newer)
    raw = json.loads(project.read_text())
    assert raw["x"] == 1 and len(raw["calibrations"]) == 1  # the newest per instrument
    assert raw["calibrations"][0]["date"] == "2099-01-01T00:00:00"
    assert raw["calibrations"][0]["file"].startswith("calibrations")
    with pytest.raises(InvalidArgumentError):
        flow.load_record(project)  # not a calibration file


@needs_library
def test_terminal_tool_walks_through_the_steps(tmp_path):
    sys.path.insert(0, os.path.join(HERE, "scripts"))
    import instrument_shell

    library = Library.load(LIB)
    sim = SimLiteVna()
    sim.e00, sim.e11, sim.t = 0j, 0j, 1 + 0j
    shown = []
    # answers: kind 1, port default, start, stop, points, kit, then Enter for each standard
    answers = iter(["1", "", "1M", "2M", "21", "1", "", "", ""])  # kit 1: ideal standards

    def ask(question):
        shown.append(question)  # the operator connects what the question says
        for standard, g in (("OPEN", 1), ("SHORT", -1), ("50 ohm LOAD", 0)):
            if standard in question:
                sim.connect(g)
        return next(answers)

    shell = instrument_shell.Shell(library, input_fn=ask, print_fn=shown.append)
    shell.model_id = "VNA_Zenko_LiteVNA67"
    shell.handle = make_handle(library, shell.model_id, sim, "vna")
    project = tmp_path / "p.json"
    project.write_text(json.dumps({"format_version": 2, "project_name": "p"}))
    shell.calibrate([str(project)])
    text = "\n".join(shown)
    assert "Connect the OPEN to port 1" in text and "Connect the 50 ohm LOAD to port 1" in text
    assert "calibration done and switched on" in text and "listed in" in text
    assert (tmp_path / "calibrations").is_dir() and "calibrations" in json.loads(
        project.read_text()
    )


@needs_library
def test_terminal_tool_with_the_values_of_a_real_kit(tmp_path, monkeypatch):
    from ola import vna_calibration as cal

    monkeypatch.chdir(tmp_path)  # the record is saved in the current folder

    sys.path.insert(0, os.path.join(HERE, "scripts"))
    import instrument_shell

    library = Library.load(LIB)
    sim = SimLiteVna()
    kit = cal.CalKit(open_c0=50.0, open_delay=30.0, short_l0=2.0, short_delay=30.0)
    frequencies = [1e6 + i * 5e4 for i in range(21)]
    shown = []
    # kind 1, default port, 1M..2M, 21 points; kit 3 (type), no losses, then the values in the
    # order of the questions, no file; then Enter for each of the three standards
    values = ["50", "", "", "", "30", "2", "", "", "", "30", ""]
    answers = iter(["1", "", "1M", "2M", "21", "3", ""] + values + [""] + ["", "", ""])

    def ask(question):
        shown.append(question)
        for standard in ("OPEN", "SHORT", "50 ohm LOAD"):
            if standard in question:
                name = standard.split()[-1]
                table = dict(zip(frequencies, cal.ideal_reflection(name, frequencies, kit)))
                sim.connect(lambda f, tb=table: tb[min(tb, key=lambda k: abs(k - f))])
        return next(answers)

    shell = instrument_shell.Shell(library, input_fn=ask, print_fn=shown.append)
    shell.model_id = "VNA_Zenko_LiteVNA67"
    shell.handle = make_handle(library, shell.model_id, sim, "vna")
    shell.calibrate([])
    assert "calibration done and switched on" in "\n".join(shown)
    record = flow.load_record(next(tmp_path.glob("*.cal.json")))
    assert record.kit == {"open_c0": 50.0, "open_delay": 30.0, "short_l0": 2.0, "short_delay": 30.0}


@needs_library
def test_scpi_vna_takes_no_kit_values():
    library = Library.load(LIB)
    sim = SimTransport(lambda cmd: "1" if cmd == "*OPC?" else None)
    handle = make_handle(library, "VNA_Siglent_SNA5002A", sim, "vna")
    assert not handle.supports("set_calibration_kit")  # the kit is defined on the instrument
    session = flow.CalibrationSession(handle, "ONE_PORT", 1, None, SWEEP, kit={"open_c0": 50.0})
    with pytest.raises(CallNotSupportedError):
        session.start()


def test_kit_files(tmp_path):
    path = tmp_path / "kit.json"
    flow.save_kit(path, {"open_c0": 50.0, "short_l0": 2.0})
    assert flow.load_kit(path) == {"open_c0": 50.0, "short_l0": 2.0}
    path.write_text('{"open_capacity": 1}')
    with pytest.raises(InvalidArgumentError):
        flow.load_kit(path)
