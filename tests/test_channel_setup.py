# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The settings of the channels of a datalogger: range, integration time, the zero with the inputs
shorted, the input impedance. On a simulated datalogger that behaves like the 34970A."""

import os
import threading
import time

import pytest

from ola.channel_setup import (
    ChannelSettings,
    ChannelSetupError,
    ConfiguredHandle,
    check_settings,
    config_calls,
    function_of,
    options_of,
    parse_impedance,
    parse_nplc,
    parse_range,
    settings_of,
    settings_of_entry,
    wrap_if_configured,
    zero_wait_s,
)
from ola.datalogger_setup import DataloggerSetupError
from ola.library import Library
from ola.measurement import Role
from ola.runner import FINAL_STATES, Runner, RunState
from ola.sim_datalogger import SimDatalogger, parse_channels
from tests.measurement_helpers import Scripted

import ola.channel_setup as channel_setup  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_WAIT = (channel_setup.ZERO_SETTLE_PLC_SECONDS, channel_setup.ZERO_SETTLE_MARGIN_S)


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The wait for the null measurement is real time: not in the tests (one has it back)."""
    monkeypatch.setattr(channel_setup, "ZERO_SETTLE_PLC_SECONDS", 0.0)
    monkeypatch.setattr(channel_setup, "ZERO_SETTLE_MARGIN_S", 0.0)


LIBRARY = os.path.join(ROOT, "Instruments_LIB", "instruments_lib.json")


def channel(number=101, **settings):
    return {"enabled": True, "name": f"ch{number}", "channel_id": str(number),
            "meas_type": "VOLT:DC", **settings}  # fmt: skip


# ---- reading the settings ---------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [(None, "AUTO"), ("", "AUTO"), ("auto", "AUTO"), (" Auto ", "AUTO"), (10, 10.0), ("10", 10.0),
     ("0,1", 0.1), ("max", "MAX"), ("min", "MIN"), (0.1, 0.1)],
)  # fmt: skip
def test_a_range_is_auto_or_a_number(value, expected):
    assert parse_range(value) == expected


@pytest.mark.parametrize("value", ["big", 0, -1, True, float("nan")])
def test_a_wrong_range_is_refused(value):
    with pytest.raises(ChannelSetupError, match="range"):
        parse_range(value)


def test_the_integration_time_is_a_number_of_cycles_or_the_default():
    assert [parse_nplc(v) for v in (None, "", 20, "100", "0,2", "max")] == [
        None, None, 20.0, 100.0, 0.2, "MAX"]  # fmt: skip
    for bad in ("long", 0, -2, False):
        with pytest.raises(ChannelSetupError, match="integration time"):
            parse_nplc(bad)


def test_the_input_impedance_is_auto_or_10m_or_not_set():
    assert [parse_impedance(v) for v in (None, "", "auto", "AUTO", "10M", "10m")] == [
        "", "", "auto", "auto", "10M", "10M"]  # fmt: skip
    with pytest.raises(ChannelSetupError, match="not one of auto, 10M"):
        parse_impedance("50 ohm")


def test_a_channel_with_nothing_set_is_not_configured():
    s = settings_of(channel(103))
    assert (s.number, s.name, s.range, s.nplc, s.zero, s.impedance) == (
        103,
        "ch103",
        "AUTO",
        None,
        False,
        "",
    )
    assert not s.configured and s.label == "103 (ch103)"
    assert settings_of({"enabled": True, "channel_id": "103", "name": "103"}).label == "103"
    for changes in ({"range": 10}, {"nplc": 20}, {"zero": True}, {"impedance": "auto"}):
        assert settings_of(channel(103, **changes)).configured, changes
    assert not settings_of(channel(103, range="AUTO", zero=False, impedance="")).configured


def test_the_function_comes_from_the_measurement_type_of_the_file():
    assert function_of("VOLT:DC").configure == "configure_dc_voltage"
    assert function_of("DC_V") is function_of("VOLT:DC") and function_of(None).name == "VOLT:DC"
    assert function_of("CURR:DC").nplc == "set_dc_current_nplc"
    assert function_of("RES").measure == "measure_resistance"
    assert function_of("FRES").range_call == "set_fresistance_range"
    assert function_of("VOLT:AC") is None and function_of("FREQ") is None  # no such settings
    assert function_of("TEMP").name == "TEMP"  # temperature has its own settings now
    assert function_of("VOLT:DC").impedance == "input_impedance_auto"
    assert function_of("CURR:DC").impedance is None


