"""What instruments were asked and gave during a run, and the need of a role that follows."""

import json
import os

import pytest

from ola import compat
from ola.library import Library
from ola.manual_instrument import ManualInstrumentHandle
from ola.runs import RunWriter, read_run
from ola.sim import SimTransport
from ola.tester import make_handle

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
needs_library = pytest.mark.skipif(LIB is None, reason="library not available")


def test_observe_keeps_the_largest_absolute_value_of_a_quantity():
    seen = {}
    compat.observe(seen, "set_voltage", {"value": 12.0}, None)
    compat.observe(seen, "read_voltage", {}, -33.5)
    compat.observe(seen, "read_voltage", {}, 4.0)
    compat.observe(seen, "read_current", {}, 0.8)
    assert seen == {"max_voltage": 33.5, "max_current": 0.8}


def test_what_is_not_a_number_or_not_a_quantity_is_ignored():
    seen = {}
    compat.observe(seen, "read_voltage", {}, "n/a")
    compat.observe(seen, "read_voltage", {}, float("nan"))
    compat.observe(seen, "read_voltage", {}, True)
    compat.observe(seen, "output_on", {}, None)
    compat.observe(seen, "read_scan", {}, [1.0, 2.0])
    assert seen == {}


@needs_library
def test_a_handle_remembers_what_it_was_asked_and_gave():
    library = Library.load(LIB)

    def answer(cmd):
        return "7.5" if "MEAS" in cmd.upper() and "VOLT" in cmd.upper() else None

    handle = make_handle(library, "PSU_Keysight_E36312A", SimTransport(answer), "PSU")
    handle.call("set_voltage", channel_number=1, value=5.0)
    handle.call("read_voltage", channel_number=1)
    assert handle.observed["max_voltage"] == 7.5


def test_a_manual_instrument_remembers_what_the_operator_set():
    library = Library.load(LIB) if LIB else None
    if library is None:
        pytest.skip("library not available")
    handle = ManualInstrumentHandle(
        "VIN",
        library,
        "power_supply",
        {"max_voltage": 60.0, "max_current": 5.0},
        prompt=lambda request: True,
    )
    handle.call("set_voltage", value=24.0)
    handle.call("set_voltage", value=12.0)
    assert handle.observed == {"max_voltage": 24.0}


@needs_library
def test_characteristics_come_only_from_numbers_the_library_gives():
    library = Library.load(LIB)
    psu = compat.characteristics(library, "PSU_OWON_ODP3033")
    assert psu["max_voltage"] == 30 and psu["max_current"] == 3 and psu["number_of_channels"] == 3
    load = compat.characteristics(library, "EL_Siglent_SDL1030X_E")
    assert (load["max_voltage"], load["max_current"], load["max_power"]) == (150, 30, 300)
    scope = compat.characteristics(library, "OSC_Siglent_SDS804X_HD")
    assert scope["bandwidth_mhz"] == 70 and scope["sample_rate_gsa_s"] == 2.0
    dmm = compat.characteristics(library, "MTR_Agilent_34401A")
    assert dmm["max_voltage"] == 1000 and dmm["max_current"] == 3
    assert compat.characteristics(library, "MTR_HP_3478A") == {}  # the library gives no numbers
    vna = compat.characteristics(library, "VNA_Zenko_LiteVNA62")
    assert vna["frequency_max_hz"] == 6.3e9 and vna["number_of_ports"] == 2
    assert compat.characteristics(library, "NOT_A_MODEL") == {}


class Handle:
    def __init__(self, name, observed):
        self.name, self.observed = name, observed


class Runner:
    bindings = {"dmm": [Handle("DMM", {"max_voltage": 33.0})], "psu": [Handle("PSU", {})]}


def test_observed_of_a_runner_leaves_out_instruments_with_nothing():
    assert compat.observed_of(Runner()) == {
        "dmm": [{"name": "DMM", "observed": {"max_voltage": 33.0}}]
    }


def test_the_end_record_of_a_run_keeps_what_was_observed(tmp_path):
    from ola.runner import FINAL_STATES

    class Event:
        kind, t = "state", 1.0

        def __init__(self, state):
            self.data = {"state": state}

    path = tmp_path / "r.jsonl"
    writer = RunWriter(path, {"run_id": "1"}, observed=lambda: compat.observed_of(Runner()))
    writer(Event(next(iter(FINAL_STATES)).value))
    run = read_run(path)
    assert run["end"]["observed"]["dmm"][0]["observed"] == {"max_voltage": 33.0}
    # without a callback the end record is as before
    other = tmp_path / "o.jsonl"
    plain = RunWriter(other, {"run_id": "2"})
    plain(Event(next(iter(FINAL_STATES)).value))
    assert "observed" not in read_run(other)["end"]


def run(observed_by_role, instruments=None):
    return {
        "header": {"instruments": instruments or {}},
        "end": {"observed": observed_by_role},
    }


def test_the_need_is_the_largest_value_ever_observed_plus_twenty_percent():
    runs = [
        run({"dmm": [{"name": "A", "observed": {"max_voltage": 30.0, "max_current": 1.0}}]}),
        run({"dmm": [{"name": "A", "observed": {"max_voltage": 33.0}}]}),
        run({"psu": [{"name": "P", "observed": {"max_voltage": 99.0}}]}),  # another role
    ]
    need = compat.role_need(runs, "dmm")
    assert need["max_voltage"] == pytest.approx(39.6)
    assert need["max_current"] == pytest.approx(1.2)
    assert compat.role_need(runs, "nobody") == {}
    assert compat.role_need([], "dmm") == {}
    assert compat.role_need([{"header": {}, "end": None}], "dmm") == {}  # an interrupted run


def test_the_previous_instrument_is_the_one_of_the_newest_run_that_has_one():
    newest = run({}, {"dmm": [{"name": "NEW", "characteristics": {"max_voltage": 100}}]})
    older = run({}, {"dmm": [{"name": "OLD", "characteristics": {"max_voltage": 200}}]})
    assert compat.previous_instruments([newest, older], "dmm")[0]["name"] == "NEW"
    legacy = {"header": {}, "end": None}  # a run from before the snapshot existed
    assert compat.previous_instruments([legacy, older], "dmm")[0]["name"] == "OLD"
    assert compat.previous_instruments([legacy], "dmm") == []


@needs_library
def test_the_snapshot_keeps_what_the_instrument_could_do_that_day():
    from ola.identity import snapshot

    library = Library.load(LIB)
    handle = make_handle(library, "PSU_OWON_ODP3033", SimTransport(lambda c: None), "PSU")
    got = snapshot(handle)
    assert got["characteristics"]["max_voltage"] == 30
    manual = ManualInstrumentHandle(
        "VIN", library, "power_supply", {"max_voltage": 60.0, "max_current": 5.0}
    )
    assert snapshot(manual)["characteristics"] == {"max_voltage": 60.0, "max_current": 5.0}
    json.dumps(snapshot(manual))
