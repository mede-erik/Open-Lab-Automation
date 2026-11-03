"""The efficiency measurement against a simulated converter, instruments and data logger."""

import threading
import time

import pytest

from ola.measurement import MeasurementError
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.runs import RunWriter, export_points_csv, read_run
from tests.efficiency_params import IOUT, VIN, good
from tests.measurement_helpers import run_to_end, wait_for

EFF = 0.9  # efficiency of the simulated converter
VOUT = 5.0


class Lab:
    """Psu + electronic load + data logger around an ideal converter of efficiency 90 %."""

    def __init__(self):
        self.vin = self.iout = self.vaux = 0.0
        self.log = []  # every call, in order: (instrument, call, args)
        self.daq_vin_error = 0.0  # the logger sees vin * (1 + error)
        self.daq_errors_left = None  # None: always; n: only the next n reads of channel 101
        self.fail = {}  # (instrument, call) -> exception to raise
        self.vin_noise = []  # values added to the logger's vin, one per read

    # converter
    @property
    def pout(self):
        return VOUT * self.iout

    @property
    def iin(self):
        return self.pout / EFF / self.vin if self.vin else 0.0

    # instruments
    def do(self, instrument, call, args):
        self.log.append((instrument, call, dict(args)))
        if (instrument, call) in self.fail:
            raise self.fail[(instrument, call)]
        if (instrument, call) == ("psu1", "set_voltage"):
            self.vin = args["value"]
        elif (instrument, call) == ("psu2", "set_voltage"):
            self.vaux = args["value"]
        elif (instrument, call) == ("load1", "set_current_level"):
            self.iout = args["value"]
        elif (instrument, call) == ("psu1", "read_voltage"):
            return self.vin
        elif (instrument, call) == ("load1", "read_current"):
            return self.iout
        elif (instrument, call) == ("daq1", "read_ch"):
            ch = args["channels"]
            if ch == "101":
                error = self.daq_vin_error
                if self.daq_errors_left is not None:
                    error = error if self.daq_errors_left > 0 else 0.0
                    self.daq_errors_left -= 1
                noise = self.vin_noise.pop(0) if self.vin_noise else 0.0
                return self.vin * (1 + error) + noise
            if ch == "102":
                return self.iin / 10  # shunt: 0.1 ohm -> scale 10 gives amperes
            if ch == "103":
                return VOUT if self.vin else 0.0
        return None


class Handle:
    def __init__(self, name, lab):
        self.name, self.lab = name, lab

    def call(self, name, **args):
        return self.lab.do(self.name, name, args)


def params(**timing):
    p = good()
    p["timing"] = {"settle_s": 0, "samples": 2, "interval_s": 0.01, **timing}
    return p


def build(p, lab=None, **runner_kw):
    lab = lab or Lab()
    registry = default_registry(user_dir="/nonexistent")
    m = registry.create("efficiency", p)
    handles = [Handle(n, lab) for n in ("psu1", "psu2", "daq1", "load1")]
    return Runner(m, {"instruments": handles}, **runner_kw), lab


def rows(runner, table="points"):
    return [e.data for e in runner.drain() if e.kind == "point" and e.data["table"] == table]


def calls(lab, instrument=None, call=None):
    return [
        c
        for c in lab.log
        if (instrument is None or c[0] == instrument) and (call is None or c[1] == call)
    ]


def answer_questions(runner, choices):
    """A stand-in for the pop-up: answers the questions with the given choices, in order."""
    given = []

    def worker():
        for choice in choices:
            if not wait_for(lambda: runner.pending_questions, timeout=5):
                return
            q = runner.pending_questions[0]
            given.append((q["data"].get("variable"), q["choices"], choice))
            runner.answer(q["id"], choice)
            wait_for(lambda: not runner.pending_questions, timeout=2)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return given, t


# ---- the normal run ----------------------------------------------------------------------------


