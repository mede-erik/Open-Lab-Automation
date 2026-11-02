"""resolve_model_commands: series commands + model override / null / patch."""

from ola.library import Library, resolve_model_commands


def _series():
    return {
        "common_scpi_commands": {
            "set_a": {"set": {"syntax": "A {value}"}, "parameters": {"value": {"type": "float"}}},
            "set_b": {
                "set": {"syntax": "B {mode}"},
                "parameters": {"mode": {"type": "string", "values": ["X", "Y"]}},
            },
            "set_c": {"set": {"syntax": "C"}},
            "set_d": {"set": {"syntax": "D"}},
        }
    }


def test_override_remove_patch():
    model = {
        "id": "M",
        "scpi_commands": {
            "set_a": {"set": {"syntax": "A2 {value}"}, "parameters": {"value": {"type": "float"}}},
            "set_b": {"patch": {"parameters": {"mode": {"values": ["X", "Y", "Z"]}}}},
            "set_c": None,
            "set_x": {"patch": {"set": {"syntax": "ignored"}}},
        },
    }
    series = _series()
    out = resolve_model_commands(series, model)
    assert out["set_a"]["set"]["syntax"] == "A2 {value}"
    assert out["set_b"]["set"]["syntax"] == "B {mode}"
    assert out["set_b"]["parameters"]["mode"] == {"type": "string", "values": ["X", "Y", "Z"]}
    assert "set_c" not in out
    assert out["set_d"] == {"set": {"syntax": "D"}}
    assert "set_x" not in out
    assert series["common_scpi_commands"]["set_b"]["parameters"]["mode"]["values"] == ["X", "Y"]


def test_driver_definition_replaces():
    model = {"id": "M", "scpi_commands": {"set_a": {"driver": {"function": "f"}}}}
    out = resolve_model_commands(_series(), model)
    assert out["set_a"] == {"driver": {"function": "f"}}


def test_library_find_model():
    lib = Library({"cat": [{"series_id": "S", **_series(), "models": [{"id": "M"}]}]})
    ref = lib.find_model("M")
    assert ref.category == "cat" and ref.series["series_id"] == "S"
    assert lib.find_model("nope") is None
    assert "set_a" in lib.commands("M")


def test_serial_settings_from_the_interface_block():
    model = {
        "id": "M",
        "interface": {
            "supported_connection_types": [
                {"type": "GPIB"},
                {
                    "type": "SERIAL",
                    "transports": [
                        {
                            "kind": "serial",
                            "baud": 9600,
                            "flow_control": "dtr_dsr",
                            "factory_defaults": True,
                        }
                    ],
                },
            ]
        },
    }
    lib = Library({"cat": [{"series_id": "S", **_series(), "models": [model, {"id": "N"}]}]})
    assert lib.serial_settings("M") == {"baud": 9600, "flow_control": "dtr_dsr"}
    assert lib.serial_settings("N") == {} and lib.serial_settings("nope") == {}
