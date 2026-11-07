# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Live validation of the efficiency parameters: what is wrong, where, and what to do."""

import pytest

from ola.efficiency_spec import SpecError, parse_params, validate_params
from ola.sweep import iter_points
from tests.efficiency_params import IIN, INSTRUMENTS, IOUT, VAUX, VIN, VOUT, good


def problems(params, bound=INSTRUMENTS, checker=None):
    return [(p.path, p.severity, p.message) for p in validate_params(params, bound, checker)]


def errors(params, **kw):
    return [(path, msg) for path, sev, msg in problems(params, **kw) if sev == "error"]


def only_error(params, **kw):
    found = errors(params, **kw)
    assert len(found) == 1, found
    return found[0]


def test_valid_parameters_have_no_problems_and_parse():
    assert problems(good()) == []
    spec = parse_params(good(), INSTRUMENTS)
    assert list(spec.variables) == ["iout", "vin", "vaux", "iin", "vout"]  # the user's order
    assert [name for name, _ in spec.axes] == ["iout", "vin"]  # swept ones only
    assert spec.point_count() == 9
    assert spec.estimated_seconds() == 9 * (8 + 4 * 10)
    assert list(spec.derived) == ["pin", "pout", "efficiency"]  # dependency order
    assert spec.variables["iin"].reads["daq"].scale == 10
    assert spec.variables["vin"].limits == (5.0, 20.0)


# ---- the order of the list is the order of the sweeps ------------------------------------------


def test_first_parameter_of_the_list_is_the_fastest_sweep():
    spec = parse_params(good(), INSTRUMENTS)
    points = list(iter_points(spec.axes))
    # iout (first) runs through all its values while vin (second) stays; then vin advances
    assert [(p["vin"], p["iout"]) for p in points[:4]] == [(9, 0.5), (9, 1.5), (9, 2.5), (12, 0.5)]
    assert points[-1] == {"iout": 2.5, "vin": 15}


def test_moving_a_parameter_in_the_list_changes_the_nesting():
    p = good()
    p["variables"][IOUT], p["variables"][VIN] = p["variables"][VIN], p["variables"][IOUT]
    spec = parse_params(p, INSTRUMENTS)
    assert [name for name, _ in spec.axes] == ["vin", "iout"]
    points = list(iter_points(spec.axes))
    assert [(x["iout"], x["vin"]) for x in points[:4]] == [(0.5, 9), (0.5, 12), (0.5, 15), (1.5, 9)]


# ---- names: the rules the user asked for -------------------------------------------------------


def test_plain_name_is_the_setpoint_and_at_name_is_a_reading():
    p = good()
    p["derived"]["err"] = "vin@daq - vin"  # reading minus what was set: both valid
    assert errors(p) == []


def test_plain_name_of_a_read_only_parameter_is_refused_with_the_fix():
    p = good()
    p["derived"]["pin"] = "vin * iin"
    path, msg = only_error(p)
    assert path == "derived.pin" and "'iin' has no setpoint" in msg and "iin@daq" in msg


def test_unknown_reading_label_lists_the_readings():
    p = good()
    p["derived"]["pin"] = "vin@dqa * iin@daq"
    path, msg = only_error(p)
    assert path == "derived.pin" and "no reading 'dqa'" in msg and "did you mean 'daq'" in msg
    assert "readings: psu, daq" in msg


def test_unknown_names_get_a_suggestion():
    p = good()
    p["derived"]["pout"] = "voutt@daq * iout@load"
    assert "unknown parameter 'voutt'" in only_error(p)[1]
    p = good()
    p["derived"]["efficiency"] = "100 * pot / pin"
    path, msg = only_error(p)
    assert path == "derived.efficiency" and "unknown name 'pot'" in msg
    assert "did you mean 'pout'" in msg


def test_derived_can_use_other_derived_in_any_order_but_not_loops():
    p = good()
    p["derived"] = {"loss": "pin - pout", "pin": "vin@daq * iin@daq", "pout": "pin * 0.9"}
    assert errors(p) == []
    assert list(parse_params(p, INSTRUMENTS).derived) == ["pin", "pout", "loss"]
    p["derived"] = {"a": "b + 1", "b": "c + 1", "c": "a + 1"}
    assert any("loop" in m for _, m in errors(p))


