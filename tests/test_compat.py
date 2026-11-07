# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

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


# ---- comparing the instruments of a role with the ones of the previous runs --------------------
def previous_run(name, characteristics, observed=None):
    return {
        "header": {"instruments": {"dmm": [{"name": name, "characteristics": characteristics}]}},
        "end": {"observed": {"dmm": [{"name": name, "observed": observed}]}} if observed else {},
    }


def new(name, characteristics):
    return [{"name": name, "characteristics": characteristics}]


def test_without_a_previous_run_nothing_is_compared():
    assert compat.check_role("dmm", new("A", {"max_voltage": 1}), []) == []
    assert (
        compat.check_role("dmm", new("A", {"max_voltage": 1}), [{"header": {}, "end": None}]) == []
    )


def test_a_lower_limit_than_the_previous_instrument_is_reported_with_both_values():
    runs = [previous_run("OLD", {"max_voltage": 200.0})]
    found = compat.check_role("dmm", new("NEW", {"max_voltage": 100.0}), runs)
    assert len(found) == 1
    f = found[0]
    assert (f.role, f.instrument, f.characteristic) == ("dmm", "NEW", "max_voltage")
    assert (f.value, f.previous, f.previous_name, f.need) == (100.0, 200.0, "OLD", None)
    assert compat.check_role("dmm", new("NEW", {"max_voltage": 200.0}), runs) == []  # equal: fine
    assert compat.check_role("dmm", new("NEW", {"max_voltage": 300.0}), runs) == []  # more: fine


def test_what_was_really_needed_decides_not_what_the_old_instrument_could_do():
    """The 200 V multimeter only read 33 V (need 39.6 V): a 100 V one is accepted, a 30 V is not."""
    runs = [previous_run("OLD", {"max_voltage": 200.0}, {"max_voltage": 33.0})]
    assert compat.check_role("dmm", new("NEW", {"max_voltage": 100.0}), runs) == []
    found = compat.check_role("dmm", new("TINY", {"max_voltage": 30.0}), runs)
    assert len(found) == 1 and found[0].need == pytest.approx(39.6) and found[0].previous == 200.0


def test_a_characteristic_the_previous_instrument_did_not_have_is_not_compared():
    runs = [previous_run("OLD", {"max_voltage": 200.0})]
    assert compat.check_role("dmm", new("NEW", {"max_current": 0.001}), runs) == []


def test_the_instrument_of_the_same_name_is_compared_with_itself_then_by_position():
    runs = [
        {
            "header": {
                "instruments": {
                    "dmm": [
                        {"name": "A", "characteristics": {"max_voltage": 100.0}},
                        {"name": "B", "characteristics": {"max_voltage": 500.0}},
                    ]
                }
            },
            "end": {},
        }
    ]
    bound = [
        {"name": "B", "characteristics": {"max_voltage": 400.0}},
        {"name": "C", "characteristics": {"max_voltage": 90.0}},
    ]
    found = compat.check_role("dmm", bound, runs)
    assert [(f.instrument, f.previous_name) for f in found] == [("B", "B"), ("C", "B")]


def test_lowest_frequency_is_left_to_the_sweep_check():
    runs = [previous_run("OLD", {"frequency_min_hz": 1e3})]
    assert compat.check_role("dmm", new("NEW", {"frequency_min_hz": 5e4}), runs) == []


def test_values_are_shown_with_their_unit():
    assert compat.format_value("max_voltage", 39.6) == "39.6 V"
    assert compat.format_value("frequency_max_hz", 6.3e9) == "6.3 GHz"
    assert compat.format_value("frequency_min_hz", 5e4) == "50 kHz"
    assert compat.format_value("number_of_channels", 4) == "4"
    assert compat.format_value("max_voltage", None) == "-"


def test_a_difference_is_kept_in_plain_values_for_the_run_header():
    f = compat.Finding("dmm", "NEW", "max_voltage", 100.0, 200.0, "OLD", None)
    assert f.to_dict() == {
        "role": "dmm",
        "instrument": "NEW",
        "characteristic": "max_voltage",
        "value": 100.0,
        "previous": 200.0,
        "previous_name": "OLD",
        "blocking": False,
    }
    json.dumps(f.to_dict())


# ---- network analyzers ---------------------------------------------------------------------------
def vna(name, **kw):
    have = {k: v for k, v in kw.items() if k.startswith(("frequency", "max_"))}
    return [
        {
            "name": name,
            "characteristics": have,
            "abilities": kw.get("abilities", {}),
        }
    ]


