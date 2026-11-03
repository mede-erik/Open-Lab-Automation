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


# ---- stop event shared with the instrument handles ----------------------------------------------


def test_ctx_cancel_event_is_the_runner_stop_event():
    seen = {}

    def run(ctx):
        seen["same"] = ctx.cancel_event is runner.stop_event

    runner = Runner(Scripted(run), {})
    run_to_end(runner)
    assert seen == {"same": True}


def test_external_stop_event_is_used():
    cancel = threading.Event()
    started = threading.Event()

    def run(ctx):
        started.set()
        ctx.sleep(30)

    runner = Runner(Scripted(run), {}, stop_event=cancel)
    assert runner.stop_event is cancel
    runner.start()
    assert started.wait(2)
    cancel.set()  # stopping through the shared event (not through runner.stop()) also works
    assert runner.join(2) and runner.state is RunState.STOPPED


def test_stop_interrupts_a_wait_inside_an_instrument_call():
    """A real Instrument call with a long delay step, cancelled through the shared event:
    the run ends STOPPED (not FAILED) and teardown still runs."""
    from ola.instrument import Instrument
    from ola.sim import SimTransport

    cancel = threading.Event()
    inst = Instrument("psu", SimTransport())
    in_call = threading.Event()

    class Handle:
        name = "psu"

        def call(self, name, **args):
            in_call.set()
            plan = {
                "call": name,
                "access": "scpi",
                "steps": [
                    {"op": "write", "text": "OUTP ON"},
                    {"op": "delay", "ms": 30000},
                    {"op": "write", "text": "NEVER"},
                ],
            }
            return inst.run(plan, cancel=cancel)

    m = Scripted(
        lambda ctx: ctx.instrument("psu").call("settle"), roles=(Role("psu", "power_supply"),)
    )
    runner = Runner(m, {"psu": Handle()}, stop_event=cancel)
    runner.start()
    assert in_call.wait(2)
    t = time.perf_counter()
    runner.stop()
    assert runner.join(2)
    assert time.perf_counter() - t < 0.5
    assert runner.state is RunState.STOPPED and runner.error is None
    assert m.order[-1] == "teardown" and inst.transport.log == ["OUTP ON"]


# ---- several tables of rows ---------------------------------------------------------------------


def test_points_can_go_to_other_tables_without_derived():
    def run(ctx):
        ctx.emit_point({"v": 1})
        ctx.emit_point({"v": 1, "k": 0}, table="samples")
        ctx.emit_point({"v": 1, "k": 1}, table="samples")
        ctx.emit_point({"v": 2})
        with pytest.raises(MeasurementError):
            ctx.emit_point({"v": 3}, table="")

    m = Scripted(run, derived=lambda v: {"double": v["v"] * 2})
    r = run_to_end(Runner(m, {}))
    rows = [e.data for e in r.drain() if e.kind == "point"]
    assert [(x["table"], x["index"]) for x in rows] == [
        ("points", 0),
        ("samples", 0),
        ("samples", 1),
        ("points", 1),
    ]
    assert rows[0]["values"] == {"v": 1, "double": 2}  # derived applied to "points"
    assert rows[1]["values"] == {"v": 1, "k": 0}  # and not to the other tables


# ---- asking the user (the pop-up with retry / abort / skip) ------------------------------------


def question_ids(runner):
    return [q["id"] for q in runner.pending_questions]