@pytest.mark.parametrize("name", ["1abc", "has space", "a-b", "a__b", "sqrt", "", "é"])
def test_invalid_parameter_names(name):
    p = good()
    p["variables"].append({"name": name, "reads": {"daq": {"instrument": "daq1", "call": "x"}}})
    assert any(path == "variables[5].name" for path, _ in errors(p))


def test_duplicate_parameter_names_and_clash_with_derived():
    p = good()
    p["variables"].append(dict(p["variables"][IIN]))
    assert only_error(p) == ("variables[5].name", "there is already a parameter called 'iin'")
    p = good()
    p["derived"]["vin"] = "1"
    assert only_error(p) == ("derived.vin", "'vin' is already a parameter, choose another name")


def test_formula_syntax_errors_are_reported_on_the_formula():
    p = good()
    p["derived"]["efficiency"] = "100 * pout /"
    path, msg = only_error(p)
    assert path == "derived.efficiency" and "syntax error" in msg
    p["derived"]["efficiency"] = "__import__('os')"
    assert only_error(p)[0] == "derived.efficiency"


# ---- structure ---------------------------------------------------------------------------------


def test_not_an_object_and_unknown_top_level_keys():
    assert errors([])[0][0] == ""
    p = good()
    p["sweeps"] = []  # the old separate section no longer exists
    path, msg = only_error(p)
    assert path == "sweeps" and "unknown field" in msg


def test_variables_section():
    assert errors({"variables": []})[0][0] == "variables"
    assert errors({"variables": {"vin": {}}})[0][0] == "variables"  # a dict is not a list
    p = good()
    p["variables"][VIN]["typo"] = 1
    assert only_error(p)[0] == "variables[1].typo"
    p = good()
    p["variables"][VOUT] = {"name": "vout"}
    found = errors(p)
    assert found[0][0] == "variables[4]" and "give 'set'" in found[0][1]
    assert found[1][0] == "derived.pout"  # and the formula that used its reading
    p = good()
    p["variables"][VIN] = "5 V"
    assert errors(p)[0][0] == "variables[1]"  # (the formulas using vin complain as well)
    p = good()
    del p["variables"][VIN]["name"]
    assert errors(p)[0] == ("variables[1].name", "the name of the parameter is missing")


def test_a_set_parameter_needs_a_value_or_a_sweep_but_not_both():
    p = good()
    del p["variables"][VAUX]["value"]
    path, msg = only_error(p)
    assert path == "variables[2]" and "no value" in msg
    p = good()
    p["variables"][VAUX]["sweep"] = {"values": [10, 12]}
    assert "fixed 'value' and a 'sweep'" in only_error(p)[1]
    p = good()
    p["variables"][IIN]["value"] = 3  # a read-only parameter cannot be fixed
    assert only_error(p)[0] == "variables[3].value"
    p = good()
    p["variables"][IIN]["sweep"] = {"values": [1]}  # nor swept
    assert only_error(p)[0] == "variables[3].sweep"


def test_sweep_axis_problems_are_reported_on_the_sweep_field():
    p = good()
    p["variables"][IOUT]["sweep"] = {"start": 1, "stop": 5}
    path, msg = only_error(p)
    assert path == "variables[0].sweep" and "either 'points' or 'step'" in msg
    p = good()
    p["variables"][VIN]["sweep"] = {"start": 0, "stop": 10, "points": 3, "scale": "log"}
    assert "start > 0" in only_error(p)[1]


def test_everything_fixed_is_a_single_point():
    p = good()
    p["variables"][IOUT].pop("sweep")
    p["variables"][IOUT]["value"] = 1
    p["variables"][VIN].pop("sweep")
    p["variables"][VIN]["value"] = 12
    assert errors(p) == []
    assert parse_params(p, INSTRUMENTS).point_count() == 1


def test_at_least_one_reading_is_required():
    p = good()
    for v in p["variables"]:
        v.pop("reads", None)
    p["variables"] = [v for v in p["variables"] if "set" in v]
    p["derived"] = {}
    p.pop("startup")
    p.pop("shutdown")
    assert any("nothing is read" in m for _, m in errors(p))


