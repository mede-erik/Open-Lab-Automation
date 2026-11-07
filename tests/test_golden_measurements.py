# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The golden-sample step in the measurements that are not VNA ones: Bode and TDR (one summary
row), ripple, regulation, S-parameters and efficiency (a table of rows, paired by a column)."""

import json
import re
from pathlib import Path

import pytest

from ola.golden import GoldenError, check_against_golden, check_rows, validate_spec
from ola.registry import default_registry
from ola.runner import Runner
from ola.runs import RunWriter

DOCS = Path(__file__).parent.parent / "docs"


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def example(doc, block):
    text = (DOCS / doc).read_text(encoding="utf-8")
    params = json.loads(re.search(rf"```json {block}\n(.*?)```", text, re.S).group(1))
    params["confirm_setup"] = False
    return params


def run(registry, module, params, handles, path=None):
    runner = Runner(registry.create(module, params), handles)
    if path is not None:
        runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(120) and runner.state.value == "finished", runner.error
    tables = {}
    for e in runner.drain():
        if e.kind == "point":
            tables.setdefault(e.data["table"], []).append(e.data["values"])
    return tables


def golden_and_check(registry, tmp_path, module, params, good, other, tolerances, verdict_of):
    """Measure the golden unit, then a copy of it and a different one, with the step on."""
    path = tmp_path / f"{module}_golden_20261103_100000.jsonl"
    run(registry, module, params, good(), path)
    with_golden = dict(params, golden={"run": str(path), "tolerances": tolerances})
    assert registry.create(module, with_golden).validate() == []
    same = run(registry, module, with_golden, good())
    different = run(registry, module, with_golden, other())
    return verdict_of(same), verdict_of(different), different


def summary_verdict(tables):
    return tables["points"][-1]["golden_verdict"]


def rows_verdict(tables):
    return tables["golden_result"][0]["golden_verdict"]


# ---- one summary row ----------------------------------------------------------------------------
def test_bode_checks_the_gain_against_a_golden_circuit(registry, tmp_path):
    from ola.sim_bode import SimBodeLab
    from tests.test_bode import lowpass

    params = example("bode.md", "bode\\.bod")
    params["sweep"]["points"] = 9

    def lab(fc):
        def make():
            bench = SimBodeLab(plant=lowpass(fc))
            return {"generator": [bench.generator], "oscilloscope": [bench.scope]}

        return make

    tolerances = {"curves": [{"trace": "gain_db", "tolerance": 1.0}]}
    same, different, tables = golden_and_check(
        registry, tmp_path, "bode", params, lab(1e3), lab(2e3), tolerances, summary_verdict
    )
    assert (same, different) == ("PASS", "FAIL")
    assert tables["golden"][0]["check"] == "gain_db (value)"


def test_tdr_checks_the_reflections_against_a_golden_cable(registry, tmp_path):
    from ola.sim_vna import SimVna

    params = example("tdr.md", "tdr\\.tdr")

    def vna(**kw):
        return lambda: {"vna": [SimVna(length_m=5.0, termination="open", velocity_factor=0.66,
                                       **kw)]}  # fmt: skip

    tolerances = {"curves": [{"trace": "impulse", "tolerance": 0.05}]}
    same, different, _ = golden_and_check(
        registry, tmp_path, "tdr", params, vna(), vna(fault_at_m=2.0, fault_gamma=0.3),
        tolerances, summary_verdict,
    )  # fmt: skip
    assert (same, different) == ("PASS", "FAIL")  # a fault that the golden cable has not


# ---- a table of rows ----------------------------------------------------------------------------
def test_ripple_pairs_the_rows_by_load_current(registry, tmp_path):
    from ola.sim_scope import SimLoad, SimScope

    params = example("ripple.md", "ripple\\.rpl")

    def bench(per_a):
        def make():
            scope = SimScope(ripple_pp_v=0.010, ripple_per_a_v=per_a, noise_rms_v=0.0005)
            return {"oscilloscope": [scope], "load": [SimLoad(scope)]}

        return make

    tolerances = {"rows": {"match": ["load_current_a"], "columns": {"pp_v": 0.004}}}
    same, different, tables = golden_and_check(
        registry, tmp_path, "ripple", params, bench(0.010), bench(0.020), tolerances, rows_verdict
    )
    assert (same, different) == ("PASS", "FAIL")
    check = tables["golden"][0]
    assert check["check"] == "pp_v (rows)" and "load_current_a=2" in check["detail"]


def test_regulation_pairs_the_rows_by_test_and_point(registry, tmp_path):
    from ola.sim_bench import SimBench

    params = example("regulation.md", "regulation\\.reg")

    def bench(mohm):
        def make():
            b = SimBench(line_mv_per_v=2.0, output_mohm=mohm)
            return {"supply": [b.supply], "load": [b.load], "meter": [b.meter]}

        return make

    golden_rows = run(registry, "regulation", params, bench(40.0)())["points"]
    match = [k for k in ("test", "vin", "i", "vin_v", "i_a") if k in golden_rows[0]][:3]
    column = next(k for k in golden_rows[0] if k.startswith("vout"))
    tolerances = {"rows": {"match": match, "columns": {column: 0.01}}}
    same, different, _ = golden_and_check(
        registry, tmp_path, "regulation", params, bench(40.0), bench(400.0), tolerances,
        rows_verdict,
    )  # fmt: skip
    assert (same, different) == ("PASS", "FAIL")


def test_sparameters_pairs_the_sweeps_and_checks_the_last_curves(registry, tmp_path):
    from ola.sim_vna import SimVna

    params = {"start_hz": 1e6, "stop_hz": 3e9, "points": 101, "sparameters": ["S21"],
              "sweeps": 2}  # fmt: skip

    def vna(loss):
        return lambda: {"vna": [SimVna(library_calls=True, loss_db_per_m_at_1ghz=loss)]}

    tolerances = {
        "rows": {"match": ["sweep"], "columns": {"S21_max_db": 0.2}},
        "curves": [{"trace": "S21", "view": "magnitude_db", "tolerance": 0.2}],
    }
    same, different, tables = golden_and_check(
        registry, tmp_path, "sparameters", params, vna(0.6), vna(1.2), tolerances, rows_verdict
    )
    assert (same, different) == ("PASS", "FAIL")
    assert {r["check"] for r in tables["golden"]} == {"S21 (magnitude_db)", "S21_max_db (rows)"}


def test_efficiency_checks_the_derived_efficiency_point_by_point(registry, tmp_path, monkeypatch):
    from ola import demo_lab

    def lab(efficiency):
        def make():
            monkeypatch.setattr(demo_lab, "EFFICIENCY", efficiency)
            the_lab = demo_lab.DemoLab()
            return {"instruments": [demo_lab.DemoHandle(n, the_lab) for n in demo_lab.INSTRUMENTS]}

        return make

    params = demo_lab.demo_params(samples=1, interval_s=0.0)
    tolerances = {"rows": {"match": ["vin", "iout"], "columns": {"efficiency": 0.5}}}
    path = tmp_path / "efficiency_golden_20261103_100000.jsonl"
    run(registry, "efficiency", params, lab(0.90)(), path)
    with_golden = dict(params, golden={"run": str(path), "tolerances": tolerances})
    assert registry.create("efficiency", with_golden).validate() == []
    assert rows_verdict(run(registry, "efficiency", with_golden, lab(0.90)())) == "PASS"
    worse = run(registry, "efficiency", with_golden, lab(0.85)())
    assert rows_verdict(worse) == "FAIL" and worse["golden"][0]["check"] == "efficiency (rows)"
    bad = dict(params, golden={"name": "x", "tolerances": {"rows": {"match": []}}})
    assert any("rows is" in p for p in registry.create("efficiency", bad).validate())


# ---- the rows themselves ------------------------------------------------------------------------
def test_rows_that_the_run_does_not_have_fail_the_check(registry, tmp_path):
    from ola.golden import run_from_result

    golden = run_from_result(
        "ripple",
        {},
        {},
        points=[{"load_current_a": 0.0, "pp_v": 0.010}, {"load_current_a": 1.0, "pp_v": 0.020}],
    )
    partial = run_from_result("ripple", {}, {}, points=[{"load_current_a": 0.0, "pp_v": 0.010}])
    spec = {"match": ["load_current_a"], "columns": {"pp_v": {"rel": 0.1}}}
    assert not check_rows(partial, golden, spec)[0].passed  # half of the golden rows
    assert check_rows(partial, golden, spec, min_overlap=0.5)[0].passed
    other = run_from_result(
        "ripple",
        {},
        {},
        points=[{"load_current_a": 0.0, "pp_v": 0.0105}, {"load_current_a": 1.0, "pp_v": 0.025}],
    )
    check = check_rows(other, golden, spec)[0]
    assert not check.passed and check.worst == pytest.approx(0.005)
    assert "1 of 2 rows" in check.detail and "load_current_a=1" in check.detail
    missing = run_from_result("ripple", {}, {}, points=[{"load_current_a": 0.0},
                                                        {"load_current_a": 1.0}])  # fmt: skip
    assert check_rows(missing, golden, spec)[0].detail == "no pair of rows has this column"
    result = check_against_golden(other, golden, {"rows": spec})
    assert result.verdict == "FAIL"


def test_the_rows_spec_is_checked():
    assert validate_spec({"rows": {"match": ["i"], "columns": {"v": 0.1}}}) == []
    for rows in ({"match": [], "columns": {"v": 1}}, {"match": ["i"]}, {"match": "i",
                 "columns": {"v": 1}}, []):  # fmt: skip
        assert any("rows is" in p for p in validate_spec({"rows": rows})), rows
    assert any("rows.v" in p for p in validate_spec({"rows": {"match": ["i"],
                                                              "columns": {"v": -1}}}))  # fmt: skip
    from ola.golden import run_from_result

    unit = run_from_result("ripple", {}, {}, points=[{"load_current_a": 0.0, "pp_v": 0.01}])
    with pytest.raises(GoldenError, match="rows is"):
        check_against_golden(unit, unit, {"rows": {"match": []}})


def test_row_tolerances_are_worked_out_from_good_units():
    from ola.golden import derive_tolerances, run_from_result

    def unit(*pp):
        return run_from_result("ripple", {}, {}, points=[
            {"load_current_a": float(i), "pp_v": v} for i, v in enumerate(pp)])  # fmt: skip

    golden = unit(0.010, 0.020)
    good = [unit(0.011, 0.020), unit(0.010, 0.023)]
    spec = derive_tolerances(golden, good, [], [], factor=2, floor=0.001,
                             rows={"match": ["load_current_a"], "columns": ["pp_v"]})  # fmt: skip
    assert spec == {
        "rows": {"match": ["load_current_a"], "columns": {"pp_v": pytest.approx(0.006)}}
    }
    for u in good:
        assert check_against_golden(u, golden, spec).verdict == "PASS"
    assert check_against_golden(unit(0.010, 0.030), golden, spec).verdict == "FAIL"
