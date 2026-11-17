# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""An entry of the instrument file gets all the information its model has."""

import copy

from ola.inst_complete import complete_entries, complete_entry


class FakeLibrary:
    def __init__(self, caps, limits=None, ids=None):
        self.caps, self.limits, self.ids = caps, limits or {}, ids or []

    def get_model_capabilities(self, kind, series, model):
        return self.caps

    def get_channel_ids(self, kind, series, model):
        return self.ids

    def get_channel_limits(self, kind, series, model, channel_id=None):
        return self.limits


def entry(kind, **extra):
    return {"instrument_type": kind, "instance_name": "x", "series": "s", "model_id": "m", **extra}


def test_a_supply_gets_its_channels_with_the_limits_of_the_model():
    lib = FakeLibrary({"number_of_channels": 2}, {"max_voltage": 30.0, "max_current": 3.0},
                      ["1", "2"])
    e = complete_entry(lib, entry("power_supply", channels=[]))
    assert [c["name"] for c in e["channels"]] == ["1", "2"]
    assert e["channels"][0] == {
        "enabled": False, "name": "1", "max_current": 3.0, "max_voltage": 30.0}


def test_what_the_entry_already_has_is_kept():
    lib = FakeLibrary({"number_of_channels": 2}, {"max_voltage": 30.0, "max_current": 3.0})
    mine = {"enabled": True, "name": "VOUT", "max_voltage": 12.0, "max_current": 1.0}
    e = complete_entry(lib, entry("power_supply", channels=[mine]))
    assert e["channels"][0] is mine and mine["max_voltage"] == 12.0
    assert len(e["channels"]) == 2


def test_a_load_without_channel_definition_has_one_channel():
    e = complete_entry(FakeLibrary({}, ids=["CH1"]), entry("electronic_load"))
    assert [c["name"] for c in e["channels"]] == ["CH1"]


def test_an_oscilloscope_gets_channel_ids_and_probe_attenuation():
    lib = FakeLibrary({"number_of_channels": 2}, ids=["CH1", "CH2"])
    e = complete_entry(lib, entry("oscilloscope"))
    assert [(c["channel_id"], c["probe_attenuation"]) for c in e["channels"]] == [
        ("CH1", 1.0), ("CH2", 1.0)]


def test_a_multimeter_gets_its_channel_settings():
    e = complete_entry(FakeLibrary({"number_of_channels": 1}), entry("multimeter"))
    assert e["channels"][0]["meas_type"] == "DC_V" and e["channels"][0]["attenuation"] == 1.0


def test_a_datalogger_with_slots_gets_its_slots_and_one_without_gets_channels():
    e = complete_entry(FakeLibrary({"number_of_slots": 3}), entry("datalogger"))
    assert [s["slot_number"] for s in e["slots"]] == [1, 2, 3]
    assert e["slots"][0] == {"slot_number": 1, "module_id": None, "channels": []}
    plain = complete_entry(FakeLibrary({"number_of_channels": 2}), entry("datalogger"))
    assert len(plain["channels"]) == 2 and "slots" not in plain


def test_a_slot_that_is_configured_stays_as_it_is():
    slot = {"slot_number": 2, "module_id": "M", "channels": [{"channel_id": "201"}]}
    e = complete_entry(FakeLibrary({"number_of_slots": 3}), entry("datalogger", slots=[slot]))
    assert e["slots"][1] is slot and len(e["slots"]) == 3


def test_a_switch_unit_gets_its_slots_and_a_network_analyzer_its_ports_and_sweep():
    sw = complete_entry(FakeLibrary({"number_of_slots": 2}), entry("switch_unit"))
    assert sw["slots"] == [{"slot_number": 1, "module_id": ""}, {"slot_number": 2, "module_id": ""}]
    vna = complete_entry(
        FakeLibrary({"number_of_ports": 2, "frequency_min_hz": 5e4, "frequency_max_hz": 6e9}),
        entry("network_analyzer"))
    assert vna["num_ports"] == 2 and len(vna["ports"]) == 2
    assert vna["sweep"]["start_hz"] == 5e4 and vna["sweep"]["stop_hz"] == 6e9


def test_manual_and_unknown_entries_are_not_touched_and_a_second_pass_changes_nothing():
    manual = {"instrument_type": "power_supply", "instance_name": "m", "is_manual": True}
    lib = FakeLibrary({"number_of_channels": 2}, ids=["1", "2"])
    assert complete_entry(lib, manual) == {
        "instrument_type": "power_supply", "instance_name": "m", "is_manual": True}
    entries = [entry("power_supply"), entry("oscilloscope"), entry("network_analyzer")]
    complete_entries(lib, entries)
    again = copy.deepcopy(entries)
    complete_entries(lib, again)
    assert again == entries
