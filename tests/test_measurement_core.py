"""Runner / context behaviour (no hardware, no registry)."""

import threading
import time

import pytest

from ola.measurement import MeasurementError, Role, Stopped
from ola.runner import Runner, RunState
from tests.measurement_helpers import FakeHandle, Scripted, run_to_end, wait_for


def kinds(runner):
    return [e.kind for e in runner.drain()]


def test_lifecycle_and_events():
    def run(ctx):
        ctx.log("hello")
        ctx.emit_point({"a": 1})
        ctx.progress(1, 2, "half")
        ctx.emit_point({"a": 2})

    m = Scripted(run)
    r = run_to_end(Runner(m, {}))
    assert r.state is RunState.FINISHED and r.error is None
    assert m.order == ["validate", "setup", "run", "teardown"]
    events = r.drain()
    assert [e.kind for e in events] == ["state", "log", "point", "progress", "point", "state"]
    assert [e.data["state"] for e in events if e.kind == "state"] == ["running", "finished"]
    points = [e.data for e in events if e.kind == "point"]
    assert [p["index"] for p in points] == [0, 1] and points[1]["values"] == {"a": 2}
    assert points[1]["elapsed_s"] >= points[0]["elapsed_s"] >= 0


def test_failure_in_run_still_tears_down():
    m = Scripted(lambda ctx: 1 / 0)
    r = run_to_end(Runner(m, {}))
    assert r.state is RunState.FAILED
    assert m.order[-1] == "teardown"
    assert r.error["phase"] == "run" and r.error["type"] == "ZeroDivisionError"
    assert "traceback" in r.error


def test_failure_in_setup_tears_down_and_skips_run():
    def bad_setup(ctx):
        raise RuntimeError("no instrument")

    m = Scripted(lambda ctx: None, setup=bad_setup)
    r = run_to_end(Runner(m, {}))
    assert r.state is RunState.FAILED and "run" not in m.order and m.order[-1] == "teardown"


def test_teardown_error_after_success_fails_the_run():
    def bad_teardown(ctx):
        raise RuntimeError("cannot switch off")

    r = run_to_end(Runner(Scripted(lambda ctx: None, teardown=bad_teardown), {}))
    assert r.state is RunState.FAILED and r.error["phase"] == "teardown"


def test_both_errors_are_kept():
    def bad_teardown(ctx):
        raise RuntimeError("second")

    r = run_to_end(Runner(Scripted(lambda ctx: 1 / 0, teardown=bad_teardown), {}))
    assert r.error["phase"] == "run" and r.error["also"][0]["phase"] == "teardown"


def test_error_code_is_reported():
    class Coded(Exception):
        code = "CALL-004"

    def run(ctx):
        raise Coded("step failed")

    r = run_to_end(Runner(Scripted(run), {}))
    assert r.error["code"] == "CALL-004"


def test_validation_errors_block_start_and_send_nothing():
    h = FakeHandle("dmm")
    m = Scripted(lambda ctx: h.call("x"), validate=lambda: ["interval too small", "no channels"])
    r = Runner(m, {})
    with pytest.raises(MeasurementError, match="interval too small; no channels"):
        r.start()
    assert r.state is RunState.IDLE and m.order == ["validate"] and h.calls == []


def test_roles_are_checked_before_start():
    roles = (
        Role("psu", "power_supply"),
        Role("dmm", "multimeter", required=False),
        Role("many", "any", multiple=True),
    )
    psu = FakeHandle("psu1")
    # missing required role
    with pytest.raises(MeasurementError, match="role 'psu'"):
        Runner(Scripted(lambda c: None, roles=roles), {}).start()
    # two instruments on a single role
    with pytest.raises(MeasurementError, match="accepts one instrument"):
        Runner(Scripted(lambda c: None, roles=roles), {"psu": [psu, FakeHandle("psu2")]}).start()
    # unknown role
    with pytest.raises(MeasurementError, match="unknown role 'oops'"):
        Runner(Scripted(lambda c: None, roles=roles), {"psu": psu, "oops": psu}).start()
    # fine: optional role omitted, multiple role with two
    ok = Scripted(lambda c: None, roles=roles)
    run_to_end(Runner(ok, {"psu": psu, "many": [FakeHandle("a"), FakeHandle("b")]}))
    assert ok.order == ["validate", "setup", "run", "teardown"]


def test_context_instrument_access():
    seen = {}

    def run(ctx):
        seen["one"] = ctx.instrument("psu").name
        seen["many"] = [h.name for h in ctx.instruments("many")]
        seen["none"] = ctx.instruments("absent")
        with pytest.raises(MeasurementError):
            ctx.instrument("many")
        with pytest.raises(MeasurementError):
            ctx.instrument("absent")

    roles = (Role("psu", "power_supply"), Role("many", "any", multiple=True))
    run_to_end(
        Runner(
            Scripted(run, roles=roles),
            {"psu": FakeHandle("p"), "many": [FakeHandle("a"), FakeHandle("b")]},
        )
    )
    assert seen == {"one": "p", "many": ["a", "b"], "none": []}


def test_stop_interrupts_a_long_sleep_and_tears_down():
    started = threading.Event()

    def run(ctx):
        started.set()
        ctx.sleep(30)

    m = Scripted(run)
    r = Runner(m, {})
    r.start()
    assert started.wait(2)
    t = time.perf_counter()
    r.stop()
    assert r.join(2)
    assert time.perf_counter() - t < 0.5
    assert r.state is RunState.STOPPED and m.order[-1] == "teardown" and r.error is None


def test_stop_during_checkpoint_loop():
    def run(ctx):
        while True:
            ctx.checkpoint()
            time.sleep(0.001)

    r = Runner(Scripted(run), {})
    r.start()
    time.sleep(0.05)
    r.stop()
    assert r.join(2) and r.state is RunState.STOPPED