def test_full_sweep_efficiency_and_order():
    runner, lab = build(params())
    run_to_end(runner)
    assert runner.state is RunState.FINISHED, runner.error
    points = rows(runner)
    assert len(points) == 9
    # iout is the first of the list: it runs fastest, vin (second) advances after a full sweep
    assert [(p["values"]["vin"], p["values"]["iout"]) for p in points[:4]] == [
        (9, 0.5),
        (9, 1.5),
        (9, 2.5),
        (12, 0.5),
    ]
    v = points[4]["values"]  # vin 12, iout 1.5
    assert v["vaux"] == 12 and v["n_samples"] == 2
    assert v["vin@daq"] == pytest.approx(12) and v["iin@daq"] == pytest.approx(5.0 * 1.5 / EFF / 12)
    assert v["pin"] == pytest.approx(12 * v["iin@daq"])
    assert v["pout"] == pytest.approx(5.0 * 1.5)
    assert v["efficiency"] == pytest.approx(90.0)
    assert all(p["values"]["efficiency"] == pytest.approx(90.0) for p in points)


def test_samples_are_stored_and_the_point_is_their_average():
    lab = Lab()
    lab.vin_noise = [0.2, -0.2] * 9  # the logger's vin alternates around the value
    p = params()
    p["variables"][VIN].pop("verify")  # (this test is about the average, not the check)
    runner, _ = build(p, lab)
    run_to_end(runner)
    events = runner.drain()
    samples = [
        e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "samples"
    ]
    pts = [e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "points"]
    assert len(samples) == 18 and [s["sample"] for s in samples[:4]] == [0, 1, 0, 1]
    assert samples[0]["vin@daq"] != samples[1]["vin@daq"]
    assert pts[0]["vin@daq"] == pytest.approx((samples[0]["vin@daq"] + samples[1]["vin@daq"]) / 2)
    assert pts[0]["vin@daq"] == pytest.approx(9.0)  # the average cancels the noise


def test_only_the_parameters_that_changed_are_set_again():
    runner, lab = build(params())
    run_to_end(runner)
    assert len(calls(lab, "psu1", "set_voltage")) == 3  # vin: 9, 12, 15
    assert len(calls(lab, "load1", "set_current_level")) == 9  # iout changes at every point
    assert len(calls(lab, "psu2", "set_voltage")) == 1  # vaux is fixed: set once


def test_setting_order_is_the_order_of_the_list_and_startup_comes_after_it():
    runner, lab = build(params())
    run_to_end(runner)
    first = [(i, c) for i, c, _ in lab.log[:5]]
    assert first == [
        ("load1", "set_current_level"),
        ("psu1", "set_voltage"),
        ("psu2", "set_voltage"),
        ("psu1", "output_on"),
        ("load1", "read_current"),
    ]
    assert lab.log[-1][:2] == ("psu1", "output_off")  # shutdown at the end


def test_moving_vin_first_changes_which_one_is_set_first_and_the_nesting():
    p = params()
    p["variables"][IOUT], p["variables"][VIN] = p["variables"][VIN], p["variables"][IOUT]
    runner, lab = build(p)
    run_to_end(runner)
    assert lab.log[0][:2] == ("psu1", "set_voltage")
    pts = rows(runner)
    assert [(x["values"]["iout"], x["values"]["vin"]) for x in pts[:4]] == [
        (0.5, 9),
        (0.5, 12),
        (0.5, 15),
        (1.5, 9),
    ]


def test_progress_and_timing():
    p = params(settle_s=0.05, samples=3, interval_s=0.05)
    p["variables"][IOUT]["sweep"] = {"values": [1.0]}
    p["variables"][VIN]["sweep"] = {"values": [12]}
    runner, _ = build(p)
    t = time.perf_counter()
    run_to_end(runner)
    assert 0.14 <= time.perf_counter() - t < 0.6  # settle 0.05 + 2 * 0.05
    progress = [e.data for e in runner.drain() if e.kind == "progress"]
    assert progress[-1]["done"] == 1 and progress[-1]["total"] == 1


# ---- numbers that cannot be computed -----------------------------------------------------------


def test_division_by_zero_gives_an_empty_value_and_the_measurement_goes_on():
    p = params()
    p["variables"][IOUT]["sweep"] = {"values": [0, 1.0]}  # iout = 0: pout = pin = 0
    p["variables"][VIN]["sweep"] = {"values": [12]}
    runner, _ = build(p)
    run_to_end(runner)
    pts = rows(runner)
    assert runner.state is RunState.FINISHED
    assert pts[0]["values"]["efficiency"] is None
    assert pts[1]["values"]["efficiency"] == pytest.approx(90.0)


