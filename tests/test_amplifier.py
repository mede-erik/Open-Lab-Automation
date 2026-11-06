"""RF amplifier: parameters and protection, gain, match, isolation, stability, compression."""

import copy

import pytest

from ola.form_model import load_form_spec
from ola.measurement import MeasurementError
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimAmplifier

PARAMS = {
    "device": {"label": "LNA #1"},
    "sweep": {
        "start_hz": 700e6,
        "stop_hz": 1050e6,
        "points": 351,
        "scale": "linear",
        "power_dbm": -30,
    },
    "frequencies_of_interest": [868e6],
    "confirm_setup": False,
}
COMPRESSION = {"frequency_hz": 868e6, "start_dbm": -40, "stop_dbm": -5, "step_db": 0.5}


def comp(**changes):
    """The compression parameters with some fields changed."""
    return {**COMPRESSION, **changes}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def params(**changes):
    p = copy.deepcopy(PARAMS)
    for key, value in changes.items():
        if key == "sweep":
            p["sweep"].update(value)
        else:
            p[key] = value
    return p


def run(registry, p, vna=None, **runner_kw):
    vna = vna or SimAmplifier()
    runner = Runner(registry.create("amplifier", p), {"vna": [vna]}, **runner_kw)
    runner.start()
    assert runner.join(30)
    return runner, vna


def results(runner):
    evs = runner.drain()
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    row = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    tables = {}
    for e in evs:
        if e.kind == "point":
            tables.setdefault(e.data["table"], []).append(e.data["values"])
    return traces, (row[0] if row else None), tables, evs


def problems(registry, p):
    return {x.path: x for x in registry.create("amplifier", p).check()}


# ---- the module and its parameters --------------------------------------------------------------
def test_the_module_is_found_with_an_editor(registry):
    info = registry.get("amplifier")
    assert info.extension == ".amp" and info.name == "RF amplifier"
    paths = {f.path.split(".")[0] for f in load_form_spec(info).fields()}
    assert set(info.params_schema) <= paths


def test_good_parameters_have_no_problems(registry):
    assert problems(registry, PARAMS) == {}
    assert problems(registry, params(compression=COMPRESSION, max_input_dbm=0)) == {}


@pytest.mark.parametrize(
    "changes,path,words",
    [
        ({"input_attenuation_db": -3}, "input_attenuation_db", "0 or more"),
        ({"max_input_dbm": "high"}, "max_input_dbm", "number"),
        ({"passband": {"from_hz": 900e6, "to_hz": 800e6}}, "passband", "from_hz below"),
        ({"passband": {"from_hz": 100e6, "to_hz": 800e6}}, "passband", "inside the sweep"),
        ({"gain_edge_db": 0}, "gain_edge_db", "above 0"),
        ({"compression": "yes"}, "compression", "must be an object"),
        ({"compression": comp(frequency_hz=5e9)}, "compression.frequency_hz", "inside"),
        ({"compression": comp(start_dbm="low")}, "compression.start_dbm", "dBm"),
        ({"compression": comp(stop_dbm=-50)}, "compression.stop_dbm", "above the start"),
        ({"compression": comp(step_db=0)}, "compression.step_db", "above 0"),
        ({"compression": comp(step_db=0.01)}, "compression.step_db", "too small"),
        ({"compression": comp(compression_db=0)}, "compression.compression_db", "above 0"),
        ({"limits": {"max": "x"}}, "limits", "must be a number"),
    ],
)  # fmt: skip
def test_wrong_parameters_say_where_and_what(registry, changes, path, words):
    found = problems(registry, params(**changes))
    assert path in found and words in found[path].message and found[path].severity == "error"


# ---- protection ---------------------------------------------------------------------------------
def test_no_source_power_is_a_warning_that_says_why(registry):
    p = params()
    del p["sweep"]["power_dbm"]
    found = problems(registry, p)
    assert (
        found["sweep.power_dbm"].severity == "warning"
        and "overdriven" in found["sweep.power_dbm"].message
    )
    assert registry.create("amplifier", p).validate() == []  # it can still run


def test_a_source_power_above_the_amplifier_limit_is_refused(registry):
    found = problems(registry, params(sweep={"power_dbm": -5}, max_input_dbm=-10))
    assert "above its maximum input" in found["sweep.power_dbm"].message
    # the attenuator is taken into account: -5 dBm at the source is -25 dBm at the amplifier
    assert (
        problems(
            registry, params(sweep={"power_dbm": -5}, max_input_dbm=-10, input_attenuation_db=20)
        )
        == {}
    )


