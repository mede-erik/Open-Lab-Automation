# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The real instrument library (``Instruments_LIB``) against the engine.

``Instruments_LIB/Tests/check_conformance.py`` checks the library against the schemas; these
tests check it against the code that uses it: every call of every model must be plannable by
``ola.call_planner`` with valid arguments, every logical value of the schema must either plan
or be refused cleanly with CALL-002, and the data the engine reads (parsers, result steps,
serial settings, driver entries) must be usable. A broken library entry fails here before
it reaches an instrument.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from ola.call_errors import CallError, ValueNotHandledError
from ola.call_planner import plan_call
from ola.library import Library
from ola.parsers import PARSERS
from ola.serial_config import apply_serial_settings
from ola.steps import Step
from ola.tester import describe_plan, missing_mandatory
from ola.was_calls import oscilloscope_calls_from_was
from tests.conftest import LIBRARY_PATH, REPO, needs_library

pytestmark = needs_library


def _model_ids():
    if LIBRARY_PATH is None:
        return []
    with open(LIBRARY_PATH, encoding="utf-8") as f:
        data = json.load(f)["instrument_library"]
    return [
        m["id"]
        for series_list in data.values()
        if isinstance(series_list, list)
        for series in series_list
        for m in series.get("models", []) or []
    ]


MODEL_IDS = _model_ids()
TRANSPORT_KINDS = {"vxi11", "raw_socket", "usbtmc", "serial", "hislip", "gpib"}


# ---------------------------------------------------------------- helpers


def _number(arg, pdef, kind):
    """A valid number for a numeric schema argument (inside min/max, preferring 1)."""
    for key in pdef.get("map") or {}:
        try:
            value = float(key)
        except ValueError:
            continue
        return int(value) if kind == "int" else value
    value = 1
    if arg.get("min") is not None and value < arg["min"]:
        value = arg["min"]
    if arg.get("max") is not None and value > arg["max"]:
        value = arg["max"]
    return int(value) if kind == "int" else float(value)


def _sample(arg, types, pdef):
    """A valid logical value for one schema argument."""
    t = arg["type"]
    kind = types.get(t, {}).get("kind")
    if "default" in arg:
        return arg["default"]
    if t in ("int", "float"):
        return _number(arg, pdef, t)
    if t == "number_or_keyword":
        return _number(arg, pdef, "float")
    if kind == "enum":
        logical = types[t]["values"]
        mapped = [v for v in logical if v in (pdef.get("map") or {})]
        return (mapped or logical)[0]
    if kind == "bool":
        return True
    if kind == "list":  # e.g. a list of S-parameters: one valid item
        item = types[t].get("item", "string")
        return [_sample({"type": item}, types, pdef)]
    if kind == "mapping":
        return {}
    if pdef.get("map"):
        return next(iter(pdef["map"]))
    if pdef.get("values"):
        return pdef["values"][0]
    return "1"


def _calls(library: Library, model_id: str):
    """(call name, definition, schema spec or None, schema types) for every call of a model."""
    ref = library.find_model(model_id)
    schema = library.schema(ref.category) or {"calls": {}, "types": {}}
    for name, definition in sorted(library.commands(model_id).items()):
        yield name, definition, schema["calls"].get(name), schema.get("types", {})


def _args(definition, spec, types):
    """Valid logical arguments for a call (from the schema, or the library parameters)."""
    params = definition.get("parameters") or {}
    if spec is not None:
        return {n: _sample(a, types, params.get(n, {})) for n, a in spec.get("args", {}).items()}
    out = {}
    for name, pdef in params.items():
        if pdef.get("from"):
            continue
        if pdef.get("values"):
            out[name] = pdef["values"][0]
        else:
            out[name] = 1 if pdef.get("type") in ("int", "float") else "1"
    return out


def _halves(definition, spec):
    """``readback`` flags to plan: the call itself, plus the read-back of a set call."""
    flags = [False]
    if spec is not None and spec["kind"] == "set" and definition.get("query"):
        flags.append(True)
    return flags


# ---------------------------------------------------------------- library shape