def test_stop_then_function_returning_normally_is_stopped():
    release = threading.Event()

    def run(ctx):
        release.wait(2)  # does not look at the stop request, returns normally

    r = Runner(Scripted(run), {})
    r.start()
    r.stop()
    release.set()
    assert r.join(2) and r.state is RunState.STOPPED


def test_pause_blocks_and_resume_continues():
    counter = {"n": 0}

    def run(ctx):
        for _ in range(1000):
            ctx.checkpoint()
            counter["n"] += 1
            time.sleep(0.002)

    r = Runner(Scripted(run), {})
    r.start()
    assert wait_for(lambda: counter["n"] > 3)
    r.pause()
    assert r.state is RunState.PAUSED
    time.sleep(0.1)
    frozen = counter["n"]
    time.sleep(0.15)
    assert counter["n"] - frozen <= 1  # at most the iteration in flight
    r.resume()
    assert r.state is RunState.RUNNING
    assert wait_for(lambda: counter["n"] > frozen + 5)
    r.stop()
    assert r.join(2) and r.state is RunState.STOPPED


def test_stop_wakes_a_paused_run():
    def run(ctx):
        while True:
            ctx.checkpoint()
            time.sleep(0.001)

    r = Runner(Scripted(run), {})
    r.start()
    time.sleep(0.02)
    r.pause()
    time.sleep(0.1)
    r.stop()
    assert r.join(2) and r.state is RunState.STOPPED


def test_checkpoint_and_sleep_do_not_raise_in_teardown():
    done = {}

    def teardown(ctx):
        ctx.checkpoint()  # stop is set: must not raise here
        ctx.sleep(0.01)
        done["ok"] = True

    started = threading.Event()

    def run(ctx):
        started.set()
        ctx.sleep(30)

    r = Runner(Scripted(run, teardown=teardown), {})
    r.start()
    started.wait(2)
    r.stop()
    assert r.join(2) and done == {"ok": True} and r.state is RunState.STOPPED


def test_stopped_exception_is_not_an_error():
    def run(ctx):
        raise Stopped()

    r = run_to_end(Runner(Scripted(run), {}))
    assert r.state is RunState.STOPPED and r.error is None


def test_cannot_start_twice():
    r = Runner(Scripted(lambda c: None), {})
    run_to_end(r)
    with pytest.raises(MeasurementError, match="already started"):
        r.start()


def test_derived_values_are_merged():
    def run(ctx):
        ctx.emit_point({"pin": 10.0, "pout": 8.5})

    m = Scripted(run, derived=lambda v: {"eta": v["pout"] / v["pin"]})
    r = run_to_end(Runner(m, {}))
    point = [e for e in r.drain() if e.kind == "point"][0]
    assert point.data["values"] == {"pin": 10.0, "pout": 8.5, "eta": 0.85}


def test_derived_cannot_overwrite_measured_values_and_errors_do_not_kill_the_run():
    def run(ctx):
        ctx.emit_point({"a": 1})
        ctx.emit_point({"a": 2})

    clash = run_to_end(Runner(Scripted(run, derived=lambda v: {"a": 99, "b": 5}), {}))
    events = clash.drain()
    points = [e.data["values"] for e in events if e.kind == "point"]
    assert points == [{"a": 1, "b": 5}, {"a": 2, "b": 5}]
    assert any(e.kind == "log" and "ignored" in e.data["message"] for e in events)

    def boom(values):
        raise ValueError("bug in derived")

    bad = run_to_end(Runner(Scripted(run, derived=boom), {}))
    events = bad.drain()
    assert bad.state is RunState.FINISHED
    assert [e.data["values"] for e in events if e.kind == "point"] == [{"a": 1}, {"a": 2}]
    warnings = [e for e in events if e.kind == "log" and "derived() failed" in e.data["message"]]
    assert len(warnings) == 1  # reported once, not for every point


def test_listener_exception_does_not_stop_the_measurement():
    got = []

    def bad_listener(event):
        raise RuntimeError("UI crashed")

    def good_listener(event):
        got.append(event.kind)

    def run(ctx):
        ctx.emit_point({"a": 1})

    r = run_to_end(Runner(Scripted(run), {}, listeners=[bad_listener, good_listener]))
    assert r.state is RunState.FINISHED and "point" in got and got[-1] == "state"
    assert any(e.kind == "log" and e.data["level"] == "warning" for e in r.drain())


def test_trace_validation_and_complex():
    out = []

    def run(ctx):
        ctx.emit_trace("ch1", [0, 1, 2], [0.0, 1.0, 4.0], unit="V")
        ctx.emit_trace("s21", [1e6, 2e6], [1 + 2j, 0.5 - 1j], kind="complex")
        with pytest.raises(MeasurementError):
            ctx.emit_trace("bad", [0, 1], [1.0])
        with pytest.raises(MeasurementError):
            ctx.emit_trace("bad", [0], [1.0], kind="polar")

    r = run_to_end(Runner(Scripted(run), {}, listeners=[out.append]))
    traces = [e.data for e in out if e.kind == "trace"]
    assert traces[0]["y"] == [0.0, 1.0, 4.0] and traces[0]["meta"] == {"unit": "V"}
    assert traces[1]["y"] == [[1.0, 2.0], [0.5, -1.0]] and r.state is RunState.FINISHED


def test_sleep_rejects_bad_values():
    def run(ctx):
        for bad in (float("nan"), float("inf"), "1"):
            with pytest.raises(MeasurementError):
                ctx.sleep(bad)

    assert run_to_end(Runner(Scripted(run), {})).state is RunState.FINISHED
