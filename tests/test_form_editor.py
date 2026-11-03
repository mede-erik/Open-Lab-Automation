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


# ---- translations -------------------------------------------------------------------------------
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


# ---- the window ---------------------------------------------------------------------------------
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


# ---- inside the project window ------------------------------------------------------------------
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
