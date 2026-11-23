# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Loads made of real resistors: equivalent resistance with tolerance, power in each resistor."""

import pytest

from ola.resistors import LoadError, channels_of, parse_load, parse_loads

R10 = {"name": "10R", "r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"}
PARALLEL = {
    "name": "22||47",
    "parallel": [
        {"r_ohm": 22, "tol_pct": 1, "power_w": 2, "channel": "202"},
        {"r_ohm": 47, "tol_pct": 5, "power_w": 2, "channel": "203"},
    ],
}
MIXED = {
    "name": "10+(22||47)",
    "series": [
        {"r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"},
        {"parallel": PARALLEL["parallel"]},
    ],
}


def test_one_resistor_is_a_range_from_its_tolerance():
    nominal, low, high = parse_load(R10).resistance()
    assert (nominal, low, high) == (10, pytest.approx(9.9), pytest.approx(10.1))
    assert parse_load({"r_ohm": 4.7}).resistance() == (4.7, 4.7, 4.7)  # no tolerance: exact


def test_series_add_and_parallel_combine_with_the_tolerances_in_the_worst_direction():
    load = parse_load(PARALLEL)
    nominal, low, high = load.resistance()
    assert nominal == pytest.approx(1 / (1 / 22 + 1 / 47))  # 14.99 ohm
    assert low == pytest.approx(1 / (1 / (22 * 0.99) + 1 / (47 * 0.95)))
    assert high == pytest.approx(1 / (1 / (22 * 1.01) + 1 / (47 * 1.05)))
    assert low < nominal < high
    series = parse_load({"series": [{"r_ohm": 10, "tol_pct": 10}, {"r_ohm": 22, "tol_pct": 5}]})
    assert series.resistance() == (32, pytest.approx(9 + 20.9), pytest.approx(11 + 23.1))


def test_groups_nest():
    nominal, low, high = parse_load(MIXED).resistance()
    parallel = 1 / (1 / 22 + 1 / 47)
    assert nominal == pytest.approx(10 + parallel)
    assert low == pytest.approx(9.9 + 1 / (1 / (22 * 0.99) + 1 / (47 * 0.95)))
    assert high == pytest.approx(10.1 + 1 / (1 / (22 * 1.01) + 1 / (47 * 1.05)))


def test_the_names_and_relays_of_a_load():
    load = parse_load(MIXED)
    assert load.name == "10+(22||47)" and load.channels() == ["201", "202", "203"]
    assert [r.name for r in load.resistors()] == [
        "10+(22||47).1",
        "10+(22||47).2.1",
        "10+(22||47).2.2",
    ]
    assert parse_load({"r_ohm": 3}, index=2).name == "load3"
    assert parse_load({"r_ohm": 3}, index=2).root.name == "load3"
    assert parse_load({"name": "x", "r_ohm": 3}).channels() == []  # no relay
    loads = parse_loads([R10, PARALLEL, MIXED])
    assert channels_of(loads) == ["201", "202", "203"]  # each relay once


def test_the_power_in_each_resistor_is_an_upper_bound():
    # one resistor: V^2 / its lowest value, as a fraction of its rating
    ((resistor, power, fraction),) = parse_load(R10).loading(5.0)
    assert resistor.name == "10R" and power == pytest.approx(25 / 9.9)
    assert fraction == pytest.approx(25 / 9.9 / 5)
    # parallel: the same voltage on both
    both = parse_load(PARALLEL).loading(5.0)
    assert [round(p, 3) for _r, p, _f in both] == [
        round(25 / (22 * 0.99), 3),
        round(25 / (47 * 0.95), 3),
    ]
    # series: the current is the same, so the larger resistor takes the larger power
    series = parse_load({"series": [{"r_ohm": 10, "power_w": 5}, {"r_ohm": 90, "power_w": 5}]})
    small, big = [p for _r, p, _f in series.loading(10.0)]  # 0.1 A: 0.1 W and 0.9 W
    assert small == pytest.approx(0.1) and big == pytest.approx(0.9)
    # no rating: no fraction, and most_loaded has nothing to say
    assert parse_load({"r_ohm": 10}).loading(5.0)[0][2] is None
    assert parse_load({"r_ohm": 10}).most_loaded(5.0) == (None, 0.0)
    resistor, fraction = parse_load(MIXED).most_loaded(10.0)
    assert resistor.name in {"10+(22||47).1", "10+(22||47).2.1", "10+(22||47).2.2"} and fraction > 0
    assert parse_load(R10).loading(-5.0)[0][1] == pytest.approx(
        25 / 9.9
    )  # the sign does not matter


@pytest.mark.parametrize(
    "raw,text",
    [
        ("10R", "must be an object"),
        ({"r_ohm": 0}, "above 0"),
        ({"r_ohm": "10"}, "above 0"),
        ({"r_ohm": 10, "tol_pct": 100}, "from 0 to below 100"),
        ({"r_ohm": 10, "power_w": 0}, "above 0"),
        ({"r_ohm": 10, "channel": 201}, "must be text"),
        ({"r_ohm": 10, "colour": "red"}, "unknown field"),
        ({"name": "", "r_ohm": 10}, "must be text"),
        ({"series": [{"r_ohm": 1}]}, "at least two"),
        ({"series": "x"}, "at least two"),
        ({"series": [{"r_ohm": 1}, {"r_ohm": 2}], "r_ohm": 3}, "not both"),
        (
            {"series": [{"r_ohm": 1}, {"r_ohm": 2}], "parallel": [{"r_ohm": 1}, {"r_ohm": 2}]},
            "not both",
        ),
        ({"series": [{"r_ohm": 1}, {"r_ohm": 2}], "tol_pct": 1}, "unknown field"),
        ({"series": [{"r_ohm": 1}, {"r_ohm": -2}]}, r"series\[1\].r_ohm"),
    ],
)
def test_a_wrong_description_says_where_and_why(raw, text):
    with pytest.raises(LoadError, match=text):
        parse_load(raw, "loads[0]")


