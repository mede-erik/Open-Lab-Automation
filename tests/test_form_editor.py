# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The form-based editor window (no screen needed, see conftest.py)."""

import glob
import json
import os
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from frontend.ui import FormEditorDialog as form_module  # noqa: E402
from frontend.ui.FormEditorDialog import FormEditorDialog  # noqa: E402
from ola.project import MeasurementFile  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from tests.test_cable import PARAMS  # noqa: E402

LANG_DIR = os.path.join(os.path.dirname(form_module.__file__), "..", "lang", "modules", "form")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.fixture(autouse=True)
def no_real_dialogs(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(f"unexpected message box: {args[1:3]}")

    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(refuse))


@pytest.fixture
def dialog(app, registry, tmp_path):
    path = tmp_path / "x.cbl"
    MeasurementFile(type="cable", role_bindings={"vna": ["vna1"]}, params=PARAMS).save(path)
    d = FormEditorDialog(str(path), registry, "cable", instruments=["vna1", "vna2"])
    yield d
    d.dirty = False
    d.close()


def edit(dialog, path, text):
    row = dialog.rows[path]
    widget = row.widget
    if hasattr(widget, "setText"):
        widget.setText(text)
    elif hasattr(widget, "setPlainText"):
        widget.setPlainText(text)
    return row


# ---- translations -----------------------------------------------------------------------------
def test_window_strings_are_in_every_language_with_the_same_placeholders():
    catalogs = {}
    for path in glob.glob(os.path.join(LANG_DIR, "*.json")):
        catalogs[os.path.basename(path)[:-5]] = json.load(open(path, encoding="utf-8"))
    assert set(catalogs) >= {"en", "it", "fr", "es", "de"}
    for lang, data in catalogs.items():
        assert set(data) == set(catalogs["en"]), lang
        for key, text in data.items():
            assert set(re.findall(r"\{(\w+)\}", text)) == set(
                re.findall(r"\{(\w+)\}", catalogs["en"][key])
            ), (lang, key)
    source = open(form_module.__file__, encoding="utf-8").read()
    assert sorted(set(re.findall(r'"(form_[a-z_]+)"', source)) - set(catalogs["en"])) == []


# ---- the window -------------------------------------------------------------------------------
def test_shows_the_values_of_the_file(dialog):
    assert dialog.rows["cable.label"].widget.text() == "RG58 #3"
    assert dialog.rows["cable.length_m"].widget.text() == "2 m"
    assert dialog.rows["sweep.start_hz"].widget.text() == "1 MHz"
    assert dialog.rows["sweep.stop_hz"].widget.text() == "3 GHz"
    assert dialog.rows["frequencies_of_interest"].widget.text() == "433 MHz, 868 MHz, 2.4 GHz"
    assert dialog.rows["mode"].widget.currentData() == "transmission"
    assert dialog.rows["vna"].widget.currentText() == "vna1"
    assert not dialog.rows["confirm_setup"].widget.isChecked()
    assert "Ready" in dialog.summary_label.text()


def test_a_new_file_asks_to_choose_the_instrument(app, registry, tmp_path):
    d = FormEditorDialog(str(tmp_path / "new.cbl"), registry, "cable", instruments=["vna1"])
    try:
        assert d.model.has_errors() and d.problem_tree.topLevelItem(0).text(1) == "vna"
        assert "Choose the instrument for 'vna'" in d.problem_tree.topLevelItem(0).text(2)
        assert "border" in d.rows["vna"].widget.styleSheet()
        d.rows["vna"].widget.setCurrentText("vna1")
        assert not d.model.has_errors()
    finally:
        d.dirty = False
        d.close()


def test_typing_with_si_prefixes_changes_the_model(dialog):
    edit(dialog, "sweep.start_hz", "500k")
    edit(dialog, "sweep.stop_hz", "6 GHz")
    edit(dialog, "frequencies_of_interest", "433M; 1.2G")
    edit(dialog, "sweep.points", "801")
    p = dialog.model.params
    assert p["sweep"]["start_hz"] == 500_000 and p["sweep"]["stop_hz"] == 6_000_000_000
    assert p["frequencies_of_interest"] == [433_000_000, 1_200_000_000]
    assert p["sweep"]["points"] == 801 and dialog.dirty
    assert dialog.model.problems() == []


def test_a_wrong_value_marks_the_field_and_keeps_the_last_good_one(dialog):
    row = edit(dialog, "sweep.start_hz", "fast")
    assert row.invalid and "border" in row.widget.styleSheet()
    assert dialog.model.get("sweep.start_hz") == 1_000_000  # the last good value stays
    edit(dialog, "sweep.start_hz", "2M")
    assert (
        not dialog.rows["sweep.start_hz"].invalid
        and dialog.model.get("sweep.start_hz") == 2_000_000
    )
    row = edit(dialog, "sweep.points", "40.5")
    assert "whole number" in row.invalid


