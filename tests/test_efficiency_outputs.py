"""Outputs of the efficiency measurement: power order, cooldown between sweeps, always on."""

import copy
import time

import pytest

from ola.runner import RunState
from tests.efficiency_lab import answer_questions, build, calls, params, rows
from tests.efficiency_params import IOUT, VAUX, VIN
from tests.measurement_helpers import run_to_end, wait_for


def call(instrument, name):
    return {"instrument": instrument, "call": name}


def with_outputs(
    cooldown_s=0.15, modes=("off_during_cooldown", "off_during_cooldown", "always_on")
):
    """The user's case. List order: iout (innermost sweep, 2 values), vin (outer sweep, 2 values),
    vaux (fixed, always on). 4 points, 2 sweeps, so 1 cooldown between them."""
    p = params(cooldown_s=cooldown_s)
    p["variables"][IOUT]["sweep"] = {"values": [1.0, 2.0]}
    p["variables"][VIN]["sweep"] = {"values": [9, 12]}
    p["variables"][VIN].pop("verify")
    p["variables"][IOUT]["output"] = {
        "on": call("load1", "load_on"),
        "off": call("load1", "load_off"),
        "mode": modes[0],
    }
    p["variables"][VIN]["output"] = {
        "on": call("psu1", "output_on"),
        "off": call("psu1", "output_off"),
        "mode": modes[1],
    }
    # the auxiliary supply HAS an off call too: the point is that it is never used
    p["variables"][VAUX]["output"] = {
        "on": call("psu2", "output_on"), "off": call("psu2", "output_off"),
        "state": call("psu2", "output_state_query"), "mode": modes[2]}  # fmt: skip
    p["startup"], p["shutdown"] = [], []
    return p


def switching(lab):
    """Only the on/off calls of the outputs, in order, as 'instrument.call'."""
    names = ("load_on", "load_off", "output_on", "output_off")
    return [f"{i}.{c}" for i, c, _ in lab.log if c in names]


def aux_off(lab):
    return [c for c in lab.log if c[0] == "psu2" and c[1].endswith("off")]


# ---- the cooldown between sweeps ---------------------------------------------------------------


def test_the_cooldown_case_switches_off_only_between_the_sweeps():
    runner, lab = build(with_outputs())
    run_to_end(runner)
    assert runner.state is RunState.FINISHED, runner.error
    assert switching(lab) == [
        # start: the always-on supply first (it was off), then the power order (iout, vin)
        "psu2.output_on", "load1.load_on", "psu1.output_on",
        # between the two sweeps: off in reverse power order; the auxiliary supply stays on
        "psu1.output_off", "load1.load_off",
        # after the cooldown: back on in power order
        "load1.load_on", "psu1.output_on",
        # end: off in reverse power order; the auxiliary supply is never switched off
        "psu1.output_off", "load1.load_off",
    ]  # fmt: skip
    assert aux_off(lab) == []


def test_nothing_is_switched_between_the_points_of_the_innermost_sweep():
    runner, lab = build(with_outputs())
    run_to_end(runner)
    names = [f"{i}.{c}" for i, c, _ in lab.log]
    reads = [k for k, n in enumerate(names) if n == "daq1.read_ch"]
    # the switching calls that happen while points are being measured: only the cooldown ones
    first_off = names.index("psu1.output_off")
    reads_before_cooldown = [k for k in reads if k < first_off]
    start, end = min(reads_before_cooldown), max(reads_before_cooldown)
    between = names[start:end]
    assert not [n for n in between if n.endswith(("_on", "_off"))]


def test_the_cooldown_lasts_the_time_asked():
    runner, lab = build(with_outputs(cooldown_s=0.4))
    run_to_end(runner)
    keys = [(i, c) for i, c, _ in lab.log]
    off = lab.stamps[keys.index(("psu1", "output_off"))]
    back = lab.stamps[len(keys) - 1 - keys[::-1].index(("psu1", "output_on"))]
    assert 0.4 <= back - off < 1.5
    assert any(e.kind == "log" and "cooldown of 0.4 s" in e.data["message"] for e in runner.drain())


def test_each_run_of_the_innermost_sweep_is_followed_by_a_cooldown():
    p = with_outputs()
    p["variables"][VAUX].pop("value")
    p["variables"][VAUX]["sweep"] = {"values": [12, 13]}  # a third swept parameter: 8 points
    runner, lab = build(p)
    run_to_end(runner)
    # innermost sweep = iout (2 points): 4 sweeps -> 3 cooldowns, whichever outer parameter moves
    assert switching(lab).count("psu1.output_off") == 3 + 1  # three cooldowns + the end
    assert len(rows(runner)) == 8
    p = with_outputs()
    runner, _ = build(p)
    run_to_end(runner)
    assert [x["values"]["sweep"] for x in rows(runner)] == [0, 0, 1, 1]


