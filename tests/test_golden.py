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
        ({"summary": {"loss_868MHz_db": {"abs": -1}}}, "not negative"),
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


# ---- the golden sample as a step of the cable measurement --------------------------------------
def cable_params(**golden):
    return {
        "mode": "transmission",
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 301, "scale": "linear"},
        "cable": {"label": "unit 7", "length_m": 2.0},
        "frequencies_of_interest": [868e6],
        "confirm_setup": False,
        "golden": golden,
    }


TOLERANCES = {"curves": [{"trace": "loss_db", "tolerance": 0.2}], "summary": {"max_loss_db": 0.2}}


def measure(registry, params, loss):
    runner = Runner(
        registry.create("cable", params),
        {"vna": [SimVna(length_m=2.0, loss_db_per_m_at_1ghz=loss)]},
    )
    runner.start()
    assert runner.join(30) and runner.state.value == "finished", runner.error
    rows, logs = {}, []
    for e in runner.drain():
        if e.kind == "point":
            rows.setdefault(e.data["table"], []).append(e.data["values"])
        elif e.kind == "log":
            logs.append(e.data["message"])
    return rows, logs


def test_the_cable_measurement_checks_itself_against_the_golden_sample(registry, tmp_path):
    golden = cable_run(registry, tmp_path, "golden", 0.6)
    rows, _ = measure(registry, cable_params(run=str(golden), tolerances=TOLERANCES), 0.6)
    assert rows["points"][0]["golden_verdict"] == "PASS" and rows["points"][0]["golden_failed"] == 0
    assert [r["check"] for r in rows["golden"]] == ["loss_db (value)", "max_loss_db"]
    rows, logs = measure(registry, cable_params(run=str(golden), tolerances=TOLERANCES), 0.9)
    summary = rows["points"][0]
    assert summary["golden_verdict"] == "FAIL" and summary["golden_failed"] == 2
    assert all(not r["passed"] for r in rows["golden"]) and rows["golden"][0]["difference"] > 0.2
    assert any("golden sample: loss_db" in m for m in logs)
    assert "verdict" not in summary  # the limit verdict is another thing (there is no limit here)


def test_a_golden_sample_that_cannot_be_read_is_no_data_not_a_failed_run(registry, tmp_path):
    params = cable_params(run=str(tmp_path / "missing.jsonl"), tolerances=TOLERANCES)
    rows, logs = measure(registry, params, 0.6)
    assert rows["points"][0]["golden_verdict"] == "NO DATA" and "golden" not in rows
    assert any("golden sample check not done" in m for m in logs)


def test_the_golden_parameter_is_checked_with_its_field(registry):
    def problems(**golden):
        return [(p.path, str(p)) for p in registry.create("cable", cable_params(**golden)).check()]

    assert problems(name="RG58", tolerances=TOLERANCES) == []
    assert [p for p, _ in problems(tolerances=TOLERANCES)] == ["golden.name"]
    bad = problems(name="RG58", tolerances={"curves": [{"trace": "loss_db", "tolerance": -1}]})
    assert bad[0][0] == "golden.tolerances" and "negative" in bad[0][1]
    assert [p for p, _ in problems(name="RG58")] == ["golden.tolerances"]
    assert problems() == []  # both fields of the editor empty: no golden sample
    p = cable_params()
    p["golden"] = "RG58"
    assert [x.path for x in registry.create("cable", p).check()] == ["golden"]


def test_the_project_finds_the_golden_sample_by_its_name(registry, tmp_path):
    from ola.measurement import MeasurementError
    from ola.project import MeasurementFile, Project
    from ola.project_session import ProjectSession

    project = Project.new("P", tmp_path / "proj")
    ref = project.add_measurement("cable", "unit 7", registry)
    params = cable_params(name="RG58 1m", tolerances=TOLERANCES)
    MeasurementFile(type="cable", role_bindings={"vna": ["vna1"]}, params=params).save(
        project.directory / ref.file
    )
    project.save()
    session = ProjectSession(
        project,
        registry,
        connect=lambda n, cancel=None: SimVna(length_m=2.0, loss_db_per_m_at_1ghz=0.6),
    )
    with pytest.raises(MeasurementError, match="no golden sample called 'RG58 1m'"):
        session.build_runner(ref)
    set_golden(project.directory, "RG58 1m", cable_run(registry, tmp_path, "golden", 0.6))
    assert session.resolve_golden({"x": 1}) == {"x": 1}
    named = cable_params(run="somewhere.jsonl", tolerances=TOLERANCES)
    assert session.resolve_golden(named) is named
    runner, path = session.build_runner(ref)
    assert runner.measurement.params["golden"]["run"].endswith("golden/RG58_1m.jsonl")
    runner.start()
    assert runner.join(30) and runner.state.value == "finished", runner.error
    text = path.read_text(encoding="utf-8")
    assert "RG58_1m.jsonl" in text.splitlines()[0]  # which golden sample, saved with the run
    assert '"golden_verdict": "PASS"' in text


