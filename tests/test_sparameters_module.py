"""The S-parameters measurement, through registry + runner, on fake and simulated analyzers."""

import cmath
import math
import os

import pytest

from ola.library import Library
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.tester import make_handle
from tests.litevna_sim import SimLiteVna
from tests.measurement_helpers import FakeHandle, run_to_end

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)

PARAMS = {"start_hz": 1e6, "stop_hz": 4e6, "points": 4, "sparameters": ["S11", "S21"]}


@pytest.fixture
def registry(tmp_path):
    return default_registry(user_dir=tmp_path / "none")


def read_result(calibrated=True):
    """4 points: S11 is -20 dB at the third, S21 is 0 dB everywhere."""
    s11 = [0.5, 0.3, 0.1, 0.4]
    return {
        "frequency": [1e6, 2e6, 3e6, 4e6],
        "parameters": {
            "S11": {"real": s11, "imaginary": [0.0] * 4},
            "S21": {"real": [1.0] * 4, "imaginary": [0.0] * 4},
        },
        "calibrated": calibrated,
    }


def run(registry, handle, **params):
    measurement = registry.create("sparameters", dict(PARAMS, **params))
    runner = run_to_end(Runner(measurement, {"vna": [handle]}))
    return runner, list(runner.drain())


def test_module_is_found_and_asks_for_a_network_analyzer(registry):
    assert "sparameters" in [m.id for m in registry.list()]
    assert registry.by_extension(".spm").id == "sparameters"
    roles = registry.create("sparameters", PARAMS).roles
    assert [(r.name, r.category) for r in roles] == [("vna", "network_analyzer")]


def test_one_sweep_records_complex_traces_and_a_summary(registry):
    handle = FakeHandle("vna", {"read_sparameters": lambda sparameters: read_result()})
    runner, events = run(registry, handle)
    assert runner.state is RunState.FINISHED
    calls = [name for name, _ in handle.calls]
    assert calls == ["set_frequency_sweep", "run_sweep", "read_sparameters"]
    assert handle.calls[0][1] == {"start_frequency": 1e6, "stop_frequency": 4e6, "points": 4}
    assert handle.calls[2][1] == {"sparameters": ["S11", "S21"]}
    traces = {e.data["name"]: e.data for e in events if e.kind == "trace"}
    assert set(traces) == {"S11", "S21"}
    assert traces["S11"]["x"] == [1e6, 2e6, 3e6, 4e6]
    assert traces["S11"]["trace_kind"] == "complex" and traces["S11"]["y"][2] == [0.1, 0.0]
    point = next(e.data["values"] for e in events if e.kind == "point")
    assert point["sweep"] == 1 and point["calibrated"] is True
    assert point["S11_min_db"] == pytest.approx(-20.0) and point["S11_min_hz"] == 3e6
    assert point["S21_max_db"] == pytest.approx(0.0)


def test_repeated_sweeps_and_optional_settings(registry):
    handle = FakeHandle("vna", {"read_sparameters": lambda sparameters: read_result()})
    runner, events = run(
        registry, handle, sweeps=3, interval_s=0.01, if_bandwidth_hz=1000, power_dbm=-10
    )
    assert [e.data["values"]["sweep"] for e in events if e.kind == "point"] == [1, 2, 3]
    assert [n for n, _ in handle.calls].count("read_sparameters") == 3
    assert ("set_if_bandwidth", {"value": 1000}) in handle.calls
    assert ("set_source_power", {"value": -10}) in handle.calls


def test_uncalibrated_data_warn_or_stop(registry):
    handle = FakeHandle("vna", {"read_sparameters": lambda sparameters: read_result(False)})
    runner, events = run(registry, handle, sweeps=2)
    warnings = [
        e.data["message"] for e in events if e.kind == "log" and e.data["level"] == "warning"
    ]
    assert runner.state is RunState.FINISHED and warnings == ["the data are not calibrated"]
    runner, _ = run(registry, handle, require_calibration=True)
    assert runner.state is RunState.FAILED
    assert "not calibrated" in str(runner.error)


@pytest.mark.parametrize(
    "bad",
    [
        {"start_hz": -1},
        {"stop_hz": 1e6},
        {"points": 1},
        {"sparameters": []},
        {"sparameters": ["S13"]},
        {"sparameters": ["S11", "S11"]},
        {"sweeps": 0},
        {"interval_s": -1},
        {"if_bandwidth_hz": 0},
        {"require_calibration": "yes"},
    ],
)
def test_parameters_are_checked(registry, bad):
    measurement = registry.create("sparameters", dict(PARAMS, **bad))
    assert measurement.validate(), bad
    assert registry.create("sparameters", PARAMS).validate() == []


@pytest.mark.skipif(LIB is None or "calibration_begin" not in open(LIB).read(), reason="library")
def test_with_the_simulated_litevna_through_the_library(registry):
    library = Library.load(LIB)
    sim = SimLiteVna()
    sim.e00, sim.e11, sim.t = 0j, 0j, 1 + 0j
    sim.connect(lambda f: 0.4 * cmath.exp(-1j * f * 1e-9))
    handle = make_handle(library, "VNA_Zenko_LiteVNA67", sim, "litevna")
    runner, events = run(registry, handle, sparameters=["S11"], points=11, stop_hz=2e6)
    assert runner.state is RunState.FINISHED, runner.error
    trace = next(e.data for e in events if e.kind == "trace")
    assert len(trace["x"]) == 11 and trace["meta"]["calibrated"] is False
    assert all(math.hypot(*v) == pytest.approx(0.4, abs=1e-4) for v in trace["y"])