def test_a_wrong_value_names_its_channel():
    with pytest.raises(ChannelSetupError, match=r"channel 103 \(shunt\): the integration time"):
        settings_of(channel(103, name="shunt", nplc="long"))
    with pytest.raises(DataloggerSetupError, match="cannot tell its channel number"):
        settings_of({"enabled": True, "name": "x", "meas_type": "VOLT:DC"})


def test_the_settings_of_an_entry_are_those_of_its_enabled_channels_in_order():
    entry = {"channels": [
        channel(103, nplc=20), {**channel(101, zero=True), "enabled": False},
        channel(102, impedance="10M"), {**channel(104), "meas_type": "VOLT:AC"},
    ]}  # fmt: skip
    assert [(s.number, s.nplc, s.impedance) for s in settings_of_entry(entry)] == [
        (102, None, "10M"),
        (103, 20.0, ""),
    ]


def test_without_a_flat_list_the_channels_of_the_slots_are_used():
    entry = {"slots": [
        {"slot_number": 1, "module_id": "M", "channels": [
            {"enabled": True, "name": "a", "meas_type": "VOLT:DC", "nplc": 10},
            {"enabled": False, "name": "b", "meas_type": "VOLT:DC"},
            {"enabled": True, "name": "c", "meas_type": "VOLT:DC", "zero": True}]},
        {"slot_number": 2, "module_id": "", "channels": [{"enabled": True, "name": "d"}]},
        {"slot_number": 3, "module_id": "M", "channels": [{"enabled": True, "name": "e"}]},
    ]}  # fmt: skip
    found = settings_of_entry(entry)
    assert [(s.number, s.name, s.nplc, s.zero) for s in found] == [
        (101, "a", 10.0, False),
        (103, "c", None, True),
        (301, "e", None, False),
    ]


# ---- the calls ---------------------------------------------------------------------------------
def settings(*channels):
    return [settings_of(c) for c in channels]


def test_the_calls_are_grouped_and_start_with_the_configure_that_resets_the_rest():
    calls = config_calls(settings(
        channel(101, range=10, nplc=20, impedance="auto"),
        channel(102, range=10, nplc=20, impedance="auto"),
        channel(103, nplc=100), channel(121, meas_type="CURR:DC", range=0.1, nplc=2),
    ))  # fmt: skip
    assert calls == [
        ("configure_dc_voltage", {"range": 10.0, "resolution": "DEF", "channels": "101,102"}),
        ("set_voltage_nplc", {"plcs": 20.0, "channels": "101,102"}),
        ("input_impedance_auto", {"state": "ON", "channels": "101,102"}),
        ("configure_dc_voltage", {"range": "AUTO", "resolution": "DEF", "channels": "103"}),
        ("set_voltage_nplc", {"plcs": 100.0, "channels": "103"}),
        ("configure_dc_current", {"range": 0.1, "resolution": "DEF", "channels": "121"}),
        ("set_dc_current_nplc", {"plcs": 2.0, "channels": "121"}),
    ]
    fixed = config_calls(settings(channel(101, impedance="10M")))
    assert fixed[-1] == ("input_impedance_auto", {"state": "OFF", "channels": "101"})
    assert config_calls([]) == []


def test_the_model_decides_what_can_be_asked():
    have = {"set_voltage_nplc", "null_offset", "set_scale_state"}
    ok = settings(channel(101, nplc=20, zero=True))
    assert check_settings(ok, have.__contains__) == []
    problems = check_settings(settings(channel(102, impedance="auto")), have.__contains__)
    assert problems == ["channel 102 (ch102): this model has no input impedance setting"]
    problems = check_settings(settings(channel(103, nplc=5)), set().__contains__)
    assert "no integration time (set_voltage_nplc)" in problems[0]
    problems = check_settings(settings(channel(104, zero=True)), {"null_offset"}.__contains__)
    assert "cannot zero a channel (set_scale_state)" in problems[0]
    current = settings(channel(121, meas_type="CURR:DC", impedance="auto"))
    assert "only for DC voltage" in check_settings(current, lambda call: True)[0]


