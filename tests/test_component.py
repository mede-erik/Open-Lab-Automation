# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A component measured with a VNA (``ola.component``, ``ola/modules/component``): the impedance
of the three connections, the equivalent values, the self-resonance and the nominal check, on
simulated inductors, capacitors and resistors."""

import math

import pytest

from ola import component as comp
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimComponent

FREQ = [1e6 * 1.02**k for k in range(300)]  # 1 MHz to about 380 MHz


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.mark.parametrize("method", comp.METHODS)
def test_each_connection_gives_the_impedance_back(method):
    sim = SimComponent(method, r_ohm=0.3, l_h=47e-9, cp_f=1.5e-12)
    name = "S11" if method == "reflection" else "S21"
    z = comp.impedance(method, [sim.s_parameter(name, f) for f in FREQ])
    for value, f in zip(z, FREQ):
        assert value == pytest.approx(sim.impedance(f), rel=1e-9)


def test_the_equivalent_values_of_an_inductor_and_a_capacitor():
    f = 10e6
    w = 2 * math.pi * f
    eq = comp.equivalent([f], [complex(2.0, w * 100e-9)])
    assert eq["l_h"][0] == pytest.approx(100e-9) and eq["c_f"][0] is None
    assert eq["q"][0] == pytest.approx(w * 100e-9 / 2.0)
    eq = comp.equivalent([f], [complex(0.05, -1 / (w * 10e-9))])
    assert eq["c_f"][0] == pytest.approx(10e-9) and eq["l_h"][0] is None
    assert eq["d"][0] == pytest.approx(0.05 * w * 10e-9)


def test_the_self_resonances():
    inductor = SimComponent("series", r_ohm=0.5, l_h=100e-9, cp_f=2e-12)
    z = [inductor.impedance(f) for f in FREQ]
    (found,) = comp.self_resonances(FREQ, z)
    expected = 1 / (2 * math.pi * math.sqrt(100e-9 * 2e-12))  # about 356 MHz
    assert found["kind"] == "parallel" and found["frequency_hz"] == pytest.approx(
        expected, rel=0.01
    )
    capacitor = SimComponent("shunt", r_ohm=0.02, l_h=1e-9, c_f=100e-9)
    (found,) = comp.self_resonances(FREQ, [capacitor.impedance(f) for f in FREQ])
    expected = 1 / (2 * math.pi * math.sqrt(1e-9 * 100e-9))  # about 15.9 MHz
    assert found["kind"] == "series" and found["frequency_hz"] == pytest.approx(expected, rel=0.01)
    assert comp.guess_kind([capacitor.impedance(f) for f in FREQ[:50]]) == "capacitor"
    assert comp.guess_kind([complex(100, 1)] * 5) == "resistor"


def test_the_method_that_suits_an_impedance():
    assert comp.best_method([0.01, 0.1, 1]) == "shunt"
    assert comp.best_method([20, 50, 200]) == "reflection"
    assert comp.best_method([1e3, 1e4, 1e5]) == "series"
    assert comp.inaccurate_points("series", [0.5, 0.01]) == 1
    assert comp.inaccurate_points("shunt", [0.5, 0.99]) == 1
    with pytest.raises(comp.ComponentError):
        comp.impedance("bridge", [0.5])


def run(registry, params, sim):
    runner = Runner(registry.create("component", params), {"vna": [sim]})
    runner.start()
    assert runner.join(30)
    events = runner.drain()
    assert runner.state is RunState.FINISHED, runner.error
    row = next(
        e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "points"
    )
    traces = {e.data["name"] for e in events if e.kind == "trace"}
    logs = [(e.data["level"], e.data["message"]) for e in events if e.kind == "log"]
    return row, traces, logs


SWEEP = {"start_hz": 1e6, "stop_hz": 500e6, "points": 401, "scale": "log"}


def test_an_inductor_in_series_and_its_nominal_value(registry):
    params = {
        "device": {"label": "L3"},
        "sweep": SWEEP,
        "method": "series",
        "kind": "inductor",
        "nominal": {"value": 100e-9, "tolerance_pct": 5, "frequency_hz": 10e6},
        "frequencies_of_interest": [10e6],
        "confirm_setup": False,
    }
    sim = SimComponent("series", r_ohm=0.5, l_h=103e-9, cp_f=2e-12)
    row, traces, _ = run(registry, params, sim)
    assert row["kind"] == "inductor" and row["verdict"] == "PASS"
    assert row["deviation_pct"] == pytest.approx(3.0, abs=0.2)
    assert row["l_h_10MHz"] == pytest.approx(103e-9, rel=0.01)
    assert row["self_resonance_kind"] == "parallel"
    assert row["self_resonance_hz"] == pytest.approx(
        1 / (2 * math.pi * math.sqrt(103e-9 * 2e-12)), rel=0.02
    )
    assert {"S21", "z_abs_ohm", "r_ohm", "x_ohm", "l_nh", "q"} <= traces
    params["nominal"]["value"] = 82e-9
    assert run(registry, params, SimComponent("series", r_ohm=0.5, l_h=103e-9))[0]["verdict"] == (
        "FAIL"
    )


def test_a_capacitor_in_shunt_with_its_esr(registry):
    params = {
        "sweep": {"start_hz": 100e3, "stop_hz": 100e6, "points": 301, "scale": "log"},
        "method": "shunt",
        "frequencies_of_interest": [1e6],
        "confirm_setup": False,
    }
    row, traces, logs = run(
        registry, params, SimComponent("shunt", r_ohm=0.03, l_h=0.8e-9, c_f=1e-6)
    )
    assert row["kind"] == "capacitor"  # found from the reactance
    w = 2 * math.pi * 1e6  # the effective capacitance: the lead inductance makes it look larger
    effective = 1 / (w * (1 / (w * 1e-6) - w * 0.8e-9))
    assert row["c_f_1MHz"] == pytest.approx(effective, rel=1e-3) and effective > 1.02e-6
    assert row["r_1MHz_ohm"] == pytest.approx(0.03, rel=0.01)  # the ESR
    assert row["self_resonance_kind"] == "series"
    assert "c_pf" in traces
    assert not any("accurate range" in m for _, m in logs)


def test_a_bad_choice_of_method_is_reported(registry):
    params = {"sweep": SWEEP, "method": "reflection", "confirm_setup": False}
    _, _, logs = run(registry, params, SimComponent("reflection", r_ohm=0.02, c_f=1e-6))
    assert any(level == "warning" and "the shunt method suits" in m for level, m in logs)


@pytest.mark.parametrize(
    "change,path",
    [
        ({"method": "bridge"}, "method"),
        ({"kind": "diode"}, "kind"),
        ({"nominal": {"value": 0, "frequency_hz": 1e6}, "kind": "inductor"}, "nominal.value"),
        ({"nominal": {"value": 1e-9, "frequency_hz": 5e9}, "kind": "inductor"},
         "nominal.frequency_hz"),
        ({"nominal": {"value": 1e-9, "frequency_hz": 1e7}}, "kind"),  # auto cannot be checked
        ({"z0": -1}, "z0"),
    ],
)  # fmt: skip
def test_the_parameters_are_checked(registry, change, path):
    from ola.modules.component.measurement import default_params

    assert registry.create("component", default_params()).validate() == []
    problems = registry.create("component", dict(default_params(), **change)).check()
    assert path in {p.path for p in problems}, problems


def test_the_example_of_the_guide_is_valid_and_runs(registry):
    """The file of docs/component.md is a real one: it validates and runs."""
    import json
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "docs" / "component.md").read_text()
    block = re.search(r"```json component\.cmp\n(.*?)```", text, re.S)
    params = json.loads(block.group(1))
    params["confirm_setup"] = False
    row, _, _ = run(registry, params, SimComponent("series", r_ohm=0.4, l_h=100e-9, cp_f=1e-12))
    assert row["verdict"] == "PASS" and row["kind"] == "inductor"
    for key in ("self_resonance_hz", "deviation_pct", "l_h_10MHz", "q_10MHz"):
        assert key in row and key.split("_10MHz")[0] in text, key