def test_instrument_must_be_in_the_project():
    p = good()
    p["variables"][VIN]["set"]["instrument"] = "psu_1"
    path, msg = only_error(p)
    assert path == "variables[1].set.instrument" and "did you mean 'psu1'" in msg
    assert "available: daq1, load1, psu1, psu2" in msg
    assert errors(p, bound=None) == []  # without a project list it is not checked


def test_set_and_read_fields():
    p = good()
    p["variables"][VIN]["set"]["call"] = ""
    assert only_error(p)[0] == "variables[1].set.call"
    p = good()
    p["variables"][VIN]["set"]["args"] = [1]
    assert only_error(p)[0] == "variables[1].set.args"
    p = good()
    p["variables"][IIN]["reads"]["daq"]["scale"] = 0
    assert only_error(p)[0] == "variables[3].reads.daq.scale"
    p = good()
    p["variables"][IIN]["reads"]["daq"]["scale"] = "10"
    assert only_error(p)[0] == "variables[3].reads.daq.scale"
    p = good()
    p["variables"][VIN]["reads"]["a@b"] = {"instrument": "daq1", "call": "x"}
    assert only_error(p)[0] == "variables[1].reads.a@b"


# ---- timing, limits, verify, start/stop --------------------------------------------------------


@pytest.mark.parametrize(
    "timing,path",
    [
        ({"settle_s": -1}, "timing.settle_s"),
        ({"samples": 0}, "timing.samples"),
        ({"samples": 2.5}, "timing.samples"),
        ({"samples": 10**6}, "timing.samples"),
        ({"interval_s": -0.1}, "timing.interval_s"),
        ({"settle_s": "8"}, "timing.settle_s"),
        ({"typo": 1}, "timing.typo"),
    ],
)
def test_timing_problems(timing, path):
    p = good()
    p["timing"] = timing
    assert only_error(p)[0] == path


def test_timing_warnings_and_defaults():
    p = good()
    p["timing"] = {"settle_s": 1, "samples": 1, "interval_s": 5}
    assert problems(p) == [
        ("timing.interval_s", "warning", "with a single sample the interval is not used")
    ]
    p.pop("timing")
    t = parse_params(p, INSTRUMENTS).timing
    assert (t.settle_s, t.samples, t.interval_s) == (0.0, 1, 0.0)


def test_limits_are_checked_against_every_value_of_the_sweep():
    p = good()
    p["variables"][VIN]["limits"] = {"min": 10, "max": 14}  # the sweep is 9, 12, 15
    path, msg = only_error(p)
    assert path == "variables[1].limits" and "2 value(s) of 'vin' outside [10, 14]: 9, 15" in msg
    p = good()
    p["variables"][VAUX]["limits"] = {"max": 10}  # the fixed value 12 is above
    assert "outside [-inf, 10]: 12" in only_error(p)[1]
    p = good()
    p["variables"][VIN]["limits"] = {"min": 5, "max": 1}
    assert "greater than max" in only_error(p)[1]
    p = good()
    p["variables"][VOUT]["limits"] = {"max": 5}  # only a parameter that is set
    assert "cannot have limits" in only_error(p)[1]


def test_verify_problems():
    p = good()
    p["variables"][VIN]["verify"] = {"read": "dqa", "tol_rel": 0.01}
    path, msg = only_error(p)
    assert path == "variables[1].verify.read" and "did you mean 'daq'" in msg
    p = good()
    p["variables"][VIN]["verify"] = {"read": "daq"}
    assert "zero tolerance" in only_error(p)[1]
    p = good()
    p["variables"][VIN]["verify"] = {"read": "daq", "tol_abs": 0.1, "on_fail": "explode"}
    assert only_error(p)[0] == "variables[1].verify.on_fail"
    p = good()
    p["variables"][IIN]["verify"] = {"read": "daq", "tol_abs": 0.1}
    assert "only a parameter that is set" in only_error(p)[1]