def test_a_single_point_per_sweep_means_a_cooldown_between_every_two_points():
    p = with_outputs()
    p["variables"][IOUT]["sweep"] = {"values": [1.0]}
    runner, lab = build(p)
    run_to_end(runner)
    assert switching(lab).count("load1.load_off") == 1 + 1  # 2 sweeps: one cooldown + the end


def test_without_cooldown_s_nothing_is_switched_between_points():
    runner, lab = build(with_outputs(cooldown_s=0))
    run_to_end(runner)
    assert switching(lab) == ["psu2.output_on", "load1.load_on", "psu1.output_on",
                              "psu1.output_off", "load1.load_off"]  # fmt: skip


def test_keep_on_outputs_stay_on_during_the_cooldown():
    runner, lab = build(with_outputs(modes=("keep_on", "keep_on", "always_on")))
    run_to_end(runner)
    assert switching(lab) == ["psu2.output_on", "load1.load_on", "psu1.output_on",
                              "psu1.output_off", "load1.load_off"]  # fmt: skip


def test_a_cycled_parameter_is_set_again_after_the_cooldown():
    p = with_outputs()
    p["variables"][VIN].pop("sweep")
    p["variables"][VIN]["value"] = 12  # fixed...
    p["variables"][VAUX].pop("value")
    p["variables"][VAUX]["sweep"] = {"values": [12, 13]}  # ...so the outer sweep is vaux
    runner, lab = build(p)
    run_to_end(runner)
    assert len(calls(lab, "psu1", "set_voltage")) == 2  # 12 V sent again after the cooldown
    assert len(calls(lab, "psu2", "set_voltage")) == 2  # vaux: 12, then 13


def test_stop_during_the_cooldown_ends_quickly_and_keeps_the_auxiliary_on():
    runner, lab = build(with_outputs(cooldown_s=30))
    runner.start()
    assert wait_for(lambda: "psu1.output_off" in switching(lab), timeout=5)
    t = time.perf_counter()
    runner.stop()
    assert runner.join(2) and time.perf_counter() - t < 1
    assert runner.state is RunState.STOPPED and aux_off(lab) == []
    assert lab.on["psu2"] is True and lab.on["psu1"] is False and lab.on["load1"] is False


# ---- the order of power-on ---------------------------------------------------------------------


def test_power_order_chosen_by_the_user_decides_on_and_off_order():
    p = with_outputs()
    p["power_order"] = ["vin", "iout"]  # the supply first, then the load
    runner, lab = build(p)
    run_to_end(runner)
    assert switching(lab) == [
        "psu2.output_on", "psu1.output_on", "load1.load_on",
        "load1.load_off", "psu1.output_off",
        "psu1.output_on", "load1.load_on",
        "load1.load_off", "psu1.output_off",
    ]  # fmt: skip


def test_always_on_outputs_are_switched_on_before_the_power_order_list():
    runner, lab = build(with_outputs())
    run_to_end(runner)
    assert switching(lab)[0] == "psu2.output_on"
    names = [f"{i}.{c}" for i, c, _ in lab.log]
    assert (
        names.index("psu2.output_on") < names.index("load1.load_on") < names.index("psu1.output_on")
    )


# ---- already on / off, always on ---------------------------------------------------------------


def test_an_always_on_output_that_is_already_on_is_left_alone():
    lab_runner = build(with_outputs())
    runner, lab = lab_runner
    lab.on["psu2"] = True  # switched on from the instrument's panel
    run_to_end(runner)
    assert "psu2.output_on" not in switching(lab)
    assert len(calls(lab, "psu2", "output_state_query")) == 1
    assert lab.on["psu2"] is True and aux_off(lab) == []
    assert any(e.kind == "log" and "already on" in e.data["message"] for e in runner.drain())


def test_an_always_on_output_that_is_off_is_switched_on_and_never_off_again():
    runner, lab = build(with_outputs())
    assert lab.on["psu2"] is False
    run_to_end(runner)
    assert switching(lab)[0] == "psu2.output_on"
    assert lab.on["psu2"] is True and aux_off(lab) == []  # still on after the measurement


@pytest.mark.parametrize(
    "answer,is_on",
    [
        (lambda on: on, None),
        (lambda on: 1 if on else 0, None),
        (lambda on: "ON" if on else "OFF", None),
        (lambda on: "1" if on else "0", None),
        (lambda on: 1.0 if on else 0.0, None),
    ],
)
def test_the_state_answer_can_be_a_bool_a_number_or_on_off_text(answer, is_on):
    for already_on in (True, False):
        runner, lab = build(with_outputs())
        lab.state_answer = answer
        lab.on["psu2"] = already_on
        run_to_end(runner)
        assert runner.state is RunState.FINISHED, runner.error
        assert ("psu2.output_on" in switching(lab)) is (not already_on)