def test_a_compression_test_that_would_overdrive_is_refused_before_anything_is_sent(registry):
    p = params(compression=COMPRESSION, max_input_dbm=-20)  # the test goes up to -5 dBm
    found = problems(registry, p)
    assert (
        "compression.stop_dbm" in found
        and "above its maximum input" in found["compression.stop_dbm"].message
    )
    vna = SimAmplifier()
    runner = Runner(registry.create("amplifier", p), {"vna": [vna]})
    with pytest.raises(MeasurementError, match="maximum input"):
        runner.start()
    assert vna.calls == []  # not a single call reached the instrument


def test_the_question_names_the_limits_and_the_attenuators(registry):
    runner, vna = run(registry, params(confirm_setup=True, max_input_dbm=-10), unattended="abort")
    q = [e.data for e in results(runner)[3] if e.kind == "question"][0]
    assert "attenuators" in q["text"] and "maximum input power of the VNA" in q["text"]
    assert "no more than -10 dBm" in q["text"] and vna.calls == []
    runner, _ = run(registry, params(confirm_setup=True), unattended="abort")
    assert (
        "damage the amplifier"
        in [e.data for e in results(runner)[3] if e.kind == "question"][0]["text"]
    )


# ---- gain, match, isolation ---------------------------------------------------------------------
def test_the_gain_the_band_and_the_return_loss_of_the_simulated_amplifier(registry):
    runner, vna = run(registry, PARAMS)
    assert runner.state is RunState.FINISHED, runner.error
    traces, row, tables, _ = results(runner)
    assert row["peak_gain_db"] == pytest.approx(20.0, abs=0.1)
    assert row["peak_at_hz"] == pytest.approx(868e6, abs=2e6)
    assert row["bandwidth_hz"] == pytest.approx(
        200e6, rel=0.03
    )  # the band of the simulated amplifier
    assert row["f_low_hz"] < 868e6 < row["f_high_hz"]
    assert row["gain_868MHz_db"] == pytest.approx(20.0, abs=0.1)
    assert row["worst_input_return_loss_db"] == pytest.approx(13.98, abs=0.05)  # |S11| = 0.2
    assert row["worst_output_return_loss_db"] == pytest.approx(16.48, abs=0.05)  # |S22| = 0.15
    assert row["min_isolation_db"] == pytest.approx(35.0, abs=0.05)
    assert row["device"] == "LNA #1" and len(tables["sweep"]) == 351
    assert [c[1]["parameter"] for c in vna.calls[1:]] == ["S21", "S11", "S12", "S22"]
    assert vna.calls[0][1]["power"] == -30  # the source power goes to the VNA


def test_the_passband_decides_where_flatness_and_match_are_judged(registry):
    whole = results(run(registry, PARAMS)[0])[1]
    narrow = results(run(registry, params(passband={"from_hz": 850e6, "to_hz": 886e6}))[0])[1]
    assert narrow["gain_flatness_db"] < whole["gain_flatness_db"] / 5
    assert narrow["gain_flatness_db"] < 0.5


def test_an_amplifier_whose_band_is_wider_than_the_sweep_says_so(registry):
    p = params(sweep={"start_hz": 840e6, "stop_hz": 900e6})
    runner, _ = run(registry, p)
    _, row, _, evs = results(runner)
    assert "bandwidth_hz" not in row
    assert any(
        "could not find" in e.data["message"] and e.data["level"] == "warning"
        for e in evs
        if e.kind == "log"
    )


# ---- stability ----------------------------------------------------------------------------------
def test_a_well_behaved_amplifier_is_unconditionally_stable(registry):
    _, row, _, evs = results(run(registry, PARAMS)[0])
    assert row["unconditionally_stable"] == "yes" and row["min_mu"] > 1 and row["min_k"] > 1
    assert "unstable_bands" not in row
    assert not any(
        "not unconditionally stable" in e.data["message"] for e in evs if e.kind == "log"
    )


def test_an_amplifier_that_could_oscillate_is_flagged_with_its_bands(registry):
    vna = SimAmplifier(s11_mag=1.1, s22_mag=1.1, isolation_db=6)
    runner, _ = run(registry, PARAMS, vna)
    assert runner.state is RunState.FINISHED  # a finding, not an error
    _, row, _, evs = results(runner)
    assert row["unconditionally_stable"] == "no" and row["min_mu"] < 1 and "unstable_bands" in row
    assert any(
        "could oscillate" in e.data["message"] and e.data["level"] == "warning"
        for e in evs
        if e.kind == "log"
    )


