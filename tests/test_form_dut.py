# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The device under test in the form of a measurement: the DUT field and its version."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.FormEditorDialog import FormEditorDialog  # noqa: E402
from ola.assets import AssetRegistry  # noqa: E402
from ola.duts import DutRegistry  # noqa: E402
from ola.form_model import FormModel, load_form_spec  # noqa: E402
from ola.project import MeasurementFile  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from tests.legacy_assets import add_legacy  # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.fixture
def archive(tmp_path):
    reg = DutRegistry(tmp_path / "duts.json")
    reg.create("antenna", "868 MHz whip", version="rev A")
    reg.add_version("DUT-0001", "rev B")
    reg.create("filter", "SAW 868")
    return reg


def dialog_for(registry, tmp_path, archive, module="return_loss", params=None):
    path = tmp_path / "m.file"
    if params is not None:
        MeasurementFile(type=module, role_bindings={"vna": ["vna1"]}, params=params).save(path)
    return FormEditorDialog(str(path), registry, module, instruments=["vna1"], duts=archive)


def close(dialog):
    dialog.dirty = False  # a changed dialog would ask about saving and wait for an answer
    dialog.close()


def items(box):
    return [box.itemText(i) for i in range(box.count())]


# ---- the model ---------------------------------------------------------------------------------
def test_an_unknown_dut_or_version_is_a_warning_not_an_error(registry, archive):
    spec = load_form_spec(registry.get("return_loss"))
    params = {"sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 11}, "confirm_setup": False,
              "device": {"label": "x", "dut_id": "DUT-0001", "version": "rev A"}}  # fmt: skip
    model = FormModel(spec, params, {"vna": ["v"]}, None, "return_loss", duts=archive)
    assert model.problems() == []
    model.set("device.version", "rev Z")
    found = model.problems()
    assert [(p.path, p.severity) for p in found] == [("device.version", "warning")]
    model.set("device.dut_id", "DUT-0099")
    assert ("device.dut_id", "warning") in [(p.path, p.severity) for p in model.problems()]
    assert not model.has_errors()
    assert FormModel(spec, params, {"vna": ["v"]}, None, "return_loss").problems() == []


# ---- the window --------------------------------------------------------------------------------
def test_the_dut_field_offers_the_archive_and_the_antenna_form_only_the_antennas(
    app, registry, tmp_path, archive
):
    d = dialog_for(registry, tmp_path, archive, "return_loss")
    assert items(d.rows["device.dut_id"].widget) == [
        "", "DUT-0001 - 868 MHz whip", "DUT-0002 - SAW 868",
    ]  # fmt: skip
    close(d)
    d = dialog_for(registry, tmp_path, archive, "antenna")
    assert items(d.rows["device.dut_id"].widget) == ["", "DUT-0001 - 868 MHz whip"]
    close(d)


def test_choosing_a_dut_fills_the_name_and_offers_the_version_in_use(
    app, registry, tmp_path, archive
):
    d = dialog_for(registry, tmp_path, archive)
    d.rows["device.dut_id"].widget.setCurrentIndex(1)
    assert d.model.get("device.dut_id") == "DUT-0001"
    assert d.model.get("device.label") == "868 MHz whip"
    assert d.model.get("device.version") == "rev B"  # the latest in use
    version = d.rows["device.version"].widget
    assert items(version) == ["", "rev B", "rev A"] and version.currentText() == "rev B"
    close(d)


def test_a_version_can_be_chosen_or_typed_and_a_name_already_there_stays(
    app, registry, tmp_path, archive
):
    d = dialog_for(registry, tmp_path, archive)
    d.rows["device.label"].widget.setText("my antenna")
    d.rows["device.dut_id"].widget.setCurrentIndex(1)
    assert d.model.get("device.label") == "my antenna"
    d.rows["device.version"].widget.setCurrentIndex(2)  # rev A
    assert d.model.get("device.version") == "rev A"
    d.rows["device.version"].widget.setCurrentText("proto 3")  # free text
    assert d.model.get("device.version") == "proto 3"
    found = d.model.problems_at("device.version")  # warned that it is not a version, no error
    assert [p.severity for p in found] == ["warning"]
    d.rows["device.version"].widget.setCurrentText("")
    assert d.model.get("device.version") is None
    close(d)


def test_a_retired_version_is_not_offered(app, registry, tmp_path, archive):
    archive.retire_version("DUT-0001", "rev B")
    d = dialog_for(registry, tmp_path, archive)
    d.rows["device.dut_id"].widget.setCurrentIndex(1)
    assert d.model.get("device.version") == "rev A"
    assert items(d.rows["device.version"].widget) == ["", "rev A"]
    close(d)


def test_a_file_made_before_the_archive_opens_with_the_dut_chosen(app, registry, tmp_path, archive):
    components = AssetRegistry(tmp_path / "assets.json")
    add_legacy(components, "antenna", "old whip")  # ANT-0001
    archive.migrate_from(components)  # DUT-0003 now
    params = {"sweep": {"start_hz": 1e6, "stop_hz": 3e9, "points": 11}, "confirm_setup": False,
              "device": {"label": "x", "asset_id": "ANT-0001"}}  # fmt: skip
    d = dialog_for(registry, tmp_path, archive, params=params)
    assert d.model.get("device.dut_id") == "DUT-0003" and d.model.get("device.asset_id") is None
    assert d.rows["device.dut_id"].widget.currentText() == "DUT-0003 - old whip"
    close(d)


def test_the_window_works_without_an_archive(app, registry, tmp_path):
    d = FormEditorDialog(str(tmp_path / "m.file"), registry, "return_loss", instruments=["vna1"])
    assert items(d.rows["device.dut_id"].widget) == [""]
    d.rows["device.dut_id"].widget.setCurrentText("DUT-0001")
    assert d.model.get("device.dut_id") == "DUT-0001"
    close(d)


def test_the_form_strings_for_the_dut_are_in_every_language():
    import json
    import os

    here = os.path.dirname(__file__)
    for lang in ("it", "en", "fr", "es", "de"):
        with open(os.path.join(here, "..", "frontend", "lang", "modules", "form", f"{lang}.json"),
                  encoding="utf-8") as f:  # fmt: skip
            assert json.load(f)["form_version_placeholder"].strip()
        for module in ("bode", "regulation", "ripple", "resistive_efficiency", "return_loss",
                       "antenna", "filter"):  # fmt: skip
            path = os.path.join(here, "..", "ola", "modules", module, "form.json")
            with open(path, encoding="utf-8") as f:
                form = json.load(f)
            texts = []

            def walk(o):
                if isinstance(o, dict):
                    if o.get("kind") in ("dut", "dut_version"):
                        texts.extend([o["label"][lang], o["help"][lang]])
                    for v in o.values():
                        walk(v)
                elif isinstance(o, list):
                    for v in o:
                        walk(v)

            walk(form)
            assert len(texts) == 4 and all(t.strip() for t in texts), (module, lang)
