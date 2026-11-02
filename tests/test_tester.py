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