def test_an_answer_that_cannot_be_understood_fails_before_anything_else_is_switched_on():
    runner, lab = build(with_outputs())
    lab.state_answer = lambda on: "maybe"
    run_to_end(runner)
    assert runner.state is RunState.FAILED
    assert "cannot tell if the output of 'vaux' is on" in runner.error["message"]
    assert "load1.load_on" not in switching(lab) and aux_off(lab) == []


def test_without_a_state_call_on_is_sent():
    p = with_outputs()
    p["variables"][VAUX]["output"].pop("state")
    runner, lab = build(p)
    lab.on["psu2"] = True
    run_to_end(runner)
    assert "psu2.output_on" in switching(lab) and aux_off(lab) == []


def test_a_managed_output_that_is_already_on_is_not_switched_on_again_but_is_switched_off_at_end():
    p = with_outputs(modes=("keep_on", "keep_on", "always_on"))
    p["variables"][VIN]["output"]["state"] = call("psu1", "output_state_query")
    runner, lab = build(p)
    lab.on["psu1"] = True
    run_to_end(runner)
    assert "psu1.output_on" not in switching(lab)
    assert switching(lab)[-2:] == ["psu1.output_off", "load1.load_off"]


# ---- the always-on output survives errors, stops and aborts ------------------------------------


def test_always_on_is_never_switched_off_after_an_error():
    runner, lab = build(with_outputs())
    lab.fail[("daq1", "read_ch")] = RuntimeError("logger lost")
    run_to_end(runner)
    assert runner.state is RunState.FAILED
    assert "psu1.output_off" in switching(lab) and "load1.load_off" in switching(lab)
    assert aux_off(lab) == [] and lab.on["psu2"] is True


def test_always_on_is_never_switched_off_after_a_stop():
    runner, lab = build(
        with_outputs(),
    )
    runner.start()
    assert wait_for(lambda: calls(lab, "psu2", "output_on"))
    runner.stop()
    assert runner.join(2) and runner.state is RunState.STOPPED
    assert "psu1.output_off" in switching(lab) and aux_off(lab) == []


def test_always_on_is_never_switched_off_when_the_user_aborts_a_mismatch():
    p = with_outputs()
    p["variables"][VIN]["verify"] = {"read": "daq", "tol_rel": 0.01}
    runner, lab = build(p)
    lab.daq_vin_error = 0.2
    given, thread = answer_questions(runner, ["abort"])
    run_to_end(runner)
    thread.join(2)
    assert runner.state is RunState.STOPPED
    assert "psu1.output_off" in switching(lab) and aux_off(lab) == []


# ---- the rest ----------------------------------------------------------------------------------


def test_an_output_without_an_off_call_is_left_alone_at_the_end():
    p = with_outputs(modes=("keep_on", "keep_on", "always_on"))
    p["variables"][IOUT]["output"].pop("off")
    runner, lab = build(p)
    run_to_end(runner)
    assert "load1.load_off" not in switching(lab) and "psu1.output_off" in switching(lab)


def test_no_output_blocks_means_the_program_switches_nothing():
    p = with_outputs()
    for v in (IOUT, VIN, VAUX):
        p["variables"][v].pop("output")
    runner, lab = build(p)
    run_to_end(runner)
    assert runner.state is RunState.FINISHED and switching(lab) == []


def test_extra_startup_and_shutdown_calls_still_work_around_the_outputs():
    p = with_outputs()
    p["startup"] = [call("daq1", "arm")]
    p["shutdown"] = [call("daq1", "disarm")]
    runner, lab = build(p)
    run_to_end(runner)
    names = [f"{i}.{c}" for i, c, _ in lab.log]
    assert names.index("psu1.output_on") < names.index("daq1.arm") < names.index("daq1.read_ch")
    assert names.index("daq1.disarm") < len(names) - 2 and names[-2:] == [
        "psu1.output_off",
        "load1.load_off",
    ]


def test_params_are_not_modified_by_the_run():
    p = with_outputs()
    before = copy.deepcopy(p)
    runner, _ = build(p)
    run_to_end(runner)
    assert p == before


def test_an_always_on_output_with_only_an_off_call_is_still_never_switched_off():
    """Not in the power order (no 'on' call), but it has an 'off' call: still never used."""
    p = with_outputs()
    p["variables"][VAUX]["output"].pop("on")
    runner, lab = build(p)
    lab.on["psu2"] = True
    run_to_end(runner)
    assert runner.state is RunState.FINISHED, runner.error
    assert aux_off(lab) == [] and lab.on["psu2"] is True


def test_an_always_on_output_with_only_an_off_call_survives_an_error():
    p = with_outputs()
    p["variables"][VAUX]["output"].pop("on")
    runner, lab = build(p)
    lab.on["psu2"] = True
    lab.fail[("daq1", "read_ch")] = RuntimeError("logger lost")
    run_to_end(runner)
    assert runner.state is RunState.FAILED and aux_off(lab) == []
    assert "psu1.output_off" in switching(lab)  # the managed outputs are switched off