def test_verify_defaults_to_asking_the_user():
    assert parse_params(good(), INSTRUMENTS).variables["vin"].verify.on_fail == "ask"
    for value in ("ask", "warn", "stop"):
        p = good()
        p["variables"][VIN]["verify"]["on_fail"] = value
        assert parse_params(p, INSTRUMENTS).variables["vin"].verify.on_fail == value


def test_startup_and_shutdown_are_extra_calls_and_their_instruments_are_checked():
    p = good()
    p.pop("shutdown")
    assert errors(p) == [] and problems(p) == []  # extra calls: neither is required
    p["startup"] = [{"instrument": "ghost", "call": "output_on"}]
    assert only_error(p)[0] == "startup[0].instrument"
    p = good()
    p["shutdown"].append({"instrument": "psu2"})
    assert only_error(p)[0] == "shutdown[1].call"


def test_several_problems_are_all_reported_at_once():
    p = good()
    p["timing"] = {"samples": 0}
    p["derived"]["pin"] = "vin * iin"
    p["variables"][VIN]["set"]["instrument"] = "ghost"
    assert {path for path, _ in errors(p)} >= {
        "timing.samples",
        "derived.pin",
        "variables[1].set.instrument",
    }


def test_parse_raises_with_the_problems_attached():
    p = good()
    p["timing"] = {"samples": 0}
    with pytest.raises(SpecError) as e:
        parse_params(p, INSTRUMENTS)
    assert e.value.problems[0].path == "timing.samples" and "timing.samples" in str(e.value)


# ---- the second level: the instrument library (checker) ----------------------------------------


class FakeChecker:
    """Stands for the application's check against the instrument library and its limits."""

    def __init__(self, supply_max=15.0, missing=()):
        self.calls, self.supply_max, self.missing = [], supply_max, set(missing)

    def check(self, instrument, call, args):
        self.calls.append((instrument, call, dict(args)))
        if (instrument, call) in self.missing:
            return [f"{instrument} does not support '{call}'"]
        if (
            instrument == "psu1"
            and call == "set_voltage"
            and args.get("value", 0) > self.supply_max
        ):
            return [f"{args['value']:g} V is above the {self.supply_max:g} V maximum of psu1"]
        return []


def test_checker_flags_values_above_the_instrument_limits_with_the_field():
    checker = FakeChecker(supply_max=14.0)  # the sweep goes to 15 V
    found = errors(good(), checker=checker)
    assert found == [("variables[1].set", "15 V is above the 14 V maximum of psu1")]
    values = [a["value"] for i, c, a in checker.calls if (i, c) == ("psu1", "set_voltage")]
    assert values == [9, 15]  # only the extremes of the axis are checked


def test_checker_flags_missing_calls_everywhere_they_are_used():
    found = errors(
        good(), checker=FakeChecker(missing={("daq1", "read_ch"), ("psu1", "output_on")})
    )
    assert {p for p, _ in found} == {
        "variables[1].reads.daq",
        "variables[3].reads.daq",
        "variables[4].reads.daq",
        "startup[0]",
    }


def test_checker_is_not_used_when_the_structure_is_already_broken():
    checker = FakeChecker()
    p = good()
    p["variables"][VIN]["set"]["call"] = ""
    errors(p, checker=checker)
    assert all(c[1] for c in checker.calls)  # never called with an empty call name


def test_validation_does_not_modify_the_parameters():
    p = good()
    before = repr(p)
    validate_params(p, INSTRUMENTS, FakeChecker())
    parse_params(p, INSTRUMENTS)
    assert repr(p) == before


# ---- outputs: keep on, off between points, always on ---------------------------------------------


def out(on="output_on", off="output_off", mode=None, instrument="psu1"):
    block = {}
    if on:
        block["on"] = {"instrument": instrument, "call": on}
    if off:
        block["off"] = {"instrument": instrument, "call": off}
    if mode:
        block["mode"] = mode
    return block


def warnings(params, **kw):
    return [(path, msg) for path, sev, msg in problems(params, **kw) if sev == "warning"]


