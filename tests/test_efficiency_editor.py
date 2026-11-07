# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The model behind the efficiency editor: the operations a user does with the mouse."""

import json

import pytest

from ola.efficiency_editor import (
    EditorError,
    EfficiencyEditor,
    get_path,
    set_path,
    split_path,
)
from ola.project import MeasurementFile
from tests.efficiency_params import INSTRUMENTS, IOUT, VAUX, VIN, good


def editor(params=None, **kw):
    return EfficiencyEditor(params if params is not None else good(), INSTRUMENTS, **kw)


# ---- paths -------------------------------------------------------------------------------------


def test_split_path():
    assert split_path("variables[1].set.call") == ["variables", 1, "set", "call"]
    assert split_path("timing.settle_s") == ["timing", "settle_s"]
    assert split_path("power_order[0]") == ["power_order", 0]


def test_get_and_set_by_path():
    data = {"variables": [{"name": "a"}, {"name": "b"}]}
    assert get_path(data, "variables[1].name") == "b"
    assert get_path(data, "variables[5].name", "none") == "none"
    set_path(data, "variables[1].set.call", "set_voltage")  # creates the missing object
    assert data["variables"][1]["set"] == {"call": "set_voltage"}
    set_path(data, "variables[1].set.call", None)  # None removes the key
    assert data["variables"][1]["set"] == {}
    set_path(data, "variables[0].reads.daq.args", None)  # nothing to remove: no error
    assert "reads" not in data["variables"][0]
    with pytest.raises(EditorError):
        set_path(data, "variables[9].name", "x")


def test_setting_a_field_invalidates_the_cached_problems():
    e = editor()
    assert e.problems() == []
    e.set("variables[1].set.call", "")
    assert any(p.path == "variables[1].set.call" for p in e.problems())


# ---- parameters --------------------------------------------------------------------------------


def test_add_duplicate_remove_parameters():
    e = editor()
    i = e.add_parameter("vsense")
    assert e.names()[-1] == "vsense" and i == 5
    second = e.add_parameter("vsense")
    assert e.names()[second] == "vsense2"
    j = e.duplicate_parameter(VIN)
    assert (
        j == VIN + 1
        and e.names()[j] == "vin2"
        and e.variables[j]["sweep"] == e.variables[VIN]["sweep"]
    )
    e.variables[j]["sweep"]["values"].append(99)  # a real copy
    assert 99 not in e.variables[VIN]["sweep"]["values"]
    e.remove_parameter(j)
    assert "vin2" not in e.names()
    with pytest.raises(EditorError):
        e.remove_parameter(99)


def test_moving_a_parameter_changes_the_order_and_stops_at_the_ends():
    e = editor()
    assert e.names()[:3] == ["iout", "vin", "vaux"]
    assert e.move_parameter(VIN, -1) == 0 and e.names()[:2] == ["vin", "iout"]
    assert e.move_parameter(0, -1) == 0  # already first
    assert e.move_parameter(len(e.names()) - 1, +1) == len(e.names()) - 1
    e2 = editor()
    assert [n for n, _ in e2.summary()["axes"]] == ["iout", "vin"]
    e2.move_parameter(VIN, -1)
    assert [n for n, _ in e2.summary()["axes"]] == ["vin", "iout"]  # the sweep order follows


def test_rename_a_parameter_updates_the_formulas_and_the_power_order():
    p = good()
    p["variables"][VIN]["output"] = {"on": {"instrument": "psu1", "call": "on"}}
    p["power_order"] = ["vin"]
    p["derived"]["err"] = "vin@daq - vin + vin_extra"
    e = editor(p)
    changed = e.rename_parameter(VIN, "vsupply")
    assert sorted(changed) == ["err", "pin"]
    assert e.params["derived"]["pin"] == "vsupply@daq * iin@daq"
    assert e.params["derived"]["err"] == "vsupply@daq - vsupply + vin_extra"  # whole names only
    assert e.params["power_order"] == ["vsupply"]
    errors = [str(p) for p in e.problems() if p.severity == "error"]
    assert errors == ["derived.err: unknown name 'vin_extra'"]  # only the name I made up


def test_rename_refuses_bad_or_taken_names():
    e = editor()
    for bad in ("1abc", "a b", "a__b", ""):
        with pytest.raises(EditorError):
            e.rename_parameter(VIN, bad)
    with pytest.raises(EditorError, match="already used"):
        e.rename_parameter(VIN, "iout")
    with pytest.raises(EditorError, match="already used"):
        e.rename_parameter(VIN, "pin")  # a derived quantity has that name
    assert e.rename_parameter(VIN, "vin") == []  # same name: nothing to do


