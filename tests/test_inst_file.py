"""The instrument file: reading, writing, and what is wrong with an entry."""

import json

import pytest

from ola import inst_file as inst


def codes(problems):
    return [c for c, _ in problems]


def supply(**over):
    entry = {
        "instrument_type": "power_supply",
        "instance_name": "PSU",
        "model_id": "PSU1",
        "visa_address": "TCPIP0::1.2.3.4::inst0::INSTR",
        "channels": [{"enabled": True, "name": "CH1", "max_voltage": 30.0, "max_current": 3.0}],
    }
    entry.update(over)
    return entry


def test_other_keys_of_the_file_survive_a_save(tmp_path):
    path = tmp_path / "lab.inst"
    path.write_text(
        json.dumps({"format": 3, "notes": "x", "instruments": [supply()]}), encoding="utf-8"
    )
    entries, extra = inst.load_inst(path)
    entries[0]["instance_name"] = "NEW"
    inst.save_inst(path, entries, extra)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["format"] == 3 and raw["notes"] == "x"
    assert raw["instruments"][0]["instance_name"] == "NEW"


def test_a_missing_file_is_empty_and_a_broken_one_is_an_error(tmp_path):
    assert inst.load_inst(tmp_path / "none.inst") == ([], {})
    bad = tmp_path / "bad.inst"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        inst.load_inst(bad)
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        inst.load_inst(bad)


def test_a_good_entry_has_no_problems():
    assert inst.check_entry(supply()) == []


def test_names():
    assert codes(inst.check_entry(supply(instance_name=" "))) == ["name_empty"]
    assert codes(inst.check_entry(supply(), other_names=["PSU"])) == ["name_duplicate"]
    assert inst.unique_name("PSU", ["PSU", "PSU_copy"]) == "PSU_copy1"


def test_a_remote_instrument_needs_an_address_and_a_known_model():
    assert "no_address" in codes(inst.check_entry(supply(visa_address="")))
    assert "no_model" in codes(inst.check_entry(supply(model_id="")))
    assert "model_unknown" in codes(inst.check_entry(supply(), model_found=False))
    manual = {
        "instrument_type": "power_supply",
        "instance_name": "VIN",
        "is_manual": True,
        "channels": [{"enabled": True, "name": "CH1", "max_voltage": 30, "max_current": 5}],
    }
    assert inst.check_entry(manual) == []


def test_the_limits_of_a_supply_or_load_are_needed_and_checked_against_the_model():
    no_limits = supply(channels=[{"enabled": True, "name": "CH1", "max_current": 0}])
    found = inst.check_entry(no_limits)
    assert [v["limit"] for c, v in found if c == "limit_missing"] == ["max_voltage", "max_current"]
    assert "no_channel" in codes(inst.check_entry(supply(channels=[{"enabled": False}])))
    caps = {"max_voltage_v": 30, "max_current_a": 3}
    over = supply(channels=[{"enabled": True, "name": "A", "max_voltage": 60, "max_current": 1}])
    assert ("limit_above_model", {"channel": "A", "limit": "max_voltage", "model": 30}) in (
        inst.check_entry(over, caps=caps)
    )
    assert inst.check_entry(over) == []  # no model limit known: nothing to compare with


def test_serial_settings_and_timeout():
    assert inst.check_entry(supply(serial={"baud": 9600, "parity": "N", "stop_bits": 1})) == []
    bad = supply(serial={"baud": -1, "parity": "X", "speed": 1})
    assert codes(inst.check_entry(bad)).count("serial_value") == 2
    assert "serial_unknown" in codes(inst.check_entry(bad))
    assert "timeout" in codes(inst.check_entry(supply(timeout_ms=5)))
    assert inst.check_entry(supply(timeout_ms=20000)) == []
    library = {"baud": 9600, "parity": "N", "data_bits": 8}
    assert inst.serial_changes({"baud": 19200, "parity": "N", "data_bits": 8}, library) == {
        "baud": 19200
    }


def vna(**over):
    entry = {
        "instrument_type": "network_analyzer",
        "instance_name": "VNA",
        "model_id": "V1",
        "visa_address": "ASRL3::INSTR",
        "num_ports": 2,
        "ports": [{"port": 1, "enabled": True, "name": "P1"}],
        "sweep": {"start_hz": 1e6, "stop_hz": 2e6, "points": 101},
    }
    entry.update(over)
    return entry


def test_network_analyzer_ports_and_sweep():
    caps = {"frequency_min_hz": 5e4, "frequency_max_hz": 6e9, "max_sweep_points": 1001}
    assert inst.check_entry(vna(), caps=caps) == []
    assert codes(inst.check_entry(vna(ports=[{"port": 1, "enabled": False}]))) == ["no_port"]
    cases = {
        "sweep_order": {"start_hz": 2e6, "stop_hz": 1e6, "points": 11},
        "sweep_range": {"start_hz": 1e3, "stop_hz": 1e6, "points": 11},
        "sweep_points": {"start_hz": 1e6, "stop_hz": 2e6, "points": 5000},
    }
    for code, sweep in cases.items():
        assert code in codes(inst.check_entry(vna(sweep=sweep), caps=caps)), code
    assert "sweep_if_bandwidth" in codes(
        inst.check_entry(vna(sweep={**vna()["sweep"], "if_bandwidth_hz": 0}))
    )


def test_ports_and_default_sweep_follow_the_model():
    assert inst.port_options({"number_of_ports": 2}) == [2]
    assert inst.port_options({"number_of_ports": [4, 2]}) == [2, 4]
    assert inst.port_options({}) == [2]
    caps = {"frequency_min_hz": 5e4, "frequency_max_hz": 6.3e9, "max_sweep_points": 101}
    assert inst.default_sweep(caps) == {"start_hz": 5e4, "stop_hz": 6.3e9, "points": 101}
    assert inst.default_sweep(None)["points"] == 201
    entry = vna()
    inst.resize_ports(entry, 4)
    assert [p["port"] for p in entry["ports"]] == [1, 2, 3, 4] and entry["num_ports"] == 4
    assert entry["ports"][0]["name"] == "P1"
    entry["ports"][0]["name"] = "DUT in"
    inst.resize_ports(entry, 2)
    assert entry["ports"][0]["name"] == "DUT in" and len(entry["ports"]) == 2


def test_types_and_numbers():
    assert inst.entry_type({"type": "Alimentatori"}) == "power_supply"
    assert inst.entry_type({"instrument_type": "network_analyzer"}) == "network_analyzer"
    assert inst.number("1,5") == 1.5 and inst.number("x", 7) == 7


def test_frequencies_are_shown_the_way_they_are_typed():
    from ola.vna_calibration_flow import parse_frequency

    for hz in (50e3, 6.3e9, 100e6, 1.5e6, 999.0):
        assert parse_frequency(inst.format_frequency(hz)) == pytest.approx(hz)
    assert inst.format_frequency(6.3e9) == "6.3G" and inst.format_frequency(50e3) == "50k"