@pytest.mark.skipif(not os.path.isfile(LIBRARY), reason="the instrument library is not here")
def test_what_the_library_gives_a_model_to_choose_from():
    library = Library.load(LIBRARY)
    options = options_of(library.commands(library.resolve_model_id("34970A")))
    assert options.nplc == ["0.02", "0.2", "1", "2", "10", "20", "100", "200"]
    assert options.ranges["VOLT:DC"] == ["0.1", "1", "10", "100", "300"]
    assert options.ranges["CURR:DC"] == ["0.01", "0.1", "1"]
    assert options.zero and options.impedance
    daq = options_of(library.commands(library.resolve_model_id("DAQ970A")))  # its own lists
    plcs = ["0.001", "0.002", "0.006", "0.02", "0.06", "0.2", "1", "2", "10", "20", "100", "200"]
    assert daq.nplc == plcs
    assert daq.ranges["VOLT:DC"] == ["0.1", "1", "10", "100", "300"]
    assert daq.ranges["CURR:DC"] == ["1e-06", "1e-05", "0.0001", "0.001", "0.01", "0.1", "1"]
    assert daq.ranges["RES"][0] == "100" and daq.ranges["RES"][-1] == "1000000000"
    assert daq.zero and daq.impedance
    # a model of another kind has none of them
    empty = options_of(library.commands(library.resolve_model_id("DL_Agilent_3499A")))
    assert (empty.nplc, empty.ranges, empty.zero, empty.impedance) == ([], {}, False, False)
    assert options_of(None).zero is False


# ---- the handle: reading what was configured ---------------------------------------------------
def handle_for(sim, *channels):
    return ConfiguredHandle(sim, settings(*channels))


def test_a_configured_channel_is_read_from_the_scan_list_not_with_measure():
    sim = SimDatalogger(signals={101: 0.25, 102: 1.0})
    h = handle_for(sim, channel(101, nplc=20))
    assert h.call("measure_dc_voltage", channels="101", range="AUTO", resolution="DEF") == 0.25
    names = [n for n, _ in sim.log]
    assert "measure_dc_voltage" not in names and names[-2:] == ["select_channels", "read_scan"]
    assert sim.state(101)["nplc"] == 20.0  # what was configured is still there
    # a channel that asks for nothing is read as before, with MEASure
    assert h.call("measure_dc_voltage", channels="102", range="AUTO", resolution="DEF") == 1.0
    assert sim.log[-1][0] == "measure_dc_voltage"
    # several channels, or a call that is not a reading: through
    h.call("measure_dc_voltage", channels="101,102", range="AUTO", resolution="DEF")
    assert sim.log[-1] == ("measure_dc_voltage", {"channels": "101,102", "range": "AUTO",
                                                  "resolution": "DEF"})  # fmt: skip


def test_the_channels_are_configured_once_and_the_scan_list_only_when_it_changes():
    sim = SimDatalogger(signals={101: 1.0, 102: 2.0})
    h = handle_for(sim, channel(101, nplc=20), channel(102, nplc=20))
    for number in (101, 101, 102, 102, 101):
        h.call("measure_dc_voltage", channels=str(number))
    names = [n for n, _ in sim.log]
    assert names.count("configure_dc_voltage") == 1 and names.count("set_voltage_nplc") == 1
    assert names.count("select_channels") == 3 and names.count("read_scan") == 5
    h.call("select_channels", channels="101,102")  # somebody else changes the list: it is noticed
    h.call("measure_dc_voltage", channels="101")
    assert [n for n, _ in sim.log].count("select_channels") == 5


def test_the_integration_time_and_the_impedance_reach_the_instrument():
    sim = SimDatalogger(signals={101: 1.0}, source_ohm={101: 1e6})
    h = handle_for(sim, channel(101, nplc=100, impedance="auto", range=10))
    value = h.call("measure_dc_voltage", channels="101")
    state = sim.state(101)
    assert (state["nplc"], state["impedance_auto"], state["range"]) == (100.0, True, 10.0)
    assert value == pytest.approx(1.0, rel=1e-3)  # 10 GOhm: the 1 MOhm source is not loaded
    fixed = handle_for(SimDatalogger(signals={101: 1.0}, source_ohm={101: 1e6}),
                       channel(101, impedance="10M"))  # fmt: skip
    assert fixed.call("measure_dc_voltage", channels="101") == pytest.approx(10 / 11, rel=1e-3)


