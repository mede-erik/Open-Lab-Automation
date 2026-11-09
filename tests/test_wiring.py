# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Connection diagrams: every module's file is valid, the texts, conditions and the drawing."""

import json
import re
from pathlib import Path

import pytest

from ola import wiring
from ola.labels import Box, Line, Text, render_svg
from ola.registry import default_registry

LANGS = ("en", "it", "fr", "es", "de")
EXAMPLE = {
    "nodes": [
        {"id": "a", "role": "vna", "at": [0, 0], "title": {"en": "VNA", "it": "VNA IT"},
         "ports": [{"id": "p", "side": "right", "label": {"en": "Port {n|1}"}}]},
        {"id": "b", "kind": "device", "at": [1, 0], "title": "{device.label|Thing}",
         "ports": [{"id": "x", "side": "left", "label": "In"},
                   {"id": "y", "side": "left", "label": "Out", "when": "extra"}]},
        {"id": "c", "at": [1, 1], "when": "!device.label", "title": "Hidden when named",
         "ports": [{"id": "z", "side": "left", "label": "Z"}]}],
    "links": [{"from": "a.p", "to": "b.x", "label": {"en": "lead", "it": "cavo"}},
              {"from": "a.p", "to": "c.z", "when": "!device.label", "style": "dashed"}],
    "notes": [{"en": "Calibrate", "it": "Calibra"}, {"when": "extra", "text": "Extra note"}],
}  # fmt: skip


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def modules_with_wiring(registry):
    return [i for i in registry.list() if (Path(i.path) / "wiring.json").is_file()]


# ---- every module's file -----------------------------------------------------------------------
def test_the_measurements_that_use_the_instruments_have_a_diagram(registry):
    ids = {i.id for i in modules_with_wiring(registry)}
    assert {
        "cable", "return_loss", "antenna", "filter", "attenuator", "amplifier", "ripple",
        "efficiency",
    } <= ids  # fmt: skip


def test_every_diagram_builds_in_every_language_with_the_starting_parameters(registry):
    import sys

    for info in modules_with_wiring(registry):
        raw = wiring.load_wiring(info.path)
        module = sys.modules[registry.load_class(info.id).__module__]
        params = module.default_params() if hasattr(module, "default_params") else {}
        for lang in LANGS:
            diagram = wiring.diagram_for(raw, params, {}, lang)
            assert not diagram.empty or info.id == "time_log", (info.id, lang)  # it needs channels
            assert diagram.links or not diagram.nodes, (info.id, lang)
            assert not any("{" in n.title or "{" in n.title for n in diagram.nodes)
            assert not any("{" in line for line in wiring.connection_lines(diagram))
            assert wiring.layout(diagram).items or not diagram.nodes


def test_every_text_has_every_language(registry):
    """A text written as a dictionary needs all five languages (the editor shows them all)."""

    def check(value, where):
        if isinstance(value, dict) and set(value) & set(LANGS):
            assert set(value) == set(LANGS), where
            placeholders = {
                tuple(re.findall(r"\{([\w.]+)(?:\|[^}]*)?\}", v)) for v in value.values()
            }
            assert len(placeholders) == 1, f"{where}: the {{fields}} differ between languages"
        elif isinstance(value, dict):
            for key, item in value.items():
                check(item, f"{where}.{key}")
        elif isinstance(value, list):
            for n, item in enumerate(value):
                check(item, f"{where}[{n}]")

    for info in modules_with_wiring(registry):
        check(wiring.load_wiring(info.path), info.id)


def test_every_field_named_in_a_diagram_is_a_parameter_of_the_module(registry):
    """``{scope.channel}`` and ``when`` name parameters: they must exist in the module's schema
    (the names a ``foreach`` makes up, like ``v`` in ``v.name``, are not parameters)."""

    def walk(value, loop, found):
        if isinstance(value, dict):
            names = set(loop)
            for path, name in value.get("foreach", []):
                if path.split(".")[0] not in names:  # v.reads follows v: not a parameter
                    found.add(path)
                names.add(name)
            conditions = value.get("when")
            for c in conditions if isinstance(conditions, list) else [conditions]:
                path = re.sub(r"^!", "", c).split("=")[0].rstrip("!") if c else ""
                if path and path.split(".")[0] not in names:
                    found.add(path)
            for item in value.values():
                walk(item, names, found)
        elif isinstance(value, list):
            for item in value:
                walk(item, loop, found)
        elif isinstance(value, str):
            for field in re.findall(r"\{([A-Za-z_][\w.]*)(?:\|[^}]*)?\}", value):
                if field.split(".")[0] not in loop:
                    found.add(field)

    for info in modules_with_wiring(registry):
        raw = wiring.load_wiring(info.path)
        found: set = set()
        walk(raw, set(), found)
        for path in found:
            assert path.split(".")[0] in info.params_schema, (info.id, path)


