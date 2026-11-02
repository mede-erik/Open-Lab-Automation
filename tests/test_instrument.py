"""Step executor / driver dispatcher (ola/instrument.py), no hardware."""

import threading
import time
from types import SimpleNamespace

import pytest

from ola import _pyconn
from ola.call_errors import CallNotSupportedError, StepFailedError
from ola.errors import TransportClosed, TransportError, TransportTimeout
from ola.instrument import Aborted, Instrument
from ola.sim import SimTransport
from ola.steps import Step
from tests.fake_instrument import FakeTcpInstrument, line_server

try:
    import ola_native
except ImportError:  # pragma: no cover
    ola_native = None


def plan(*steps, call="test_call"):
    return {"call": call, "access": "scpi", "steps": list(steps)}


# ---- steps -------------------------------------------------------------------------------------


def test_step_validation():
    assert Step.from_dict({"op": "write", "text": "A"}).returns == "string"
    for bad in (
        {"op": "jump"},
        {"op": "write"},
        {"op": "write", "text": ""},
        {"op": "write", "text": "A", "ms": 5},
        {"op": "delay"},
        {"op": "delay", "ms": -1},
        {"op": "delay", "ms": 1, "text": "A"},
        {"op": "query", "text": "A?", "returns": "complex"},
        {"op": "write", "text": "A", "returns": "float"},
        {"op": "query", "text": "A?", "timeout_ms": 0},
        {"op": "write", "text": "A", "typo": 1},
        {"text": "A"},
    ):
        with pytest.raises(ValueError):
            Step.from_dict(bad)


def test_bad_plan_does_no_io():
    t = SimTransport()
    inst = Instrument("x", t)
    with pytest.raises(ValueError):
        inst.run(plan({"op": "write", "text": "A"}, {"op": "write", "text": "B", "typo": 1}))
    assert t.log == []  # validated up front: nothing was sent


# ---- results -----------------------------------------------------------------------------------


def test_order_and_raw_results():
    t = SimTransport(lambda c: "1.5" if c == "A?" else None)
    inst = Instrument("x", t)
    out = inst.run(
        plan(
            {"op": "write", "text": "SEL 1"},
            {"op": "query", "text": "A?", "returns": "float"},
            {"op": "delay", "ms": 1},
            {"op": "write", "text": "DONE"},
        )
    )
    assert t.log == ["SEL 1", "A?", "DONE"]
    assert out == [None, 1.5, None, None]


@pytest.mark.parametrize(
    "returns,reply,expected",
    [
        ("string", "hello", "hello"),
        ("float", "+1.5E+00", 1.5),
        ("int", "3", 3),
        ("int", "+1", 1),
        ("int", "2.0", 2),
    ],
)
def test_return_types(returns, reply, expected):
    inst = Instrument("x", SimTransport(lambda c: reply))
    assert inst.run(plan({"op": "query", "text": "Q?", "returns": returns})) == [expected]


def test_binary_return():
    blob = bytes(range(200))
    inst = Instrument("x", SimTransport(lambda c: blob))
    assert inst.run(plan({"op": "query", "text": "CURV?", "returns": "binary"})) == [blob]


@pytest.mark.parametrize("returns,reply", [("float", "abc"), ("int", "1.5")])
def test_unparsable_answer_is_step_failure(returns, reply):
    inst = Instrument("x", SimTransport(lambda c: reply))
    with pytest.raises(StepFailedError) as e:
        inst.run(plan({"op": "query", "text": "Q?", "returns": returns}))
    assert e.value.step_index == 0 and isinstance(e.value.cause, ValueError)


def test_plan_may_be_an_object():
    inst = Instrument("x", SimTransport(lambda c: "7"))
    p = SimpleNamespace(call="c", access="scpi", steps=[Step("query", text="Q?", returns="int")])
    assert inst.run(p) == [7]


# ---- failures and recovery ---------------------------------------------------------------------


def test_step_failure_reports_index_and_cause():
    t = SimTransport(lambda c: None)  # never answers
    inst = Instrument("x", t)
    with pytest.raises(StepFailedError) as e:
        inst.run(
            plan(
                {"op": "write", "text": "A"},
                {"op": "query", "text": "Q?"},
                {"op": "write", "text": "NEVER"},
                call="get_it",
            )
        )
    err = e.value
    assert err.code == "CALL-004" and err.step_index == 1 and err.call == "get_it"
    assert isinstance(err.cause, TransportTimeout) and err.cause.code == "TRN-003"
    assert t.log == ["A", "Q?"]  # stopped at the failing step


def test_next_call_discards_stale_input_after_failure():
    answers = {"n": 0}

    def responder(cmd):
        if cmd == "SLOW?":
            return None  # first call: no answer in time (timeout)
        answers["n"] += 1
        return "fresh"

    t = SimTransport(responder)
    inst = Instrument("x", t)
    with pytest.raises(StepFailedError):
        inst.run(plan({"op": "query", "text": "SLOW?"}))
    t._inbox.append(b"late answer\n")  # the late answer of the failed call arrives afterwards
    assert inst.run(plan({"op": "query", "text": "NEXT?"})) == ["fresh"]
    assert t.flush_count == 1


def test_no_flush_when_everything_is_fine():
    t = SimTransport(lambda c: "1")
    inst = Instrument("x", t)
    inst.run(plan({"op": "query", "text": "Q?"}))
    inst.run(plan({"op": "query", "text": "Q?"}))
    assert t.flush_count == 0


def test_closed_transport_is_step_failure():
    t = SimTransport(lambda c: "1")
    t.close()
    with pytest.raises(StepFailedError) as e:
        Instrument("x", t).run(plan({"op": "query", "text": "Q?"}))
    assert isinstance(e.value.cause, TransportClosed)


