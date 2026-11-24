# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Editable label templates: free lines, validation and the file of the user."""

import json

import pytest

from ola.assets import Asset
from ola.label_templates import LabelTemplate, LabelTemplateError, TemplateStore, problems
from ola.labels import PRESETS, build_drawing, fill_line, render_svg, unknown_placeholders

CARD = Asset(
    "DUT-0007", "converter", "Buck 5V", "step down", {"topology": "buck"},
    serial="A12", owner="Erik", created="2026-11-24",
)  # fmt: skip


def texts(drawing):
    return [i.text for i in drawing.items if hasattr(i, "text")]


def test_a_line_takes_the_data_of_the_card():
    assert fill_line("{id}", CARD) == "DUT-0007"
    assert fill_line("Owner: {owner}  S/N {serial}", CARD) == "Owner: Erik S/N A12"
    assert fill_line("{name} / {description}", CARD) == "Buck 5V / step down"


def test_a_line_with_nothing_to_show_is_empty_and_literal_text_stays():
    assert fill_line("Rev {version}", CARD) == ""  # no version: the whole line goes
    assert fill_line("Property of the lab", CARD) == "Property of the lab"
    assert fill_line("{version} {name}", CARD) == "Buck 5V"  # one empty place, the other has data
    assert fill_line("{nonsense} {name}", CARD) == "{nonsense} Buck 5V"
    assert unknown_placeholders("{id} {nope} {name}") == ["nope"]


def test_the_free_lines_replace_the_ticked_fields():
    template = LabelTemplate("Bench", 60, 30, lines=("{id}", "Rev {version}", "Owner {owner}"))
    drawing = build_drawing(template.to_spec(), CARD)
    shown = texts(drawing)
    assert "DUT-0007" in shown and "Owner Erik" in shown
    assert not any("Rev" in t for t in shown) and "Buck 5V" not in shown
    assert "DUT-0007" in render_svg(drawing)


def test_lines_that_do_not_fit_are_dropped_from_the_end_and_reported():
    template = LabelTemplate(
        "Tiny", 30, 12, lines=("{id}",) + tuple(f"line {n} {{name}}" for n in range(8))
    )
    drawing = build_drawing(template.to_spec(), CARD)
    assert drawing.dropped and drawing.dropped[0].startswith("line 7")
    assert "DUT-0007" in texts(drawing)  # the code is always kept


def test_what_is_wrong_with_a_template_is_said():
    ok = LabelTemplate("Mine", 60, 30, lines=("{id}", "{name}"))
    assert problems(ok) == []
    assert any("code" in p for p in problems(LabelTemplate("x", lines=("{name}",))))
    assert any("unknown" in p for p in problems(LabelTemplate("x", lines=("{id}", "{nope}"))))
    assert any("built-in" in p for p in problems(LabelTemplate("50x25")))
    assert any("name" in p for p in problems(LabelTemplate("  ")))
    assert any("width" in p for p in problems(LabelTemplate("x", width_mm=5)))
    assert any("layout" in p for p in problems(LabelTemplate("x", layout="round")))
    assert any("at most" in p for p in problems(LabelTemplate("x", lines=["{id}"] * 13)))
    assert any("longer" in p for p in problems(LabelTemplate("x", lines=("{id}" + "a" * 90,))))
    assert any("at least" in p for p in problems(LabelTemplate("x", lines=())))


def test_the_store_keeps_the_templates_in_a_file(tmp_path):
    path = tmp_path / "t.json"
    store = TemplateStore(path)
    assert store.names() == []
    store.put(LabelTemplate("A", 60, 30, lines=("{id}", "{name}")))
    store.put(LabelTemplate("B", 40, 20, "flag", ("{id}",), qr=False, border=True))
    again = TemplateStore(path)
    assert again.names() == ["A", "B"]
    b = again.get("B")
    assert (b.layout, b.qr, b.border, tuple(b.lines)) == ("flag", False, True, ("{id}",))
    spec = b.to_spec()
    assert spec.layout == "flag" and spec.lines == ("{id}",) and spec.width_mm == 40


def test_a_template_can_be_renamed_in_place_but_not_duplicated_by_name(tmp_path):
    store = TemplateStore(tmp_path / "t.json")
    store.put(LabelTemplate("A"))
    store.put(LabelTemplate("B"))
    with pytest.raises(LabelTemplateError, match="already"):
        store.put(LabelTemplate("A"))
    store.put(LabelTemplate("C", 70, 30), replace="A")
    assert store.names() == ["C", "B"] and store.get("C").width_mm == 70
    store.put(LabelTemplate("B", 55, 25), replace="B")  # the same name, edited
    assert store.get("B").width_mm == 55
    with pytest.raises(LabelTemplateError):
        store.put(LabelTemplate("D", lines=("{name}",)))  # not valid: nothing is saved
    assert TemplateStore(tmp_path / "t.json").names() == ["C", "B"]


def test_delete_and_duplicate(tmp_path):
    store = TemplateStore(tmp_path / "t.json")
    store.put(LabelTemplate("A"))
    assert store.delete("A") is True and store.delete("A") is False
    copy = store.duplicate("50x25")  # a built-in format is the starting point of a new one
    assert copy.name == "50x25 copy" and copy.width_mm == PRESETS["50x25"].width_mm
    assert "{id}" in copy.lines and problems(copy) == []
    assert store.duplicate("50x25").name == "50x25 copy 2"
    with pytest.raises(LabelTemplateError):
        store.duplicate("nothing")


def test_a_damaged_file_is_reported_and_left_alone(tmp_path):
    path = tmp_path / "t.json"
    path.write_text("{broken")
    with pytest.raises(LabelTemplateError):
        TemplateStore(path)
    assert path.read_text() == "{broken"
    path.write_text(json.dumps({"templates": [{"width_mm": 3}]}))
    with pytest.raises(LabelTemplateError):
        TemplateStore(path)


def test_the_default_file_follows_the_environment(tmp_path, monkeypatch):
    from ola.label_templates import default_path

    monkeypatch.setenv("OLA_LABEL_TEMPLATES", str(tmp_path / "x.json"))
    assert default_path() == tmp_path / "x.json"