def test_the_diagram_follows_the_parameters(registry):
    raw = wiring.load_wiring(registry.get("amplifier").path)
    plain = wiring.diagram_for(raw, {"device": {"label": "LNA #1"}})
    padded = wiring.diagram_for(raw, {"input_attenuation_db": 10})
    assert [n.id for n in plain.nodes] == ["vna", "dut"] and len(plain.links) == 2
    assert [n.id for n in padded.nodes] == ["vna", "att", "dut"] and len(padded.links) == 3
    assert plain.node("dut").title == "LNA #1" and padded.node("dut").title == "Amplifier"
    assert padded.node("att").title == "10 dB attenuator"
    cable = wiring.load_wiring(registry.get("cable").path)
    thru = wiring.diagram_for(cable, {})
    refl = wiring.diagram_for(cable, {"mode": "reflection", "termination": "short"})
    assert {n.id for n in thru.nodes} == {"vna", "dut"} and len(thru.links) == 2
    assert {n.id for n in refl.nodes} == {"vna", "dut", "short"}
    assert wiring.diagram_for(cable, {"mode": "reflection"}).node("open").title == "Open"
    ripple = wiring.load_wiring(registry.get("ripple").path)
    assert "load" not in {n.id for n in wiring.diagram_for(ripple, {}).nodes}
    with_load = wiring.diagram_for(
        ripple, {"conditions": {"currents_a": [1]}, "scope": {"channel": 3}}
    )
    assert with_load.node("scope").ports[0].label == "CH3" and "load" in {
        n.id for n in with_load.nodes
    }


# ---- the file format ---------------------------------------------------------------------------
def test_fields_defaults_languages_and_names():
    d = wiring.diagram_for(
        EXAMPLE, {"device": {"label": "LNA"}, "n": 2.0}, {"vna": ["A", "B"]}, "it"
    )
    assert d.node("a").title == "VNA IT" and d.node("a").subtitle == "A, B"
    assert d.node("a").ports[0].label == "Port 2"  # {n|1} -> 2 (a float prints without .0)
    assert d.node("b").title == "LNA" and [p.id for p in d.node("b").ports] == ["x"]
    assert [n.id for n in d.nodes] == ["a", "b"]  # c is for an unnamed device
    assert wiring.connection_lines(d) == ["VNA IT Port 2 -> LNA In (cavo)"]
    assert d.notes == ["Calibra"]
    d2 = wiring.diagram_for(EXAMPLE, {"extra": True}, None, "xx")  # unknown language: English
    assert d2.node("b").title == "Thing" and d2.node("a").title == "VNA"
    assert d2.notes == ["Calibrate", "Extra note"] and [p.id for p in d2.node("b").ports] == [
        "x",
        "y",
    ]
    assert [n.id for n in d2.nodes] == ["a", "b", "c"] and d2.links[1].dashed


@pytest.mark.parametrize(
    "condition,params,expected",
    [
        (None, {}, True), ("a", {"a": 1}, True), ("a", {"a": 0}, False), ("a", {}, False),
        ("!a", {}, True), ("!a", {"a": [1]}, False), ("a.b", {"a": {"b": "x"}}, True),
        ("m=reflection", {"m": "reflection"}, True), ("m=reflection", {}, False),
        ("m!=reflection", {}, True), ("m!=reflection", {"m": "reflection"}, False),
        (["a", "!b"], {"a": 1}, True), (["a", "!b"], {"a": 1, "b": 1}, False),
    ],
)  # fmt: skip
def test_conditions(condition, params, expected):
    assert wiring.is_on(condition, params) is expected


def test_a_link_to_a_port_that_is_not_drawn_is_an_error():
    bad = {"nodes": EXAMPLE["nodes"], "links": [{"from": "a.p", "to": "b.y"}]}  # y needs 'extra'
    with pytest.raises(wiring.WiringError, match="no such node or port"):
        wiring.diagram_for(bad, {})


