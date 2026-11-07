"""The model behind the form-based editors, and the cable's form.json."""

import copy
import json

import pytest

from ola.form_model import (
    KINDS,
    FormModel,
    FormSpecError,
    check_from_measurement,
    load_form_spec,
    localized,
    parse_form_spec,
)
from ola.measurement import MeasurementError
from ola.registry import default_registry
from ola.run_view import parse_si
from tests.test_cable import PARAMS


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.fixture
def model(registry):
    info = registry.get("cable")
    return FormModel(
        load_form_spec(info),
        PARAMS,
        {"vna": ["vna1"]},
        check_from_measurement(lambda p: registry.create("cable", p)),
        "cable",
        info.version,
    )


# ---- numbers with SI prefixes -----------------------------------------------------------------
@pytest.mark.parametrize(
    "text,unit,value",
    [
        ("433M", "Hz", 433e6), ("433 MHz", "Hz", 433e6), ("2.4G", "Hz", 2.4e9),
        ("2,4 GHz", "Hz", 2.4e9), ("1e6", "Hz", 1e6), ("10m", "", 0.01), ("5 m", "m", 5.0),
        ("1.5", "m", 1.5), ("10 mm", "m", 0.01),
        ("500k", "", 500e3), ("  75  ", "", 75.0), ("-3", "dBm", -3.0),
    ],
)  # fmt: skip
def test_parse_si(text, unit, value):
    assert parse_si(text, unit) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "abc", "M", "1..2", "nan", "inf", "1 x 2"])
def test_parse_si_refuses_what_is_not_a_number(text):
    assert parse_si(text, "Hz") is None


# ---- the form.json of a module ----------------------------------------------------------------
def test_the_cable_form_loads_and_covers_the_parameters(registry):
    spec = load_form_spec(registry.get("cable"))
    paths = [f.path for f in spec.fields()]
    assert paths[0] == "vna" and "sweep.points" in paths and "limits" in paths
    assert {f.kind for f in spec.fields()} <= set(KINDS)
    # every field a measurement of this type understands can be edited
    schema = set(registry.get("cable").params_schema)
    assert schema <= {p.split(".")[0] for p in paths}, schema - {p.split(".")[0] for p in paths}


def test_every_text_of_the_cable_form_is_in_all_five_languages(registry):
    spec = load_form_spec(registry.get("cable"))
    langs = {"en", "it", "fr", "es", "de"}
    texts = []
    for section in spec.sections:
        texts.append(section.title)
        for f in spec.fields() if False else section.fields:
            texts += [f.label, f.help, f.placeholder] + [c.label for c in f.choices]
    for text in texts:
        if isinstance(text, dict):
            assert set(text) == langs, text
        else:
            assert text == "", text  # an untranslated text would be missing in four languages


def test_localized_text():
    assert localized({"en": "Start", "it": "Inizio"}, "it") == "Inizio"
    assert localized({"en": "Start"}, "de") == "Start"  # falls back to English
    assert localized({"it": "Inizio"}, "de") == "Inizio"  # or whatever there is
    assert localized("plain", "it") == "plain" and localized(None) == ""


@pytest.mark.parametrize(
    "raw,words",
    [
        ({}, "sections"),
        ({"sections": []}, "sections"),
        ({"sections": [{"fields": 1}]}, "list 'fields'"),
        ({"sections": [{"fields": [{"kind": "text"}]}]}, "'path'"),
        ({"sections": [{"fields": [{"path": "a", "kind": "color"}]}]}, "'kind'"),
        ({"sections": [{"fields": [{"path": "a", "kind": "choice"}]}]}, "needs 'choices'"),
        (
            {"sections": [{"fields": [{"path": "a", "kind": "text", "visible_if": {}}]}]},
            "visible_if",
        ),
    ],
)  # fmt: skip
def test_a_wrong_form_says_where(raw, words):
    with pytest.raises(FormSpecError, match=words):
        parse_form_spec(raw)