def test_output_blocks_are_parsed():
    p = good()
    p["variables"][VIN]["output"] = out(mode="off_during_cooldown")
    p["variables"][VAUX]["output"] = out(off=None, mode="always_on", instrument="psu2")
    spec = parse_params(p, INSTRUMENTS)
    assert spec.variables["vin"].output.mode == "off_during_cooldown"
    assert spec.variables["vin"].output.on.call == "output_on"
    assert (
        spec.variables["vaux"].output.mode == "always_on"
        and spec.variables["vaux"].output.off is None
    )
    assert spec.variables["iout"].output is None


def test_output_mode_defaults_to_keep_on():
    p = good()
    p["variables"][VIN]["output"] = out()
    assert parse_params(p, INSTRUMENTS).variables["vin"].output.mode == "keep_on"


def test_output_problems():
    p = good()
    p["variables"][VIN]["output"] = out(mode="sometimes")
    path, msg = only_error(p)
    assert path == "variables[1].output.mode" and "keep_on, off_during_cooldown, always_on" in msg
    p = good()
    p["variables"][IIN]["output"] = out()  # a read-only parameter has no output
    assert only_error(p)[0] == "variables[3].output"
    p = good()
    p["variables"][VIN]["output"] = {"on": {"instrument": "psu1", "call": "output_on"}, "typo": 1}
    assert only_error(p)[0] == "variables[1].output.typo"
    p = good()
    p["variables"][VIN]["output"] = "off"
    assert only_error(p)[0] == "variables[1].output"
    p = good()
    p["variables"][VIN]["output"] = out(instrument="psu_1")
    found = errors(p)
    assert {path for path, _ in found} == {
        "variables[1].output.on.instrument",
        "variables[1].output.off.instrument",
    }


def test_switching_off_during_cooldown_needs_both_calls():
    for block in (
        out(off=None, mode="off_during_cooldown"),
        out(on=None, mode="off_during_cooldown"),
    ):
        p = good()
        p["variables"][VIN]["output"] = block
        path, msg = only_error(p)
        assert path == "variables[1].output" and "both 'on' and 'off'" in msg


def test_warnings_say_what_stays_on():
    p = good()
    p["variables"][VAUX]["output"] = out(mode="always_on", instrument="psu2")
    found = warnings(p)
    on_output = [m for path, m in found if path == "variables[2].output"]
    assert any("always on" in m and "stays ON" in m for m in on_output)
    assert any("also after an error or a stop" in m for m in on_output)
    assert any("no 'state' call" in m and "already on" in m for m in on_output)
    assert any("ignored" in m for path, m in found if path == "variables[2].output.off")
    p = good()
    p["variables"][VIN]["output"] = out(off=None)
    assert any("stays on at the end" in m for path, m in warnings(p))
    assert errors(p) == []


def test_a_state_call_removes_the_state_warning_and_is_parsed():
    p = good()
    p["variables"][VAUX]["output"] = {
        **out(off=None, mode="always_on", instrument="psu2"),
        "state": {"instrument": "psu2", "call": "output_state_query"},
    }
    assert not [m for _, m in warnings(p) if "no 'state' call" in m]
    spec = parse_params(p, INSTRUMENTS)
    assert spec.variables["vaux"].output.state.call == "output_state_query"
    p["variables"][VAUX]["output"]["state"] = {"instrument": "ghost", "call": "x"}
    assert only_error(p)[0] == "variables[2].output.state.instrument"


def test_a_shutdown_call_cannot_switch_off_an_always_on_output():
    p = good()
    p["variables"][VAUX]["output"] = out(mode="always_on", instrument="psu2")
    p["shutdown"] = [{"instrument": "psu2", "call": "output_off"}]
    path, msg = only_error(p)
    assert path == "shutdown[0]" and "'vaux', which is always on" in msg
    p["shutdown"] = [{"instrument": "psu1", "call": "output_off"}]  # another output: fine
    assert errors(p) == []


def test_the_library_checker_also_sees_the_output_calls():
    p = good()
    p["shutdown"] = []
    p["variables"][VIN]["output"] = out()
    found = errors(p, checker=FakeChecker(missing={("psu1", "output_off")}))
    assert found == [("variables[1].output.off", "psu1 does not support 'output_off'")]


