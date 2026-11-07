# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The aging of a cable: its loss against the date, from the runs that used its code."""

import pytest

from ola.registry import default_registry
from ola.runner import Runner
from ola.runs import RunWriter
from ola.sim_vna import SimVna
from ola.trend import (
    DAY,
    TrendError,
    TrendPoint,
    assess,
    export_csv,
    figures,
    fit_line,
    format_trend,
    parse_when,
    series,
    trend_for,
)

CODE = "CBL-0042"


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def cable_run(registry, folder, stamp, loss, code=CODE, finish=True):
    params = {
        "mode": "transmission",
        "sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 101, "scale": "linear"},
        "cable": {"label": "RG58 #3", "length_m": 2.0, "asset_id": code},
        "frequencies_of_interest": [868e6],
        "confirm_setup": False,
    }
    runner = Runner(
        registry.create("cable", params),
        {"vna": [SimVna(length_m=2.0, loss_db_per_m_at_1ghz=loss)]},
    )
    folder.mkdir(exist_ok=True)
    path = folder / f"cable_{code}_{stamp}.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    runner.start()
    assert runner.join(20)
    if not finish:
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    return path


def points(values, start="2026-01-01 10:00", step_days=30.0):
    t0 = parse_when(start)
    return [TrendPoint(f"d{i}", t0 + i * step_days * DAY, v, None) for i, v in enumerate(values)]


# ---- the line ---------------------------------------------------------------------------------
def test_the_line_through_a_straight_series_is_exact():
    line = fit_line(points([1.0, 1.1, 1.2, 1.3], step_days=10))
    assert line["slope"] * DAY == pytest.approx(0.01)
    assert line["rms"] < 1e-12 and line["se"] < 1e-12
    with pytest.raises(TrendError, match="at least two"):
        fit_line(points([1.0]))
    with pytest.raises(TrendError, match="same time"):
        fit_line(points([1.0, 1.1], step_days=0))


def test_a_steady_cable_passes_and_noise_is_not_aging():
    steady = assess(points([1.00, 1.02, 0.99, 1.01, 1.00, 1.01]), limit=3.0)
    assert steady.verdict == "PASS" and not steady.significant and steady.direction == "steady"
    assert steady.limit_date is None


def test_a_cable_that_gets_worse_is_followed_to_its_limit():
    # +0.1 dB every 30 days: 1.217 dB a year, the limit 2.0 is crossed in about 200 days
    trend = assess(points([1.0, 1.1, 1.2, 1.3, 1.4]), limit=2.0, warn_within_days=365)
    assert trend.significant and trend.direction == "worse"
    assert trend.rate_per_year == pytest.approx(1.2175, rel=1e-3)
    assert trend.days_to_limit == pytest.approx(180, abs=1.5)
    assert trend.verdict == "WARNING" and "reaches the limit 2" in trend.reasons[0]
    assert trend.limit_date is not None
    # without the warning window the same series is fine
    assert assess(points([1.0, 1.1, 1.2, 1.3, 1.4]), limit=2.0).verdict == "PASS"
    assert (
        assess(points([1.0, 1.1, 1.2, 1.3, 1.4]), limit=2.0, warn_within_days=30).verdict == "PASS"
    )


def test_a_cable_past_the_limit_or_too_fast_fails():
    past = assess(points([1.0, 1.5, 2.1]), limit=2.0)
    assert past.verdict == "FAIL" and "past the limit" in past.reasons[0]
    fast = assess(points([1.0, 1.1, 1.2, 1.3]), max_rate_per_year=0.5)
    assert fast.verdict == "FAIL" and "per year" in fast.reasons[0]
    assert assess(points([1.0, 1.1, 1.2, 1.3]), max_rate_per_year=5).verdict == "PASS"


def test_a_figure_that_should_stay_high_is_followed_the_other_way():
    falling = points([20.0, 19.0, 18.0, 17.0])  # a return loss that gets worse as it falls
    worse = assess(falling, limit=10.0, warn_within_days=3000, higher_is_worse=False)
    assert worse.verdict == "WARNING" and worse.direction == "better"  # the number rises or falls
    assert worse.days_to_limit == pytest.approx(210, abs=3)
    below = assess(points([12.0, 11.0, 9.0]), limit=10.0, higher_is_worse=False)
    assert below.verdict == "FAIL"


def test_a_cable_that_gets_better_is_not_a_problem():
    better = assess(points([1.4, 1.3, 1.2, 1.1]), limit=2.0, max_rate_per_year=0.1)
    assert better.verdict == "PASS" and better.rate_per_year < 0 and better.limit_date is None


