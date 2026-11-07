"""The logic of the results comparison tool, on run files made by real measurements."""

import csv
import json
import math
import os
import time

import pytest

from ola.compare import (
    CompareError,
    curve,
    difference,
    difference_stats,
    export_overlay_csv,
    load_run,
    measured_name,
    mixed_types,
    points_columns,
    run_date,
    summary_table,
    trace_names,
)
from ola.registry import default_registry
from ola.runner import Runner
from ola.runs import RunWriter
from ola.sim_vna import SimVna


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def cable_run(registry, tmp_path, label, length=2.0, loss=0.6, stamp="20261103_100000"):
    """A real cable measurement on a simulated cable, written to a run file."""
    params = {
        "mode": "transmission",
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 301, "scale": "linear"},
        "cable": {"label": label, "length_m": length},
        "frequencies_of_interest": [868e6],
        "confirm_setup": False,
    }
    runner = Runner(
        registry.create("cable", params),
        {"vna": [SimVna(length_m=length, loss_db_per_m_at_1ghz=loss)]},
    )
    path = tmp_path / f"cable_{label.replace(' ', '_')}_{stamp}.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(20)
    return path


# ---- loading ------------------------------------------------------------------------------------
def test_a_run_is_loaded_with_its_name_date_curves_and_summary(registry, tmp_path):
    path = cable_run(registry, tmp_path, "RG58 #3")
    run = load_run(path)
    assert run.name == "RG58 #3" and run.measurement == "cable" and run.state == "finished"
    assert run.when == "2026-11-03 10:00" and run.label == "RG58 #3 - 2026-11-03 10:00"
    assert {"S21", "loss_db", "group_delay_ns"} <= set(run.traces)
    assert isinstance(run.traces["S21"]["y"][0], complex)  # stored as pairs, loaded as numbers
    assert run.summary["cable"] == "RG58 #3" and run.summary["length_m"] == 2.0
    assert load_run(path, label="my cable").label == "my cable"


def test_the_name_of_what_was_measured_comes_from_the_parameters():
    assert measured_name({"cable": {"label": " A "}}) == "A"
    assert measured_name({"device": {"label": "ant"}, "cable": {"label": ""}}) == "ant"
    assert measured_name({"filter": {"label": "f1"}}) == "f1"
    assert measured_name({"cable": {"length_m": 1}}) == "" and measured_name({}) == ""


def test_the_date_comes_from_the_file_name_or_the_file(tmp_path):
    assert run_date(tmp_path / "x_20260102_030405.jsonl") == "2026-01-02 03:04"
    plain = tmp_path / "plain.jsonl"
    plain.write_text("")
    assert run_date(plain) == time.strftime(
        "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(plain))
    )


@pytest.mark.parametrize(
    "text,words",
    [
        ("", "no header"),
        ("not json at all\n", "no header"),
        ('{"kind": "run", "run_id": "x", "measurement": "m", "params": {}}\n', "no results"),
    ],
)
def test_a_file_that_cannot_be_compared_says_why(tmp_path, text, words):
    path = tmp_path / "bad_20261103_100000.jsonl"
    path.write_text(text)
    with pytest.raises(CompareError, match=words):
        load_run(path)
    with pytest.raises(CompareError, match="cannot read"):
        load_run(tmp_path / "missing.jsonl")


def test_an_interrupted_run_is_still_read(registry, tmp_path):
    path = cable_run(registry, tmp_path, "cut")
    lines = path.read_text().splitlines()
    kept = [line for line in lines if '"kind": "end"' not in line]  # no end line
    path.write_text("\n".join(kept) + "\n")
    assert load_run(path).state == "interrupted"


# ---- curves in common ---------------------------------------------------------------------------
def test_common_curves_are_listed_with_how_many_runs_have_them(registry, tmp_path):
    a = load_run(cable_run(registry, tmp_path, "A"))
    b = load_run(cable_run(registry, tmp_path, "B", stamp="20261103_110000"))
    names = dict(trace_names([a, b]))
    assert names["S21"] == 2 and names["loss_db"] == 2
    other = load_run(cable_run(registry, tmp_path, "C", stamp="20261103_120000"))
    other.traces["only_here"] = other.traces["loss_db"]
    listed = trace_names([a, b, other])
    assert listed[-1] == ("only_here", 1) and all(n == 3 for _, n in listed[:-1])