def test_a_module_without_a_form_has_none(registry):
    assert load_form_spec(registry.get("time_log")) is None


# ---- editing ----------------------------------------------------------------------------------
def test_values_are_read_and_set(model):
    assert model.get("sweep.points") == 401 and model.get("cable.label") == "RG58 #3"
    model.set("sweep.points", 801)
    assert model.params["sweep"]["points"] == 801
    assert PARAMS["sweep"]["points"] == 401  # the original is not touched


def test_removing_a_value_removes_empty_parents(model):
    model.set("sweep.if_bandwidth_hz", 300)
    model.set("sweep.if_bandwidth_hz", None)
    assert "if_bandwidth_hz" not in model.params["sweep"]
    model.set("cable.label", None)
    model.set("cable.length_m", None)
    assert "cable" not in model.params  # nothing left in it
    model.set("limits.max", None)  # removing what is not there is fine
    assert "limits" not in model.params


def test_the_instrument_of_a_role(model):
    assert model.instrument("vna") == "vna1"
    model.set_instrument("vna", "other")
    assert model.role_bindings == {"vna": ["other"]}
    model.set_instrument("vna", None)
    assert model.instrument("vna") is None and model.role_bindings == {}


def test_fields_depend_on_other_fields(model):
    spec = {f.path: f for f in model.spec.fields()}
    assert model.visible(spec["also_s11"]) and not model.visible(spec["termination"])
    model.set("mode", "reflection")
    assert not model.visible(spec["also_s11"]) and model.visible(spec["termination"])
    assert model.visible(spec["sweep.points"])  # a field with no condition


def test_problems_follow_the_edits_and_name_the_field(model):
    assert model.problems() == [] and not model.has_errors()
    model.set("sweep.points", 1)
    assert [p.path for p in model.problems()] == ["sweep.points"] and model.has_errors()
    assert model.problems_at("sweep")[0].message.startswith("the number of points")
    assert model.problems_at("cable") == []
    model.set("sweep.points", 401)
    assert model.problems() == []


def test_one_wrong_value_can_make_several_fields_wrong(model):
    model.set("sweep.stop_hz", 5e5)  # below the start, and the frequencies of interest fall outside
    assert {p.path for p in model.problems()} == {"sweep.stop_hz", "frequencies_of_interest"}


def test_a_warning_is_a_problem_but_not_an_error(model):
    model.set("sweep.points", 61)  # too coarse for a 2 m cable
    assert model.problems() and not model.has_errors()


def test_check_when_the_module_cannot_even_be_built(registry):
    def broken(params):
        raise ValueError("cannot build")

    problems = check_from_measurement(broken)({})
    assert [(p.path, p.message) for p in problems] == [("", "cannot build")]


def test_a_module_with_only_validate_gives_problems_without_a_path(registry):
    check = check_from_measurement(lambda p: registry.create("time_log", p))
    problems = check({})
    assert problems and all(p.path == "" for p in problems)


# ---- the file ---------------------------------------------------------------------------------
def test_save_and_open_keep_everything(model, registry, tmp_path):
    model.set("cable.label", "Cable B")
    path = tmp_path / "b.cbl"
    model.save(path)
    saved = json.loads(path.read_text())
    assert saved["type"] == "cable" and saved["role_bindings"] == {"vna": ["vna1"]}
    assert saved["params"]["cable"]["label"] == "Cable B" and saved["module_version"] == "1.0.0"
    again = FormModel.from_file(model.spec, path, expected_type="cable")
    assert again.params == model.params and again.instrument("vna") == "vna1"
    with pytest.raises(MeasurementError, match="not a 'time_log'"):
        FormModel.from_file(model.spec, path, expected_type="time_log")


def test_the_original_parameters_stay_valid_json(model):
    json.dumps(copy.deepcopy(model.params))


