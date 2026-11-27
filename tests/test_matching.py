# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Matching networks (``ola.matching``): every L network found makes the load look like ``z0``,
and the antenna and the return loss measurements report them."""

import math

import pytest

from ola import matching
from ola.registry import default_registry
from ola.runner import Runner, RunState
from ola.sim_vna import SimVna

LOADS = [100 + 50j, 20 - 30j, 25 + 0j, 200 - 150j, 10 + 80j, 49 + 1j, 5 - 2j, 1000 + 0j]


@pytest.mark.parametrize("load", LOADS)
def test_every_network_matches_the_load(load):
    found = matching.networks(load, 868e6)
    assert found, load
    for net in found:
        assert abs(net["z_in"] - 50) < 1e-6, net
        assert net["series"]["where"] == "series" and net["shunt"]["where"] == "shunt"
        assert net["series"]["value"] > 0 and net["shunt"]["value"] > 0
    assert [n["q"] for n in found] == sorted(n["q"] for n in found)  # the widest first


def test_the_shapes_that_exist():
    shapes = {n["shape"] for n in matching.networks(100 + 0j, 1e8)}
    assert shapes == {"shunt_load"}  # above z0: only the shunt next to the load
    shapes = {n["shape"] for n in matching.networks(20 - 30j, 1e8)}
    assert shapes == {"shunt_load", "series_load"}  # below z0 and outside the circle: both
    assert matching.networks(50 + 0j, 1e8) == []  # already matched


def test_the_components_and_the_text():
    w = 2 * math.pi * 1e8
    assert matching.component(10.0, 1e8, shunt=False) == {
        "kind": "L", "value": pytest.approx(10 / w), "where": "series",
    }  # fmt: skip
    assert matching.component(-10.0, 1e8, shunt=False)["kind"] == "C"
    assert matching.component(0.01, 1e8, shunt=True)["kind"] == "C"
    assert matching.component(-0.01, 1e8, shunt=True)["kind"] == "L"
    text = matching.describe(matching.networks(100 + 50j, 868e6)[0])
    assert text == "series 2.99 pF, then shunt (to ground) 31.6 nH next to the load"


def test_what_cannot_be_matched():
    with pytest.raises(matching.MatchingError, match="no resistance"):
        matching.networks(0 + 30j, 1e8)
    with pytest.raises(matching.MatchingError):
        matching.networks(50 + 10j, 0)
    summary, lines = matching.summary_at([1e8, 2e8], [0, 0], [10, 10], [1.5e8])
    assert summary == {"match_150MHz_count": 0} and "no resistance" in lines[0]


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.mark.parametrize("module", ["antenna", "return_loss"])
def test_the_measurements_report_the_networks(registry, module):
    params = {
        "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 151},
        "match_frequencies_hz": [900e6],
        "confirm_setup": False,
    }
    runner = Runner(registry.create(module, params), {"vna": [SimVna(termination="antenna")]})
    runner.start()
    assert runner.join(30)
    events = runner.drain()
    assert runner.state is RunState.FINISHED, runner.error
    row = next(
        e.data["values"] for e in events if e.kind == "point" and e.data["table"] == "points"
    )
    assert row["match_900MHz_count"] >= 2 and "next to the load" in row["match_900MHz_1"]
    assert row["match_900MHz_q"] > 0
    assert any(e.kind == "log" and "matching" in e.data["message"] for e in events)
    bad = dict(params, match_frequencies_hz=[2e9])
    assert any(p.path == "match_frequencies_hz" for p in registry.create(module, bad).check())