def test_a_problem_of_the_module_is_shown_at_its_field(dialog):
    edit(dialog, "sweep.points", "1")
    assert dialog.model.has_errors()
    assert "border" in dialog.rows["sweep.points"].widget.styleSheet()
    assert dialog.problem_tree.topLevelItemCount() == 1
    assert dialog.problem_tree.topLevelItem(0).text(1) == "sweep.points"
    assert "Cannot start" in dialog.summary_label.text()
    edit(dialog, "sweep.points", "401")
    assert dialog.problem_tree.topLevelItemCount() == 0 and "Ready" in dialog.summary_label.text()


def test_a_warning_does_not_stop_the_measurement(dialog):
    edit(dialog, "sweep.points", "61")  # too coarse for a 2 m cable
    assert not dialog.model.has_errors() and dialog.problem_tree.topLevelItemCount() == 1
    assert dialog.problem_tree.topLevelItem(0).text(0) == "▲"
    assert "Ready" in dialog.summary_label.text()


def test_fields_appear_and_disappear_with_the_mode(dialog):
    dialog.show()
    assert dialog.rows["also_s11"].container.isVisible()
    assert not dialog.rows["termination"].container.isVisible()
    box = dialog.rows["mode"].widget
    box.setCurrentIndex(box.findData("reflection"))
    assert dialog.rows["termination"].container.isVisible()
    assert not dialog.rows["also_s11"].container.isVisible()
    assert dialog.model.get("mode") == "reflection"


def test_limits_are_typed_as_json(dialog):
    row = edit(dialog, "limits", '{"max": 1.5}')
    assert dialog.model.get("limits") == {"max": 1.5} and not row.invalid
    row = edit(dialog, "limits", '{"max": ')
    assert "JSON" in row.invalid and dialog.model.get("limits") == {"max": 1.5}
    edit(dialog, "limits", '{"maximum": 1}')  # valid JSON, wrong limit: the module says so
    assert dialog.model.problems_at("limits")[0].message.startswith("unknown limit key")
    edit(dialog, "limits", "")
    assert dialog.model.get("limits") is None


def test_choosing_the_instrument_and_clearing_optional_fields(dialog):
    box = dialog.rows["vna"].widget
    box.setCurrentText("vna2")
    assert dialog.model.instrument("vna") == "vna2"
    edit(dialog, "cable.length_m", "")
    assert dialog.model.get("cable.length_m") is None  # empty means not given
    edit(dialog, "cable.label", "")
    assert "cable" not in dialog.model.params


def test_save_writes_the_file_in_the_project_format(dialog, tmp_path):
    edit(dialog, "cable.label", "RG316 #1")
    assert dialog.save() and not dialog.dirty
    saved = json.loads((tmp_path / "x.cbl").read_text())
    assert saved["type"] == "cable" and saved["role_bindings"] == {"vna": ["vna1"]}
    assert (
        saved["params"]["cable"]["label"] == "RG316 #1"
        and saved["params"]["sweep"]["points"] == 401
    )


def test_save_with_errors_asks_first(dialog, tmp_path, monkeypatch):
    edit(dialog, "sweep.points", "1")
    asked = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No),
    )
    assert not dialog.save() and asked and "1 error" in asked[0]
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    assert dialog.save()


def test_a_new_file_starts_from_the_defaults_of_the_module(app, registry, tmp_path):
    d = FormEditorDialog(str(tmp_path / "new.cbl"), registry, "cable", instruments=["vna1"])
    try:
        assert d.model.get("sweep.points") == 401 and d.model.get("mode") == "transmission"
        assert d.rows["sweep.stop_hz"].widget.text() == "3 GHz"
        d.rows["vna"].widget.setCurrentText("vna1")
        assert not d.model.has_errors()  # valid, once the VNA is chosen
    finally:
        d.dirty = False
        d.close()


def test_a_module_without_a_form_is_refused_clearly(app, registry, tmp_path):
    with pytest.raises(ValueError, match="no form"):
        FormEditorDialog(str(tmp_path / "x.tlg"), registry, "time_log")


def test_a_double_click_on_a_problem_goes_to_its_field(dialog, monkeypatch):
    edit(dialog, "sweep.points", "1")
    seen = []
    monkeypatch.setattr(
        dialog.rows["sweep.points"].widget, "setFocus", lambda *a: seen.append("points")
    )
    item = dialog.problem_tree.topLevelItem(0)
    dialog.problem_tree.itemDoubleClicked.emit(item, 0)
    assert seen == ["points"]
    dialog.navigate("nothing.here")  # a path with no field: nothing happens
    dialog.navigate(None)


# ---- inside the project window ----------------------------------------------------------------
def test_new_cable_measurement_starts_valid_and_opens_the_form(app, registry, tmp_path):
    from ola.project import Project
    from ola.project_session import ProjectSession

    session = ProjectSession(Project.new("P", tmp_path), registry, instruments=["vna1"])
    ref = session.create("cable", "Cable A")
    assert ref.file.endswith(".cbl")
    params = session.load(ref).params
    assert params["sweep"]["points"] == 401  # from default_params() of the module
    d = FormEditorDialog(str(session.path(ref)), registry, "cable", instruments=session.instruments)
    try:
        assert d.rows["sweep.points"].widget.text() == "401"
    finally:
        d.dirty = False
        d.close()