def test_a_curve_in_a_view(registry, tmp_path):
    run = load_run(cable_run(registry, tmp_path, "A"))
    x, y = curve(run, "S21", "loss_db")
    assert len(x) == 301 and y[0] < y[-1] and y[-1] > 0  # the loss grows with the frequency
    assert curve(run, "loss_db", "value")[1] == pytest.approx(
        y
    )  # the same, as the measurement made it
    with pytest.raises(CompareError, match="no curve 'nothing'"):
        curve(run, "nothing", "value")


# ---- the difference between two curves ----------------------------------------------------------
def test_the_difference_of_two_real_cables_is_the_difference_of_their_loss(registry, tmp_path):
    a = load_run(cable_run(registry, tmp_path, "A", length=1.0))
    b = load_run(cable_run(registry, tmp_path, "B", length=3.0, stamp="20261103_110000"))
    xs, d = difference(curve(a, "loss_db", "value"), curve(b, "loss_db", "value"))
    assert len(xs) == 301
    assert d[0] < d[-1]  # B (3 m) loses more than A (1 m), more at the top
    ratio = d[-1] / curve(a, "loss_db", "value")[1][-1]
    assert ratio == pytest.approx(2.0, rel=0.01)  # 3 m - 1 m = twice the loss of 1 m
    stats = difference_stats(xs, d)
    assert stats["max_abs"] == pytest.approx(d[-1]) and stats["at_x"] == xs[-1]
    assert stats["points"] == 301 and 0 < stats["mean"] < stats["max_abs"]
    assert stats["rms"] >= abs(stats["mean"])


def test_the_difference_uses_only_the_overlap_and_invents_nothing():
    ref = ([1.0, 2.0, 3.0, 4.0], [0.0, 0.0, 0.0, 0.0])
    other = ([2.5, 3.5], [10.0, 20.0])  # covers only 3 on the reference grid
    xs, d = difference(ref, other)
    assert xs == [3.0] and d == [pytest.approx(15.0)]  # read between its points
    assert difference(ref, ([10.0, 11.0], [1.0, 2.0])) == ([], [])  # no overlap
    assert difference(([], []), other) == ([], []) and difference(ref, ([], [])) == ([], [])


def test_difference_stats_keep_the_sign_of_the_largest_difference():
    stats = difference_stats([1, 2, 3], [0.5, -2.0, 1.0])
    assert stats["max_abs"] == -2.0 and stats["at_x"] == 2
    assert stats["mean"] == pytest.approx(-1 / 6) and stats["rms"] == pytest.approx(
        math.sqrt(5.25 / 3)
    )
    assert difference_stats([], []) == {}


# ---- the summary figures ------------------------------------------------------------------------
def test_the_summary_figures_side_by_side_with_the_change_from_the_reference(registry, tmp_path):
    a = load_run(cable_run(registry, tmp_path, "A", length=1.0))
    b = load_run(cable_run(registry, tmp_path, "B", length=3.0, stamp="20261103_110000"))
    rows = {r["key"]: r for r in summary_table([a, b], reference=0)}
    row = rows["loss_868MHz_db"]
    assert row["values"][1] > row["values"][0]
    assert row["deltas"][0] is None and row["deltas"][1] == pytest.approx(
        row["values"][1] - row["values"][0]
    )
    assert rows["cable"]["values"] == ["A", "B"] and rows["cable"]["deltas"] == [
        None,
        None,
    ]  # text: no delta
    # with the other run as the reference the change reverses
    back = {r["key"]: r for r in summary_table([a, b], reference=1)}["loss_868MHz_db"]
    assert back["deltas"][0] == pytest.approx(-row["deltas"][1]) and back["deltas"][1] is None


