"""Tests of the efficiency editor window (run without a screen, see conftest.py)."""

import glob
import json
import os
import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from frontend.ui import EfficiencyEditorDialog as dialog_module  # noqa: E402
from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog  # noqa: E402
from tests.efficiency_params import INSTRUMENTS, good  # noqa: E402

LANG_DIR = os.path.join(
    os.path.dirname(dialog_module.__file__), "..", "lang", "modules", "efficiency"
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app):
    d = EfficiencyEditorDialog(params=good(), instruments=INSTRUMENTS)
    yield d
    d.dirty = False
    d.close()


def _catalogs():
    out = {}
    for path in sorted(glob.glob(os.path.join(LANG_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            out[os.path.basename(path)[:-5]] = json.load(f)
    return out


# ---- translations -----------------------------------------------------------------------------
def test_all_languages_have_the_same_keys():
    catalogs = _catalogs()
    assert set(catalogs) >= {"en", "it", "fr", "es", "de"}
    reference = set(catalogs["en"])
    for lang, data in catalogs.items():
        assert set(data) == reference, lang
        assert all(text.strip() for text in data.values()), lang


def test_placeholders_are_the_same_in_every_language():
    catalogs = _catalogs()
    for key, text in catalogs["en"].items():
        wanted = set(re.findall(r"\{(\w+)\}", text))
        for lang, data in catalogs.items():
            assert set(re.findall(r"\{(\w+)\}", data[key])) == wanted, (lang, key)


def test_every_key_used_by_the_window_exists():
    source = open(dialog_module.__file__, encoding="utf-8").read()
    used = set(re.findall(r'"(eff_[a-z_0-9]+)"', source))
    en = _catalogs()["en"]
    # keys built from a pattern, one for each value
    families = {
        "eff_group_{}": ["setpoints", "readings", "derived"],
        "eff_{}": ["value", "values", "start", "stop", "points", "step", "scale", "offset"]
        + ["startup", "shutdown", "startup_help", "shutdown_help"],
        "eff_mode_{}": dialog_module.SWEEP_MODES,
        "eff_out_{}": dialog_module.OUTPUT_MODES + ("on", "off", "state"),
        "eff_out_help_{}": dialog_module.OUTPUT_MODES,
        "eff_on_fail_{}": dialog_module.ON_FAIL,
    }
    for pattern, values in families.items():
        used |= {pattern.format(v) for v in values}
    assert sorted(used - set(en)) == []


# ---- the window -------------------------------------------------------------------------------
def test_opens_with_the_parameters_in_order(dialog):
    items = [dialog.param_list.item(i).text() for i in range(dialog.param_list.count())]
    assert [t.split(".")[1].split()[0] for t in items] == dialog.editor.names()
    assert dialog.problem_tree.topLevelItemCount() == len(dialog.editor.problems())
    assert not dialog.editor.has_errors()


def test_editing_a_field_changes_the_model_and_validates(dialog):
    dialog.param_list.setCurrentRow(1)
    edit = dialog.sweep_rows["values"][1]
    edit.setText("9, 12, 18")
    assert dialog.editor.get("variables[1].sweep.values") == [9, 12, 18]
    assert dialog.dirty
    edit.setText("9, abc")  # not a list of numbers: the model keeps the last good one
    assert dialog.editor.get("variables[1].sweep.values") == [9, 12, 18]
    assert "border" in edit.styleSheet()


def test_a_value_outside_the_limits_is_marked(dialog):
    dialog.param_list.setCurrentRow(1)  # vin has limits 5..20
    dialog.sweep_rows["values"][1].setText("9, 12, 25")
    assert dialog.editor.has_errors()
    assert dialog.problem_tree.topLevelItemCount() >= 1
    assert (
        "cannot" in dialog.summary_label.text().lower()
        or "non si" in dialog.summary_label.text().lower()
    )
    assert dialog.param_messages.text() != ""


def test_reordering_changes_the_model_and_the_list(dialog):
    before = dialog.editor.names()
    dialog.param_list.setCurrentRow(0)
    dialog._move_parameter(+1)
    after = dialog.editor.names()
    assert after[0] == before[1] and after[1] == before[0]
    assert dialog.param_list.currentRow() == 1
    assert "2. " + before[0] in dialog.param_list.item(1).text()


def test_rename_updates_the_formulas(dialog):
    dialog.param_list.setCurrentRow(1)
    old = dialog.editor.names()[1]
    dialog.name_edit.setText("vsource")
    dialog.name_edit.editingFinished.emit()
    assert "vsource" in dialog.editor.names()
    assert old not in dialog.editor.names()
    assert not dialog.editor.has_errors()


def test_group_toggle_creates_and_removes_the_block(dialog):
    dialog.param_list.setCurrentRow(2)  # vaux has no verify
    assert dialog.editor.get("variables[2].verify") is None
    dialog.verify_group.setChecked(True)
    assert isinstance(dialog.editor.get("variables[2].verify"), dict)
    dialog.verify_group.setChecked(False)
    assert dialog.editor.get("variables[2].verify") is None


def test_changing_the_output_mode_updates_the_power_tab(dialog):
    dialog.param_list.setCurrentRow(1)
    dialog.output_group.setChecked(True)
    position = dialog.output_mode.findData("always_on")
    dialog.output_mode.setCurrentIndex(position)
    assert dialog.editor.get("variables[1].output.mode") == "always_on"
    assert "vin" in dialog.always_label.text()
    assert "vin" not in [dialog.power_list.item(i).text() for i in range(dialog.power_list.count())]


def test_formula_tab_edits_and_reports_errors(dialog):
    dialog._add_formula()
    row = dialog.formula_table.currentRow()
    name = dialog._formula_names[row]
    dialog.formula_edit.setText("vin * nothing_here")
    dialog._formula_text_edited(dialog.formula_edit.text())
    assert dialog.editor.params["derived"][name] == "vin * nothing_here"
    assert dialog.editor.has_errors()
    assert "nothing_here" in dialog.formula_message.text()
    dialog._remove_formula()
    assert not dialog.editor.has_errors()


def test_navigate_to_a_problem_selects_the_parameter(dialog):
    dialog.param_list.setCurrentRow(1)
    dialog.sweep_rows["values"][1].setText("9, 12, 25")
    dialog.param_list.setCurrentRow(0)
    problem = next(p for p in dialog.editor.problems() if p.path.startswith("variables[1]"))
    dialog.navigate(problem.path)
    assert dialog.param_list.currentRow() == 1
    assert dialog.tabs.currentIndex() == 0


def test_save_writes_the_file_and_clears_the_dirty_flag(dialog, tmp_path):
    dialog.file_path = str(tmp_path / "x.eff")
    dialog.timing_summary.parent()  # widgets exist
    assert dialog.save()
    assert os.path.isfile(dialog.file_path)
    assert not dialog.dirty


def test_save_with_errors_asks_first(dialog, tmp_path, monkeypatch):
    dialog.file_path = str(tmp_path / "bad.eff")
    dialog.param_list.setCurrentRow(1)
    dialog.sweep_rows["values"][1].setText("9, 12, 25")
    answers = []

    def no(*args, **kwargs):
        answers.append(args[2])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(no))
    assert not dialog.save()
    assert answers and not os.path.exists(dialog.file_path)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    assert dialog.save() and os.path.exists(dialog.file_path)


def test_a_saved_file_is_opened_again_identically(dialog, tmp_path, app):
    path = str(tmp_path / "y.eff")
    dialog.file_path = path
    dialog.save()
    again = EfficiencyEditorDialog(path, instruments=INSTRUMENTS)
    try:
        assert again.editor.params == dialog.editor.params
    finally:
        again.dirty = False
        again.close()


def test_new_dialog_without_file_starts_from_the_template(app):
    d = EfficiencyEditorDialog(instruments=INSTRUMENTS)
    try:
        assert d.param_list.count() >= 1
        assert d.editor.has_errors()  # the template still has to be filled in
    finally:
        d.dirty = False
        d.close()


# ---- themes and many parameters ---------------------------------------------------------------
def test_text_colours_follow_the_theme(app):
    from PyQt6.QtGui import QColor, QPalette

    from frontend.ui.efficiency_widgets import text_color

    old = app.palette()
    try:
        dark = QPalette(old)
        dark.setColor(QPalette.ColorRole.Window, QColor("#222222"))
        app.setPalette(dark)
        bright = text_color("ok")
        light = QPalette(old)
        light.setColor(QPalette.ColorRole.Window, QColor("#f0f0f0"))
        app.setPalette(light)
        assert bright != text_color("ok")
    finally:
        app.setPalette(old)


def test_errors_are_listed_before_warnings(dialog):
    dialog.param_list.setCurrentRow(1)
    dialog.sweep_rows["values"][1].setText("9, 12, 25")  # an error (outside the limits)
    dialog.param_list.setCurrentRow(2)
    dialog.output_group.setChecked(True)  # adds warnings (no state call)
    marks = [
        dialog.problem_tree.topLevelItem(i).text(0)
        for i in range(dialog.problem_tree.topLevelItemCount())
    ]
    assert marks == sorted(marks, key=lambda m: m != "●")
    assert marks[0] == "●"


def test_ten_parameters_all_appear_in_order(app):
    params = good()
    template = params["variables"][2]  # vaux: a set parameter with a fixed value
    params["variables"] = params["variables"] + [dict(template, name=f"extra{i}") for i in range(5)]
    d = EfficiencyEditorDialog(params=params, instruments=INSTRUMENTS)
    try:
        assert d.param_list.count() == 10
        for row in range(10):
            d.param_list.setCurrentRow(row)
            assert d.name_edit.text() == d.editor.names()[row]
    finally:
        d.dirty = False
        d.close()


def test_a_formula_with_a_problem_is_selected_first(dialog):
    dialog.editor.set_formula("bad", "vin * nothing_here")
    dialog.formula_table.setCurrentCell(-1, -1)  # nothing selected, as when the window opens
    dialog._refresh_formulas()
    row = dialog.formula_table.currentRow()
    assert dialog._formula_names[row] == "bad"


def test_names_are_grouped_by_type_and_titles_are_not_inserted(dialog):
    items = [dialog.names_list.item(i) for i in range(dialog.names_list.count())]
    headers = [i for i in items if i.data(Qt.ItemDataRole.UserRole) == "header"]
    assert len(headers) == 3  # set values, readings, computed
    assert items[0] is headers[0]
    dialog.formula_edit.setEnabled(True)
    dialog.formula_edit.setText("")
    dialog._insert_name(headers[0])
    assert dialog.formula_edit.text() == ""
    dialog._insert_name(items[1])
    assert dialog.formula_edit.text() == items[1].data(Qt.ItemDataRole.UserRole)