def test_nesting_and_size_are_limited():
    deep = {"r_ohm": 1}
    for _ in range(18):
        deep = {"series": [deep, {"r_ohm": 1}]}
    with pytest.raises(LoadError, match="nested too deep"):
        parse_load(deep)
    many = {"parallel": [{"r_ohm": 1}] * 65}
    with pytest.raises(LoadError, match="too many resistors"):
        parse_load(many)


def test_a_list_of_loads_needs_distinct_names():
    assert [x.name for x in parse_loads([R10, PARALLEL])] == ["10R", "22||47"]
    with pytest.raises(LoadError, match="give a list of loads"):
        parse_loads([])
    with pytest.raises(LoadError, match="give a list of loads"):
        parse_loads(None)
    with pytest.raises(LoadError, match=r"loads\[1\].name: two loads are called '10R'"):
        parse_loads([R10, {"name": "10R", "r_ohm": 5}])
    with pytest.raises(LoadError, match=r"loads\[1\].r_ohm"):
        parse_loads([R10, {"name": "x", "r_ohm": -1}])


# ---- in words and as a schematic --------------------------------------------------------------
def test_a_resistance_is_written_as_on_the_resistor():
    from ola.resistors import _value

    assert [_value(v) for v in (22, 4.7, 0.47, 2200, 2.2e6, 1000, 1e6)] == [
        "22", "4.7", "0.47", "2.2k", "2.2M", "1k", "1M",
    ]  # fmt: skip


def test_the_load_is_described_in_words_nested_as_written():
    from ola.resistors import describe

    assert describe(parse_load({"r_ohm": 22})) == "22 ohm = 22 ohm"
    assert describe(parse_load(R10)) == (
        "10 ohm (+/-1 %, 5 W) = 10 ohm, 9.9 to 10.1 ohm with the tolerances"
    )
    text = describe(parse_load(MIXED))
    assert text.startswith("10 ohm (+/-1 %, 5 W) in series with (22 ohm (+/-1 %, 2 W) in parallel")
    assert "with 47 ohm (+/-5 %, 2 W)) = 24.99 ohm" in text and "with the tolerances" in text
    both = describe(
        parse_load({"parallel": [{"series": [{"r_ohm": 1}, {"r_ohm": 2}]}, {"r_ohm": 3}]})
    )
    assert both.startswith("(1 ohm in series with 2 ohm) in parallel with 3 ohm = ")


def test_the_schematic_draws_every_resistor_inside_the_picture():
    import xml.etree.ElementTree as ET

    from ola.labels import Box, Line, Text, render_svg
    from ola.resistors import schematic

    for raw, count in ((R10, 1), (PARALLEL, 2), (MIXED, 3)):
        load = parse_load(raw)
        drawing = schematic(load)
        boxes = [i for i in drawing.items if isinstance(i, Box)]
        assert len(boxes) == count
        texts = [i.text for i in drawing.items if isinstance(i, Text)]
        assert load.name in texts and "+" in texts and "−" in texts
        for r in load.resistors():
            assert f"{r.r_ohm:g} Ω" in texts
        for item in drawing.items:  # nothing outside the picture
            if isinstance(item, Box):
                assert 0 <= item.x and item.x + item.w <= drawing.width
                assert 0 <= item.y and item.y + item.h <= drawing.height
            if isinstance(item, Line):
                for x, y in ((item.x1, item.y1), (item.x2, item.y2)):
                    assert -1e-9 <= x <= drawing.width + 1e-9 and -1e-9 <= y <= drawing.height
        root = ET.fromstring(render_svg(drawing))  # a well-formed SVG
        assert root.tag.endswith("svg")


def test_in_the_schematic_the_resistors_are_where_series_and_parallel_put_them():
    from ola.labels import Box
    from ola.resistors import schematic

    def boxes(raw):
        return [i for i in schematic(parse_load(raw)).items if isinstance(i, Box)]

    series = boxes({"series": [{"r_ohm": 1}, {"r_ohm": 2}, {"r_ohm": 3}]})
    assert [round(b.y, 6) for b in series] == [round(series[0].y, 6)] * 3  # side by side
    assert series[0].x < series[1].x < series[2].x
    parallel = boxes({"parallel": [{"r_ohm": 1}, {"r_ohm": 2}, {"r_ohm": 3}]})
    assert parallel[0].y < parallel[1].y < parallel[2].y  # one above the other
    assert len({round(b.x, 6) for b in parallel}) == 1
    wide = boxes({"parallel": [{"series": [{"r_ohm": 1}, {"r_ohm": 2}]}, {"r_ohm": 3}]})
    assert wide[0].y < wide[2].y and wide[0].x < wide[1].x  # a series in the first branch


def test_a_resistor_of_a_kit_must_be_resolved_before_it_is_used():
    from ola.resistors import has_refs

    ref = {"kit": "PWR", "ref": "R22"}
    assert has_refs(ref) and has_refs([R10, {"series": [R10, ref]}]) and not has_refs(R10)
    assert not has_refs({**R10, "kit": "PWR", "ref": "R10"})  # values and where they came from
    with pytest.raises(LoadError, match="'R22' of a kit is not resolved"):
        parse_load({"name": "x", "series": [R10, ref]}, "loads[0]")
    kept = parse_load({**R10, "kit": "PWR", "ref": "R10"}).root
    assert (kept.kit, kept.ref, kept.r_ohm) == ("PWR", "R10", 10)