def test_what_a_model_cannot_do_is_said_and_not_silently_skipped():
    sim = SimDatalogger(without=("input_impedance_auto",))
    h = handle_for(sim, channel(101, impedance="auto"))
    with pytest.raises(ChannelSetupError, match="no input impedance setting"):
        h.call("measure_dc_voltage", channels="101")
    assert sim.log == []  # nothing was sent
    with pytest.raises(ChannelSetupError, match="no input impedance"):
        wrap_if_configured(sim, {"channels": [channel(101, impedance="auto")]})
    no_scan = SimDatalogger(without=("read_scan",))
    with pytest.raises(ChannelSetupError, match="reads no scan list"):
        wrap_if_configured(no_scan, {"channels": [channel(101, nplc=20)]})


def test_a_datalogger_with_no_settings_is_left_alone():
    sim = SimDatalogger()
    assert wrap_if_configured(sim, {"channels": [channel(101), channel(102, range="AUTO")]}) is sim
    assert wrap_if_configured(sim, {}) is sim
    wrapped = wrap_if_configured(sim, {"channels": [channel(101, nplc=20)]})
    assert isinstance(wrapped, ConfiguredHandle) and wrapped.wrapped is sim
    assert wrapped.name == "dlog" and wrapped.supports("null_offset")  # the plain handle's
    assert "ConfiguredHandle" in repr(wrapped) and "[101]" in repr(wrapped)


def test_the_connection_says_which_instrument_has_a_setting_it_cannot_use():
    from ola.connection import ConnectionProblem, ProjectConnector

    sim = SimDatalogger(without=("null_offset",))
    entry = {"channels": [channel(101, zero=True)]}
    with pytest.raises(ConnectionProblem, match="'dlog1': channel 101 .*cannot zero"):
        ProjectConnector._with_channel_settings("dlog1", entry, sim)
    assert ProjectConnector._with_channel_settings("dlog1", {}, sim) is sim  # no channels at all
    assert ProjectConnector._with_channel_settings("d", {"channels": [channel(105)]}, sim) is sim


# ---- the zero procedure ------------------------------------------------------------------------
def operator(runner, sim, answers=None, log=None):
    """What the person at the bench does: when asked to short a channel, short it; when asked to
    connect it back, connect it; then answer."""
    questions = []

    def work():
        done = set()
        while runner.state not in FINAL_STATES:
            for q in list(runner.pending_questions):
                if q["id"] in done:
                    continue
                done.add(q["id"])
                data = q.get("data") or {}
                questions.append((data.get("step"), data.get("channel"), q["text"]))
                choice = (answers or {}).get((data.get("step"), data.get("channel")), "continue")
                if data.get("step") == "short" and choice == "continue":
                    sim.short(data["channel"])  # the operator only shorts it if he goes on
                elif data.get("step") == "reconnect":
                    sim.connect(data["channel"])
                runner.answer(q["id"], choice)
            time.sleep(0.003)

    threading.Thread(target=work, daemon=True).start()
    return questions


METER = (Role("meter", "any"),)


def reader(readings, channels=(101,), after=None):
    """A measurement that reads each channel through ``measure_dc_voltage`` of its ``meter``."""

    def run(ctx):
        meter = ctx.instrument("meter")
        for n in channels:
            readings.setdefault(n, []).append(
                meter.call("measure_dc_voltage", channels=str(n), range="AUTO", resolution="DEF")
            )
        if after:
            after(ctx)

    return run


def run_with(sim, h, readings, **kw):
    measurement = Scripted(reader(readings, **kw), roles=METER)
    runner = Runner(measurement, {"meter": [h]})
    return runner, measurement


