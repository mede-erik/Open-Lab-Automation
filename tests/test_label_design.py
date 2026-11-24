# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The label of each kind: ready-made designs, one size, manual positions, the file."""

import json

import pytest

from ola.assets import Asset
from ola.label_design import (
    KINDS,
    DEFAULT_LINES,
    Element,
    KindDesign,
    LabelSetup,
    auto_elements,
    build_kind_drawing,
    default_design,
    design_problems,
    sample_asset,
    setup_problems,
)
from ola.label_templates import LabelTemplateError, TemplateStore
from ola.labels import QR, Text, attribute_units, fill_line, placeholder_names


def texts(drawing):
    return [i for i in drawing.items if isinstance(i, Text)]


def positions(d):
    return [(t.text, round(t.x, 2), round(t.y, 2), round(t.size, 2)) for t in texts(d)]


def shown(drawing):
    return [t.text for t in texts(drawing)]


def test_every_kind_has_a_ready_made_label_that_fits():
    setup = LabelSetup()
    for kind in KINDS:
        card = sample_asset(kind)
        drawing = build_kind_drawing(setup, default_design(kind), card)
        assert card.id in shown(drawing) and any(isinstance(i, QR) for i in drawing.items)
        assert not drawing.warnings, (kind, drawing.warnings)
    assert set(DEFAULT_LINES) == set(KINDS)
    assert default_design("something else").lines == DEFAULT_LINES["generic"]


def test_the_default_lines_follow_the_draft():
    cable = shown(build_kind_drawing(LabelSetup(), default_design("cable"), sample_asset("cable")))
    assert cable == ["CAB-0042", "RG316 SMA-SMA", "SMA - SMA 1 m"]  # no measurement: no last line
    att = shown(build_kind_drawing(LabelSetup(), default_design("attenuator"),
                                   sample_asset("attenuator")))  # fmt: skip
    assert att[2] == "10 dB, 6 GHz, 2 W" and att[3] == "SMA"


def test_the_attributes_of_the_cards_are_places_with_their_unit():
    card = sample_asset("attenuator")
    assert fill_line("Att {nominal_db}", card) == "Att 10 dB"
    assert fill_line("{max_frequency} max", card) == "6 GHz max"
    assert fill_line("{kind} by {manufacturer}", card) == "attenuator by"  # no maker: empty place
    assert fill_line("{input_voltage}", sample_asset("converter")) == "12 V"
    assert fill_line("{nominal_db}", sample_asset("cable")) == ""  # a cable has none
    assert {"nominal_db", "topology", "kind", "manufacturer", "serial"} <= set(placeholder_names())
    assert attribute_units()["max_frequency"] == "Hz"


def test_the_size_is_one_for_every_kind():
    setup = LabelSetup(width_mm=70, height_mm=37)
    for kind in ("cable", "converter"):
        drawing = build_kind_drawing(setup, default_design(kind), sample_asset(kind))
        assert (drawing.width, drawing.height) == (70, 37)
    assert setup_problems(setup) == []
    assert any("width" in p for p in setup_problems(LabelSetup(width_mm=3)))
    assert any("layout" in p for p in setup_problems(LabelSetup(layout="round")))


def test_converting_to_manual_keeps_the_label_as_it_was():
    setup = LabelSetup()
    for kind in KINDS:
        card = sample_asset(kind)
        lines = default_design(kind).lines
        manual = KindDesign(tuple(lines), auto_elements(setup, lines, card))
        a = build_kind_drawing(setup, default_design(kind), card)
        b = build_kind_drawing(setup, manual, card)
        pos = positions
        assert pos(a) == pos(b), kind


def test_a_manual_label_puts_each_text_where_the_user_said():
    setup = LabelSetup(width_mm=60, height_mm=30, qr=False)
    design = KindDesign(
        ("{id}",),
        [
            Element("text", "{id}", x=2, y=3, w=56, size=6, bold=True),
            Element("text", "{name}", x=58, y=12, w=40, size=3, align="end"),
            Element("text", "{name}", x=30, y=20, w=20, size=3, align="middle"),
        ],
    )
    drawing = build_kind_drawing(setup, design, sample_asset("cable"))
    first, second, third = texts(drawing)
    assert (first.x, first.y, first.size, first.bold) == (2, 3 + first.size, 6, True)
    assert second.anchor == "end" and second.x == 98  # the right end of its box
    assert third.anchor == "middle" and third.x == 40
    assert any("outside the label" in w for w in drawing.warnings)  # the second one is too wide


