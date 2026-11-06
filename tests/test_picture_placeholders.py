"""The placeholders of the connection pictures: one per picture of the work list, ignored by the
program until they are replaced."""

import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ola import wiring
from ola.registry import default_registry

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "make_picture_placeholders", ROOT / "scripts" / "make_picture_placeholders.py"
)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def listed(registry):
    """Every picture the modules list: (folder, file name)."""
    out = []
    for info in registry.list():
        raw = wiring.load_wiring(info.path)
        for entry in (raw or {}).get("images", []):
            out.append((Path(info.path), entry["file"]))
    return out


def test_the_work_list_is_read_with_all_its_fields(registry):
    entries = script.parse_work_list((ROOT / "docs" / "wiring-images.md").read_text("utf-8"))
    assert len(entries) == len(listed(registry)) == 17
    assert [e["number"] for e in entries] == [str(n) for n in range(1, 18)]
    first = entries[0]
    assert first["file"] == "cable_transmission" and first["folder"] == "ola/modules/cable/"
    assert "trasmissione" in first["when"] and "VNA" in first["draw"] and first["details"]
    assert "\n" not in first["draw"] and "  " not in first["draw"]  # wrapped lines are joined


def test_the_work_list_and_the_modules_name_the_same_pictures(registry):
    entries = script.parse_work_list((ROOT / "docs" / "wiring-images.md").read_text("utf-8"))
    from_doc = {(ROOT / e["folder"], e["file"]) for e in entries}
    assert from_doc == {(folder, name) for folder, name in listed(registry)}


def test_every_picture_has_its_placeholder_in_the_folder_of_its_module(registry):
    for folder, name in listed(registry):
        path = folder / f"{name}.svg"
        assert path.is_file(), f"run scripts/make_picture_placeholders.py: {path} is missing"
        assert wiring.is_placeholder(path), f"{path} is a real drawing or lost its mark"
        root = ET.parse(path).getroot()  # a well-formed SVG
        assert root.tag.endswith("svg") and float(root.get("width")) == 1600
        text = path.read_text(encoding="utf-8")
        assert name in text and "SEGNAPOSTO" in text and wiring.PLACEHOLDER_MARK in text


def test_the_placeholders_say_what_the_work_list_says():
    entries = script.parse_work_list((ROOT / "docs" / "wiring-images.md").read_text("utf-8"))
    for entry in entries:
        svg = (ROOT / entry["folder"] / f"{entry['file']}.svg").read_text(encoding="utf-8")
        assert entry["folder"] in svg
        first_words = " ".join(script.plain(entry["draw"]).split()[:4])
        assert first_words in svg, entry["file"]
        assert "**" not in svg and "`" not in svg  # no markdown marks


def test_the_program_ignores_a_placeholder_and_uses_a_real_drawing(tmp_path):
    (tmp_path / "filter.svg").write_text(
        script.render_placeholder({"file": "filter", "folder": "x/", "title": "Filtro"}),
        encoding="utf-8",
    )
    images = [{"file": "filter", "optional": True}]
    warnings = []
    assert wiring.pick_image(images, {}, "en", tmp_path, warnings) is None and warnings == []
    (tmp_path / "filter.png").write_bytes(b"png")  # a real picture next to the placeholder
    assert wiring.pick_image(images, {}, "en", tmp_path, warnings) == tmp_path / "filter.png"
    (tmp_path / "filter.png").unlink()
    (tmp_path / "filter.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")  # replaced
    assert wiring.pick_image(images, {}, "en", tmp_path, warnings) == tmp_path / "filter.svg"
    assert not wiring.is_placeholder(tmp_path / "filter.svg")
    assert not wiring.is_placeholder(tmp_path / "missing.svg")
    # a listed picture that is not optional and only exists as a placeholder is reported
    (tmp_path / "pad.svg").write_text("<!-- OLA-PLACEHOLDER -->")
    assert wiring.pick_image([{"file": "pad"}], {}, "en", tmp_path, warnings) is None
    assert warnings == ["picture not found: pad"]


def test_a_module_shows_its_own_diagram_while_the_picture_is_a_placeholder(registry):
    from ola.wiring import diagram_for

    for info in registry.list():
        raw = wiring.load_wiring(info.path)
        if raw and raw.get("images") and raw.get("nodes"):
            diagram = diagram_for(raw, {}, None, "en", info.path)
            assert diagram.image is None and diagram.warnings == [], info.id
            assert diagram.nodes, info.id  # the program's drawing is what is shown


def fake_root(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (tmp_path / "ola" / "modules" / "m").mkdir(parents=True)
    (docs / "wiring-images.md").write_text(
        "## 1. First\n\n* **File**: `one`\n* **Cartella**: `ola/modules/m/`\n"
        "* **Quando si vede**: always.\n* **Cosa disegnare**: a box and\n  a line.\n"
        "* **Dettagli**: with **bold** and `code`.\n\n---\n\n# Foglio\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "LIST", docs / "wiring-images.md")
    return tmp_path / "ola" / "modules" / "m"


def test_the_script_writes_missing_placeholders_and_never_overwrites_a_drawing(
    tmp_path, monkeypatch, capsys
):
    folder = fake_root(tmp_path, monkeypatch)
    assert script.main(["--check"]) == 0
    assert "missing      ola/modules/m/one.svg" in capsys.readouterr().out
    assert not (folder / "one.svg").exists()  # --check writes nothing
    assert script.main([]) == 0
    out = capsys.readouterr().out
    assert "written      ola/modules/m/one.svg" in out and "1 written now" in out
    text = (folder / "one.svg").read_text(encoding="utf-8")
    assert "a box and a line." in text and "with bold and code." in text
    assert script.main([]) == 0 and "placeholder  ola/modules/m/one.svg" in capsys.readouterr().out
    (folder / "one.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")  # my drawing
    assert script.main([]) == 0 and "drawn        ola/modules/m/one.svg" in capsys.readouterr().out
    assert (folder / "one.svg").read_text() == "<svg xmlns='http://www.w3.org/2000/svg'/>"
    (folder / "one.svg").unlink()
    (folder / "one.png").write_bytes(b"png")  # drawn as a png: nothing is written next to it
    assert script.main([]) == 0 and "drawn        ola/modules/m/one.png" in capsys.readouterr().out
    assert not (folder / "one.svg").exists()


def test_a_long_description_makes_a_taller_placeholder():
    entry = {"file": "x", "folder": "f/", "title": "T", "when": "w", "draw": "word " * 400}
    svg = script.render_placeholder(entry)
    height = int(re.search(r'height="(\d+)"', svg).group(1))
    assert height > 800 and f'viewBox="0 0 1600 {height}"' in svg
    short = script.render_placeholder({"file": "x", "folder": "f/", "title": "T"})
    assert 'height="800"' in short


def test_an_empty_list_is_reported(tmp_path, monkeypatch, capsys):
    fake_root(tmp_path, monkeypatch)
    script.LIST.write_text("nothing here\n", encoding="utf-8")
    assert script.main([]) == 1 and "no pictures found" in capsys.readouterr().out


def test_the_docs_describe_the_placeholders():
    text = (ROOT / "docs" / "wiring-images.md").read_text("utf-8")
    assert "OLA-PLACEHOLDER" in text and "scripts/make_picture_placeholders.py" in text
    assert "segnaposto" in text.lower()
    assert "placeholder" in (ROOT / "docs" / "wiring.md").read_text("utf-8")
    json.loads((ROOT / "ola" / "modules" / "filter" / "wiring.json").read_text("utf-8"))