def test_removing_a_parameter_leaves_the_formulas_to_the_problem_list():
    e = editor()
    e.remove_parameter(VIN)
    assert e.params["derived"]["pin"] == "vin@daq * iin@daq"  # not silently changed
    assert any(p.path == "derived.pin" for p in e.problems())


# ---- readings ----------------------------------------------------------------------------------


def test_reading_labels_add_remove_rename():
    e = editor()
    assert e.reading_labels(VIN) == ["psu", "daq"]
    assert e.add_reading(VIN, "scope") == "scope" and e.add_reading(VIN, "scope") == "scope2"
    e.remove_reading(VIN, "scope2")
    e.remove_reading(VIN, "scope")
    changed = e.rename_reading(VIN, "daq", "logger")
    assert changed == ["pin"] and e.params["derived"]["pin"] == "vin@logger * iin@daq"
    assert e.variables[VIN]["verify"]["read"] == "logger"  # the check follows
    assert e.reading_labels(VIN) == ["psu", "logger"]  # same position
    with pytest.raises(EditorError):
        e.rename_reading(VIN, "logger", "psu")
    with pytest.raises(EditorError):
        e.rename_reading(VIN, "ghost", "x")


def test_removing_the_verified_reading_removes_the_check():
    e = editor()
    e.remove_reading(VIN, "daq")
    assert "verify" not in e.variables[VIN]


def test_removing_the_last_reading_removes_the_empty_dict():
    e = editor()
    e.remove_reading(IOUT, "load")
    assert "reads" not in e.variables[IOUT]


# ---- sweeps ------------------------------------------------------------------------------------


def test_sweep_modes_and_values():
    e = editor()
    assert (
        e.sweep_mode(IOUT) == "points"
        and e.sweep_mode(VIN) == "list"
        and e.sweep_mode(VAUX) == "fixed"
    )
    assert e.sweep_values(VIN) == [9, 12, 15] and e.sweep_values(VAUX) == [12.0]
    assert e.sweep_values(3) is None and e.sweep_mode(3) == "none"  # iin: only read


def test_switching_the_mode_keeps_the_range_and_gives_valid_defaults():
    e = editor()
    e.set_sweep_mode(VIN, "points")
    assert e.variables[VIN]["sweep"] == {"start": 9, "stop": 15, "points": 3}
    e.set_sweep_mode(VIN, "step")
    assert e.sweep_mode(VIN) == "step" and e.sweep_error(VIN) is None
    e.set_sweep_mode(VIN, "log")
    assert e.sweep_mode(VIN) == "log" and e.sweep_error(VIN) is None
    e.set_sweep_mode(VIN, "fixed")
    assert "sweep" not in e.variables[VIN] and "value" in e.variables[VIN]
    fixed = e.variables[VIN]["value"]
    e.set_sweep_mode(VIN, "list")
    assert e.sweep_mode(VIN) == "list" and e.sweep_values(VIN) == [fixed]  # keeps the value
    e.set_sweep_mode(VIN, "none")
    assert e.sweep_mode(VIN) == "none"
    with pytest.raises(EditorError):
        e.set_sweep_mode(VIN, "spiral")


def test_sweep_error_says_why():
    e = editor()
    e.set("variables[0].sweep.points", 0)
    assert "integer >= 1" in e.sweep_error(IOUT)
    assert e.sweep_values(IOUT) is None


# ---- formulas and names ------------------------------------------------------------------------


def test_available_names_for_the_formula_editor():
    names = editor().available_names()
    assert names["setpoints"] == ["iout", "vin", "vaux"]  # parameters that are set
    assert "vin@daq" in names["readings"] and "iin@daq" in names["readings"]
    assert names["derived"] == ["pin", "pout", "efficiency"]


def test_set_remove_rename_formulas():
    e = editor()
    e.set_formula("loss", "pin - pout")
    assert e.params["derived"]["loss"] == "pin - pout" and e.problems() == []
    changed = e.rename_formula("pin", "p_in")
    assert sorted(changed) == ["efficiency", "loss"]
    assert e.params["derived"]["efficiency"] == "100 * pout / p_in"
    assert list(e.params["derived"])[:3] == ["p_in", "pout", "efficiency"]  # same position
    e.remove_formula("loss")
    assert "loss" not in e.params["derived"]
    with pytest.raises(EditorError):
        e.set_formula("vin", "1")  # clashes with a parameter
    with pytest.raises(EditorError):
        e.set_formula("bad name", "1")
    with pytest.raises(EditorError):
        e.rename_formula("ghost", "x")


