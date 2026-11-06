"""Pass / fail limits on a curve."""

import pytest

from ola.limits import LimitError, parse_limits

FREQ = [1e6, 1e9, 2e9, 3e9]


def test_no_limits_means_nothing_to_check():
    limits = parse_limits(None)
    assert limits.empty and parse_limits({}).empty
    verdict = limits.check(FREQ, [1, 2, 3, 4])
    assert verdict.passed and verdict.checked == 0
    assert "no limit" in verdict.summary()


def test_constant_maximum_pass_and_fail():
    limits = parse_limits({"max": 1.5})
    ok = limits.check(FREQ, [0.2, 0.5, 1.0, 1.4])
    assert ok.passed and ok.margin == pytest.approx(0.1) and ok.worst_freq == 3e9
    assert ok.summary().startswith("PASS")
    bad = limits.check(FREQ, [0.2, 1.6, 1.0, 1.7])
    assert not bad.passed and bad.failing == [1e9, 3e9]
    assert bad.margin == pytest.approx(-0.2) and bad.worst_freq == 3e9
    assert "FAIL (2 of 4" in bad.summary()


def test_a_value_exactly_on_the_limit_passes():
    assert parse_limits({"max": 1.0}).check([1e6], [1.0]).passed


def test_minimum():
    limits = parse_limits({"min": 10})
    assert limits.check(FREQ, [12, 11, 10, 15]).passed
    assert limits.check(FREQ, [12, 9, 10, 15]).failing == [1e9]


def test_a_line_between_points_is_straight_and_flat_outside():
    limits = parse_limits({"max": [[1e9, 1.0], [3e9, 2.0]]})
    assert limits.bounds(1e9) == (None, 1.0)
    assert limits.bounds(2e9)[1] == pytest.approx(1.5)
    assert limits.bounds(1e6)[1] == 1.0 and limits.bounds(5e9)[1] == 2.0  # flat outside
    assert not limits.check([2e9], [1.6]).passed and limits.check([2e9], [1.4]).passed


def test_bands_have_their_own_limits_and_leave_the_rest_unchecked():
    limits = parse_limits(
        {"bands": [{"from": 1e9, "to": 2e9, "max": 1.0}, {"from": 2.5e9, "to": 3e9, "min": 0.2}]}
    )
    assert limits.bounds(5e8) == (None, None)
    verdict = limits.check([5e8, 1.5e9, 2.2e9, 2.8e9], [99, 0.9, 99, 0.3])
    assert verdict.passed and verdict.checked == 2  # only two points have a limit
    assert not limits.check([1.5e9], [1.1]).passed
    assert not limits.check([2.8e9], [0.1]).passed


def test_a_band_and_a_general_limit_both_apply_the_stricter_wins():
    limits = parse_limits({"max": 2.0, "bands": [{"from": 1e9, "to": 2e9, "max": 1.0}]})
    assert limits.bounds(1.5e9) == (None, 1.0) and limits.bounds(3e9) == (None, 2.0)
    loose = parse_limits({"max": 1.0, "bands": [{"from": 1e9, "to": 2e9, "max": 2.0}]})
    assert loose.bounds(1.5e9) == (None, 1.0)


def test_lines_for_a_plot():
    limits = parse_limits({"max": 1.5, "min": [[1e6, 0.0], [3e9, 1.0]]})
    lines = limits.lines([1e6, 3e9])
    assert lines["max"] == [(1e6, 1.5), (3e9, 1.5)] and lines["min"] == [(1e6, 0.0), (3e9, 1.0)]
    assert parse_limits({"max": 1}).lines([1, 2]).keys() == {"max"}


@pytest.mark.parametrize(
    "spec,words",
    [
        ({"maximum": 1}, "unknown limit key"),
        ({"max": "high"}, "must be a number"),
        ({"max": []}, "number or a list"),
        ({"max": [[1e6]]}, "each point"),
        ({"max": [[1e6, 1], [1e6, 2]]}, "same frequency"),
        ({"min": 5, "max": 1}, "above"),
        ({"bands": [{"from": 1e9}]}, "'from' and 'to'"),
        ({"bands": [{"from": 2e9, "to": 1e9, "max": 1}]}, "below"),
        ({"bands": [{"from": 1e9, "to": 2e9}]}, "'min' or a 'max'"),
        ({"bands": [{"from": 1e9, "to": 2e9, "min": 3, "max": 1}]}, "above"),
        ("max 1.5", "object"),
    ],
)
def test_wrong_limits_say_what_is_wrong(spec, words):
    with pytest.raises(LimitError, match=words):
        parse_limits(spec)


def test_length_mismatch():
    with pytest.raises(LimitError, match="frequencies"):
        parse_limits({"max": 1}).check([1, 2], [1])
