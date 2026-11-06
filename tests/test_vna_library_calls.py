"""The measurements on a VNA that speaks the library's category (set_frequency_sweep,
run_sweep, read_sparameters) or the simple calls: the same results."""

import copy
import os

import pytest

from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimAmplifier, SimVna
from ola.vna_common import can_set_power, sweep_notes, uses_library_calls

SWEEP = {"start_hz": 800e6, "stop_hz": 940e6, "points": 71, "scale": "linear"}
CASES = {
    "cable": ({"sweep": {**SWEEP}, "cable": {"label": "c", "length_m": 1.0}}, {}),
    "return_loss": ({"sweep": {**SWEEP}, "device": {"label": "d"}}, {"termination": "antenna"}),
    "antenna": ({"sweep": {**SWEEP}, "device": {"label": "a"}}, {"termination": "antenna"}),
    "filter": (
        {"sweep": {**SWEEP}, "filter": {"type": "bandpass"}, "also_s11": True},
        {"filter_type": "bandpass", "filter_f0_hz": 868e6, "filter_bw_hz": 40e6},
    ),
    "attenuator": (
        {"sweep": {**SWEEP}, "attenuator": {"label": "p", "nominal_db": 10, "tolerance_db": 1}},
        {"attenuator_db": 10.0},
    ),
    "amplifier": (
        {"sweep": {**SWEEP, "start_hz": 600e6, "stop_hz": 1.1e9}, "device": {"label": "lna"}},
        {"cls": SimAmplifier},
    ),
}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def run(registry, module, params, **sim):
    p = copy.deepcopy(params)
    p["confirm_setup"] = False
    sim = dict(sim)
    vna = sim.pop("cls", SimVna)(**sim)
    runner = Runner(registry.create(module, p), {"vna": [vna]})
    runner.start()
    assert runner.join(60)
    evs = runner.drain()
    rows = [e.data["values"] for e in evs if e.kind == "point" and e.data["table"] == "points"]
    logs = [(e.data["level"], e.data["message"]) for e in evs if e.kind == "log"]
    traces = {e.data["name"]: e.data for e in evs if e.kind == "trace"}
    return runner, vna, (rows[0] if rows else None), logs, traces


# ---- which calls ------------------------------------------------------------------------------
def test_the_instrument_decides_which_calls_are_used():
    assert not uses_library_calls(SimVna())
    assert uses_library_calls(SimVna(library_calls=True))
    assert not uses_library_calls(object())  # a handle without supports(): the simple calls

    class Old:  # the first draft of the category, with select_sparameters and no read list
        def supports(self, name):
            return name in ("set_frequency_sweep", "select_sparameters", "run_sweep")

    assert not uses_library_calls(Old())
    assert can_set_power(SimVna())  # the simple calls set the power with the sweep
    assert can_set_power(SimVna(library_calls=True))
    assert not can_set_power(SimVna(library_calls=True, library_extras=False))  # a LiteVNA


@pytest.mark.parametrize("module", sorted(CASES))
def test_a_measurement_gives_the_same_numbers_with_either_set_of_calls(registry, module):
    params, sim = CASES[module]
    simple = run(registry, module, params, **sim)
    library = run(registry, module, params, library_calls=True, **sim)
    assert simple[0].state is RunState.FINISHED, simple[0].error
    assert library[0].state is RunState.FINISHED, library[0].error
    a, b = simple[2], library[2]
    assert set(a) == set(b)
    for key, value in a.items():
        if isinstance(value, float):
            assert b[key] == pytest.approx(value, rel=1e-9, abs=1e-12), (module, key)
        else:
            assert b[key] == value, (module, key)
    assert not any(lv == "warning" for lv, _ in library[3])  # nothing it cannot do was asked


