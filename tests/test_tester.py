"""Interactive tester: selection flow, calls, self-test (simulated instrument, no hardware)."""

import os

import pytest

from ola import tester
from ola.library import Library

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
pytestmark = pytest.mark.skipif(LIB is None, reason="library not available")


@pytest.fixture(scope="module")
def library():
    return Library.load(LIB)


def run_script(library, answers):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "instrument_shell", os.path.join(HERE, "scripts", "instrument_shell.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    feed = iter(answers)
    out = []

    def ask(prompt):
        try:
            value = next(feed)
        except StopIteration:
            raise EOFError
        out.append(prompt + value)
        return value

    module.Shell(library, ask, lambda s="": out.append(str(s)), simulate=True).run()
    return "\n".join(out)


def test_categories_and_models(library):
    keys = [k for k, _ in tester.categories(library)]
    assert "dataloggers_series" in keys and "power_supplies_series" in keys
    ids = [m for m, _, _ in tester.models_of(library, "dataloggers_series")]
    assert "DL_Keysight_DAQ970A" in ids
    kinds = [i["type"] for i in tester.interfaces(library, "DL_Agilent_34970A")]
    assert "SERIAL" in kinds


def test_shell_session_with_a_simulated_datalogger(library):
    keys = [k for k, _ in tester.categories(library)]
    category = str(keys.index("dataloggers_series") + 1)
    models = [m for m, _, _ in tester.models_of(library, "dataloggers_series")]
    model = str(models.index("DL_Keysight_DAQ970A") + 1)
    text = run_script(
        library,
        [
            category,
            model,
            "1",
            "1.5,2.5,3.5",
            "missing",
            "plan select_channels channels=101:103",
            "call read_scan",
            "call set_function function=VOLTage:DC channels=101",
            "n",
            "quit",
        ],
    )
    assert "Connected to DL_Keysight_DAQ970A" in text
    assert "none: all mandatory calls are defined" in text
    assert "commands: ROUT:SCAN (@101:103)" in text
    assert "result: [1.5, 2.5, 3.5]" in text
    assert "this writes to the instrument" in text and "not sent" in text


def test_self_test_runs_queries_only(library):
    model = "PSU_OWON_ODP3033"
    handle = tester.make_handle(library, model, tester.open_simulated("1"), model)
    results = tester.self_test(library, model, handle)
    by_call = {r.call: r for r in results}
    assert by_call["read_voltage"].status == "ok"
    assert by_call["output_state_query"].detail == "True"
    assert by_call["output_on"].status == "skip" and "writes" in by_call["output_on"].detail
    assert by_call["set_voltage"].status == "skip"
    sim = handle._instrument.transport
    assert not any(c.startswith("OUTP ON") for c in sim.log)


def test_self_test_reports_a_failing_call(library):
    model = "PSU_OWON_ODP3033"
    handle = tester.make_handle(library, model, tester.open_simulated("not a number"), model)
    results = {r.call: r for r in tester.self_test(library, model, handle)}
    assert results["read_voltage"].status == "fail"


def test_serial_settings_helper():
    pytest.importorskip("pyvisa")
    from pyvisa import constants as c

    from ola.serial_config import apply_serial_settings

    class Resource:
        pass

    res = Resource()
    apply_serial_settings(
        res,
        {"baud": 9600, "data_bits": 8, "parity": "N", "stop_bits": 2, "flow_control": "dtr_dsr"},
    )
    assert res.baud_rate == 9600 and res.parity == c.Parity.none
    assert res.stop_bits == c.StopBits.two and res.flow_control == c.ControlFlow.dtr_dsr
    with pytest.raises(ValueError):
        apply_serial_settings(res, {"flow_control": "bogus"})


def test_serial_settings_all_stop_bits_and_flow_names():
    """Every value the library may use maps to a pyvisa constant (names differ between versions)."""
    pytest.importorskip("pyvisa")
    from ola.serial_config import apply_serial_settings

    class Resource:
        pass

    for stop in (1, 1.5, 2):
        for flow in ("none", "xon_xoff", "rts_cts", "dtr_dsr"):
            for parity in ("N", "E", "O"):
                apply_serial_settings(
                    Resource(), {"stop_bits": stop, "flow_control": flow, "parity": parity}
                )


def test_open_visa_serial_on_a_pseudo_terminal(library):
    """Whole serial path (settings, terminators, set_remote, queries) against a fake RS-232
    instrument on a pseudo-terminal."""
    pytest.importorskip("pyvisa_py")
    pty = pytest.importorskip("pty")
    import threading
    import tty

    master, slave = pty.openpty()
    tty.setraw(master)
    seen = []

    def instrument():
        buf = b""
        while True:
            try:
                buf += os.read(master, 256)
            except OSError:
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode().strip()
                seen.append(cmd)
                reply = {
                    "*IDN?": b"HEWLETT-PACKARD,34970A,0,13-2-2\r\n",
                    "READ?": b"+1.5E+00,+2.0E-01\r\n",
                }.get(cmd)
                if reply:
                    os.write(master, reply)

    threading.Thread(target=instrument, daemon=True).start()
    model = "DL_Agilent_34970A"
    connection = tester.open_visa(
        f"ASRL{os.ttyname(slave)}::INSTR", library, model, timeout_ms=2000
    )
    try:
        handle = tester.make_handle(library, model, connection, model)
        handle.call("set_remote")
        assert handle.call("identification_query").startswith("HEWLETT-PACKARD,34970A")
        assert handle.call("read_scan") == [1.5, 0.2]
        assert seen == ["SYST:REM", "*IDN?", "READ?"]
    finally:
        connection.close()


def test_probe_serial_finds_an_answering_instrument():
    pty = pytest.importorskip("pty")
    pytest.importorskip("serial")
    import threading
    import tty

    master, slave = pty.openpty()
    tty.setraw(master)

    def instrument():
        buf = b""
        while True:
            try:
                buf += os.read(master, 256)
            except OSError:
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip() == b"*IDN?":
                    os.write(master, b"HEWLETT-PACKARD,34970A,0,13-2-2\r\n")

    threading.Thread(target=instrument, daemon=True).start()
    seen = []
    found = tester.probe_serial(os.ttyname(slave), timeout=0.5, progress=seen.append)
    assert found and found[0].answer.startswith("HEWLETT-PACKARD,34970A")
    assert found[0].baud == 57600 and found[0].flow_control == "xon_xoff"
    assert seen and "57600" in seen[0]


def test_probe_serial_without_answer_returns_nothing():
    pty = pytest.importorskip("pty")
    pytest.importorskip("serial")
    master, slave = pty.openpty()  # nobody answers on the master side
    found = tester.probe_serial(os.ttyname(slave), timeout=0.2, bauds=(9600,), flows=("none",))
    assert found == []
    assert tester.serial_port_from_address("ASRL/dev/ttyUSB1::INSTR") == "/dev/ttyUSB1"


def test_loopback_serial_with_an_echoing_pty():
    pty = pytest.importorskip("pty")
    pytest.importorskip("serial")
    import threading
    import tty

    master, slave = pty.openpty()
    tty.setraw(master)

    def echo():
        while True:
            try:
                data = os.read(master, 256)
            except OSError:
                return
            os.write(master, data)

    threading.Thread(target=echo, daemon=True).start()
    assert tester.loopback_serial(os.ttyname(slave), timeout=0.5) == "hello"
    mute_master, mute_slave = pty.openpty()
    assert tester.loopback_serial(os.ttyname(mute_slave), timeout=0.2) is None


def test_self_test_skips_heavy_calls_unless_asked(library):
    model = "DL_Agilent_34970A"
    handle = tester.make_handle(library, model, tester.open_simulated("0"), model)
    results = {r.call: r for r in tester.self_test(library, model, handle)}
    assert results["self_test"].status == "skip" and "reset" in results["self_test"].detail
    assert "*TST?" not in handle._instrument.transport.log


def test_datalogger_self_test_has_a_long_timeout_and_monitor_data_is_a_list(library):
    from ola.call_planner import plan_call

    plan = plan_call(library, "DL_Agilent_34970A", "self_test")
    assert plan.steps == [{"op": "query", "text": "*TST?", "returns": "int", "timeout_ms": 60000}]
    monitor = plan_call(library, "DL_Agilent_34970A", "query_monitor_data")
    assert monitor.interpret([""]) == [] and monitor.interpret(["+1.5E+00"]) == [1.5]


def test_self_test_runs_fetch_readings_after_read_scan(library):
    model = "DL_Agilent_34970A"
    handle = tester.make_handle(library, model, tester.open_simulated("1.5"), model)
    order = [r.call for r in tester.self_test(library, model, handle)]
    assert order.index("fetch_readings") == order.index("read_scan") + 1