def test_the_zero_takes_out_the_offset_of_the_wiring():
    sim = SimDatalogger(signals={101: 0.050}, wiring_offset={101: 0.0004})
    h = handle_for(sim, channel(101, zero=True))
    readings = {}
    runner, _ = run_with(sim, h, readings)
    questions = operator(runner, sim)
    runner.start()
    assert runner.join(10) and runner.state is RunState.FINISHED, runner.error
    assert readings[101][0] == pytest.approx(0.050, abs=1e-12)  # the 0.4 mV of the wiring is gone
    assert [(step, n) for step, n, _t in questions] == [("short", 101), ("reconnect", 101)]
    assert "connect the two input terminals of the channel together" in questions[0][2]
    assert "connect its terminals back" in questions[1][2] and "offset" in questions[1][2]
    assert 101 not in sim.shorted
    # a reading with MEASure would have lost it: this is why a configured channel is not read so
    assert sim.call("measure_dc_voltage", channels="101", range="AUTO") == pytest.approx(0.0504)


def test_the_zero_goes_channel_by_channel_in_order():
    sim = SimDatalogger(signals={101: 0.1, 102: 0.2, 103: 0.3},
                        wiring_offset={101: 0.001, 102: -0.002, 103: 0.0})  # fmt: skip
    h = handle_for(sim, channel(103), channel(102, zero=True), channel(101, zero=True, nplc=20))
    readings = {}
    runner, _ = run_with(sim, h, readings, channels=(101, 102, 103))
    questions = operator(runner, sim)
    runner.start()
    assert runner.join(10) and runner.state is RunState.FINISHED, runner.error
    assert [(s, n) for s, n, _t in questions] == [
        ("short", 101), ("reconnect", 101), ("short", 102), ("reconnect", 102)]  # fmt: skip
    assert readings[101][0] == pytest.approx(0.1) and readings[102][0] == pytest.approx(0.2)
    assert readings[103][0] == pytest.approx(0.3)  # a channel that asks for nothing: as before
    assert sim.state(101)["nplc"] == 20.0 and sim.state(101)["scale"]  # kept by the zero
    assert not sim.state(103)["scale"]
    # the order of what the instrument was told: configure everything, then zero one by one
    kinds = [e.split()[0] for e in sim.events]
    before = kinds[: kinds.index("null")]
    assert before == ["configure", "configure", "nplc"]  # 101,102 and 103 (one call each group)
    assert [e for e in sim.events if e.startswith("null")] == ["null 101", "null 102"]


def test_the_log_says_the_offset_that_was_taken():
    sim = SimDatalogger(signals={101: 0.05}, wiring_offset={101: 0.0004})
    runner, _ = run_with(sim, handle_for(sim, channel(101, zero=True)), {})
    operator(runner, sim)
    runner.start()
    assert runner.join(10)
    logs = [e.data["message"] for e in runner.drain() if e.kind == "log"]
    assert any("channel 101 (ch101) zeroed (offset -0.0004)" in m for m in logs), logs


def test_a_channel_can_be_skipped_and_is_then_read_without_the_zero():
    sim = SimDatalogger(signals={101: 0.050, 102: 0.1}, wiring_offset={101: 0.0004, 102: 0.0004})
    h = handle_for(sim, channel(101, zero=True), channel(102, zero=True))
    readings = {}
    runner, _ = run_with(sim, h, readings, channels=(101, 102))
    questions = operator(runner, sim, {("short", 101): "skip_zero"})
    runner.start()
    assert runner.join(10) and runner.state is RunState.FINISHED, runner.error
    assert readings[101][0] == pytest.approx(0.0504)  # not zeroed
    assert readings[102][0] == pytest.approx(0.1)  # zeroed
    assert [(s, n) for s, n, _t in questions] == [
        ("short", 101),
        ("short", 102),
        ("reconnect", 102),
    ]
    logs = [e.data["message"] for e in runner.drain() if e.kind == "log"]
    assert any("channel 101 (ch101): not zeroed (skipped)" in m for m in logs)


def test_aborting_the_zero_stops_the_run_before_anything_is_measured():
    sim = SimDatalogger(signals={101: 0.05})
    readings = {}
    runner, measurement = run_with(sim, handle_for(sim, channel(101, zero=True)), readings)
    operator(runner, sim, {("short", 101): "abort"})
    runner.start()
    assert runner.join(10) and runner.state is RunState.STOPPED
    assert readings == {} and "run" not in measurement.order
    assert not [n for n, _ in sim.log if n == "null_offset"]
    sim2 = SimDatalogger(signals={101: 0.05}, wiring_offset={101: 0.0004})
    runner = run_with(sim2, handle_for(sim2, channel(101, zero=True)), {})[0]
    operator(runner, sim2, {("reconnect", 101): "abort"})  # stops at the second question
    runner.start()
    assert runner.join(10) and runner.state is RunState.STOPPED


