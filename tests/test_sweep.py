"""Sweep axes and the nested walk."""

import pytest

from ola.sweep import SweepError, axis_values, iter_points, total_points


def test_list():
    assert axis_values({"values": [9, 12, 15.5]}) == [9.0, 12.0, 15.5]


def test_linear_by_points_includes_both_ends():
    assert axis_values({"start": 0, "stop": 1, "points": 5}) == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert axis_values({"start": 2, "stop": 2, "points": 1}) == [2.0]
    assert axis_values({"start": 5, "stop": 1, "points": 3}) == [5.0, 3.0, 1.0]


def test_linear_by_step_includes_stop_even_with_float_noise():
    assert axis_values({"start": 0, "stop": 1, "step": 0.1})[-1] == pytest.approx(1.0)
    assert len(axis_values({"start": 0, "stop": 1, "step": 0.1})) == 11
    assert axis_values({"start": 1, "stop": 0, "step": -0.5}) == [1.0, 0.5, 0.0]
    assert axis_values({"start": 0, "stop": 1, "step": 3}) == [0.0]  # one point, stop not reached


def test_log():
    v = axis_values({"start": 1, "stop": 1000, "points": 4, "scale": "log"})
    assert v == pytest.approx([1, 10, 100, 1000]) and v[-1] == 1000.0


@pytest.mark.parametrize(
    "spec,message",
    [
        ([], "an axis is an object"),
        ({}, "give 'values'"),
        ({"start": 1}, "give 'values'"),
        ({"start": 1, "stop": 2}, "either 'points' or 'step'"),
        ({"start": 1, "stop": 2, "points": 3, "step": 1}, "either 'points' or 'step'"),
        ({"start": 1, "stop": 2, "points": 0}, "integer >= 1"),
        ({"start": 1, "stop": 2, "points": 2.5}, "integer >= 1"),
        ({"start": 1, "stop": 2, "points": True}, "integer >= 1"),
        ({"start": 1, "stop": 2, "step": 0}, "non-zero"),
        ({"start": 1, "stop": 5, "step": -1}, "towards stop"),
        ({"start": 1, "stop": 5, "points": 3, "scale": "db"}, "'linear' or 'log'"),
        ({"start": 0, "stop": 5, "points": 3, "scale": "log"}, "start > 0"),
        ({"start": 1, "stop": 5, "step": 1, "scale": "log"}, "needs 'points'"),
        ({"start": "1", "stop": 5, "points": 3}, "finite number"),
        ({"start": float("nan"), "stop": 5, "points": 3}, "finite number"),
        ({"start": 1, "stop": float("inf"), "points": 3}, "finite number"),
        ({"values": []}, "non-empty"),
        ({"values": [1, "2"]}, "values\\[1\\]"),
        ({"values": [1], "start": 0}, "do not give"),
        ({"values": [1], "typo": 0}, "unknown field"),
        ({"start": 0, "stop": 1, "points": 10**6}, "too many points"),
        ({"start": 0, "stop": 10**9, "step": 1}, "too many points"),
    ],
)
def test_invalid_axes(spec, message):
    with pytest.raises(SweepError, match=message):
        axis_values(spec)


def test_nested_walk_first_axis_is_the_innermost_and_fastest():
    axes = [("iout", [1, 2, 3]), ("vin", [9, 12])]
    points = list(iter_points(axes))
    assert total_points(axes) == 6 == len(points)
    # iout (first) runs through all its values, then vin (second) advances one step
    assert points[:4] == [
        {"iout": 1, "vin": 9},
        {"iout": 2, "vin": 9},
        {"iout": 3, "vin": 9},
        {"iout": 1, "vin": 12},
    ]


def test_three_axes_each_advances_when_the_previous_one_has_finished():
    axes = [("a", [1, 2]), ("b", [10, 20]), ("c", [100, 200])]
    points = [(p["a"], p["b"], p["c"]) for p in iter_points(axes)]
    assert points == [
        (1, 10, 100),
        (2, 10, 100),
        (1, 20, 100),
        (2, 20, 100),
        (1, 10, 200),
        (2, 10, 200),
        (1, 20, 200),
        (2, 20, 200),
    ]
    assert list(next(iter_points(axes))) == ["a", "b", "c"]  # keys in the order of the axes


def test_no_axes_is_a_single_point():
    assert total_points([]) == 1 and list(iter_points([])) == [{}]