def test_loading(tmp_path):
    assert wiring.load_wiring(tmp_path) is None
    (tmp_path / "wiring.json").write_text("{", encoding="utf-8")
    with pytest.raises(wiring.WiringError, match="cannot read"):
        wiring.load_wiring(tmp_path)
    (tmp_path / "wiring.json").write_text('{"nodes": []}', encoding="utf-8")
    with pytest.raises(wiring.WiringError, match="non-empty list"):
        wiring.load_wiring(tmp_path)
    (tmp_path / "wiring.json").write_text(json.dumps(EXAMPLE), encoding="utf-8")
    assert wiring.load_wiring(tmp_path)["nodes"][0]["id"] == "a"


# ---- the drawing -------------------------------------------------------------------------------
def boxes(drawing):
    return [i for i in drawing.items if isinstance(i, Box)]


def separate(a, b):
    """True if two boxes do not touch."""
    return a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y


def contains(a, b):
    """True if box ``b`` is inside box ``a`` (the inner frame of a device)."""
    return a.x <= b.x and a.y <= b.y and b.x + b.w <= a.x + a.w and b.y + b.h <= a.y + a.h


def test_the_boxes_do_not_overlap_and_everything_is_inside_the_page(registry):
    import sys

    for info in modules_with_wiring(registry):
        raw = wiring.load_wiring(info.path)
        module = sys.modules[registry.load_class(info.id).__module__]
        base = module.default_params() if hasattr(module, "default_params") else {}
        for params in (base, {**base, "input_attenuation_db": 6, "mode": "reflection",
                              "conditions": {"currents_a": [1]}}):  # fmt: skip
            d = wiring.layout(wiring.diagram_for(raw, params, {"vna": ["Some VNA"]}))
            outer = [b for b in boxes(d)]
            for n, a in enumerate(outer):
                for b in outer[n + 1 :]:
                    apart = separate(a, b)
                    inside = contains(a, b) or contains(b, a)
                    assert apart or inside, (info.id, a, b)  # a device has an inner frame
            for item in d.items:
                if isinstance(item, Line):
                    assert 0 <= min(item.x1, item.x2) and max(item.x1, item.x2) <= d.width
                    assert 0 <= min(item.y1, item.y2) and max(item.y1, item.y2) <= d.height


def test_the_text_of_a_box_fits_its_box(registry):
    from ola.labels import text_width

    raw = wiring.load_wiring(registry.get("ripple").path)
    d = wiring.layout(
        wiring.diagram_for(
            raw,
            {"conditions": {"currents_a": [1]}},
            {"oscilloscope": ["A very long instrument name"]},
        )
    )
    frame = boxes(d)
    for text in (i for i in d.items if isinstance(i, Text)):
        if text.anchor != "middle":
            continue
        width = text_width(text.text, text.size, text.bold)
        assert (
            any(
                b.x <= text.x - width / 2 + 1e-6 and text.x + width / 2 <= b.x + b.w + 1e-6
                for b in frame
            )
            or text.size == wiring.LINK_MM
        ), text.text


def test_links_are_right_angled_and_the_drawing_writes_as_svg(registry):
    raw = wiring.load_wiring(registry.get("filter").path)
    d = wiring.layout(wiring.diagram_for(raw, {"filter": {"label": "SAW"}}, {"vna": ["LiteVNA"]}))
    for line in (i for i in d.items if isinstance(i, Line)):
        assert line.x1 == line.x2 or line.y1 == line.y2
    svg = render_svg(d)
    assert svg.startswith("<svg") and "LiteVNA" in svg and "SAW" in svg and "test lead" in svg


def test_a_far_port_label_is_right_aligned():
    d = wiring.layout(wiring.diagram_for(EXAMPLE, {}))
    anchors = {t.text: t.anchor for t in d.items if isinstance(t, Text)}
    assert anchors["Port 1"] == "end" and anchors["In"] == "start"
    assert 'text-anchor="end"' in render_svg(d)


# ---- the steps ---------------------------------------------------------------------------------
PARAMS = {
    "variables": [
        {"name": "vin", "set": {"instrument": "psu1", "call": "set_voltage"},
         "reads": {"daq": {"instrument": "daq1", "args": {"channels": "101"}}}},
        {"name": "iin",
         "reads": {"daq": {"instrument": "daq1", "args": {"channels": "102"}, "scale": 10}}},
    ],
    "device": {"label": "X"},
}  # fmt: skip