# ---- cooldown and power order ------------------------------------------------------------


def cooldown_params(
    cooldown_s=600, modes=("off_during_cooldown", "off_during_cooldown", "always_on")
):
    p = good()
    p["variables"][IOUT]["output"] = out("load_on", "load_off", modes[0], "load1")
    p["variables"][VIN]["output"] = out(mode=modes[1])
    p["variables"][VAUX]["output"] = out(off=None, mode=modes[2], instrument="psu2")
    p["variables"][VAUX]["output"]["state"] = {"instrument": "psu2", "call": "output_state_query"}
    p["timing"]["cooldown_s"] = cooldown_s
    p["startup"], p["shutdown"] = [], []
    return p


def test_cooldown_is_parsed_and_counted():
    p = cooldown_params()
    spec = parse_params(p, INSTRUMENTS)
    assert spec.timing.cooldown_s == 600
    # iout (3 points) is the innermost sweep, vin has 3 values -> 3 sweeps -> 2 cooldowns
    assert spec.sweep_length() == 3 and spec.point_count() == 9 and spec.cooldown_count() == 2
    assert spec.estimated_seconds() == 9 * (8 + 4 * 10) + 2 * 600
    assert errors(p) == []


def test_no_cooldown_without_cooldown_s_or_with_a_single_sweep():
    p = cooldown_params(cooldown_s=0)
    assert parse_params(p, INSTRUMENTS).cooldown_count() == 0
    p = cooldown_params()
    p["variables"][VIN].pop("sweep")
    p["variables"][VIN]["value"] = 12
    spec = parse_params(p, INSTRUMENTS)
    assert spec.cooldown_count() == 0 and spec.estimated_seconds() == 3 * (8 + 4 * 10)


def test_cooldown_settings_that_do_not_fit_together_are_warned_about():
    texts = [
        m for path, m in warnings(cooldown_params(cooldown_s=0)) if path == "timing.cooldown_s"
    ]
    assert any("cooldown_s is 0" in m for m in texts)
    p = cooldown_params(modes=("keep_on", "keep_on", "keep_on"))
    texts = [m for path, m in warnings(p) if path == "timing.cooldown_s"]
    assert any("keeps running" in m for m in texts)
    p = cooldown_params()
    p["variables"][VIN].pop("sweep")
    p["variables"][VIN]["value"] = 12
    texts = [m for path, m in warnings(p) if path == "timing.cooldown_s"]
    assert any("never used" in m for m in texts)
    assert errors(cooldown_params()) == [] and not [
        m for path, m in warnings(cooldown_params()) if path == "timing.cooldown_s"
    ]


def test_cooldown_s_must_be_a_non_negative_number():
    for bad in (-1, "10", True):
        p = cooldown_params(cooldown_s=bad)
        assert only_error(p)[0] == "timing.cooldown_s"


def test_power_order_defaults_to_the_list_order_without_the_always_on_outputs():
    spec = parse_params(cooldown_params(), INSTRUMENTS)
    assert spec.power_order == ["iout", "vin"]  # vaux is always on: not in the list


def test_power_order_can_be_chosen_by_the_user():
    p = cooldown_params()
    p["power_order"] = ["vin", "iout"]  # the supply first, then the load
    assert parse_params(p, INSTRUMENTS).power_order == ["vin", "iout"]


def test_power_order_problems():
    p = cooldown_params()
    p["power_order"] = ["vin", "vaux", "iout"]
    path, msg = only_error(p)
    assert path == "power_order[1]" and "always on" in msg and "before this list" in msg
    p["power_order"] = ["vin", "vinn"]
    found = errors(p)
    assert found[0][0] == "power_order[1]" and "did you mean 'vin'" in found[0][1]
    assert any(path == "power_order" and "iout" in msg for path, msg in found)  # missing one
    p["power_order"] = ["vin", "iout", "vin"]
    assert any("appears twice" in m for _, m in errors(p))
    p["power_order"] = ["vin", "iin"]  # iin has no output
    assert any("no output with an 'on' call" in m for _, m in errors(p))
    p["power_order"] = "vin"
    assert errors(p)[0][0] == "power_order"
