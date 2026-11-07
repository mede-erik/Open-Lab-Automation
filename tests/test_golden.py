# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The golden sample: a run against a good one, with a verdict (cable runs on a simulated VNA)."""

import pytest

from ola.compare import load_run
from ola.golden import (
    GoldenError,
    check_against_golden,
    check_figure,
    find_golden,
    format_result,
    golden_path,
    list_golden,
    set_golden,
)
from ola.registry import default_registry
from ola.runner import Runner
from ola.runs import RunWriter
from ola.sim_vna import SimVna


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def cable_run(registry, tmp_path, label, loss=0.6, stop=3e9, stamp="20261103_100000"):
    params = {
        "mode": "transmission",
        "sweep": {"start_hz": 1e6, "stop_hz": stop, "points": 301, "scale": "linear"},
        "cable": {"label": label, "length_m": 2.0},
        "frequencies_of_interest": [868e6],
        "confirm_setup": False,
    }
    runner = Runner(
        registry.create("cable", params),
        {"vna": [SimVna(length_m=2.0, loss_db_per_m_at_1ghz=loss)]},
    )
    path = tmp_path / f"cable_{label.replace(' ', '_')}_{stamp}.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(20)
    return path


CURVE = {"trace": "S21", "view": "loss_db"}


def test_the_same_cable_passes_and_a_lossier_one_fails(registry, tmp_path):
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    good = load_run(cable_run(registry, tmp_path, "good", 0.6, stamp="20261104_100000"))
    worn = load_run(cable_run(registry, tmp_path, "worn", 0.9, stamp="20261105_100000"))
    spec = {"curves": [{**CURVE, "tolerance": 0.2}], "summary": {"loss_868MHz_db": 0.1}}
    assert check_against_golden(good, golden, spec).verdict == "PASS"
    result = check_against_golden(worn, golden, spec)
    assert result.verdict == "FAIL" and not result.passed
    assert any("S21 (loss_db)" in r for r in result.reasons)
    assert any("loss_868MHz_db" in r for r in result.reasons)
    # the difference is the loss added by the worse cable: 0.3 dB/m x 2 m at 1 GHz, growing
    curve_check = result.checks[0]
    assert curve_check.worst > 0.5 and curve_check.margin < 0 and curve_check.at_x > 1e9


def test_the_tolerance_can_follow_the_frequency_and_be_asymmetric(registry, tmp_path):
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    worn = load_run(cable_run(registry, tmp_path, "worn", 0.9, stamp="20261105_100000"))
    # the extra loss grows as the square root of the frequency (0.02 dB at 1 MHz, 1.04 at 3 GHz)
    line = [[1e6, 0.1], [3e8, 0.5], [3e9, 1.2]]
    ok = check_against_golden(worn, golden, {"curves": [{**CURVE, "tolerance": line}]})
    assert ok.verdict == "PASS"
    # a more lossy cable has a larger loss: the "upper" side is the one that fails
    up = {"upper": 0.1, "lower": 5.0}
    assert (
        check_against_golden(worn, golden, {"curves": [{**CURVE, "tolerance": up}]}).verdict
        == "FAIL"
    )
    down = {"upper": 5.0, "lower": 0.1}
    assert (
        check_against_golden(worn, golden, {"curves": [{**CURVE, "tolerance": down}]}).verdict
        == "PASS"
    )


def test_a_narrower_sweep_does_not_prove_anything(registry, tmp_path):
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    short = load_run(cable_run(registry, tmp_path, "short", 0.6, stop=1e9, stamp="20261104_100000"))
    result = check_against_golden(short, golden, {"curves": [{**CURVE, "tolerance": 5.0}]})
    assert result.verdict == "FAIL" and "covers" in result.reasons[0]
    loose = {"curves": [{**CURVE, "tolerance": 5.0}], "min_overlap": 0.3}
    assert check_against_golden(short, golden, loose).verdict == "PASS"


def test_a_figure_has_an_absolute_and_a_relative_tolerance(registry, tmp_path):
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    worn = load_run(cable_run(registry, tmp_path, "worn", 0.9, stamp="20261105_100000"))
    base = golden.summary["loss_868MHz_db"]
    delta = worn.summary["loss_868MHz_db"] - base
    assert delta > 0.1
    assert not check_figure(worn, golden, "loss_868MHz_db", delta * 0.5).passed
    assert check_figure(worn, golden, "loss_868MHz_db", delta * 1.01).passed
    assert check_figure(worn, golden, "loss_868MHz_db", {"rel": delta / base * 1.01}).passed
    # the larger of the two counts
    both = {"abs": delta * 0.1, "rel": delta / base * 1.01}
    assert check_figure(worn, golden, "loss_868MHz_db", both).passed
    assert not check_figure(worn, golden, "no_such_figure", 1.0).passed