def test_a_step_is_a_text_or_a_dictionary_of_languages_or_an_object():
    raw = [
        "Plain {device.label}",
        {"en": "English {device.label|none}", "it": "Italiano {device.label|nessuno}"},
        {"text": "Only with a label", "when": "device.label"},
        {"text": "Only without a label", "when": "!device.label"},
    ]
    assert wiring.steps_for(raw, PARAMS, "it") == [
        "Plain X", "Italiano X", "Only with a label",
    ]  # fmt: skip
    assert wiring.steps_for(raw, {}, "xx") == ["Plain ?", "English none", "Only without a label"]


def test_foreach_repeats_a_step_for_every_item_and_nests():
    raw = [
        {"text": "{v_number}. {v.name}", "foreach": [["variables", "v"]]},
        {"text": "{v.name}/{r.key}: channel {r.args.channels}",
         "foreach": [["variables", "v"], ["v.reads", "r"]], "when": "r.args.channels"},
        {"text": "{v.name} is set by {v.set.instrument}", "foreach": [["variables", "v"]],
         "when": "v.set"},
        {"text": "nothing", "foreach": [["missing", "m"]]},
    ]  # fmt: skip
    assert wiring.steps_for(raw, PARAMS, "en") == [
        "1. vin", "2. iin", "vin/daq: channel 101", "iin/daq: channel 102",
        "vin is set by psu1",
    ]  # fmt: skip


def test_a_dictionary_is_repeated_with_its_keys_and_a_plain_value_has_a_value():
    params = {"limits": {"max": 3, "min": 1}}
    raw = [{"text": "{x.key}={x.value}", "foreach": [["limits", "x"]]}]
    assert wiring.steps_for(raw, params, "en") == ["max=3", "min=1"]


def test_the_efficiency_says_where_each_instrument_goes(registry):
    from ola.demo_lab import demo_params

    raw = wiring.load_wiring(registry.get("efficiency").path)
    steps = wiring.diagram_for(raw, demo_params(), {}, "en").steps
    assert "Connect channel 101 of daq1 to «vin» of the converter." in steps
    assert (
        "Connect channel 102 of daq1 to «iin» of the converter (the reading is multiplied by 10)."
        in steps
    )
    assert "Connect channel 103 of daq1 to «vout» of the converter." in steps
    assert (
        "Connect channel 1 of psu1 to «vin» of the converter: it sets «vin» (set_voltage)." in steps
    )
    assert "Connect load1 to «iout» of the converter: it sets «iout» (set_current_level)." in steps
    assert not any("psu1" in s and "read_voltage" in s for s in steps)  # an internal reading
    it = wiring.diagram_for(raw, demo_params(), {}, "it").steps
    assert "Collega il canale 101 di daq1 a «vin» del convertitore." in it


def test_the_time_log_says_what_goes_where(registry):
    raw = wiring.load_wiring(registry.get("time_log").path)
    params = {"channels": [{"name": "temp", "instrument": "daq1", "args": {"channels": "201"}},
                           {"name": "vout", "instrument": "dmm1"}]}  # fmt: skip
    d = wiring.diagram_for(raw, params)
    assert d.steps == ["Connect «temp» to daq1, channel 201.", "Connect «vout» to dmm1."]
    assert not d.nodes and wiring.layout(d).width == 0
    assert wiring.diagram_for(raw, {}).empty  # no channels: nothing to show


def test_every_module_with_a_diagram_has_steps_in_every_language(registry):
    import sys

    for info in modules_with_wiring(registry):
        raw = wiring.load_wiring(info.path)
        assert raw.get("steps"), info.id
        module = sys.modules[registry.load_class(info.id).__module__]
        params = module.default_params() if hasattr(module, "default_params") else {}
        counts = {len(wiring.diagram_for(raw, params, {}, lang).steps) for lang in LANGS}
        assert len(counts) == 1, (info.id, counts)  # the same steps in every language


# ---- the pictures ------------------------------------------------------------------------------
def test_the_first_picture_that_fits_and_exists_is_chosen(tmp_path):
    for name in ("plain.svg", "att_en.svg", "att_it.svg"):
        (tmp_path / name).write_text("x")
    images = [
        {"file": "att_{lang}.svg", "when": "input_attenuation_db"},
        {"file": "plain.svg"},
    ]
    warnings = []
    assert wiring.pick_image(images, {}, "en", tmp_path, warnings) == tmp_path / "plain.svg"
    assert wiring.pick_image(images, {"input_attenuation_db": 6}, "it", tmp_path, warnings) == (
        tmp_path / "att_it.svg"
    )
    assert wiring.pick_image(images, {"input_attenuation_db": 6}, "fr", tmp_path, warnings) == (
        tmp_path / "att_en.svg"
    )  # no French picture: the English one
    only = [{"file": "gone_{lang}.png"}]
    assert wiring.pick_image(only, {}, "de", tmp_path, warnings) is None and warnings
    assert wiring.pick_image(images, {}, "en", None, []) is None