def test_no_transport():
    with pytest.raises(CallNotSupportedError):
        Instrument("x").run(plan({"op": "write", "text": "A"}))


# ---- concurrency -------------------------------------------------------------------------------


def make_channel_instrument():
    """VAL? returns the channel selected by the last SEL n: interleaved calls get it wrong."""
    state = {"ch": None}

    def responder(cmd):
        if cmd.startswith("SEL "):
            state["ch"] = cmd.split()[1]
            return None
        if cmd == "VAL?":
            return state["ch"]

    return Instrument("psu", SimTransport(responder))


def test_all_steps_of_a_call_are_atomic():
    inst = make_channel_instrument()
    wrong = []

    def worker(ch):
        for _ in range(100):
            out = inst.run(
                plan(
                    {"op": "write", "text": f"SEL {ch}"},
                    {"op": "delay", "ms": 0.2},
                    {"op": "query", "text": "VAL?"},
                )
            )
            if out[2] != str(ch):
                wrong.append((ch, out[2]))

    threads = [threading.Thread(target=worker, args=(c,)) for c in (1, 2, 3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert wrong == []


def test_delay_on_one_instrument_does_not_block_another():
    slow, fast = Instrument("slow", SimTransport()), Instrument("fast", SimTransport(lambda c: "1"))
    t = threading.Thread(target=lambda: slow.run(plan({"op": "delay", "ms": 400})))
    t.start()
    time.sleep(0.05)
    start = time.perf_counter()
    fast.run(plan({"op": "query", "text": "Q?"}))
    assert time.perf_counter() - start < 0.1
    t.join()


def test_abort_interrupts_a_delay():
    t = SimTransport(lambda c: "1")
    inst = Instrument("x", t)
    cancel = threading.Event()
    threading.Timer(0.05, cancel.set).start()
    start = time.perf_counter()
    with pytest.raises(Aborted):
        inst.run(
            plan(
                {"op": "write", "text": "A"},
                {"op": "delay", "ms": 5000},
                {"op": "write", "text": "NEVER"},
            ),
            cancel=cancel,
        )
    assert time.perf_counter() - start < 1.0
    assert t.log == ["A"]
    inst.run(plan({"op": "write", "text": "B"}))  # usable again, input flushed first
    assert t.flush_count == 1


def test_already_cancelled_call_sends_nothing():
    t = SimTransport()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Aborted):
        Instrument("x", t).run(plan({"op": "write", "text": "A"}), cancel=cancel)
    assert t.log == []


# ---- drivers -----------------------------------------------------------------------------------


class FakeDriver:
    def __init__(self):
        self.calls = []

    def call(self, function, args):
        self.calls.append((function, args))
        if function == "boom":
            raise RuntimeError("SDK error")
        return {"echo": args}


def test_driver_plan_dispatch():
    d = FakeDriver()
    inst = Instrument("ad2", driver=d)
    out = inst.run(
        {
            "call": "set_x",
            "access": "driver",
            "driver": {"function": "scope_set_range", "args": {"v": 5}},
        }
    )
    assert out == [{"echo": {"v": 5}}]
    assert d.calls == [("scope_set_range", {"v": 5})]


def test_driver_errors_and_missing_driver():
    d = FakeDriver()
    with pytest.raises(StepFailedError) as e:
        Instrument("ad2", driver=d).run(
            {"call": "c", "access": "driver", "driver": {"function": "boom", "args": {}}}
        )
    assert e.value.step_index == 0 and isinstance(e.value.cause, RuntimeError)
    with pytest.raises(CallNotSupportedError):
        Instrument("x").run(
            {"call": "c", "access": "driver", "driver": {"function": "f", "args": {}}}
        )


def test_unknown_access_rejected():
    with pytest.raises(ValueError):
        Instrument("x", SimTransport()).run({"call": "c", "access": "magic", "steps": []})


# ---- error codes -------------------------------------------------------------------------------


def test_trn_exceptions_have_a_code():
    assert TransportTimeout("[TRN-003] timeout").code == "TRN-003"
    assert TransportClosed("[TRN-004] closed").code == "TRN-004"
    assert TransportError("[TRN-001] x").code == "TRN-001"
    assert TransportError("no prefix").code == "TRN-002"


# ---- with the real transports ------------------------------------------------------------------

IMPLS = [pytest.param(_pyconn.PyConnection, id="python")]
if ola_native is not None:
    IMPLS.append(pytest.param(ola_native.Connection, id="native"))


@pytest.mark.parametrize("Conn", IMPLS)
def test_over_real_transport(Conn):
    state = {"ch": None}

    def reply(cmd):
        if cmd.startswith(b"INST:NSEL "):
            state["ch"] = cmd.split()[1].decode()
            return None
        if cmd == b"VOLT?":
            return f"ch{state['ch']}\n".encode()
        return None

    inst = FakeTcpInstrument(line_server(reply))
    c = Conn.open_tcp("127.0.0.1", inst.port, 1000)
    psu = Instrument("psu", c)
    out = psu.run(
        plan(
            {"op": "write", "text": "INST:NSEL 2"},
            {"op": "query", "text": "VOLT?", "timeout_ms": 500},
        )
    )
    assert out == [None, "ch2"]
    with pytest.raises(StepFailedError) as e:
        psu.run(plan({"op": "query", "text": "UNKNOWN?", "timeout_ms": 100}))
    assert e.value.cause.code == "TRN-003"
    # the connection is still usable afterwards (stale input flushed first)
    assert psu.run(
        plan({"op": "write", "text": "INST:NSEL 3"}, {"op": "query", "text": "VOLT?"})
    ) == [None, "ch3"]
