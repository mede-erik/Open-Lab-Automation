# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The editor of an S-parameters file (.spm): its form.json, the problems at their field and the
tick boxes of the S-parameters (a ``multichoice`` field)."""

import pytest

from ola.form_model import KINDS, FormModel, FormSpecError, load_form_spec, parse_form_spec
from ola.modules.sparameters.measurement import check_params, default_params
from ola.registry import default_registry

LANGS = {"en", "it", "fr", "es", "de"}


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.fixture(scope="module")
def spec(registry):
    return load_form_spec(registry.get("sparameters"))


def paths(problems, severity="error"):
    return {p.path for p in problems if p.severity == severity}


# ---- the module ---------------------------------------------------------------------------------
def test_a_new_file_starts_valid(registry):
    params = default_params()
    assert check_params(params) == []
    assert registry.create("sparameters", params).validate() == []


@pytest.mark.parametrize(
    "change,path",
    [
        ({"sweep": {"start_hz": -1, "stop_hz": 1e9, "points": 201}}, "sweep.start_hz"),
        ({"sweep": {"start_hz": 1e6, "stop_hz": 1e5, "points": 201}}, "sweep.stop_hz"),
        ({"sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 1}}, "sweep.points"),
        ({"sparameters": []}, "sparameters"),
        ({"sparameters": ["S11", "S11"]}, "sparameters"),
        ({"sparameters": ["S33"]}, "sparameters"),
        ({"sweeps": 0}, "sweeps"),
        ({"interval_s": -2}, "interval_s"),
        ({"sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 201, "if_bandwidth_hz": 0}},
         "sweep.if_bandwidth_hz"),
        ({"sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 201, "power_dbm": "x"}},
         "sweep.power_dbm"),
        ({"z0": -50}, "z0"),
        ({"require_calibration": "yes"}, "require_calibration"),
    ],
)
def test_each_problem_is_at_its_field(registry, change, path):
    params = {**default_params(), **change}
    assert path in paths(check_params(params))
    assert any(s.startswith(path) for s in registry.create("sparameters", params).validate())


def test_a_file_of_the_old_form_is_checked_at_the_new_paths():
    old = {"start_hz": 1e6, "stop_hz": 1e5, "points": 11, "sparameters": ["S11"]}
    assert "sweep.stop_hz" in paths(check_params(old))


def test_an_interval_with_a_single_sweep_is_only_a_warning():
    problems = check_params({**default_params(), "sweeps": 1, "interval_s": 5})
    assert paths(problems) == set() and paths(problems, "warning") == {"interval_s"}


# ---- the form -----------------------------------------------------------------------------------
def test_the_form_covers_every_parameter(registry, spec):
    fields = [f.path for f in spec.fields()]
    assert fields[0] == "vna" and {f.kind for f in spec.fields()} <= set(KINDS)
    schema = set(registry.get("sparameters").params_schema)
    assert schema <= {p.split(".")[0] for p in fields}, schema - {p.split(".")[0] for p in fields}
    chosen = next(f for f in spec.fields() if f.path == "sparameters")
    assert chosen.kind == "multichoice"
    assert [c.value for c in chosen.choices] == ["S11", "S21", "S12", "S22"]


def test_every_text_of_the_form_is_in_all_five_languages(spec):
    for section in spec.sections:
        assert set(section.title) == LANGS
        for f in section.fields:
            for text in (f.label, f.help, f.placeholder):
                assert text == "" or set(text) == LANGS, (f.path, text)


def test_a_multichoice_without_choices_is_refused():
    raw = {"sections": [{"fields": [{"path": "a", "kind": "multichoice"}]}]}
    with pytest.raises(FormSpecError, match="'multichoice' needs 'choices'"):
        parse_form_spec(raw)


def test_the_model_reports_the_problems_at_the_fields(registry, spec):
    model = FormModel(
        spec, default_params(), {}, check=lambda p: registry.create("sparameters", p).check(),
        measurement_type="sparameters", required_roles=["vna"],
    )  # fmt: skip
    assert {p.path for p in model.problems()} == {"vna"}  # only the instrument is missing
    model.set_instrument("vna", "vna1")
    model.set("sparameters", [])
    assert [p.path for p in model.problems_at("sparameters")] == ["sparameters"]
    model.set("sparameters", ["S11", "S21"])
    assert not model.has_errors()


# ---- the window ---------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_window_ticks_the_parameters_and_saves_them(app, registry, tmp_path):
    from frontend.ui.FormEditorDialog import FormEditorDialog
    from ola.project import MeasurementFile

    path = tmp_path / "x.spm"
    params = {**default_params(), "sparameters": ["S21"]}
    MeasurementFile(type="sparameters", role_bindings={"vna": ["vna1"]}, params=params).save(path)
    dialog = FormEditorDialog(str(path), registry, "sparameters", instruments=["vna1"])
    boxes = {tick.value: tick for tick in dialog.rows["sparameters"].widget.boxes}
    assert [v for v, tick in boxes.items() if tick.isChecked()] == ["S21"]
    boxes["S11"].setChecked(True)
    assert dialog.model.get("sparameters") == ["S11", "S21"]  # in the order of the form
    for tick in boxes.values():
        tick.setChecked(False)
    assert dialog.model.get("sparameters") == [] and dialog.model.has_errors()
    boxes["S22"].setChecked(True)
    dialog.save()
    assert MeasurementFile.load(path).params["sparameters"] == ["S22"]
    dialog.dirty = False
    dialog.close()
