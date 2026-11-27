# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The VNA measurements share their parameters: the same names everywhere (the old ones are still
read), the reference impedance, the calibration that can be required, the aperture of the group
delay, and the amplifier on a forward-only VNA."""

import cmath
import json
import math
from pathlib import Path

import pytest

from ola import rf
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimAmplifier, SimVna
from ola.vna_common import RENAMED, upgrade_params, upgraded

ROOT = Path(__file__).resolve().parent.parent
VNA_MODULES = (
    "sparameters",
    "return_loss",
    "filter",
    "amplifier",
    "attenuator",
    "antenna",
    "cable",
    "tdr",
    "crystal",
)
SWEEP = {"start_hz": 1e6, "stop_hz": 1e9, "points": 101}


@pytest.fixture
def registry(tmp_path):
    return default_registry(user_dir=tmp_path / "none")


def run(registry, type_id, params, vna):
    runner = Runner(registry.create(type_id, params), {"vna": [vna]})
    runner.start()
    assert runner.join(30)
    return runner, list(runner.drain())


def test_old_names_are_read_and_the_new_ones_win():
    old = {"also_return_loss": False, "gain_edge_db": 6, "other": 1}
    assert upgrade_params(old)
    assert old == {"also_s11": False, "edge_db": 6, "other": 1}
    assert not upgrade_params(old)  # nothing left to change
    both = {"also_return_loss": False, "also_s11": True}
    assert upgraded(both) == {"also_s11": True} and "also_return_loss" in both  # a copy
    flat = {"start_hz": 1e6, "stop_hz": 2e6, "points": 11, "sparameters": ["S11"]}
    assert upgraded(flat, flat_sweep=True) == {
        "sweep": {"start_hz": 1e6, "stop_hz": 2e6, "points": 11},
        "sparameters": ["S11"],
    }
    assert upgraded(dict(flat, sweep={"points": 3}), flat_sweep=True)["sweep"] == {"points": 3}
    assert set(RENAMED.values()) == {"also_s11", "edge_db"}


def test_every_vna_measurement_offers_the_common_fields_in_its_editor():
    common = {"z0", "require_calibration", "confirm_setup", "averages"}
    for module in VNA_MODULES:
        form = json.loads((ROOT / "ola" / "modules" / module / "form.json").read_text())
        paths = {f["path"] for s in form["sections"] for f in s["fields"]}
        assert common <= paths, (module, common - paths)
        assert not paths & set(RENAMED), (module, "an old name is still in the editor")
        assert "sweep.start_hz" in paths, module
        schema = json.loads((ROOT / "ola" / "modules" / module / "module.json").read_text())
        assert common - {"averages"} <= set(schema["params_schema"]) | {"confirm_setup"}, module
    for module in ("filter", "cable"):
        form = json.loads((ROOT / "ola" / "modules" / module / "form.json").read_text())
        assert "group_delay_aperture" in {f["path"] for s in form["sections"] for f in s["fields"]}


@pytest.mark.parametrize("module", VNA_MODULES)
def test_every_vna_measurement_checks_the_common_fields(registry, module):
    from importlib import import_module

    defaults = import_module(f"ola.modules.{module}.measurement").default_params()
    for bad, path in (({"z0": 0}, "z0"), ({"require_calibration": "yes"}, "require_calibration")):
        problems = registry.create(module, dict(defaults, **bad)).check()
        assert any(p.path == path for p in problems), (module, bad)


def test_the_aperture_smooths_the_group_delay():
    freq = [1e6 * i for i in range(1, 201)]
    delay = 5e-9
    noise = [0.05 * math.sin(i * 2.1) for i in range(len(freq))]  # phase noise, rad
    s21 = [cmath.exp(-1j * (2 * math.pi * f * delay + n)) for f, n in zip(freq, noise)]
    one = rf.group_delay_s(freq, s21)
    ten = rf.group_delay_s(freq, s21, aperture=10)
    inner = slice(20, 180)

    def spread(values):
        return max(values[inner]) - min(values[inner])

    assert spread(ten) < spread(one) / 5
    assert sum(ten[inner]) / len(ten[inner]) == pytest.approx(delay, rel=0.02)
    assert one == rf.group_delay_s(freq, s21, aperture=1)  # 1 is the behaviour of before
    with pytest.raises(rf.RfError):
        rf.group_delay_s(freq, s21, aperture=0)


def test_a_required_calibration_stops_the_measurement(registry):
    params = {"sweep": dict(SWEEP), "confirm_setup": False, "require_calibration": True}
    runner, _ = run(registry, "return_loss", params, SimVna(library_calls=True, calibrated=False))
    assert runner.state is RunState.FAILED and "requires a calibration" in str(runner.error)
    vna = SimVna(library_calls=True, termination="open")
    vna.uncorrected = ["S11"]
    runner, _ = run(registry, "return_loss", params, vna)
    assert runner.state is RunState.FAILED and "S11 is not corrected" in str(runner.error)
    runner, events = run(registry, "return_loss", dict(params, require_calibration=False), vna)
    assert runner.state is RunState.FINISHED  # only a warning without the requirement
    assert any(e.kind == "log" and "not corrected" in e.data["message"] for e in events)


def test_the_amplifier_on_a_forward_only_vna(registry):
    params = {
        "sweep": {"start_hz": 700e6, "stop_hz": 1050e6, "points": 101, "power_dbm": -30},
        "confirm_setup": False,
        "also_reverse": False,
        "gain_edge_db": 3,  # the old name of edge_db
    }
    vna = SimAmplifier()
    runner, events = run(registry, "amplifier", params, vna)
    assert runner.state is RunState.FINISHED, runner.error
    traces = {e.data["name"] for e in events if e.kind == "trace"}
    assert {"S21", "S11"} <= traces and not traces & {"S12", "S22", "stability_mu"}
    row = next(
        e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "points"
    )
    assert row["peak_gain_db"] == pytest.approx(20, abs=0.5) and "bandwidth_hz" in row
    assert "min_mu" not in row and "unconditionally_stable" not in row
    assert any(e.kind == "log" and "forward only" in e.data["message"] for e in events)


def test_the_touchstone_export_writes_the_reference_impedance_of_the_measurement(
    registry, tmp_path
):
    from ola.runs import RunWriter, export_touchstone

    for z0, expected in ((75, "R 75"), (None, "R 50")):
        params = {"sweep": dict(SWEEP, points=11), "confirm_setup": False}
        if z0:
            params["z0"] = z0
        runner = Runner(registry.create("sparameters", params), {"vna": [SimVna()]})
        path = tmp_path / f"run_{z0}.jsonl"
        runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
        runner.start()
        assert runner.join(30)
        out = tmp_path / f"x_{z0}.s1p"
        export_touchstone(path, out)
        option = next(line for line in out.read_text().splitlines() if line.startswith("#"))
        assert option.endswith(expected), option