# ---- a role with no instrument ----------------------------------------------------------------
def test_a_required_role_without_an_instrument_is_an_error_at_its_field(registry):
    info = registry.get("cable")
    check = check_from_measurement(lambda p: registry.create("cable", p))
    model = FormModel(
        load_form_spec(info), PARAMS, {}, check, "cable", info.version, required_roles=["vna"]
    )
    assert [(p.path, p.severity) for p in model.problems()] == [("vna", "error")]
    assert "no instrument chosen for 'vna'" in model.problems()[0].message and model.has_errors()
    model.set_instrument("vna", "vna1")
    assert model.problems() == []


def test_the_text_of_the_role_problem_can_be_translated(registry):
    model = FormModel(
        load_form_spec(registry.get("cable")), PARAMS, {}, required_roles=["vna"],
        role_message=lambda role: f"scegli {role}",
    )  # fmt: skip
    assert model.problems()[0].message == "scegli vna"


# ---- a code from the registry -----------------------------------------------------------------
def test_the_asset_field_of_the_forms_asks_for_its_kind_and_the_name_it_fills(registry):
    wanted = {
        "cable": ("cable.asset_id", "cable", "cable.label"),
        "return_loss": ("device.asset_id", None, "device.label"),
        "antenna": ("device.asset_id", "antenna", "device.label"),
        "amplifier": ("device.asset_id", "amplifier", "device.label"),
        "filter": ("filter.asset_id", "filter", "filter.label"),
        "attenuator": ("attenuator.asset_id", "attenuator", "attenuator.label"),
        "ripple": ("device.asset_id", None, "device.label"),
        "regulation": ("device.asset_id", None, "device.label"),
        "bode": ("device.asset_id", None, "device.label"),
        "tdr": ("device.asset_id", "cable", "device.label"),
    }
    for module, (path, kind, label) in wanted.items():
        field = next(f for f in load_form_spec(registry.get(module)).fields() if f.kind == "asset")
        assert (field.path, field.asset_kind, field.label_path) == (path, kind, label), module


def test_an_unknown_code_is_a_warning_not_an_error(registry, tmp_path):
    from ola.assets import AssetRegistry

    cards = AssetRegistry(tmp_path / "assets.json")
    cards.create("cable", "RG316")
    info = registry.get("cable")
    params = {**PARAMS, "cable": {"label": "x", "asset_id": "CBL-0001"}}
    check = check_from_measurement(lambda p: registry.create("cable", p))
    model = FormModel(load_form_spec(info), params, {"vna": ["v"]}, check, "cable", assets=cards)
    assert model.problems() == []
    model.set("cable.asset_id", "CBL-0099")
    found = model.problems()
    assert [(p.path, p.severity) for p in found] == [("cable.asset_id", "warning")]
    assert not model.has_errors() and "not in the registry" in found[0].message
    without = FormModel(load_form_spec(info), params, {"vna": ["v"]}, check, "cable")
    without.set("cable.asset_id", "CBL-0099")
    assert without.problems() == []  # no registry: nothing to say


@pytest.mark.parametrize(
    "module,group",
    [
        ("cable", "cable"),
        ("return_loss", "device"),
        ("antenna", "device"),
        ("amplifier", "device"),
        ("filter", "filter"),
        ("attenuator", "attenuator"),
        ("ripple", "device"),
        ("regulation", "device"),
        ("bode", "device"),
        ("tdr", "device"),
    ],
)
def test_every_measurement_checks_the_code_it_is_given(registry, module, group):
    import sys

    start = sys.modules[registry.load_class(module).__module__].default_params()
    assert registry.create(module, start).check() == []  # the starting point is valid
    for good in ("CBL-0001", "ola:ant-7", "", None):
        ok = {**start, group: {**start.get(group, {}), "asset_id": good}}
        assert registry.create(module, ok).check() == [], (module, good)
    bad = {**start, group: {**start.get(group, {}), "asset_id": "my cable"}}
    found = registry.create(module, bad).check()
    assert [(p.path, p.severity) for p in found] == [(f"{group}.asset_id", "error")]
    assert "CBL-0042" in found[0].message
    assert registry.create(module, bad).validate()  # and it stops the measurement from starting
