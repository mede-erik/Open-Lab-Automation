# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The four S-parameters with a VNA that drives port 1 only (the LiteVNA): the device is turned
round by the operator between the two directions (``manual_reversal``)."""

import time

import pytest

from ola.measurement import Stopped
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimAmplifier, SimVna
from ola.vna_common import acquire

SWEEP = {"start_hz": 700e6, "stop_hz": 1050e6, "points": 71, "power_dbm": -30}
ALL = ["S11", "S21", "S12", "S22"]


class OneWay:
    """A forward-only VNA in front of a two-port: it measures S11 and S21 of what is connected,
    and refuses S12 and S22. ``flipped`` is the device turned round (the operator did it)."""

    def __init__(self, device):
        self.device, self.flipped, self.name = device, False, "oneway"
        self.read = []

    def supports(self, name):
        return self.device.supports(name)

    def call(self, name, **args):
        if name == "read_sparameter":
            wanted = args["parameter"]
            if wanted in ("S12", "S22"):
                raise AssertionError(f"a forward-only VNA cannot measure {wanted}")
            self.read.append((wanted, self.flipped))
            if self.flipped:
                wanted = {"S11": "S22", "S21": "S12"}[wanted]
            return self.device.call(name, parameter=wanted)
        return self.device.call(name, **args)


class Ctx:
    """What ``acquire`` uses of a measurement context; answering a question turns the device."""

    def __init__(self, vna, answer="continue"):
        self.vna, self.answer, self.questions, self.messages = vna, answer, [], []

    def ask(self, text, choices, default=None, data=None):
        self.questions.append(dict(data or {}, text=text))
        if self.answer == "continue":
            self.vna.flipped = not self.vna.flipped
        return self.answer

    def log(self, text, level="info"):
        self.messages.append(text)

    def checkpoint(self):
        pass

    def progress(self, *args):
        pass


def test_the_reverse_parameters_are_read_with_the_device_turned_round():
    device = SimAmplifier()
    vna = OneWay(device)
    ctx = Ctx(vna)
    freq, data = acquire(ctx, vna, SWEEP, ALL, manual_reversal=True)
    _, truth = acquire(Ctx(None), device, SWEEP, ALL)
    for name in ALL:
        assert data[name] == pytest.approx(truth[name], abs=1e-12), name
    assert [q["text_key"] for q in ctx.questions] == ["run_q_reverse_device"]
    assert ctx.questions[0]["text_args"] == {"parameters": "S12, S22"}
    assert vna.flipped  # the device is left turned round
    assert [f for _, f in vna.read] == [False, False, True, True]
    assert any("manual reversal" in m for m in ctx.messages)


def test_without_reverse_parameters_nothing_is_asked():
    vna = OneWay(SimAmplifier())
    ctx = Ctx(vna)
    acquire(ctx, vna, SWEEP, ["S21", "S11"], manual_reversal=True)
    assert ctx.questions == [] and not vna.flipped


def test_only_the_reverse_ones_and_an_abort():
    vna = OneWay(SimAmplifier())
    _, data = acquire(Ctx(vna), vna, SWEEP, ["S22"], manual_reversal=True)
    assert set(data) == {"S22"} and vna.read == [("S11", True)]
    with pytest.raises(Stopped):
        acquire(Ctx(OneWay(SimAmplifier()), "abort"), OneWay(SimAmplifier()), SWEEP, ALL, 1, True,
                (), True)  # fmt: skip


def run_turning(registry, type_id, params, vna, timeout=30):
    """Run a measurement and answer its questions the way an operator would: turning the device
    when asked (a ``reverse`` question), then continuing."""
    runner = Runner(registry.create(type_id, params), {"vna": [vna]})
    runner.start()
    asked = []
    deadline = time.monotonic() + timeout
    while runner.state not in (RunState.FINISHED, RunState.FAILED, RunState.STOPPED):
        for question in runner.pending_questions:
            data = question.get("data") or {}
            asked.append(data.get("text_key") or data.get("kind"))
            if data.get("kind") == "reverse":
                vna.flipped = not vna.flipped
            runner.answer(question["id"], "continue")
        assert time.monotonic() < deadline, "the run did not end"
        time.sleep(0.01)
    runner.join(5)
    return runner, list(runner.drain()), asked


@pytest.fixture
def registry(tmp_path):
    return default_registry(user_dir=tmp_path / "none")


def test_the_amplifier_on_a_forward_only_vna_with_its_stability(registry):
    params = {"sweep": dict(SWEEP), "confirm_setup": False, "manual_reversal": True}
    vna = OneWay(SimAmplifier())
    runner, events, asked = run_turning(registry, "amplifier", params, vna)
    assert runner.state is RunState.FINISHED, runner.error
    reference = run_turning(registry, "amplifier", dict(params, manual_reversal=False),
                            SimAmplifier())[1]  # fmt: skip

    def row(evs):
        return next(e.data["values"] for e in evs if e.kind == "point"
                    and e.data["table"] == "points")  # fmt: skip

    for key in ("min_mu", "min_k", "worst_output_return_loss_db", "min_isolation_db"):
        assert row(events)[key] == pytest.approx(row(reference)[key], rel=1e-9), key
    assert asked == ["run_q_reverse_device"]


def test_the_compression_asks_to_put_the_amplifier_back(registry):
    comp = {"frequency_hz": 868e6, "start_dbm": -40, "stop_dbm": -20, "step_db": 5}
    params = {"sweep": dict(SWEEP), "confirm_setup": False, "manual_reversal": True,
              "compression": comp}  # fmt: skip
    vna = OneWay(SimAmplifier())
    runner, _, asked = run_turning(registry, "amplifier", params, vna)
    assert runner.state is RunState.FINISHED, runner.error
    assert asked == ["run_q_reverse_device", "run_q_forward_device"]
    assert not vna.flipped  # the compression was measured the right way round


def test_the_attenuator_reads_its_output_match_by_turning_round(registry):
    params = {
        "attenuator": {"label": "pad", "nominal_db": 6},
        "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 51},
        "confirm_setup": False,
        "manual_reversal": True,
    }
    vna = OneWay(SimVna(attenuator_db=6.0))
    runner, events, asked = run_turning(registry, "attenuator", params, vna)
    assert runner.state is RunState.FINISHED, runner.error
    row = next(e.data["values"] for e in events if e.kind == "point"
               and e.data["table"] == "points")  # fmt: skip
    assert "min_output_return_loss_db" in row and asked == ["run_q_reverse_device"]


def test_the_parameter_is_checked(registry):
    params = {"sweep": dict(SWEEP), "confirm_setup": False, "manual_reversal": "yes"}
    assert any(p.path == "manual_reversal" for p in registry.create("amplifier", params).check())
