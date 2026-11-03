"""frontend.core.LoadInstruments: the GUI view of the library must agree with the engine
(ola.library) for every model, and must fail cleanly on a bad library file."""

import json

import pytest

from frontend.core.LoadInstruments import LoadInstruments
from tests.conftest import needs_library

TYPES = {
    "power_supplies_series": "power_supply",
    "dataloggers_series": "datalogger",
    "oscilloscopes_series": "oscilloscope",
    "electronic_loads_series": "electronic_load",
    "switch_units_series": "switch_unit",
}


@pytest.fixture(scope="module")
def li(library_path):
    loader = LoadInstruments()
    assert loader.load_instruments(library_path) is True
    return loader


def _gui_models(li):
    for key, type_name in TYPES.items():
        for series in li.instruments.get(key, []) or []:
            for model in series.get("models", []) or []:
                yield type_name, series["series_id"], model


# ---------------------------------------------------------------- loading


@pytest.mark.parametrize(
    "content",
    ["{broken", json.dumps([1, 2]), json.dumps({"instrument_library": {"foo": []}})],
)
def test_bad_library_files_are_refused(tmp_path, content):
    path = tmp_path / "lib.json"
    path.write_text(content, encoding="utf-8")
    li = LoadInstruments()
    assert li.load_instruments(str(path)) is False
    assert li.instruments == {}


def test_missing_library_file_is_refused(tmp_path):
    li = LoadInstruments()
    assert li.load_instruments(str(tmp_path / "missing.json")) is False


def test_library_without_wrapper_key_is_accepted(tmp_path):
    path = tmp_path / "lib.json"
    path.write_text(json.dumps({"power_supplies_series": []}), encoding="utf-8")
    li = LoadInstruments()
    assert li.load_instruments(str(path)) is True


def test_default_path_loads_the_submodule(library_path):
    li = LoadInstruments()
    assert li.load_instruments() is True
    assert li.instruments


# ---------------------------------------------------------------- agreement with the engine


@needs_library
def test_every_category_of_the_gui_types_is_loaded(li):
    for key, type_name in TYPES.items():
        if li.instruments.get(key):
            assert type_name in li.get_all_types()
            assert li.get_series(type_name) == li.instruments[key]


@needs_library
def test_gui_and_engine_see_the_same_commands(li, library):
    checked = 0
    engine = li.get_library()
    for type_name, series_id, model in _gui_models(li):
        model_id = model["id"]
        gui = li.get_model_scpi(type_name, series_id, model_id)
        assert gui == library.commands(model_id) == engine.commands(model_id), model_id
        assert engine.schema(library.find_model(model_id).category) == library.schema(
            library.find_model(model_id).category
        )
        checked += 1
    assert checked > 0


@needs_library
def test_names_and_connections_of_every_model(li):
    for type_name, series_id, model in _gui_models(li):
        model_id = model["id"]
        assert li.get_series_name(type_name, series_id)
        assert li.get_model_name(type_name, series_id, model_id) == model["name"]
        assert li.get_supported_connections(type_name, series_id, model_id), model_id
        found = li.find_instrument(type_name, series_id, model_id)
        assert found is not None, model_id


@needs_library
def test_channels_and_limits_of_sources_and_loads(li):
    for type_name, series_id, model in _gui_models(li):
        if type_name not in ("power_supply", "electronic_load"):
            continue
        model_id = model["id"]
        ids = li.get_channel_ids(type_name, series_id, model_id)
        assert ids, model_id
        assert len(ids) == len(set(ids)), f"{model_id}: duplicated channel ids {ids}"
        for channel_id in ids:
            limits = li.get_channel_limits(type_name, series_id, model_id, channel_id)
            # max_voltage may be 0 for a negative output (E3631A -25 V: range -25..0)
            assert limits["max_voltage"] is None or limits["max_voltage"] >= 0, model_id
            current = limits["max_current"]
            assert current is None or current > 0, f"{model_id} {channel_id} max_current"
        if type_name == "power_supply":
            limits = li.get_channel_limits(type_name, series_id, model_id, ids[0])
            assert limits["max_voltage"] and limits["max_current"], model_id


@needs_library
def test_power_supply_channel_limits_are_ordered(li):
    for type_name, series_id, model in _gui_models(li):
        for channel in li.get_channel_info(type_name, series_id, model["id"]) or []:
            if not isinstance(channel, dict):
                continue
            for key, spec in channel.items():
                if isinstance(spec, dict) and "min" in spec and "max" in spec:
                    assert spec["min"] <= spec["max"], f"{model['id']} {key}"


@needs_library
def test_visible_models_hide_experimental_ones(li):
    for type_name in TYPES.values():
        for series in li.get_series(type_name) or []:
            sid = series["series_id"]
            every = li.get_visible_models(type_name, sid, include_experimental=True)
            visible = li.get_visible_models(type_name, sid) or []
            assert every == series["models"]
            assert visible == [m for m in every if not m.get("experimental", False)]
        visible_series = li.get_visible_series(type_name) or []
        for series in visible_series:
            assert series["models"] and not any(m.get("experimental") for m in series["models"])


@needs_library
def test_datalogger_modules(li):
    modules = li.get_all_datalogger_modules()
    ids = [m["id"] for m in modules]
    assert ids and len(ids) == len(set(ids))
    for module_id in ids:
        assert li.get_module_info(module_id)["id"] == module_id
        assert li.get_module_channels(module_id) >= 0
    assert li.get_module_info("NOPE") is None and li.get_module_channels("NOPE") == 0
    for series in li.get_series("datalogger") or []:
        for model in series["models"]:
            enabled = li.get_enabled_compatible_modules(
                "datalogger", series["series_id"], model["id"]
            )
            compatible = li.get_compatible_modules("datalogger", series["series_id"], model["id"])
            for module in enabled:
                assert module["id"] in compatible and not module.get("not_enabled", False)
    assert li.get_compatible_modules("power_supply", "x", "y") == []


def test_unknown_lookups_return_none(li):
    assert li.get_series("boh") is None
    assert li.get_models("power_supply", "NOPE") is None
    assert li.get_model_scpi("power_supply", "NOPE", "NOPE") is None
    assert li.get_model_capabilities("oscilloscope", "NOPE", "NOPE") is None