# ---- verification: set value against the independent reading -----------------------------------


def faulty_lab():
    lab = Lab()
    lab.daq_vin_error = 0.20  # the logger sees 20 % more than what was set
    return lab


def test_a_mismatch_stops_and_asks_and_skip_goes_on():
    lab = faulty_lab()
    runner, _ = build(params(), lab)
    given, thread = answer_questions(runner, ["skip", "skip", "skip"])
    run_to_end(runner)
    thread.join(2)
    assert runner.state is RunState.FINISHED
    assert [g[0] for g in given] == ["vin", "vin", "vin"]  # asked once per vin value
    assert given[0][1] == ["retry", "abort", "skip"]
    events = runner.drain()
    question = [e.data for e in events if e.kind == "question"][0]
    assert "'vin' read by daq (10.8) differs from the set value (9) by 20.0%" in question["text"]
    assert question["data"]["error_rel"] == pytest.approx(0.2) and question["default"] == "abort"
    pts = [e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "points"]
    assert len(pts) == 9 and pts[0]["verify_skipped"] == "vin"  # the data says it was skipped


def test_retry_sets_everything_again_and_measures_the_point_again():
    lab = Lab()
    lab.daq_errors_left = 1  # only the very first reading of vin is wrong
    lab.daq_vin_error = 0.20
    p = params(samples=2)
    p["variables"][IOUT]["sweep"] = {"values": [1.0]}
    p["variables"][VIN]["sweep"] = {"values": [12]}
    runner, _ = build(p, lab)
    given, thread = answer_questions(runner, ["retry"])
    run_to_end(runner)
    thread.join(2)
    assert runner.state is RunState.FINISHED and [g[2] for g in given] == ["retry"]
    assert len(calls(lab, "psu1", "set_voltage")) == 2  # set again after the retry
    assert len(calls(lab, "load1", "set_current_level")) == 2
    events = runner.drain()
    samples = [
        e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "samples"
    ]
    assert [(s["attempt"], s["sample"]) for s in samples] == [(1, 0), (2, 0), (2, 1)]
    points = [e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "points"]
    assert len(points) == 1 and "verify_skipped" not in points[0]
    assert points[0]["vin@daq"] == pytest.approx(12.0)  # the retried data, not the bad one


def test_abort_ends_the_run_stopped_and_switches_the_outputs_off():
    runner, lab = build(params(), faulty_lab())
    given, thread = answer_questions(runner, ["abort"])
    run_to_end(runner)
    thread.join(2)
    assert runner.state is RunState.STOPPED and runner.error is None
    assert lab.log[-1][:2] == ("psu1", "output_off")
    assert rows(runner) == []  # nothing was published


def test_unattended_run_uses_the_given_answer():
    runner, _ = build(params(), faulty_lab(), unattended="skip")
    run_to_end(runner)
    assert runner.state is RunState.FINISHED and len(rows(runner)) == 9
    runner, _ = build(params(), faulty_lab(), unattended="abort")
    run_to_end(runner)
    assert runner.state is RunState.STOPPED


def test_on_fail_warn_only_logs_and_on_fail_stop_fails_the_run():
    p = params()
    p["variables"][VIN]["verify"]["on_fail"] = "warn"
    runner, _ = build(p, faulty_lab())
    run_to_end(runner)
    events = runner.drain()
    assert runner.state is RunState.FINISHED
    assert any(
        e.kind == "log" and e.data["level"] == "warning" and "differs" in e.data["message"]
        for e in events
    )
    assert not any(e.kind == "question" for e in events)
    p["variables"][VIN]["verify"]["on_fail"] = "stop"
    runner, lab = build(p, faulty_lab())
    run_to_end(runner)
    assert (
        runner.state is RunState.FAILED and "differs from the set value" in runner.error["message"]
    )
    assert lab.log[-1][:2] == ("psu1", "output_off")