# ---- the calls that are sent ------------------------------------------------------------------
def test_the_library_calls_are_sent_in_order_and_once_per_sweep(registry):
    params, sim = CASES["filter"]
    p = {**params, "averages": 3}
    _, vna, _, _, _ = run(registry, "filter", p, library_calls=True, **sim)
    names = [n for n, _ in vna.calls]
    assert names == [
        "set_frequency_sweep",
        "run_sweep", "read_sparameters", "run_sweep", "read_sparameters",
        "run_sweep", "read_sparameters",
    ]  # fmt: skip
    assert vna.calls[0][1] == {"start_frequency": 800e6, "stop_frequency": 940e6, "points": 71}
    assert vna.calls[2][1] == {"sparameters": ["S21", "S11"]}  # the list goes with the read
    assert "select_sparameters" not in names  # the library has no such call


def test_the_amplifier_reads_all_four_parameters_from_one_sweep(registry):
    params, sim = CASES["amplifier"]
    _, vna, row, _, _ = run(registry, "amplifier", params, library_calls=True, **sim)
    assert [n for n, _ in vna.calls] == ["set_frequency_sweep", "run_sweep", "read_sparameters"]
    assert sorted(vna.calls[2][1]["sparameters"]) == ["S11", "S12", "S21", "S22"]
    assert row["min_k"] > 0 and "unconditionally_stable" in row and row["peak_gain_db"] > 15


def test_the_simple_calls_are_unchanged(registry):
    params, sim = CASES["filter"]
    _, vna, _, _, _ = run(registry, "filter", params, **sim)
    assert [n for n, _ in vna.calls] == ["set_sweep", "read_sparameter", "read_sparameter"]
    assert vna.calls[0][1]["sweep_type"] == "linear"


# ---- what the instrument cannot do -------------------------------------------------------------
ASKED = {"scale": "log", "if_bandwidth_hz": 100, "power_dbm": -10}


def test_what_the_instrument_cannot_do_is_warned_about_and_left_out(registry):
    """A LiteVNA: no set_source_power, no set_if_bandwidth, a linear sweep."""
    params, sim = CASES["return_loss"]
    p = {**params, "sweep": {**SWEEP, **ASKED}}
    runner, vna, row, logs, _ = run(
        registry, "return_loss", p, library_calls=True, library_extras=False, **sim
    )
    assert runner.state is RunState.FINISHED, runner.error
    warned = [m for lv, m in logs if lv == "warning"]
    assert len(warned) == 3
    assert any("sweeps linearly" in m for m in warned) and any("IF bandwidth" in m for m in warned)
    assert any("source power" in m for m in warned)
    assert [n for n, _ in vna.calls] == ["set_frequency_sweep", "run_sweep", "read_sparameters"]
    assert row["best_return_loss_db"] > 0
    # the same file on the simple calls sends them all and warns of nothing
    _, simple, _, logs, _ = run(registry, "return_loss", p, **sim)
    assert not any(lv == "warning" for lv, _ in logs)
    assert simple.calls[0][1]["sweep_type"] == "log" and simple.calls[0][1]["power"] == -10


def test_the_optional_calls_are_used_when_the_instrument_has_them(registry):
    """A Siglent or an R&S: set_if_bandwidth and set_source_power (value), no log sweep yet."""
    params, sim = CASES["return_loss"]
    p = {**params, "sweep": {**SWEEP, **ASKED}}
    runner, vna, _, logs, _ = run(registry, "return_loss", p, library_calls=True, **sim)
    assert runner.state is RunState.FINISHED, runner.error
    assert [(n, a) for n, a in vna.calls[:2]] == [
        ("set_if_bandwidth", {"value": 100.0}),
        ("set_source_power", {"value": -10.0}),
    ]
    warned = [m for lv, m in logs if lv == "warning"]
    assert len(warned) == 1 and "sweeps linearly" in warned[0]  # only the log sweep is missing