def test_a_figure_only_one_run_has_is_shown_without_a_change(registry, tmp_path):
    a = load_run(cable_run(registry, tmp_path, "A"))
    b = load_run(cable_run(registry, tmp_path, "B", stamp="20261103_110000"))
    del b.points[0]["velocity_factor"]
    row = {r["key"]: r for r in summary_table([a, b])}["velocity_factor"]
    assert row["values"][1] is None and row["deltas"] == [None, None]


# ---- different kinds of measurement; a table of many points -------------------------------------
def test_runs_of_different_measurements_can_be_loaded_together_and_are_flagged(registry, tmp_path):
    cable = load_run(cable_run(registry, tmp_path, "A"))
    params = {
        "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 101},
        "device": {"label": "whip"},
        "confirm_setup": False,
    }
    runner = Runner(
        registry.create("return_loss", params), {"vna": [SimVna(termination="antenna")]}
    )
    path = tmp_path / "rl_20261103_130000.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(20)
    rl = load_run(path)
    assert mixed_types([cable, rl]) and not mixed_types([cable, cable])
    assert rl.name == "whip"
    assert dict(trace_names([cable, rl]))["S11"] == 1  # a curve only one of them has


def test_efficiency_style_tables_share_their_numeric_columns(tmp_path):
    def table_run(name, scale):
        path = tmp_path / f"{name}_20261103_100000.jsonl"
        lines = [{"kind": "run", "run_id": name, "measurement": "efficiency", "params": {}}]
        for i, vin in enumerate((9, 12, 15)):
            lines.append(
                {
                    "kind": "point",
                    "table": "points",
                    "index": i,
                    "elapsed_s": i,
                    "values": {"vin": vin, "efficiency": 90 + scale * vin, "note": "x"},
                }
            )
        lines.append({"kind": "end", "state": "finished", "error": None})
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
        return load_run(path)

    a, b = table_run("a", 0.1), table_run("b", 0.2)
    assert points_columns([a, b]) == [
        "vin",
        "efficiency",
    ]  # numbers in both; the text column is left out
    assert a.summary == {}  # a table of several points has no summary row
    assert points_columns([]) == []


# ---- export -------------------------------------------------------------------------------------
def test_the_overlay_is_exported_with_a_column_pair_per_run(registry, tmp_path):
    a = load_run(cable_run(registry, tmp_path, "A", length=1.0))
    b = load_run(cable_run(registry, tmp_path, "B", length=3.0, stamp="20261103_110000"))
    out = tmp_path / "overlay.csv"
    assert export_overlay_csv(out, [a, b], "loss_db", "value") == 301
    rows = list(csv.reader(open(out)))
    assert rows[0] == [f"x [{a.label}]", f"y [{a.label}]", f"x [{b.label}]", f"y [{b.label}]"]
    assert float(rows[1][0]) == 1e6 and float(rows[-1][3]) > float(rows[-1][1])
    with pytest.raises(CompareError, match="no run has a curve"):
        export_overlay_csv(out, [a, b], "nothing", "value")


def test_a_table_run_gives_lines_like_the_run_window(tmp_path):
    from ola.compare import points_series

    path = tmp_path / "t_20261103_100000.jsonl"
    lines = [{"kind": "run", "run_id": "t", "measurement": "efficiency", "params": {}}]
    for i, (iout, vin) in enumerate([(1, 12), (1, 9), (2, 9), (2, 12)]):
        values = {"vin": vin, "iout": iout, "efficiency": 90 + vin / iout}
        lines.append(
            {"kind": "point", "table": "points", "index": i, "elapsed_s": i, "values": values}
        )
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
    run = load_run(path)
    grouped = points_series(run, "vin", "efficiency", ["iout"])
    assert [label for label, _, _ in grouped] == ["iout=1", "iout=2"]
    assert grouped[0][1] == [9.0, 12.0]  # sorted by x inside a line
    assert points_series(run, "vin", "efficiency")[0][0] == "efficiency"
