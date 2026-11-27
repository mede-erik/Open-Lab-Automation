# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A quartz crystal measured with a VNA (``ola.crystal``, ``ola/modules/crystal``): its equivalent
circuit from a series-thru S21, on a simulated crystal of known values."""

import json
import math
import re
from pathlib import Path

import pytest

from ola import crystal
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimCrystal

ROOT = Path(__file__).resolve().parent.parent


def sweep_of(sim, points=2001, below=2e3, above=4e3):
    fp = 10e6 * math.sqrt(1 + sim.cm_f / sim.c0_f)
    start, stop = 10e6 - below, fp + above
    return [start + (stop - start) * k / (points - 1) for k in range(points)]


def test_the_equivalent_circuit_of_a_crystal():
    sim = SimCrystal(fs_hz=10e6, rm_ohm=20, lm_h=10e-3, c0_f=4e-12)
    freq = sweep_of(sim)
    got = crystal.analyse(
        freq, [sim.s_parameter("S21", f) for f in freq], load_capacitance_f=18e-12
    )
    assert got["fs_hz"] == pytest.approx(10e6, abs=2)  # C0 moves the zero of X by a hair
    assert got["rm_ohm"] == pytest.approx(20, rel=1e-3)
    assert got["lm_h"] == pytest.approx(10e-3, rel=1e-3)
    assert got["cm_f"] == pytest.approx(sim.cm_f, rel=1e-3)
    assert got["q"] == pytest.approx(2 * math.pi * 10e6 * 10e-3 / 20, rel=1e-3)
    assert got["c0_f"] == pytest.approx(4e-12, rel=0.01)
    assert got["fp_hz"] == pytest.approx(10e6 * math.sqrt(1 + sim.cm_f / 4e-12), abs=5)
    expected = 10e6 * (1 + sim.cm_f / (2 * (4e-12 + 18e-12)))
    assert got["fl_hz"] == pytest.approx(expected, abs=5)
    assert got["pulling_ppm_per_pf"] < 0


def test_without_the_parallel_resonance_c0_is_not_found():
    sim = SimCrystal()
    freq = [10e6 - 2e3 + 4e3 * k / 1000 for k in range(1001)]  # only around fs
    got = crystal.analyse(
        freq, [sim.s_parameter("S21", f) for f in freq], load_capacitance_f=18e-12
    )
    assert got["c0_f"] is None and got["fp_hz"] is None and "fl_hz" not in got
    assert got["rm_ohm"] == pytest.approx(20, rel=1e-3)


def test_a_sweep_that_misses_the_crystal_is_refused():
    sim = SimCrystal()
    freq = [9.9e6 + 10 * k for k in range(101)]
    with pytest.raises(crystal.CrystalError, match="centre the sweep"):
        crystal.analyse(freq, [sim.s_parameter("S21", f) for f in freq])
    assert crystal.check_sweep_for(9.9e6, 10.1e6, 101)  # far too coarse
    assert not crystal.check_sweep_for(9.998e6, 10.004e6, 2001)


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def run(registry, params, sim):
    runner = Runner(registry.create("crystal", params), {"vna": [sim]})
    runner.start()
    assert runner.join(30)
    events = runner.drain()
    assert runner.state is RunState.FINISHED, runner.error
    row = next(
        e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "points"
    )
    logs = [(e.data["level"], e.data["message"]) for e in events if e.kind == "log"]
    return row, {e.data["name"] for e in events if e.kind == "trace"}, logs


def test_the_measurement_checks_the_frequency_with_its_load(registry):
    sim = SimCrystal(fs_hz=10e6 - 150, rm_ohm=25)  # 15 ppm low at series resonance
    params = {
        "sweep": {"start_hz": 9.998e6, "stop_hz": 10.04e6, "points": 2001},
        "nominal_frequency_hz": 10e6,
        "tolerance_ppm": 30,
        "load_capacitance_pf": 18,
        "confirm_setup": False,
    }
    row, traces, _ = run(registry, params, sim)
    assert {"S21", "s21_db", "x_ohm", "r_ohm"} <= traces
    # with 18 pF the crystal runs about 575 ppm above fs: far off a 10 MHz series crystal
    assert row["offset_ppm"] == pytest.approx((row["fl_hz"] - 10e6) / 10, rel=1e-9)
    assert row["verdict"] == "FAIL"
    del params["load_capacitance_pf"]  # a series-resonant crystal: fs is checked
    row, _, _ = run(registry, params, sim)
    assert row["offset_ppm"] == pytest.approx(-15, abs=0.5) and row["verdict"] == "PASS"


def test_the_example_of_the_guide_runs_and_names_the_results(registry):
    text = (ROOT / "docs" / "crystal.md").read_text()
    params = json.loads(re.search(r"```json crystal\.xtl\n(.*?)```", text, re.S).group(1))
    params["confirm_setup"] = False
    assert registry.create("crystal", params).validate() == []
    # a crystal made for 18 pF: its series resonance is below 10 MHz, the frequency with the load
    # is 10 MHz
    fs = 10e6
    for _ in range(5):  # Cm follows fs (Lm is fixed): a few rounds settle both
        fs = 10e6 / (1 + SimCrystal(fs_hz=fs).cm_f / (2 * (4e-12 + 18e-12)))
    row, _, _ = run(registry, params, SimCrystal(fs_hz=fs))
    assert row["verdict"] == "PASS" and abs(row["offset_ppm"]) < 1
    for key in ("fs_hz", "fp_hz", "rm_ohm", "lm_h", "cm_f", "c0_f", "q", "fl_hz", "offset_ppm"):
        assert key in row and f"`{key}`" in text, key


@pytest.mark.parametrize(
    "change,path",
    [
        ({"sweep": {"start_hz": 9.9e6, "stop_hz": 10.1e6, "points": 2001, "scale": "log"}},
         "sweep.scale"),
        ({"nominal_frequency_hz": 5e6}, "nominal_frequency_hz"),
        ({"tolerance_ppm": -1}, "tolerance_ppm"),
        ({"load_capacitance_pf": "big"}, "load_capacitance_pf"),
        ({"z0": 0}, "z0"),
    ],
)  # fmt: skip
def test_the_parameters_are_checked(registry, change, path):
    from ola.modules.crystal.measurement import default_params

    assert registry.create("crystal", default_params()).validate() == []
    problems = registry.create("crystal", dict(default_params(), **change)).check()
    assert path in {p.path for p in problems}, problems