def test_a_logarithmic_sweep_is_sent_after_the_sweep_when_the_instrument_can_do_it(registry):
    """set_frequency_sweep always sets a linear sweep: set_sweep_type must come after it."""
    params, sim = CASES["return_loss"]
    p = {**params, "sweep": {**SWEEP, "scale": "log"}}
    runner, vna, _, logs, traces = run(
        registry, "return_loss", p, library_calls=True, library_sweep_type=True, **sim
    )
    assert runner.state is RunState.FINISHED, runner.error
    assert [n for n, _ in vna.calls[:2]] == ["set_frequency_sweep", "set_sweep_type"]
    assert vna.calls[1][1] == {"sweep_type": "LOG"}
    assert not any(lv == "warning" for lv, _ in logs)
    x = traces["return_loss_db"]["x"]
    assert x[1] / x[0] == pytest.approx(x[-1] / x[-2])  # spaced by a ratio: really logarithmic
    # a linear file puts it back to linear
    _, vna, _, _, _ = run(
        registry, "return_loss", params, library_calls=True, library_sweep_type=True, **sim
    )
    assert vna.calls[1] == ("set_sweep_type", {"sweep_type": "LINEAR"})


def test_an_instrument_that_has_the_call_but_only_a_linear_sweep_is_warned_about(registry):
    """The LiteVNA: set_sweep_type is there, LOG is not handled (CALL-002)."""
    params, sim = CASES["return_loss"]
    kw = dict(library_calls=True, library_sweep_type=True, library_linear_only=True, **sim)
    p = {**params, "sweep": {**SWEEP, "scale": "log"}}
    runner, vna, row, logs, traces = run(registry, "return_loss", p, **kw)
    assert runner.state is RunState.FINISHED, runner.error
    warned = [m for lv, m in logs if lv == "warning"]
    assert warned == ["this VNA cannot sweep logarithmically: the sweep is linear"]
    x = traces["return_loss_db"]["x"]
    assert x[1] - x[0] == pytest.approx(x[-1] - x[-2])  # linear
    assert row["best_return_loss_db"] > 0
    runner, vna, _, logs, _ = run(
        registry, "return_loss", params, **kw
    )  # a linear file: no problem
    assert runner.state is RunState.FINISHED and not any(lv == "warning" for lv, _ in logs)


def test_the_notes_say_what_is_left_out():
    vna = SimVna(library_calls=True, library_extras=False)
    assert sweep_notes(vna, {"scale": "linear"}) == []
    assert len(sweep_notes(vna, {"scale": "log", "if_bandwidth_hz": 1, "power_dbm": 0})) == 3
    full = SimVna(library_calls=True, library_sweep_type=True)
    assert sweep_notes(full, {"scale": "log", "if_bandwidth_hz": 1, "power_dbm": 0}) == []
    assert sweep_notes(SimVna(), {"scale": "log", "if_bandwidth_hz": 1, "power_dbm": 0}) == []


def test_data_that_are_not_calibrated_are_warned_about(registry):
    params, sim = CASES["attenuator"]
    runner, _, _, logs, _ = run(
        registry, "attenuator", params, library_calls=True, calibrated=False, **sim
    )
    assert runner.state is RunState.FINISHED
    warned = [m for lv, m in logs if lv == "warning" and "not calibrated" in m]
    assert len(warned) == 1  # once, not for every sweep
    p = {**params, "averages": 3}
    _, _, _, logs, _ = run(registry, "attenuator", p, library_calls=True, calibrated=False, **sim)
    assert len([1 for lv, m in logs if "not calibrated" in m]) == 1


COMPRESSION = {"frequency_hz": 868e6, "start_dbm": -40, "stop_dbm": -10, "step_db": 2}


def test_the_compression_test_is_refused_when_the_vna_cannot_set_its_power(registry):
    params, _ = CASES["amplifier"]
    p = {**params, "compression": COMPRESSION, "confirm_setup": True}
    vna = SimVna(library_calls=True, library_extras=False)
    runner = Runner(registry.create("amplifier", p), {"vna": [vna]})
    runner.start()
    assert runner.join(30) and runner.state is RunState.FAILED
    assert "has no call to set it" in runner.error["message"]
    assert (
        vna.calls == [] and runner.pending_questions == []
    )  # before the question, before anything