def test_wrong_requests_are_refused_with_a_sentence(registry, tmp_path):
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    run = load_run(cable_run(registry, tmp_path, "run", 0.6, stamp="20261104_100000"))
    for spec, text in (
        ({}, "at least one"),
        ({"curves": [{"trace": "S21"}]}, "needs 'trace' and 'tolerance'"),
        ({"curves": [{**CURVE, "tolerance": -1}]}, "cannot be negative"),
        ({"curves": [{**CURVE, "tolerance": "big"}]}, "must be a number, a line or an object"),
        ({"curves": [{**CURVE, "tolerance": {"x": 1}}]}, "'upper' and 'lower'"),
        ({"summary": {"loss_868MHz_db": {"abs": -1}}}, "cannot be negative"),
        ({"summary": {"loss_868MHz_db": 1}, "min_overlap": 0}, "min_overlap"),
        ({"summary": {"loss_868MHz_db": 1}, "extra": 1}, "unknown key"),
    ):
        with pytest.raises(GoldenError, match=text):
            check_against_golden(run, golden, spec)


def test_a_curve_the_run_does_not_have_is_a_failure_not_a_crash(registry, tmp_path):
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    run = load_run(cable_run(registry, tmp_path, "run", 0.6, stamp="20261104_100000"))
    result = check_against_golden(run, golden, {"curves": [{"trace": "S99", "tolerance": 1}]})
    assert result.verdict == "FAIL" and "S99" in result.reasons[0]


def test_the_golden_sample_is_kept_in_the_project(registry, tmp_path):
    path = cable_run(registry, tmp_path, "RG58 #3", 0.6)
    project = tmp_path / "project"
    target = set_golden(project, "RG58 / 1m", path)
    assert target == golden_path(project, "RG58 / 1m") and target.parent.name == "golden"
    assert list_golden(project) == ["RG58_1m"]
    found = find_golden(project, "RG58 / 1m")
    assert found is not None and found.label == "golden RG58 / 1m" and "S21" in found.traces
    assert find_golden(project, "other") is None and list_golden(tmp_path / "none") == []
    with pytest.raises(GoldenError, match="give the golden sample a name"):
        golden_path(project, " / ")


def test_a_run_that_did_not_finish_cannot_be_the_golden_sample(registry, tmp_path):
    path = cable_run(registry, tmp_path, "cut", 0.6)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")  # no end line: interrupted
    with pytest.raises(GoldenError, match="did not finish"):
        set_golden(tmp_path / "project", "cut", path)


def test_two_kinds_of_measurement_are_not_compared(registry, tmp_path):
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    other = load_run(cable_run(registry, tmp_path, "run", 0.6, stamp="20261104_100000"))
    other.measurement = "filter"
    with pytest.raises(GoldenError, match="not the same|golden sample a cable"):
        check_against_golden(other, golden, {"summary": {"loss_868MHz_db": 1}})


def test_the_text_of_a_result_lists_every_check(registry, tmp_path):
    golden = load_run(cable_run(registry, tmp_path, "golden", 0.6))
    worn = load_run(cable_run(registry, tmp_path, "worn", 0.9, stamp="20261105_100000"))
    spec = {"curves": [{**CURVE, "tolerance": 5.0}], "summary": {"loss_868MHz_db": 0.01}}
    text = format_result(check_against_golden(worn, golden, spec))
    assert text.startswith("FAIL: 1 of 2 checks ok")
    assert "ok   S21 (loss_db)" in text and "FAIL loss_868MHz_db" in text


def test_the_script_gives_the_verdict_as_an_exit_code(registry, tmp_path, capsys):
    from scripts.golden_check import main

    golden = cable_run(registry, tmp_path, "golden", 0.6)
    good = cable_run(registry, tmp_path, "good", 0.6, stamp="20261104_100000")
    worn = cable_run(registry, tmp_path, "worn", 0.9, stamp="20261105_100000")
    args = ["--curve", "S21:loss_db:0.2", "--figure", "loss_868MHz_db:10%"]
    assert main([str(good), str(golden), *args]) == 0
    assert main([str(worn), str(golden), *args]) == 1
    assert "FAIL" in capsys.readouterr().out
    project = tmp_path / "project"
    assert main(["--list", str(project)]) == 0 and "no golden sample" in capsys.readouterr().out
    assert main(["--set", str(project), "RG58", str(golden)]) == 0
    assert main(["--list", str(project)]) == 0 and "RG58" in capsys.readouterr().out
    assert main([str(good), "RG58", "--project", str(project), *args]) == 0
    assert main([str(good), "none", "--project", str(project), *args]) == 2
    assert "no golden sample called" in capsys.readouterr().err
    assert main([str(good), str(golden)]) == 2  # nothing to check
