"""Switching the outputs: keep on, off between points, always on (never switched off)."""

import copy

from ola.runner import RunState
from tests.efficiency_lab import answer_questions, build, calls, params
from tests.efficiency_params import IOUT, VAUX, VIN
from tests.measurement_helpers import run_to_end, wait_for


def switch(instrument, call):
    return {"instrument": instrument, "call": call}


def with_outputs(modes=("off_between_points", "off_between_points", "always_on"), **timing):
    """The standard parameters (list order: iout, vin, vaux) with output blocks.

    The microcontroller case of the user: the load and the input supply are switched off between
    points, the auxiliary supply is always on. Two points: iout 1 and 2 A at vin 12 V."""
    p = params(**timing)
    p["variables"][IOUT]["sweep"] = {"values": [1.0, 2.0]}
    p["variables"][VIN].pop("sweep")
    p["variables"][VIN]["value"] = 12
    p["variables"][VIN].pop("verify")
    p["variables"][IOUT]["output"] = {
        "on": switch("load1", "load_on"),
        "off": switch("load1", "load_off"),
        "mode": modes[0],
    }
    p["variables"][VIN]["output"] = {
        "on": switch("psu1", "output_on"),
        "off": switch("psu1", "output_off"),
        "mode": modes[1],
    }
    # the auxiliary supply HAS an off call too: the point is that it is never used
    p["variables"][VAUX]["output"] = {
        "on": switch("psu2", "output_on"),
        "off": switch("psu2", "output_off"),
        "mode": modes[2],
    }
    p["startup"], p["shutdown"] = [], []
    return p


def switching(lab):
    """Only the on/off calls of the outputs, in order, as 'instrument.call'."""
    return [
        f"{i}.{c}" for i, c, _ in lab.log if c in ("load_on", "load_off", "output_on", "output_off")
    ]


def test_the_microcontroller_case():
    runner, lab = build(with_outputs())
    run_to_end(runner)
    assert runner.state is RunState.FINISHED, runner.error
    assert switching(lab) == [
        # start: everything on, in the order of the list (iout, vin, vaux)
        "load1.load_on", "psu1.output_on", "psu2.output_on",
        # between the two points: load and input off in reverse list order; vaux is not touched
        "psu1.output_off", "load1.load_off",
        # second point: back on in list order
        "load1.load_on", "psu1.output_on",
        # end: off in reverse order; vaux is never switched off
        "psu1.output_off", "load1.load_off",
    ]  # fmt: skip
    assert not [c for c in lab.log if c[0] == "psu2" and c[1].endswith("off")]


def test_a_cycled_parameter_is_set_again_before_it_is_switched_on_again():
    runner, lab = build(with_outputs())
    run_to_end(runner)
    # vin is fixed at 12 V, but its output was cycled, so the setpoint is sent again
    assert len(calls(lab, "psu1", "set_voltage")) == 2
    assert len(calls(lab, "psu2", "set_voltage")) == 1  # vaux: always on, set only once
    first_on = [c[:2] for c in lab.log].index(("psu1", "output_on"))
    assert ("psu1", "set_voltage") in [c[:2] for c in lab.log[:first_on]]  # set, then on


def test_default_mode_keeps_the_outputs_on_between_points_and_off_at_the_end():
    p = with_outputs(modes=("keep_on", "keep_on", "keep_on"))
    runner, lab = build(p)
    run_to_end(runner)
    assert switching(lab) == [
        "load1.load_on", "psu1.output_on", "psu2.output_on",
        "psu2.output_off", "psu1.output_off", "load1.load_off",
    ]  # fmt: skip


def test_mode_defaults_to_keep_on():
    p = with_outputs()
    for v in (IOUT, VIN, VAUX):
        p["variables"][v]["output"].pop("mode")
    runner, lab = build(p)
    run_to_end(runner)
    assert switching(lab)[3:] == ["psu2.output_off", "psu1.output_off", "load1.load_off"]


def test_always_on_is_never_switched_off_after_an_error():
    lab_runner = build(with_outputs(settle_s=0))
    runner, lab = lab_runner
    lab.fail[("daq1", "read_ch")] = RuntimeError("logger lost")
    run_to_end(runner)
    assert runner.state is RunState.FAILED
    assert "psu1.output_off" in switching(lab) and "load1.load_off" in switching(lab)
    assert not [c for c in lab.log if c[0] == "psu2" and c[1].endswith("off")]


def test_always_on_is_never_switched_off_after_a_stop():
    runner, lab = build(with_outputs(settle_s=0.05))
    runner.start()
    assert wait_for(lambda: calls(lab, "psu2", "output_on"))
    runner.stop()
    assert runner.join(2) and runner.state is RunState.STOPPED
    assert "psu1.output_off" in switching(lab)
    assert not [c for c in lab.log if c[0] == "psu2" and c[1].endswith("off")]


def test_always_on_is_never_switched_off_when_the_user_aborts_a_mismatch():
    p = with_outputs()
    p["variables"][VIN]["verify"] = {"read": "daq", "tol_rel": 0.01}
    runner, lab = build(p)
    lab.daq_vin_error = 0.2
    given, thread = answer_questions(runner, ["abort"])
    run_to_end(runner)
    thread.join(2)
    assert runner.state is RunState.STOPPED
    assert "psu1.output_off" in switching(lab)
    assert not [c for c in lab.log if c[0] == "psu2" and c[1].endswith("off")]


def test_an_output_without_an_off_call_is_left_alone():
    p = with_outputs(modes=("keep_on", "keep_on", "keep_on"))
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
    p["startup"] = [switch("daq1", "arm")]
    p["shutdown"] = [switch("daq1", "disarm")]
    runner, lab = build(p)
    run_to_end(runner)
    names = [f"{i}.{c}" for i, c, _ in lab.log]
    assert names.index("psu2.output_on") < names.index("daq1.arm") < names.index("daq1.read_ch")
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