def test_a_text_too_long_for_its_box_is_shrunk_then_cut_and_said():
    setup = LabelSetup(qr=False)
    design = KindDesign(("{id}",), [
        Element("text", "{id}", 1, 1, 30, 4, True),
        Element("text", "{description}", 1, 10, 6, 3),
    ])  # fmt: skip
    card = Asset("CBL-0001", "cable", "x", "a very long description of the cable")
    drawing = build_kind_drawing(setup, design, card)
    assert shown(drawing)[1].endswith("…") and "{description}" in drawing.dropped
    assert any("cut" in w for w in drawing.warnings)


def test_the_qr_element_is_placed_and_can_be_left_out():
    design = KindDesign(
        ("{id}",), [Element("qr", x=2, y=2, size=20), Element("text", "{id}", 25, 2, 20, 5)]
    )
    drawing = build_kind_drawing(LabelSetup(), design, sample_asset("cable"))
    qr = next(i for i in drawing.items if isinstance(i, QR))
    assert qr.x > 2 and qr.x + qr.size < 22.01  # the code and its quiet zone fit the square
    none = build_kind_drawing(LabelSetup(qr=False), design, sample_asset("cable"))
    assert not any(isinstance(i, QR) for i in none.items)
    small = KindDesign(
        ("{id}",), [Element("qr", x=0, y=0, size=6), Element("text", "{id}", 8, 1, 30, 4)]
    )
    assert any(
        "too small" in w
        for w in build_kind_drawing(LabelSetup(), small, sample_asset("cable")).warnings
    )


def test_a_flag_is_always_automatic():
    setup = LabelSetup(width_mm=60, height_mm=15, layout="flag", qr=False)
    manual = KindDesign(("{id}", "{name}"), [Element("text", "{id}", 0, 0, 5, 3)])
    drawing = build_kind_drawing(setup, manual, sample_asset("cable"))
    assert shown(drawing).count("CAB-0042") == 2  # both panels of the flag


def test_what_is_wrong_with_a_design_is_said():
    ok = KindDesign(("{id}", "{name}"))
    assert design_problems(ok) == []
    assert any("code" in p for p in design_problems(KindDesign(("{name}",))))
    assert any("unknown" in p for p in design_problems(KindDesign(("{id}", "{nope}"))))
    bad = KindDesign(
        ("{id}",), [Element("text", "{name}", 0, 0, 10, 3), Element("qr"), Element("qr")]
    )
    wrong = design_problems(bad)
    assert any("code" in p for p in wrong) and any("one QR" in p for p in wrong)
    wrong = design_problems(
        KindDesign(("{id}",), [Element("text", "{id}", 0, 0, 0, -1, align="up")])
    )
    assert any("width" in p for p in wrong) and any("size" in p for p in wrong)
    assert any("alignment" in p for p in wrong)
    assert any("type" in p for p in design_problems(KindDesign(("{id}",), [Element("blob")])))


def test_the_store_keeps_the_size_and_the_designs_of_the_user(tmp_path):
    path = tmp_path / "t.json"
    store = TemplateStore(path)
    assert store.setup == LabelSetup() and not store.is_customised("cable")
    assert store.design("cable").lines == DEFAULT_LINES["cable"]
    store.set_setup(LabelSetup(width_mm=62, height_mm=29, border=True))
    mine = KindDesign(("{id}", "Att {nominal_db}"))
    store.set_design("attenuator", mine)
    manual = KindDesign(
        ("{id}",), [Element("text", "{id}", 1, 1, 30, 5, True), Element("qr", 40, 1, 20)]
    )
    store.set_design("cable", manual)
    again = TemplateStore(path)
    assert again.setup.width_mm == 62 and again.setup.border
    assert again.design("attenuator").lines == ("{id}", "Att {nominal_db}")
    assert again.design("cable").manual and again.design("cable").elements[1].type == "qr"
    assert again.design("converter").lines == DEFAULT_LINES["converter"]  # untouched kind
    drawing = again.drawing(sample_asset("attenuator"))
    assert "Att 10 dB" in shown(drawing) and (drawing.width, drawing.height) == (62, 29)
    assert again.reset_design("attenuator") is True and again.reset_design("attenuator") is False
    assert TemplateStore(path).design("attenuator").lines == DEFAULT_LINES["attenuator"]


def test_the_store_refuses_what_is_not_valid_and_still_reads_the_old_file(tmp_path):
    store = TemplateStore(tmp_path / "t.json")
    with pytest.raises(LabelTemplateError):
        store.set_setup(LabelSetup(width_mm=2))
    with pytest.raises(LabelTemplateError):
        store.set_design("cable", KindDesign(("{name}",)))
    assert store.setup == LabelSetup() and not store.designs
    old = tmp_path / "old.json"  # the first version had only the named templates
    old.write_text(json.dumps({"format_version": 1, "templates": []}))
    assert TemplateStore(old).setup == LabelSetup()
    old.write_text(json.dumps({"templates": [], "designs": {"cable": "nope"}}))
    with pytest.raises(LabelTemplateError):
        TemplateStore(old)