def test_too_few_measurements_say_so():
    for values, count in (([], 0), ([1.0], 1), ([1.0, 1.1], 2)):
        t = assess(points(values))
        assert t.verdict == "NOT ENOUGH DATA", count
    same_day = assess(points([1.0, 1.1, 1.2], step_days=0.01))
    assert same_day.verdict == "NOT ENOUGH DATA" and "over 0.0 day" in same_day.reasons[-1]
    assert assess(points([1.0, 1.1], step_days=60), min_points=2).verdict == "PASS"


def test_wrong_options_are_refused():
    with pytest.raises(TrendError, match="limit must be a number"):
        assess(points([1.0, 1.1, 1.2]), limit="big")


# ---- from the run files -----------------------------------------------------------------------
def test_the_series_comes_from_the_runs_of_the_cable(registry, tmp_path):
    runs = tmp_path / "runs"
    for stamp, loss in (("20260101_100000", 0.60), ("20260401_100000", 0.65),
                        ("20260701_100000", 0.72), ("20261001_100000", 0.80)):  # fmt: skip
        cable_run(registry, runs, stamp, loss)
    cable_run(registry, runs, "20260501_100000", 0.50, code="CBL-0099")  # another cable
    cable_run(registry, runs, "20260601_100000", 0.90, finish=False)  # did not finish
    got = series(CODE, [runs, tmp_path / "missing"], "loss_868MHz_db")
    assert [p.when[:10] for p in got] == ["2026-01-01", "2026-04-01", "2026-07-01", "2026-10-01"]
    values = [p.value for p in got]
    assert values == sorted(values) and values[0] < values[-1] < 2 * values[0]
    assert "loss_868MHz_db" in figures(CODE, [runs]) and "max_loss_db" in figures(CODE, [runs])
    assert series(CODE, [runs], "no_such_figure") == [] and series("CBL-0001", [runs]) == []
    assert series(CODE, [runs], "loss_868MHz_db", measurement="filter") == []


def test_the_trend_of_a_worn_cable_is_found_from_its_runs(registry, tmp_path):
    runs = tmp_path / "runs"
    for stamp, loss in (("20260101_100000", 0.60), ("20260401_100000", 0.65),
                        ("20260701_100000", 0.72), ("20261001_100000", 0.80)):  # fmt: skip
        cable_run(registry, runs, stamp, loss)
    trend = trend_for(CODE, [runs], "max_loss_db", limit=2.5, max_rate_per_year=0.2)
    assert trend.verdict == "FAIL" and trend.direction == "worse"
    assert trend.first < trend.last and trend.rate_per_year > 0.2
    text = format_trend(trend)
    assert "max_loss_db: FAIL" in text and "2026-10-01" in text and "per year" in text
    # the same cable, by a gentler rule
    ok = trend_for(CODE, [runs], "max_loss_db", limit=20.0, max_rate_per_year=5.0)
    assert ok.verdict == "PASS"


def test_the_series_can_be_exported(registry, tmp_path):
    runs = tmp_path / "runs"
    cable_run(registry, runs, "20260101_100000", 0.6)
    cable_run(registry, runs, "20260401_100000", 0.7)
    out = tmp_path / "trend.csv"
    export_csv(series(CODE, [runs], "max_loss_db"), out)
    rows = out.read_text(encoding="utf-8").splitlines()
    assert (
        rows[0] == "date,value,run" and len(rows) == 3 and rows[1].startswith("2026-01-01 10:00,")
    )


def test_the_script_gives_the_verdict_as_an_exit_code(registry, tmp_path, capsys):
    from scripts.cable_trend import main

    runs = tmp_path / "runs"
    for stamp, loss in (("20260101_100000", 0.60), ("20260401_100000", 0.65),
                        ("20260701_100000", 0.72), ("20261001_100000", 0.80)):  # fmt: skip
        cable_run(registry, runs, stamp, loss)
    base = [CODE, str(runs)]
    assert main(base + ["--limit", "20", "--max-rate", "5"]) == 0
    assert main(base + ["--limit", "2.5", "--max-rate", "0.2"]) == 1
    assert "FAIL" in capsys.readouterr().out
    assert main(base + ["--list-figures"]) == 0 and "max_loss_db" in capsys.readouterr().out
    out = tmp_path / "t.csv"
    assert main(base + ["--csv", str(out)]) == 0 and out.is_file()
    with pytest.raises(SystemExit):
        main(base + ["--limit", "x"])  # not a number: refused by the parser
    assert main(["CBL-9999", str(runs)]) == 1  # no measurement: not enough data