# ---- compression --------------------------------------------------------------------------------
def test_the_compression_point_is_where_the_simulated_amplifier_has_it(registry):
    runner, vna = run(registry, params(compression=COMPRESSION))
    assert runner.state is RunState.FINISHED, runner.error
    traces, row, tables, _ = results(runner)
    assert row["small_signal_gain_db"] == pytest.approx(20.0, abs=0.05)
    assert row["p1db_input_dbm"] == pytest.approx(vna.p1db_input_dbm, abs=0.15)
    assert row["p1db_output_dbm"] == pytest.approx(vna.p1db_output_dbm, abs=0.15)
    assert (
        row["gain_at_point_db"] == pytest.approx(19.0, abs=0.05)
        and row["compression_at_hz"] == 868e6
    )
    assert len(tables["compression"]) == 71 and tables["compression"][0]["pin_dbm"] == -40
    assert (
        traces["gain_vs_power_db"]["meta"]["x_unit"] == "dBm"
        and traces["gain_vs_power_db"]["meta"]["hidden"]
    )
    assert row["peak_gain_db"] == pytest.approx(
        20.0, abs=0.1
    )  # the sweep results are in the same row


def test_the_power_is_put_back_after_the_compression_test(registry):
    _, vna = run(registry, params(compression=COMPRESSION))
    name, args = vna.calls[-1]
    assert name == "set_sweep" and args["power"] == -30 and args["start_frequency"] == 700e6


def test_the_power_is_put_back_even_when_the_test_fails(registry):
    class Fails(SimAmplifier):
        def _read(self, parameter):
            if self.sweep.get("power", -30) > -35 and self.sweep["points"] == 3:
                raise RuntimeError("the VNA went away")
            return super()._read(parameter)

    runner, vna = run(registry, params(compression=COMPRESSION), Fails())
    assert runner.state is RunState.FAILED and "went away" in runner.error["message"]
    name, args = vna.calls[-1]
    assert name == "set_sweep" and args["power"] == -30  # back to the low power


def test_stopping_during_the_compression_test_also_restores_the_power(registry):
    import time

    class Slow(SimAmplifier):
        def _read(self, parameter):
            if self.sweep["points"] == 3:
                time.sleep(0.03)
            return super()._read(parameter)

    vna = Slow()
    runner = Runner(registry.create("amplifier", params(compression=COMPRESSION)), {"vna": [vna]})
    runner.start()
    time.sleep(0.4)
    runner.stop()
    assert runner.join(10) and runner.state is RunState.STOPPED
    name, args = vna.calls[-1]
    assert name == "set_sweep" and args["power"] == -30


def test_no_restore_when_there_was_no_compression_test(registry):
    _, vna = run(registry, PARAMS)
    assert [c[0] for c in vna.calls] == ["set_sweep", "read_sparameter", "read_sparameter",
                                         "read_sparameter", "read_sparameter"]  # fmt: skip


def test_the_attenuator_moves_the_power_axis(registry):
    plain = results(run(registry, params(compression=COMPRESSION))[0])[1]
    padded = results(run(registry, params(compression=COMPRESSION, input_attenuation_db=10))[0])[1]
    # same source powers; the report is at the amplifier input, which is 10 dB lower
    assert padded["p1db_input_dbm"] == pytest.approx(plain["p1db_input_dbm"] - 10, abs=1e-6)
    assert padded["p1db_output_dbm"] == pytest.approx(plain["p1db_output_dbm"] - 10, abs=1e-6)
    assert padded["small_signal_gain_db"] == pytest.approx(plain["small_signal_gain_db"])


def test_a_compression_that_is_not_reached_says_so_and_gives_no_point(registry):
    shallow = comp(stop_dbm=-30)  # still deep in the linear range
    runner, _ = run(registry, params(compression=shallow))
    _, row, _, evs = results(runner)
    assert "p1db_input_dbm" not in row and "peak_gain_db" in row
    assert any(
        "not reached" in e.data["message"] and "raise stop_dbm" in e.data["message"]
        for e in evs
        if e.kind == "log"
    )


def test_a_different_compression_level(registry):
    one = results(run(registry, params(compression=COMPRESSION))[0])[1]["p1db_input_dbm"]
    three = results(run(registry, params(compression=comp(compression_db=3)))[0])[1][
        "p1db_input_dbm"
    ]
    assert three > one + 3  # a deeper compression needs more power


# ---- limits and the view ------------------------------------------------------------------------
def test_a_gain_mask_passes_or_fails_and_is_drawn_on_the_db_view(registry):
    ok = results(
        run(registry, params(limits={"bands": [{"from": 820e6, "to": 920e6, "min": 15}]}))[0]
    )
    assert ok[1]["verdict"] == "PASS"
    assert ok[0]["S21"]["meta"]["limits"]["view"] == "magnitude_db"
    bad_runner, _ = run(
        registry, params(limits={"min": 18})
    )  # the gain falls off at the edges of the sweep
    assert bad_runner.state is RunState.FINISHED
    assert results(bad_runner)[1]["verdict"] == "FAIL"


def test_the_traces_s21_visible_and_the_rest_hidden(registry):
    traces, _, _, _ = results(run(registry, PARAMS)[0])
    assert "hidden" not in traces["S21"]["meta"]
    assert all(
        traces[n]["meta"]["hidden"] for n in ("S11", "S22", "S12", "stability_mu", "stability_k")
    )