def test_the_zero_waits_for_the_null_measurement_of_a_slow_channel(monkeypatch):
    monkeypatch.setattr(channel_setup, "ZERO_SETTLE_PLC_SECONDS", REAL_WAIT[0])
    monkeypatch.setattr(channel_setup, "ZERO_SETTLE_MARGIN_S", REAL_WAIT[1])
    assert zero_wait_s(settings_of(channel(101))) == pytest.approx(1.04)  # 1 cycle
    assert zero_wait_s(settings_of(channel(101, nplc=0.02))) == pytest.approx(1.0008)
    assert zero_wait_s(settings_of(channel(101, nplc=100))) == pytest.approx(5.0)
    assert zero_wait_s(settings_of(channel(101, nplc=200))) == pytest.approx(9.0)
    assert zero_wait_s(settings_of(channel(101, nplc="MAX"))) == pytest.approx(1.04)
    slept = []
    sim = SimDatalogger(signals={101: 0.05})
    h = handle_for(sim, channel(101, zero=True, nplc=20))

    class Ctx:
        def ask(self, text, choices, default=None, data=None):
            return "continue"

        def log(self, message, level="info"):
            pass

        def sleep(self, seconds):
            slept.append(seconds)

    h.prepare_run(Ctx())
    assert slept == [pytest.approx(1.8)]  # 20 cycles, twice, and a second


def test_a_script_that_never_prepared_gets_the_channels_configured_and_a_warning(caplog):
    sim = SimDatalogger(signals={101: 0.05}, wiring_offset={101: 0.0004})
    h = handle_for(sim, channel(101, zero=True, nplc=20))
    with caplog.at_level("WARNING", logger="ola.channel_setup"):
        value = h.call("measure_dc_voltage", channels="101")
        h.call("measure_dc_voltage", channels="101")
    assert value == pytest.approx(0.0504) and sim.state(101)["nplc"] == 20.0
    assert [r.message for r in caplog.records].count(
        "channel 101 (ch101) asks for the zero but the run did not do it"
    ) == 1


def test_the_runner_prepares_each_handle_once_and_before_the_measurement():
    sim = SimDatalogger(signals={101: 0.05, 102: 0.1})
    h = handle_for(sim, channel(101, nplc=20))
    order = []
    original = h.prepare_run

    def spy(ctx):
        order.append("prepare")
        original(ctx)

    h.prepare_run = spy
    roles = (Role("meter", "any"), Role("other", "any"), Role("plain", "any"))
    measurement = Scripted(
        lambda ctx: order.append("run"), setup=lambda ctx: order.append("setup"), roles=roles
    )
    runner = Runner(measurement, {"meter": [h], "other": [h], "plain": [sim]})
    runner.start()
    assert runner.join(10) and runner.state is RunState.FINISHED, runner.error
    assert order == ["prepare", "setup", "run"]  # once, though bound to two roles
    assert sim.state(101)["nplc"] == 20.0


def test_a_failure_to_prepare_fails_the_run_with_the_reason():
    sim = SimDatalogger(without=("set_voltage_nplc",))
    h = ConfiguredHandle(sim, settings(channel(101, nplc=20)))
    runner = Runner(Scripted(lambda ctx: None, roles=METER), {"meter": [h]})
    runner.start()
    assert runner.join(10) and runner.state is RunState.FAILED
    assert "no integration time" in runner.error["message"]