def test_a_measurement_can_stop_and_ask_and_continue_with_the_answer():
    got = {}

    def run(ctx):
        got["choice"] = ctx.ask(
            "vin differs by 20%", ["retry", "abort", "skip"], default="abort", data={"error": 0.2}
        )
        ctx.emit_point({"after": 1})

    m = Scripted(run)
    r = Runner(m, {})
    r.start()
    assert wait_for(lambda: question_ids(r))
    assert r.state is RunState.WAITING  # visible to the interface
    q = r.pending_questions[0]
    assert q["text"] == "vin differs by 20%" and q["choices"] == ["retry", "abort", "skip"]
    assert q["default"] == "abort" and q["data"] == {"error": 0.2}
    r.answer(q["id"], "skip")
    assert r.join(2)
    assert got == {"choice": "skip"} and r.state is RunState.FINISHED
    events = r.drain()
    kinds_ = [e.kind for e in events]
    assert kinds_.index("question") < kinds_.index("answered") < kinds_.index("point")
    answered = [e.data for e in events if e.kind == "answered"][0]
    assert answered == {"id": q["id"], "choice": "skip", "auto": False}
    states = [e.data["state"] for e in events if e.kind == "state"]
    assert states == ["running", "waiting", "running", "finished"]
    assert r.pending_questions == []


def test_default_choice_is_the_first_one():
    got = {}
    r = Runner(Scripted(lambda ctx: got.update(c=ctx.ask("q", ["a", "b"]))), {}, unattended="zzz")
    run_to_end(r)
    assert got == {"c": "a"}


def test_unattended_runs_answer_at_once_with_the_given_choice_or_the_default():
    got = []

    def run(ctx):
        got.append(ctx.ask("q1", ["retry", "abort", "skip"], default="abort"))
        got.append(ctx.ask("q2", ["yes", "no"], default="no"))  # "skip" is not offered here

    r = run_to_end(Runner(Scripted(run), {}, unattended="skip"))
    assert got == ["skip", "no"] and r.state is RunState.FINISHED
    events = r.drain()
    assert [e.data["auto"] for e in events if e.kind == "answered"] == [True, True]


def test_stop_while_waiting_ends_the_run_and_still_tears_down():
    m = Scripted(lambda ctx: ctx.ask("q", ["retry", "abort"]))
    r = Runner(m, {})
    r.start()
    assert wait_for(lambda: question_ids(r))
    t = time.perf_counter()
    r.stop()
    assert r.join(2) and time.perf_counter() - t < 0.5
    assert r.state is RunState.STOPPED and m.order[-1] == "teardown"
    assert r.pending_questions == []


def test_invalid_answers_are_refused_and_the_question_stays_open():
    r = Runner(Scripted(lambda ctx: ctx.ask("q", ["retry", "abort"])), {})
    r.start()
    assert wait_for(lambda: question_ids(r))
    qid = question_ids(r)[0]
    with pytest.raises(ValueError, match="not one of the choices"):
        r.answer(qid, "explode")
    with pytest.raises(MeasurementError, match="no pending question"):
        r.answer("nope", "retry")
    assert question_ids(r) == [qid]  # still waiting
    r.answer(qid, "retry")
    assert r.join(2) and r.state is RunState.FINISHED
    with pytest.raises(MeasurementError, match="no pending question"):
        r.answer(qid, "retry")  # a second answer is too late


@pytest.mark.parametrize(
    "choices,default",
    [
        ([], None),
        (["a", "a"], None),
        (["a", ""], None),
        (["a", 3], None),
        (["a", "b"], "c"),
    ],
)
def test_ask_validates_its_arguments(choices, default):
    seen = {}

    def run(ctx):
        try:
            ctx.ask("q", choices, default=default)
        except MeasurementError as exc:
            seen["error"] = str(exc)

    run_to_end(Runner(Scripted(run), {}, unattended="a"))
    assert "error" in seen


def test_the_run_file_keeps_the_question_and_the_answer(tmp_path):
    from ola.runs import RunWriter, read_run

    m = Scripted(lambda ctx: ctx.ask("vin is 20% off", ["retry", "abort", "skip"], "abort"))
    runner = Runner(m, {}, collect=False, unattended="skip", run_id="q1")
    writer = RunWriter(tmp_path / "run.jsonl", RunWriter.header_for(runner))
    runner.add_listener(writer)
    run_to_end(runner)
    data = read_run(writer.path)
    assert [x["kind"] for x in data["questions"]] == ["question", "answered"]
    assert data["questions"][0]["text"] == "vin is 20% off"
    assert data["questions"][1]["choice"] == "skip"