# ---- a cable or device from the registry ------------------------------------------------------
@pytest.fixture
def cards(tmp_path):
    from ola.assets import AssetRegistry

    registry = AssetRegistry(tmp_path / "assets.json")
    registry.create("cable", "RG316 SMA-SMA", attributes={"length_m": 1.0})
    registry.create("cable", "RG58 N-N")
    registry.create("antenna", "whip")
    return registry


@pytest.fixture
def asset_dialog(app, registry, tmp_path, cards):
    path = tmp_path / "c.cbl"
    params = {k: v for k, v in PARAMS.items()}
    params["cable"] = {"label": "", "length_m": 2.0}
    MeasurementFile(type="cable", role_bindings={"vna": ["vna1"]}, params=params).save(path)
    d = FormEditorDialog(str(path), registry, "cable", instruments=["vna1"], assets=cards)
    yield d
    d.dirty = False
    d.close()


def test_the_registry_offers_the_cables_and_not_the_antennas(asset_dialog):
    box = asset_dialog.rows["cable.asset_id"].widget
    items = [box.itemText(i) for i in range(box.count())]
    assert items == ["", "CBL-0001 - RG316 SMA-SMA", "CBL-0002 - RG58 N-N"]  # the kind of the field


def test_choosing_a_cable_sets_its_code_and_fills_the_empty_name(asset_dialog):
    box = asset_dialog.rows["cable.asset_id"].widget
    box.setCurrentIndex(1)
    assert asset_dialog.model.get("cable.asset_id") == "CBL-0001"
    assert asset_dialog.model.get("cable.label") == "RG316 SMA-SMA"
    assert asset_dialog.rows["cable.label"].widget.text() == "RG316 SMA-SMA"  # shown too


def test_a_name_already_typed_is_not_overwritten(asset_dialog):
    asset_dialog.rows["cable.label"].widget.setText("my own name")
    asset_dialog.rows["cable.asset_id"].widget.setCurrentIndex(2)
    assert asset_dialog.model.get("cable.asset_id") == "CBL-0002"
    assert asset_dialog.model.get("cable.label") == "my own name"


def test_a_scanned_code_is_normalised(asset_dialog):
    box = asset_dialog.rows["cable.asset_id"].widget
    box.setCurrentText("OLA:cbl-2")  # what a scanner types
    assert asset_dialog.model.get("cable.asset_id") == "CBL-0002"
    assert not asset_dialog.rows["cable.asset_id"].invalid
    box.setCurrentText("")  # cleared: the key goes away
    assert asset_dialog.model.get("cable.asset_id") is None


def test_something_that_is_not_a_code_marks_the_field(asset_dialog):
    row = asset_dialog.rows["cable.asset_id"]
    row.widget.setCurrentText("my cable")
    assert "Not a code" in row.invalid and "border" in row.widget.styleSheet()
    assert asset_dialog.model.get("cable.asset_id") is None  # nothing wrong is stored


def test_a_code_that_is_not_in_the_registry_is_a_warning_at_its_field(asset_dialog):
    asset_dialog.rows["cable.asset_id"].widget.setCurrentText("CBL-0099")
    assert asset_dialog.model.get("cable.asset_id") == "CBL-0099"
    assert not asset_dialog.model.has_errors()  # it can still be measured
    assert any("not in the registry" in asset_dialog.problem_tree.topLevelItem(i).text(2)
               for i in range(asset_dialog.problem_tree.topLevelItemCount()))  # fmt: skip


def test_a_saved_code_is_shown_with_its_name_when_the_file_is_opened_again(
    app, registry, tmp_path, cards
):
    path = tmp_path / "again.cbl"
    params = {**PARAMS, "cable": {"label": "x", "asset_id": "CBL-0002"}}
    MeasurementFile(type="cable", role_bindings={"vna": ["v"]}, params=params).save(path)
    d = FormEditorDialog(str(path), registry, "cable", instruments=["v"], assets=cards)
    try:
        assert d.rows["cable.asset_id"].widget.currentText() == "CBL-0002 - RG58 N-N"
        assert d.model.get("cable.asset_id") == "CBL-0002"  # showing it did not change it
        assert not d.dirty
    finally:
        d.close()


def test_without_a_registry_the_field_still_takes_a_typed_code(app, registry, tmp_path):
    d = FormEditorDialog(str(tmp_path / "n.cbl"), registry, "cable", instruments=["v"])
    try:
        box = d.rows["cable.asset_id"].widget
        assert box.count() == 1  # only the empty entry
        box.setCurrentText("CBL-0007")
        d.rows["vna"].widget.setCurrentText("v")  # (a new file also needs its instrument)
        assert d.model.get("cable.asset_id") == "CBL-0007" and not d.model.has_errors()
    finally:
        d.dirty = False
        d.close()