def test_a_listed_picture_that_is_missing_is_reported_and_the_next_one_is_tried(tmp_path):
    (tmp_path / "b.svg").write_text("x")
    warnings = []
    chosen = wiring.pick_image([{"file": "a.svg"}, {"file": "b.svg"}], {}, "en", tmp_path, warnings)
    assert chosen == tmp_path / "b.svg" and warnings == ["picture not found: a.svg"]


def test_the_diagram_carries_the_picture_and_the_warning(tmp_path):
    raw = {"nodes": EXAMPLE["nodes"], "images": [{"file": "nope.png"}]}
    d = wiring.diagram_for(raw, {}, None, "en", tmp_path)
    assert d.image is None and d.warnings and d.nodes  # falls back to the drawn diagram
    (tmp_path / "nope.png").write_bytes(b"x")
    assert wiring.diagram_for(raw, {}, None, "en", tmp_path).image == tmp_path / "nope.png"


def test_a_file_may_have_only_steps_or_only_pictures(tmp_path):
    (tmp_path / "wiring.json").write_text('{"steps": ["Do it"]}', encoding="utf-8")
    assert wiring.diagram_for(wiring.load_wiring(tmp_path), {}).steps == ["Do it"]
    (tmp_path / "wiring.json").write_text('{"images": [{"file": "a.svg"}]}', encoding="utf-8")
    assert wiring.load_wiring(tmp_path)["images"]
    (tmp_path / "wiring.json").write_text('{"notes": ["x"]}', encoding="utf-8")
    with pytest.raises(wiring.WiringError, match="'nodes', 'steps' or 'images'"):
        wiring.load_wiring(tmp_path)


def test_a_name_without_an_extension_finds_svg_png_jpg_and_a_missing_optional_one_is_silent(
    tmp_path,
):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.JPG").write_bytes(b"x")
    (tmp_path / "c.svg").write_text("x")
    warnings = []
    assert wiring.pick_image([{"file": "a"}], {}, "en", tmp_path, warnings) == tmp_path / "a.png"
    assert wiring.pick_image([{"file": "c"}], {}, "en", tmp_path, warnings) == tmp_path / "c.svg"
    assert wiring.pick_image([{"file": "a.png"}], {}, "en", tmp_path, warnings) is not None
    assert (
        wiring.pick_image([{"file": "nope", "optional": True}], {}, "en", tmp_path, warnings)
        is None
    )
    assert warnings == []
    assert wiring.pick_image([{"file": "nope"}], {}, "en", tmp_path, warnings) is None
    assert warnings == ["picture not found: nope"]


def test_the_pictures_a_module_lists_can_be_dropped_in(registry, tmp_path):
    """Every module lists the pictures it would like, all optional: with none there is no warning,
    and a picture put next to wiring.json is used for the parameters it is meant for."""
    for info in modules_with_wiring(registry):
        raw = wiring.load_wiring(info.path)
        for entry in raw.get("images", []):
            assert entry.get("optional"), (info.id, entry)  # none ships a missing file
        assert wiring.diagram_for(raw, {}, None, "en", info.path).warnings == [], info.id
    raw = wiring.load_wiring(registry.get("amplifier").path)
    (tmp_path / "amplifier_with_attenuator.png").write_bytes(b"x")
    with_att = wiring.diagram_for(raw, {"input_attenuation_db": 6}, None, "en", tmp_path)
    assert with_att.image == tmp_path / "amplifier_with_attenuator.png"
    assert wiring.diagram_for(raw, {}, None, "en", tmp_path).image is None  # no plain one yet
    cable = wiring.load_wiring(registry.get("cable").path)
    (tmp_path / "cable_reflection_short.svg").write_text("x")
    short = {"mode": "reflection", "termination": "short"}
    assert wiring.diagram_for(cable, short, None, "en", tmp_path).image is not None
    assert wiring.diagram_for(cable, {"mode": "reflection"}, None, "en", tmp_path).image is None