# ---- the same step in the other VNA measurements ------------------------------------------------
from ola.sim_vna import SimAmplifier  # noqa: E402

# module: (example block of its guide, the good unit, a different one, a curve, its view, tolerance)
MODULES = {
    "filter": (
        "filter.md", "filter\\.flt",
        lambda: SimVna(filter_type="bandpass", filter_f0_hz=868e6, filter_bw_hz=20e6,
                       filter_order=3),
        lambda: SimVna(filter_type="bandpass", filter_f0_hz=878e6, filter_bw_hz=20e6,
                       filter_order=3),
        "S21", "magnitude_db", 1.0,
    ),
    "amplifier": (
        "amplifier.md", "amplifier\\.amp", lambda: SimAmplifier(), lambda: SimAmplifier(gain_db=17),
        "S21", "magnitude_db", 1.0,
    ),
    "attenuator": (
        "attenuator.md", "attenuator\\.att",
        lambda: SimVna(attenuator_db=10.2, attenuator_slope_db_per_ghz=0.05),
        lambda: SimVna(attenuator_db=11.0, attenuator_slope_db_per_ghz=0.05),
        "attenuation_db", "value", 0.3,
    ),
    "return_loss": (
        "return-loss.md", "return_loss\\.rtl", lambda: SimVna(termination="antenna"),
        lambda: SimVna(termination="antenna", antenna_f0_hz=900e6),
        "return_loss_db", "value", 1.0,
    ),
    "antenna": (
        "antenna.md", "antenna\\.ant", lambda: SimVna(termination="antenna"),
        lambda: SimVna(termination="antenna", antenna_f0_hz=900e6),
        "return_loss_db", "value", 1.0,
    ),
}  # fmt: skip


def module_run(registry, module, params, vna, path=None):
    runner = Runner(registry.create(module, params), {"vna": [vna]})
    if path is not None:
        runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(60) and runner.state.value == "finished", runner.error
    return [e.data["values"] for e in runner.drain()
            if e.kind == "point" and e.data["table"] == "points"]  # fmt: skip


@pytest.mark.parametrize("module", sorted(MODULES))
def test_every_vna_measurement_checks_itself_against_a_golden_sample(registry, tmp_path, module):
    import json as _json
    import re as _re
    from pathlib import Path

    doc, block, good, other, trace, view, tolerance = MODULES[module]
    text = (Path(__file__).parent.parent / "docs" / doc).read_text(encoding="utf-8")
    params = _json.loads(_re.search(rf"```json {block}\n(.*?)```", text, _re.S).group(1))
    params["confirm_setup"] = False
    params.pop("compression", None)  # the gain only: the compression test has no curve to compare
    golden = tmp_path / f"{module}_golden_20261103_100000.jsonl"
    module_run(registry, module, params, good(), golden)
    tolerances = {"curves": [{"trace": trace, "view": view, "tolerance": tolerance}]}
    params["golden"] = {"run": str(golden), "tolerances": tolerances}
    assert [p for p in registry.create(module, params).check() if p.severity == "error"] == []
    same = module_run(registry, module, params, good())
    assert same[-1]["golden_verdict"] == "PASS", module
    different = module_run(registry, module, params, other())
    assert different[-1]["golden_verdict"] == "FAIL" and different[-1]["golden_failed"] == 1
    bad = dict(params, golden={"name": "x", "tolerances": {"curves": []}})
    assert any(p.path == "golden.tolerances" for p in registry.create(module, bad).check())