# ---- the simulator itself ----------------------------------------------------------------------
def test_the_simulated_datalogger_behaves_like_the_34970a_where_it_matters():
    sim = SimDatalogger(signals={101: 1.0}, wiring_offset={101: 0.01})
    sim.call("configure_dc_voltage", range="AUTO", resolution="DEF", channels="101")
    sim.call("set_voltage_nplc", plcs=20, channels="101")
    sim.short(101)  # the operator shorts the terminals, the null takes only the offset
    sim.call("null_offset", channels="101")
    sim.connect(101)
    sim.call("set_scale_state", state="ON", channels="101")
    sim.call("select_channels", channels="101")
    assert sim.call("read_scan") == [pytest.approx(1.0)] and sim.readback(
        "set_scale_offset", channels="101") == pytest.approx(-0.01)  # fmt: skip
    sim.call("configure_dc_voltage", range=10, resolution="DEF", channels="101")  # CONFigure resets
    state = sim.state(101)
    assert (state["nplc"], state["scale"], state["offset"], state["range"]) == (1.0, False, 0.0, 10)
    assert sim.call("read_scan") == [pytest.approx(1.01)]
    with pytest.raises(ValueError, match="unknown call"):
        sim.call("set_voltage_range", range=1, channels="101")
    with pytest.raises(ValueError, match="no readback"):
        sim.readback("set_voltage_nplc", channels="101")
    assert parse_channels("(@101:103, 105)") == [101, 102, 103, 105]
    assert "SimDatalogger" in repr(sim)


def test_channel_settings_hold_what_the_label_needs():
    s = ChannelSettings(101, "101", function_of("VOLT:DC"))
    assert s.label == "101" and not s.configured


# ---- temperature: probe, sensor and integration time -----------------------------------------
def temp(number=101, **settings):
    return {"enabled": True, "name": f"t{number}", "channel_id": str(number),
            "meas_type": "TEMP", **settings}  # fmt: skip


def test_temperature_has_an_integration_time_but_no_range_impedance_or_zero():
    f = function_of("TEMP")
    assert (f.configure, f.measure, f.nplc) == (
        "configure_temperature", "measure_temperature", "set_temperature_nplc",
    )  # fmt: skip
    assert f.range_call is None and f.impedance is None and f.zero is False
    assert channel_setup.MEASURE_CALLS["measure_temperature"] is f  # read from the scan list


def test_a_temperature_channel_needs_its_probe_and_sensor():
    with pytest.raises(ChannelSetupError, match="probe type"):
        settings_of(temp())
    s = settings_of(temp(probe_type="TCouple", sensor_type="K", nplc=20))
    assert (s.probe, s.sensor, s.nplc, s.range) == ("TCouple", "K", 20.0, "AUTO")
    assert s.configured


def test_a_temperature_zero_is_refused_and_the_editor_says_so():
    bad = temp(probe_type="RTD", sensor_type="85", zero=True)
    with pytest.raises(ChannelSetupError, match="zero"):
        settings_of(bad)
    assert any("zero" in p for p in channel_setup.channel_problems(bad))


def test_temperature_configures_with_probe_and_sensor_then_sets_the_integration_time():
    calls = config_calls(settings(
        temp(101, probe_type="TCouple", sensor_type="K", nplc=20),
        temp(102, probe_type="TCouple", sensor_type="K"),
    ))  # fmt: skip
    assert calls == [
        ("configure_temperature", {"probe_type": "TCouple", "type": "K", "resolution": "DEF",
                                   "channels": "101"}),
        ("set_temperature_nplc", {"plcs": 20.0, "channels": "101"}),
        ("configure_temperature", {"probe_type": "TCouple", "type": "K", "resolution": "DEF",
                                   "channels": "102"}),
    ]  # fmt: skip


def test_the_library_gives_the_probes_sensors_and_integration_times_of_a_model():
    library = Library.load(LIBRARY)
    options = options_of(library.commands(library.resolve_model_id("34970A")))
    assert options.probes["TCouple"] == ["B", "E", "J", "K", "N", "R", "S", "T"]
    assert options.probes["RTD"] == ["85", "91"]
    assert options.probes["THERmistor"] == ["2252", "5000", "10000"]
    assert options.temp_nplc == options.nplc
    # the DAQ970A has its own temperature integration times and sensor types
    daq = options_of(library.commands(library.resolve_model_id("DAQ970A")))
    assert daq.temp_nplc and "100" in daq.temp_nplc
    assert daq.probes["FTHermistor"] == ["2252", "5000", "10000"]
    assert daq.probes["TCouple"] == ["B", "E", "J", "K", "N", "R", "S", "T"]