def test_removing_the_last_formula_removes_the_section():
    e = editor({"variables": [], "derived": {"a": "1"}})
    e.remove_formula("a")
    assert "derived" not in e.params


# ---- power order -------------------------------------------------------------------------------


def power_params():
    p = good()
    for i, name in ((IOUT, "load"), (VIN, "psu1")):
        p["variables"][i]["output"] = {
            "on": {"instrument": "load1" if i == IOUT else "psu1", "call": "on"},
            "off": {"instrument": "load1" if i == IOUT else "psu1", "call": "off"},
        }
    p["variables"][VAUX]["output"] = {
        "on": {"instrument": "psu2", "call": "on"},
        "mode": "always_on",
    }
    return p


def test_power_order_default_excludes_always_on_and_can_be_moved():
    e = editor(power_params())
    assert e.managed_outputs() == ["iout", "vin"] and e.power_order() == ["iout", "vin"]
    assert e.move_power(1, -1) == 0 and e.power_order() == ["vin", "iout"]
    assert e.params["power_order"] == ["vin", "iout"]
    assert e.move_power(0, -1) == 0  # at the top already
    e.reset_power_order()
    assert "power_order" not in e.params and e.power_order() == ["iout", "vin"]


def test_power_order_ignores_stale_names_and_adds_new_outputs():
    e = editor(power_params())
    e.set_power_order(["ghost", "vin"])
    assert e.power_order() == ["vin", "iout"]


# ---- problems, summary -------------------------------------------------------------------------


def test_problems_at_a_prefix():
    e = editor()
    e.set("variables[1].set.call", "")
    e.set("timing.samples", 0)
    assert [p.path for p in e.problems_at("variables[1]")] == ["variables[1].set.call"]
    assert [p.path for p in e.problems_at("timing")] == ["timing.samples"]
    assert e.problems_at("variables[0]") == [] and e.has_errors()


def test_summary_of_a_valid_measurement():
    s = editor().summary()
    assert s["valid"] and s["points"] == 9 and s["sweeps"] == 3 and s["cooldowns"] == 0
    assert s["seconds"] == 9 * (8 + 4 * 10) and s["axes"] == [("iout", 3), ("vin", 3)]
    e = editor()
    e.set("timing.cooldown_s", 600)
    assert e.summary()["cooldowns"] == 2
    e.set("variables[1].set.call", "")
    assert e.summary() == {"valid": False}


@pytest.mark.parametrize(
    "seconds,text", [(5, "5 s"), (90, "1 min 30 s"), (600, "10 min"), (3725, "1 h 2 min")]
)
def test_format_duration(seconds, text):
    assert EfficiencyEditor.format_duration(seconds) == text


# ---- templates, files --------------------------------------------------------------------------


def test_template_tells_you_what_to_fill_in():
    e = EfficiencyEditor(EfficiencyEditor.template(["psu1", "daq1"]), ["psu1", "daq1"])
    assert e.names() == ["iout", "vin", "iin", "vout"]
    paths = {p.path for p in e.problems() if p.severity == "error"}
    assert "variables[0].set.call" in paths and "variables[2].reads.daq.call" in paths
    assert not EfficiencyEditor(None).names()  # an empty one is fine too


def test_save_and_open_roundtrip(tmp_path):
    e = editor()
    path = tmp_path / "conv.eff"
    e.save(str(path))
    data = json.loads(path.read_text())
    assert data["type"] == "efficiency" and data["role_bindings"] == {
        "instruments": ["daq1", "load1", "psu1", "psu2"]
    }  # the instruments used
    again = EfficiencyEditor.from_file(str(path), instruments=INSTRUMENTS)
    assert again.params == e.params
    assert isinstance(e.to_measurement_file(), MeasurementFile)


def test_opening_another_kind_of_file_is_refused(tmp_path):
    path = tmp_path / "log.tlg"
    MeasurementFile("time_log").save(path)
    with pytest.raises(EditorError, match="not an efficiency file"):
        EfficiencyEditor.from_file(str(path))


def test_the_editor_works_on_a_copy():
    p = good()
    e = EfficiencyEditor(p, INSTRUMENTS)
    e.rename_parameter(VIN, "x")
    assert p["variables"][VIN]["name"] == "vin"