def test_without_a_golden_sample_the_context_is_left_alone():
    from ola.golden import GoldenRecorder, recording

    ctx = object()
    assert recording(ctx, "filter", {}) is ctx and recording(ctx, "filter", {"golden": {}}) is ctx
    assert isinstance(recording(ctx, "filter", {"golden": {"name": "x"}}), GoldenRecorder)


# ---- tolerances from several good units ---------------------------------------------------------
def test_tolerances_are_worked_out_from_good_units_and_pass_them(registry, tmp_path):
    from ola.golden import derive_tolerances

    golden = load_run(cable_run(registry, tmp_path, "golden", 0.60))
    good = [
        load_run(cable_run(registry, tmp_path, f"good{n}", loss, stamp=f"2026110{n}_100000"))
        for n, loss in ((4, 0.62), (5, 0.58), (6, 0.61))
    ]
    spec = derive_tolerances(golden, good, [("S21", "loss_db")], ["max_loss_db"], factor=1.5)
    line = spec["curves"][0]["tolerance"]
    assert 2 <= len(line) <= 42 and [x for x, _ in line] == sorted(x for x, _ in line)
    assert line[0][1] == pytest.approx(0.05)  # the floor: at 1 MHz they are all the same
    assert line[-1][1] > line[0][1]  # the units differ more at the top of the band
    worst = 2 * 0.02 * 1.73  # 0.02 dB/m more over 2 m, growing as the root of the frequency
    assert line[-1][1] == pytest.approx(1.5 * worst, rel=0.25)
    assert set(spec["summary"]) == {"max_loss_db"}
    for unit in good:  # every unit it was made from passes
        assert check_against_golden(unit, golden, spec).verdict == "PASS"
    worn = load_run(cable_run(registry, tmp_path, "worn", 0.75, stamp="20261109_100000"))
    assert check_against_golden(worn, golden, spec).verdict == "FAIL"


def test_the_line_is_never_tighter_than_a_good_unit_between_its_points(registry, tmp_path):
    from ola.golden import derive_tolerances

    golden = load_run(cable_run(registry, tmp_path, "golden", 0.60))
    good = [load_run(cable_run(registry, tmp_path, "good", 0.66, stamp="20261104_100000"))]
    for points in (4, 7, 40, 1000):
        spec = derive_tolerances(golden, good, [("S21", "loss_db")], [], 1.0, 0.0, points)
        assert check_against_golden(good[0], golden, spec).verdict == "PASS", points


def test_tolerances_need_good_units_and_curves_they_have(registry, tmp_path):
    from ola.golden import derive_tolerances

    golden = load_run(cable_run(registry, tmp_path, "golden", 0.60))
    good = load_run(cable_run(registry, tmp_path, "good", 0.62, stamp="20261104_100000"))
    with pytest.raises(GoldenError, match="at least one good unit"):
        derive_tolerances(golden, [])
    with pytest.raises(GoldenError, match="factor"):
        derive_tolerances(golden, [good], factor=0)
    with pytest.raises(GoldenError, match="S99"):
        derive_tolerances(golden, [good], [("S99", "value")])
    with pytest.raises(GoldenError, match="nothing"):
        derive_tolerances(golden, [good], [], [])
    every = derive_tolerances(golden, [good])  # no curve, all the figures of the summary
    assert "max_loss_db" in every["summary"] and "curves" not in every


def test_the_script_works_the_tolerances_out(registry, tmp_path, capsys):
    import json as _json

    from scripts.golden_check import main

    golden = cable_run(registry, tmp_path, "golden", 0.60)
    good = cable_run(registry, tmp_path, "good", 0.62, stamp="20261104_100000")
    out = tmp_path / "tol.json"
    args = ["--derive", str(golden), str(good), "--derive-curve", "S21:loss_db", "--out", str(out)]
    assert main(args) == 0
    spec = _json.loads(out.read_text(encoding="utf-8"))
    assert spec["curves"][0]["trace"] == "S21" and "max_loss_db" in spec["summary"]
    capsys.readouterr()
    assert main([str(good), str(golden), "--spec", str(out)]) == 0
    with pytest.raises(SystemExit):
        main(["--derive", str(golden)])  # the golden run alone: refused by the parser
