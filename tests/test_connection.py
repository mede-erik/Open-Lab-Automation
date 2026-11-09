# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""ProjectConnector: the handle of every instrument of a project's .inst file.

Needs the instrument library and the handles (``ola.library``, ``ola.instrument_handle``,
``ola.manual_instrument``); the tests are skipped where those modules are not present.
"""

import json
import threading

import pytest

pytest.importorskip("ola.library")
pytest.importorskip("ola.instrument_handle")
pytest.importorskip("ola.manual_instrument")

from ola.call_errors import CallError  # noqa: E402
from ola.connection import ConnectionProblem, ProjectConnector, read_inst_entries  # noqa: E402
from ola.library import Library  # noqa: E402
from ola.sim import SimTransport  # noqa: E402

SCHEMA = {
    "schema_version": 1,
    "category": "power_supplies_series",
    "types": {"bool": {"kind": "bool"}},
    "calls": {
        "set_voltage": {
            "requirement": "mandatory",
            "kind": "set",
            "args": {
                "channel_number": {"type": "int", "min": 1, "required": False},
                "value": {"type": "float"},
            },
        },
        "read_voltage": {
            "requirement": "mandatory",
            "kind": "query",
            "args": {"channel_number": {"type": "int", "min": 1, "required": False}},
            "result": {"type": "float"},
        },
        "output_on": {"requirement": "mandatory", "kind": "action"},
        "set_remote": {"requirement": "optional", "kind": "action"},
    },
}
SERIES = {
    "series_id": "S",
    "common_scpi_commands": {
        "set_voltage": {
            "set": {"steps": [{"op": "write", "text": "VOLT {value}"}]},
            "parameters": {"channel_number": {"type": "int"}, "value": {"type": "float"}},
        },
        "read_voltage": {
            "query": {
                "steps": [{"op": "query", "text": "MEAS:VOLT?", "returns": "float"}],
                "return_type": "float",
            },
            "parameters": {"channel_number": {"type": "int"}},
        },
        "set_remote": {"set": {"steps": [{"op": "write", "text": "SYST:REM"}]}},
    },
    "models": [{"id": "PSU1", "model": "Brand PSU1", "name": "Brand PSU1"}],
}


def library():
    return Library({"power_supplies_series": [SERIES]}, {"power_supplies_series": SCHEMA})


def write_inst(tmp_path, instruments):
    path = tmp_path / "p.inst"
    path.write_text(json.dumps({"instruments": instruments}))
    return path


REAL = {"instance_name": "PSU", "instrument_type": "power_supply", "model_id": "PSU1",
        "visa_address": "TCPIP0::1.2.3.4::inst0::INSTR"}  # fmt: skip
MANUAL = {"instance_name": "VIN", "instrument_type": "power_supply", "is_manual": True,
          "channels": [{"max_voltage": 20.0, "max_current": 5.0}]}  # fmt: skip


class Opener:
    """Stands in for opening a real instrument: gives simulated ones and remembers them."""

    def __init__(self):
        self.opened = []

    def __call__(self, address, library, model_id, timeout_ms):
        sim = SimTransport(lambda cmd: "3.5" if cmd == "MEAS:VOLT?" else None)
        sim.closed = False
        close = sim.close

        def closing():
            sim.closed = True
            close()

        sim.close = closing
        self.opened.append((address, model_id, sim))
        return sim


def make(tmp_path, instruments, prompt=None, opener=None):
    path = write_inst(tmp_path, instruments)
    opener = opener or Opener()
    return ProjectConnector(library(), lambda: path, prompt=prompt, opener=opener), opener


def test_a_remote_instrument_is_opened_at_its_address_and_works(tmp_path):
    connector, opener = make(tmp_path, [REAL])
    handle = connector("PSU")
    assert opener.opened[0][:2] == ("TCPIP0::1.2.3.4::inst0::INSTR", "PSU1")
    assert handle.name == "PSU"
    assert handle.call("read_voltage", channel_number=1) == 3.5
    handle.call("set_voltage", channel_number=1, value=5)
    assert "VOLT 5" in opener.opened[0][2].log


def test_the_connection_is_kept_between_runs_and_the_handle_is_new(tmp_path):
    connector, opener = make(tmp_path, [REAL])
    first, second = connector("PSU", threading.Event()), connector("PSU", threading.Event())
    assert len(opener.opened) == 1  # opened once
    assert first is not second  # each run has its own handle (its own cancel event)
    connector.close()
    assert opener.opened[0][2].closed


def test_a_changed_address_reopens_the_connection(tmp_path):
    connector, opener = make(tmp_path, [REAL])
    connector("PSU")
    path = write_inst(tmp_path, [{**REAL, "visa_address": "TCPIP0::9.9.9.9::inst0::INSTR"}])
    connector._inst_path = lambda: path
    connector("PSU")
    assert len(opener.opened) == 2 and opener.opened[0][2].closed


def test_serial_instruments_are_put_in_remote_mode_once(tmp_path):
    serial = {**REAL, "visa_address": "ASRL1::INSTR"}
    connector, opener = make(tmp_path, [serial])
    connector("PSU")
    connector("PSU")
    assert opener.opened[0][2].log.count("SYST:REM") == 1


def test_a_manual_instrument_asks_the_operator(tmp_path):
    asked = []

    def prompt(request, cancel):
        asked.append(request.text)
        return True

    connector, opener = make(tmp_path, [MANUAL], prompt=prompt)
    handle = connector("VIN", threading.Event())
    handle.call("set_voltage", value=12)
    assert asked == ["Set 'VIN' 12.0 V"]
    assert not opener.opened  # nothing is opened for a manual instrument


def test_a_manual_instrument_cancelled_by_the_operator(tmp_path):
    connector, _ = make(tmp_path, [MANUAL], prompt=lambda request, cancel: False)
    with pytest.raises(CallError) as info:
        connector("VIN").call("set_voltage", value=12)
    assert info.value.code == "CALL-006"


def test_a_value_above_the_limit_of_a_manual_instrument_is_refused(tmp_path):
    connector, _ = make(tmp_path, [MANUAL], prompt=lambda r, c: True)
    with pytest.raises(CallError, match="exceeds"):
        connector("VIN").call("set_voltage", value=30)


@pytest.mark.parametrize(
    "entry,words",
    [
        ({**REAL, "model_id": "NOPE"}, "not in the instrument library"),
        ({k: v for k, v in REAL.items() if k != "visa_address"}, "no address"),
        ({k: v for k, v in REAL.items() if k != "model_id"}, "no model"),
    ],
)
def test_problems_say_what_to_fix(tmp_path, entry, words):
    connector, _ = make(tmp_path, [entry])
    with pytest.raises(ConnectionProblem, match=words):
        connector("PSU")


def test_an_unknown_name_lists_the_known_ones(tmp_path):
    connector, _ = make(tmp_path, [REAL, MANUAL])
    with pytest.raises(ConnectionProblem, match="PSU, VIN"):
        connector("X")


def test_an_instrument_that_does_not_answer_is_named(tmp_path):
    def failing(address, library, model_id, timeout_ms):
        raise OSError("timed out")

    connector, _ = make(tmp_path, [REAL], opener=failing)
    with pytest.raises(ConnectionProblem, match="PSU.*1.2.3.4.*timed out"):
        connector("PSU")


def test_no_instrument_file(tmp_path):
    connector = ProjectConnector(library(), lambda: None)
    with pytest.raises(ConnectionProblem, match="no instrument file"):
        connector("PSU")
    with pytest.raises(ConnectionProblem, match="cannot read"):
        read_inst_entries(tmp_path / "missing.inst")


def test_works_inside_a_project_session(tmp_path):
    """The connector is the 'connect' of ProjectSession: a time-less smoke test of the wiring."""
    from ola.project import Project
    from ola.project_session import ProjectSession
    from ola.registry import default_registry

    path = write_inst(tmp_path, [REAL])
    session = ProjectSession(
        Project.new("P", tmp_path, "p.inst"),
        default_registry(user_dir="/nonexistent"),
        connect=ProjectConnector(library(), lambda: path, opener=Opener()),
    )
    assert session.instruments == ["PSU"]
    handles = session.bind(
        __import__("ola.project", fromlist=["MeasurementFile"]).MeasurementFile(type="time_log"),
        session.registry.get("time_log"),
        threading.Event(),
    )
    assert handles["instruments"][0].name == "PSU"


def test_the_application_builds_the_connector_from_a_library_file(tmp_path):
    """frontend/ui/connector_setup: library file + project -> ProjectConnector (needs PyQt6)."""
    pytest.importorskip("PyQt6")
    from frontend.ui.connector_setup import make_connector
    from ola.project import Project
    from ola.project_session import ProjectSession
    from ola.registry import default_registry

    lib_dir = tmp_path / "lib"
    (lib_dir / "schema").mkdir(parents=True)
    (lib_dir / "instruments_lib.json").write_text(
        json.dumps({"schema_version": 1, "instrument_library": {"power_supplies_series": [SERIES]}})
    )
    (lib_dir / "schema" / "psu.json").write_text(json.dumps(SCHEMA))
    write_inst(tmp_path, [REAL])
    session = ProjectSession(
        Project.new("P", tmp_path, "p.inst"), default_registry(user_dir="/nonexistent")
    )
    connector = make_connector(session, str(lib_dir / "instruments_lib.json"))
    assert isinstance(connector, ProjectConnector)
    assert connector.names() == ["PSU"]


def test_a_whole_run_through_the_session_reads_the_instrument(tmp_path):
    """Project file + .inst + library + simulated instrument -> a finished run with its data."""
    from ola.project import MeasurementFile, Project
    from ola.project_session import ProjectSession
    from ola.registry import default_registry
    from ola.runner import RunState
    from ola.runs import read_run

    path = write_inst(tmp_path, [REAL])
    registry = default_registry(user_dir="/nonexistent")
    project = Project.new("P", tmp_path, "p.inst")
    session = ProjectSession(
        project, registry, connect=ProjectConnector(library(), lambda: path, opener=Opener())
    )
    ref = session.create("time_log", "Voltage")
    params = {
        "interval_s": 0.01,
        "samples": 3,
        "channels": [
            {
                "name": "v",
                "instrument": "PSU",
                "call": "read_voltage",
                "args": {"channel_number": 1},
            }
        ],
    }
    MeasurementFile(type="time_log", role_bindings={"instruments": ["PSU"]}, params=params).save(
        session.path(ref)
    )
    runner, run_file = session.build_runner(ref)
    runner.start()
    assert runner.join(10) and runner.state is RunState.FINISHED, runner.error
    points = read_run(run_file)["points"]
    assert len(points) == 3 and all(p["values"]["v"] == 3.5 for p in points)


def test_serial_settings_and_timeout_of_the_entry_reach_the_opener(tmp_path):
    seen = []

    def opener(address, library, model_id, timeout_ms, serial_override=None):
        seen.append((address, timeout_ms, serial_override))
        return SimTransport(lambda cmd: "3.5")

    entry = {**REAL, "visa_address": "ASRL3::INSTR", "serial": {"baud": 19200}, "timeout_ms": 9000}
    path = write_inst(tmp_path, [entry])
    connector = ProjectConnector(library(), lambda: path, opener=opener)
    connector("PSU")
    connector("PSU")  # same settings: the open connection is reused
    assert seen == [("ASRL3::INSTR", 9000, {"baud": 19200})]
    path = write_inst(tmp_path, [{**entry, "serial": {"baud": 9600}}])
    connector("PSU")  # other settings: opened again
    assert len(seen) == 2 and seen[1][2] == {"baud": 9600}


def test_an_entry_without_settings_calls_the_opener_as_before(tmp_path):
    connector, opener = make(tmp_path, [REAL])
    connector("PSU")
    assert opener.opened[0][:2] == ("TCPIP0::1.2.3.4::inst0::INSTR", "PSU1")


def test_what_an_instrument_can_do_is_known_without_connecting(tmp_path):
    manual = {
        "instrument_type": "power_supply",
        "instance_name": "VIN",
        "is_manual": True,
        "channels": [{"enabled": True, "name": "CH1", "max_voltage": 30.0, "max_current": 5.0}],
    }
    connector, opener = make(tmp_path, [REAL, manual])
    assert connector.characteristics("VIN") == {"max_voltage": 30.0, "max_current": 5.0}
    assert connector.characteristics("PSU") == {}  # the test library gives no numbers
    assert connector.characteristics("nobody") == {}
    assert opener.opened == []  # nothing was opened