def test_library_has_models():
    assert len(MODEL_IDS) > 0


def test_model_ids_are_unique():
    duplicated = sorted({m for m in MODEL_IDS if MODEL_IDS.count(m) > 1})
    assert duplicated == []


def test_series_ids_are_unique(library):
    ids = [
        s.get("series_id")
        for series_list in library.categories.values()
        if isinstance(series_list, list)
        for s in series_list
        if "models" in s
    ]
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


def test_every_schema_category_has_series(library):
    for category in library.schemas:
        assert library.categories.get(category), f"schema for {category} but no series"


def test_schema_version_matches(library):
    for category, schema in library.schemas.items():
        assert schema["schema_version"] == library.schema_version, category


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_model_is_found_and_resolved(library, model_id):
    ref = library.find_model(model_id)
    assert ref is not None
    assert library.resolve_model_id(model_id) == model_id
    for key in ("name", "manufacturer", "model"):
        assert ref.model.get(key), f"{model_id}: '{key}' is empty"


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_model_has_every_mandatory_call(library, model_id):
    assert missing_mandatory(library, model_id) == []


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_interface_block(library, model_id):
    model = library.find_model(model_id).model
    conns = model.get("interface", {}).get("supported_connection_types", [])
    assert conns, f"{model_id} has no connection type"
    for conn in conns:
        # "type" is a label shown to the user (LXI, USB-TMC, "LXI raw socket", ...)
        assert isinstance(conn.get("type"), str) and conn["type"].strip(), conn
        for transport in conn.get("transports", []) or []:
            assert transport.get("kind") in TRANSPORT_KINDS, transport
            if transport["kind"] == "raw_socket":
                assert 0 < int(transport["port"]) < 65536


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_serial_settings_are_applicable(library, model_id):
    """The serial values of the library must be values pyvisa knows (no typo in parity,
    flow control, stop bits)."""
    settings = library.serial_settings(model_id)
    resource = SimpleNamespace()
    apply_serial_settings(resource, settings)
    if "baud" in settings:
        assert resource.baud_rate > 0
    for key in ("write_termination", "read_termination"):
        if key in settings:
            # empty for a binary protocol without terminator (LiteVNA)
            assert isinstance(settings[key], str)