def test_the_compression_test_works_through_set_source_power(registry):
    params, sim = CASES["amplifier"]
    p = {**params, "sweep": {**params["sweep"], "power_dbm": -30}, "compression": COMPRESSION}
    simple = run(registry, "amplifier", p, **sim)
    library = run(registry, "amplifier", p, library_calls=True, **sim)
    assert library[0].state is RunState.FINISHED, library[0].error
    a, b = simple[2], library[2]
    assert b["p1db_input_dbm"] == pytest.approx(a["p1db_input_dbm"], abs=1e-9)
    assert b["small_signal_gain_db"] == pytest.approx(a["small_signal_gain_db"], abs=1e-9)
    powers = [x["value"] for n, x in library[1].calls if n == "set_source_power"]
    assert powers[0] == -30 and powers[1:-1] == [-40 + 2 * k for k in range(16)]
    assert powers[-1] == -30  # the power is put back afterwards
    warned = [m for lv, m in library[3] if lv == "warning"]
    assert not warned


# ---- a bad answer -----------------------------------------------------------------------------
class Odd(SimVna):
    def __init__(self, answer, **kw):
        super().__init__(library_calls=True, **kw)
        self.answer = answer

    def _library_call(self, name, args):
        result = super()._library_call(name, args)
        return self.answer(result) if name == "read_sparameters" else result


@pytest.mark.parametrize(
    "answer,words",
    [
        (lambda r: "nothing", "no S-parameters"),
        (lambda r: {"frequency": r["frequency"]}, "no S-parameters"),
        (lambda r: {**r, "parameters": {"S11": r["parameters"]["S11"]}}, "did not give S21"),
        (
            lambda r: {**r, "parameters": {"S21": {"real": [1.0], "imaginary": [0.0]}}},
            "values for S21",
        ),
        (lambda r: {**r, "parameters": {"S21": {"real": [1.0]}}}, "did not give S21"),
    ],
)
def test_an_answer_that_does_not_fit_is_an_error_that_says_what_was_wrong(registry, answer, words):
    params, _ = CASES["attenuator"]
    p = {**params, "confirm_setup": False}
    vna = Odd(answer, attenuator_db=10.0)
    runner = Runner(registry.create("attenuator", p), {"vna": [vna]})
    runner.start()
    assert runner.join(30) and runner.state is RunState.FAILED
    assert words in runner.error["message"]


# ---- the real library --------------------------------------------------------------------------
def test_the_library_calls_exist_for_the_network_analyzers_of_the_library():
    import json

    from ola.call_planner import plan_call
    from ola.library import Library

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "Instruments_LIB", "instruments_lib.json")
    schema = os.path.join(here, "Instruments_LIB", "schema", "vna.json")
    if not (os.path.isfile(path) and os.path.isfile(schema)):
        pytest.skip("library not available")
    calls = json.load(open(schema, encoding="utf-8"))["calls"]
    if "select_sparameters" in calls or "args" not in calls.get("read_sparameters", {}):
        pytest.skip(
            "the library is an older version of the category (read_sparameters has no list)"
        )
    lib = Library.load(path)
    models = ["VNA_Zenko_LiteVNA62", "VNA_Zenko_LiteVNA64", "VNA_Zenko_LiteVNA67"]
    if lib.find_model(models[0]) is None:
        pytest.skip("the library has no network analyzer category")
    params, sim = CASES["filter"]
    _, vna, _, _, _ = run(default_registry(user_dir="/nonexistent"), "filter", params,
                          library_calls=True, **sim)  # fmt: skip
    sent = {}
    for name, args in vna.calls:
        sent.setdefault(name, args)
    for model in models:
        for name, args in sent.items():
            plan_call(lib, model, name, args)  # raises if the model cannot do it