def test_the_tolerance_is_absolute_plus_relative():
    p = params()
    p["variables"][VIN]["verify"] = {"read": "daq", "tol_rel": 0.0, "tol_abs": 2.0}
    lab = Lab()
    lab.daq_vin_error = 0.10  # +0.9 .. +1.5 V: inside 2 V
    runner, _ = build(p, lab)
    run_to_end(runner)
    assert runner.state is RunState.FINISHED
    assert not any(e.kind == "question" for e in runner.drain())


# ---- safety, stop, errors ----------------------------------------------------------------------


def test_stop_in_the_middle_switches_the_outputs_off():
    p = params(settle_s=0.05)
    runner, lab = build(p)
    runner.start()
    assert wait_for(lambda: calls(lab, "psu1", "output_on"))
    runner.stop()
    assert runner.join(2) and runner.state is RunState.STOPPED
    assert lab.log[-1][:2] == ("psu1", "output_off")
    assert len(rows(runner)) < 9


def test_all_shutdown_calls_are_made_even_if_one_fails():
    p = params()
    p["shutdown"] = [
        {"instrument": "load1", "call": "load_off"},
        {"instrument": "psu1", "call": "output_off"},
        {"instrument": "psu2", "call": "output_off"},
    ]
    lab = Lab()
    lab.fail[("load1", "load_off")] = RuntimeError("load does not answer")
    runner, _ = build(p, lab)
    run_to_end(runner)
    assert runner.state is RunState.FAILED and runner.error["phase"] == "teardown"
    assert [c[:2] for c in lab.log[-3:]] == [
        ("load1", "load_off"),
        ("psu1", "output_off"),
        ("psu2", "output_off"),
    ]


def test_an_unbound_instrument_is_found_before_anything_is_sent():
    lab = Lab()
    registry = default_registry(user_dir="/nonexistent")
    m = registry.create("efficiency", params())
    handles = [Handle(n, lab) for n in ("psu1", "daq1", "load1")]  # psu2 is missing
    runner = Runner(m, {"instruments": handles})
    run_to_end(runner)
    assert runner.state is RunState.FAILED and "psu2" in runner.error["message"]
    assert [c for c in lab.log if c[1] != "output_off"] == []


def test_invalid_parameters_stop_before_starting_and_say_where():
    p = params()
    p["derived"]["pin"] = "vin * iin"
    runner, lab = build(p)
    with pytest.raises(MeasurementError, match="derived.pin: 'iin' has no setpoint"):
        runner.start()
    assert lab.log == []


def test_a_reading_that_is_not_a_number_fails_with_a_clear_message():
    lab = Lab()
    original = lab.do
    lab.do = lambda i, c, a: "n/a" if (i, c) == ("daq1", "read_ch") else original(i, c, a)
    runner, _ = build(params(), lab)
    run_to_end(runner)
    assert runner.state is RunState.FAILED
    assert "expected a number, got 'n/a'" in runner.error["message"]


def test_a_failing_instrument_call_fails_the_run_and_keeps_the_error_code():
    class Coded(Exception):
        code = "CALL-004"

    lab = Lab()
    lab.fail[("psu1", "set_voltage")] = Coded("step failed")
    runner, _ = build(params(), lab)
    run_to_end(runner)
    assert runner.state is RunState.FAILED and runner.error["code"] == "CALL-004"


# ---- results on disk ---------------------------------------------------------------------------


def test_run_file_has_points_and_samples_and_exports_to_csv(tmp_path):
    runner, _ = build(params(), collect=False)
    writer = RunWriter(tmp_path / "eff.jsonl", RunWriter.header_for(runner))
    runner.add_listener(writer)
    run_to_end(runner)
    data = read_run(writer.path)
    assert data["header"]["measurement"] == "efficiency"
    assert len(data["points"]) == 9 and len(data["tables"]["samples"]) == 18
    assert export_points_csv(writer.path, tmp_path / "points.csv") == 9
    assert export_points_csv(writer.path, tmp_path / "samples.csv", table="samples") == 18
    header = open(tmp_path / "points.csv").readline().strip().split(",")
    assert "efficiency" in header and "vin@daq" in header and "iout" in header