# ---------------------------------------------------------------- planning


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_every_call_plans_with_valid_arguments(library, model_id):
    """Every call of the model plans; set calls with a query half also plan the read-back."""
    failures = []
    for name, definition, spec, types in _calls(library, model_id):
        args = _args(definition, spec, types)
        for readback in _halves(definition, spec):
            try:
                plan = plan_call(library, model_id, name, args, readback=readback)
            except CallError as exc:
                failures.append(f"{name}{' (readback)' if readback else ''} {args}: {exc}")
                continue
            if plan.access == "driver":
                assert plan.driver["function"], name
                continue
            assert plan.steps, name
            for step in plan.steps:
                Step.from_dict(step)
                assert "{" not in (step.get("text") or ""), f"{name}: unresolved placeholder"
            assert describe_plan(library, model_id, name, args, readback=readback)
    assert failures == []


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_every_logical_value_plans_or_is_refused_cleanly(library, model_id):
    """For enum, bool and keyword arguments every logical value of the schema either plans or
    is refused with CALL-002 (not handled by this model); never another error."""
    failures = []
    for name, definition, spec, types in _calls(library, model_id):
        if spec is None:
            continue
        base = _args(definition, spec, types)
        for arg_name, arg in spec.get("args", {}).items():
            kind = types.get(arg["type"], {}).get("kind")
            item_type = types.get(types.get(arg["type"], {}).get("item"), {})
            if kind == "enum":
                values = types[arg["type"]]["values"]
            elif kind == "list" and item_type.get("kind") == "enum":
                values = [[v] for v in item_type["values"]]
            elif kind == "bool":
                values = [True, False]
            elif arg["type"] == "number_or_keyword":
                values = list(arg.get("keywords", []))
            else:
                continue
            for value in values:
                try:
                    plan_call(library, model_id, name, {**base, arg_name: value})
                except ValueNotHandledError:
                    pass
                except CallError as exc:
                    failures.append(f"{name} {arg_name}={value!r}: {exc}")
    assert failures == []


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_maps_use_logical_values(library, model_id):
    """A ``map`` translates logical values: its keys must be values of the schema type
    (a vendor value as key would never be reached)."""
    bad = []
    for name, definition, spec, types in _calls(library, model_id):
        if spec is None:
            continue
        params = definition.get("parameters") or {}
        for pname, pdef in params.items():
            source = pdef.get("from", pname)
            if not isinstance(source, str) or not pdef.get("map"):
                continue
            arg = spec.get("args", {}).get(source)
            if arg is None:
                continue
            t = types.get(arg["type"], {})
            if t.get("kind") == "enum":
                allowed = set(t["values"])
            elif t.get("kind") == "bool":
                allowed = {"true", "false"}
            else:
                continue
            extra = set(pdef["map"]) - allowed
            if extra:
                bad.append(f"{name}.{pname}: {sorted(extra)} not in {sorted(allowed)}")
    assert bad == []


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_parsers_and_result_steps_exist(library, model_id):
    bad = []
    for name, definition, _spec, _types in _calls(library, model_id):
        for half_name in ("set", "query"):
            half = definition.get(half_name) or {}
            n_steps = len(half.get("steps", [None]))
            parse = half.get("parse")
            if parse:
                if parse.get("name") not in PARSERS:
                    bad.append(f"{name}: unknown parser {parse.get('name')!r}")
                source = parse.get("from_steps", [])  # a list of steps, or "queries"
                if isinstance(source, str):
                    if source != "queries":
                        bad.append(f"{name}: parser reads from {source!r}")
                elif any(not 0 <= i < n_steps for i in source):
                    bad.append(f"{name}: parser reads a step that does not exist")
            if "result_step" in half and not 0 <= half["result_step"] < n_steps:
                bad.append(f"{name}: result_step {half['result_step']} out of range")
    assert bad == []


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_driver_models_only_use_drivers(library, model_id):
    ref = library.find_model(model_id)
    if ref.model.get("access", "scpi") != "driver":
        return
    for name, definition in library.commands(model_id).items():
        assert "driver" in definition, f"{model_id}.{name}: a driver model needs 'driver'"


def test_query_answers_are_interpreted(library):
    """A query whose answer is translated (response_map / bool) accepts every answer the
    library lists and refuses an unknown one with CALL-005."""
    checked = 0
    for model_id in MODEL_IDS:
        for name, definition, spec, types in _calls(library, model_id):
            if spec is None or spec["kind"] != "query":
                continue
            query = definition.get("query") or {}
            if "steps" in query or "split" in query or query.get("parse"):
                continue
            plan = plan_call(library, model_id, name, _args(definition, spec, types))
            if "response_map" in query:
                for answer, logical in query["response_map"].items():
                    assert plan.interpret([answer]) == logical
            elif "bool" in query:
                for answer in query["bool"].get("true", []):
                    assert plan.interpret([answer]) is True
                for answer in query["bool"].get("false", []):
                    assert plan.interpret([answer]) is False
            else:
                continue
            with pytest.raises(CallError) as info:
                plan.interpret(["#not-an-answer#"])
            assert info.value.code == "CALL-005"
            checked += 1
    assert checked > 0


# ---------------------------------------------------------------- example files


@pytest.mark.parametrize(
    "was_file",
    [
        "examples/test-dcdc-project/osc1.was",
        "examples/test-dcdc-project/Wav_setup.was",
        "examples/Test_scpi/wave_setting.was",
    ],
)
def test_example_oscilloscope_settings_plan_on_every_oscilloscope(library, was_file):
    with open(os.path.join(REPO, was_file), encoding="utf-8") as f:
        was = json.load(f)
    calls = oscilloscope_calls_from_was(was)
    assert calls
    scopes = [m for m in MODEL_IDS if library.find_model(m).category == "oscilloscopes_series"]
    for model_id in scopes:
        for name, args in calls:
            assert plan_call(library, model_id, name, args).steps, f"{model_id}.{name}"