SWEEP = {"sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 401}}


def test_where_the_sweep_is():
    assert compat.sweep_of(SWEEP) == {"start_hz": 1e6, "stop_hz": 3e9, "points": 401.0}
    top = {"start_hz": 1e6, "stop_hz": 1e9, "points": 201, "sparameters": ["S11"]}
    assert compat.sweep_of(top)["stop_hz"] == 1e9
    assert compat.sweep_of({"sweep": {"start_hz": "x"}}) is None
    assert compat.sweep_of({}) is None


def test_a_sweep_outside_the_range_of_the_vna_blocks_and_shows_both_ranges():
    runs = [previous_run("OLD", {"frequency_min_hz": 9e3, "frequency_max_hz": 4.5e9})]
    runs[0]["header"]["instruments"] = {
        "vna": runs[0]["header"]["instruments"]["dmm"]
    }  # the role of this test is "vna"
    new_vna = vna("LITE", frequency_min_hz=5e4, frequency_max_hz=2e9)
    found = compat.check_network_analyzer("vna", new_vna, SWEEP, runs)
    assert [(f.characteristic, f.blocking) for f in found] == [("frequency_max_hz", True)]
    f = found[0]
    assert (f.value, f.previous, f.previous_name, f.need) == (2e9, 4.5e9, "OLD", 3e9)
    low = compat.check_network_analyzer(
        "vna", vna("LITE", frequency_min_hz=5e6, frequency_max_hz=6e9), SWEEP, runs
    )
    assert [(f.characteristic, f.need) for f in low] == [("frequency_min_hz", 1e6)]


def test_the_range_blocks_also_when_the_measurement_was_never_run():
    found = compat.check_network_analyzer(
        "vna", vna("LITE", frequency_min_hz=5e4, frequency_max_hz=2e9), SWEEP, []
    )
    assert len(found) == 1 and found[0].blocking and found[0].previous is None


def test_a_sweep_inside_the_range_and_a_vna_without_numbers_are_fine():
    assert (
        compat.check_network_analyzer(
            "vna",
            vna("A", frequency_min_hz=9e3, frequency_max_hz=4.5e9),
            {"sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 11}},
            [],
        )
        == []
    )
    assert (
        compat.check_network_analyzer("vna", vna("B"), SWEEP, []) == []
    )  # the library says nothing
    assert compat.check_network_analyzer("vna", vna("C", frequency_max_hz=1e9), {}, []) == []


def test_too_many_points_block():
    found = compat.check_network_analyzer(
        "vna", vna("A", max_sweep_points=201), {"sweep": {**SWEEP["sweep"], "points": 401}}, []
    )
    assert [(f.characteristic, f.need, f.value) for f in found] == [("max_sweep_points", 401, 201)]


def used_run(used):
    return {
        "header": {"instruments": {"vna": [{"name": "OLD"}]}},
        "end": {"observed": {"vna": [{"name": "OLD", "observed": {}, "used": used}]}},
    }


def test_sparameters_and_source_power_used_before_are_warnings_not_blocks():
    runs = [used_run({"sparameters": ["S11", "S12", "S21", "S22"], "source_power": True})]
    lite = vna("LITE")
    lite[0]["abilities"] = {"sparameters": ["S11", "S21"], "source_power": False}
    found = compat.check_network_analyzer("vna", lite, {}, runs)
    by_key = {f.characteristic: f for f in found}
    assert set(by_key) == {"sparameters", "source_power"}
    assert not by_key["sparameters"].blocking and not by_key["source_power"].blocking
    assert by_key["sparameters"].value_text == "S11, S21"
    assert by_key["sparameters"].need_text == "S11, S12, S21, S22"
    # a VNA that does everything, or one the library says nothing about, is not reported
    full = vna("FULL")
    full[0]["abilities"] = {"sparameters": ["S11", "S12", "S21", "S22"], "source_power": True}
    assert compat.check_network_analyzer("vna", full, {}, runs) == []
    unknown = vna("X")
    unknown[0]["abilities"] = {"sparameters": None, "source_power": True}
    assert compat.check_network_analyzer("vna", unknown, {}, runs) == []


def test_what_a_vna_was_asked_is_remembered_and_goes_into_the_end_record():
    store = {}
    compat.note_use(store, "read_sparameters", {"sparameters": ["S21", "S11"]})
    compat.note_use(store, "read_sparameters", {"sparameters": ["S11"]})
    compat.note_use(store, "set_source_power", {"value": -10})
    compat.note_use(store, "set_if_bandwidth", {"value": 1000})
    assert store == {"sparameters": ["S11", "S21"], "source_power": True}

    class H:
        name, observed, used = "VNA", {}, store

    class R:
        bindings = {"vna": [H()]}

    assert compat.observed_of(R())["vna"][0]["used"] == store
    assert compat.role_use([{"end": {"observed": compat.observed_of(R())}}], "vna") == store
