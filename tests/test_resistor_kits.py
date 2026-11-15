# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Kits of resistors: the file, the registry, and the references of a load to a kit."""

import json

import pytest

from ola.resistor_kits import Kit, KitError, KitRegistry, KitResistor, default_path
from ola.resistors import parse_loads


def power_kit():
    return Kit(
        "PWR",
        [
            KitResistor("R10", 10, tol_pct=1, power_w=50, channel="201"),
            KitResistor("R22", 22, tol_pct=1, power_w=50, channel="202", note="blue one"),
            KitResistor("R47", 47, tol_pct=5, power_w=25),
        ],
        "the power resistors of the bench",
    )


@pytest.fixture
def kits(tmp_path):
    registry = KitRegistry(tmp_path / "kits.json")
    registry.put(power_kit())
    return registry


# ---- the file ---------------------------------------------------------------------------------
def test_the_default_file_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OLA_RESISTOR_KITS_FILE", str(tmp_path / "mine.json"))
    assert default_path() == tmp_path / "mine.json"
    monkeypatch.delenv("OLA_RESISTOR_KITS_FILE")
    assert default_path().name == "resistor_kits.json"
    assert default_path().parent.name == ".open_lab_automation"


def test_a_missing_file_is_an_empty_registry_and_the_first_save_makes_it(tmp_path):
    path = tmp_path / "sub" / "kits.json"
    registry = KitRegistry(path)
    assert registry.names() == [] and not path.exists()
    registry.put(power_kit())
    assert path.is_file()
    again = KitRegistry(path)
    kit = again.get("PWR")
    assert kit.note == "the power resistors of the bench"
    assert [(r.name, r.r_ohm, r.tol_pct, r.power_w, r.channel) for r in kit.resistors] == [
        ("R10", 10, 1, 50, "201"), ("R22", 22, 1, 50, "202"), ("R47", 47, 5, 25, ""),
    ]  # fmt: skip
    assert kit.get("R22").note == "blue one" and kit.get("R99") is None


def test_the_file_has_only_what_each_resistor_has_and_the_old_one_is_kept(tmp_path):
    registry = KitRegistry(tmp_path / "kits.json")
    registry.put(Kit("A", [KitResistor("R1", 4.7)]))
    data = json.loads((tmp_path / "kits.json").read_text(encoding="utf-8"))
    assert data == {
        "format_version": 1,
        "kits": {"A": {"resistors": [{"name": "R1", "r_ohm": 4.7}]}},
    }
    assert not (tmp_path / "kits.json.bak").exists()
    registry.put(Kit("B", []))  # a second save keeps the first file
    assert json.loads((tmp_path / "kits.json.bak").read_text(encoding="utf-8")) == data
    assert not (tmp_path / "kits.json.tmp").exists()


@pytest.mark.parametrize(
    "content,text",
    [
        ("not json", "cannot read the kits"),
        ("[]", "not a file of resistor kits"),
        ('{"kits": []}', "not a file of resistor kits"),
        ('{"format_version": 9, "kits": {}}', "newer version"),
        ('{"kits": {"A": 5}}', "must be an object"),
        ('{"kits": {"A": {"resistors": [{"name": "R1", "r_ohm": -3}]}}}', "above 0"),
        ('{"kits": {"A": {"resistors": [{"name": "R1", "r_ohm": 3, "colour": 1}]}}}', "unknown"),
        ('{"kits": {"A": {"resistors": [{"r_ohm": 3}]}}}', "give a name"),
        (
            '{"kits": {"A": {"resistors": [{"name": "R", "r_ohm": 1},'
            ' {"name": "R", "r_ohm": 2}]}}}',
            "two resistors are called 'R'",
        ),
    ],
)
def test_a_damaged_file_is_refused_with_a_sentence(tmp_path, content, text):
    path = tmp_path / "kits.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(KitError, match=text):
        KitRegistry(path)


# ---- the kits ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "resistor,text",
    [
        (KitResistor("", 5), "give a name"),
        (KitResistor("R 1", 5), None),  # a space inside a name is fine
        (KitResistor('R"1', 5), "cannot be used"),
        (KitResistor("R{1}", 5), "cannot be used"),
        (KitResistor("R" * 61, 5), "cannot be used"),
        (KitResistor("R1", 0), "above 0"),
        (KitResistor("R1", float("nan")), "above 0"),
        (KitResistor("R1", 5, tol_pct=100), "from 0 to below 100"),
        (KitResistor("R1", 5, tol_pct=-1), "from 0 to below 100"),
        (KitResistor("R1", 5, power_w=0), "above 0"),
        (KitResistor("R1", 5, channel=201), "must be text"),
    ],
)
def test_a_resistor_that_cannot_be_used_is_refused_and_nothing_changes(tmp_path, resistor, text):
    registry = KitRegistry(tmp_path / "kits.json")
    if text is None:
        registry.put(Kit("A", [resistor]))
        assert registry.get("A").resistors[0].name == "R 1"
        return
    with pytest.raises(KitError, match=text):
        registry.put(Kit("A", [resistor]))
    assert registry.names() == [] and not (tmp_path / "kits.json").exists()


def test_a_kit_needs_a_name_and_distinct_resistors(tmp_path):
    registry = KitRegistry(tmp_path / "kits.json")
    with pytest.raises(KitError, match="the name of the kit"):
        registry.put(Kit(" ", []))
    with pytest.raises(KitError, match="two resistors are called 'R1'"):
        registry.put(Kit("A", [KitResistor("R1", 1), KitResistor("R1", 2)]))
    with pytest.raises(KitError, match="too many"):
        registry.put(Kit("A", [KitResistor(f"R{i}", 1) for i in range(201)]))


def test_the_registry_keeps_its_own_copy_of_a_kit(kits):
    kit = kits.get("PWR")
    outside = power_kit()
    kits.put(outside, save=False)
    outside.resistors[0].r_ohm = 999  # later changes outside do not reach the registry
    assert kits.get("PWR").resistors[0].r_ohm == 10 and kit is not kits.get("PWR")


def test_kits_are_renamed_and_deleted(kits):
    kits.put(Kit("Small", [KitResistor("R1", 1)]))
    assert kits.names() == ["PWR", "Small"]
    kits.rename("Small", "Little")
    assert kits.names() == ["Little", "PWR"] and kits.get("Little").name == "Little"
    assert KitRegistry(kits.path).names() == ["Little", "PWR"]  # saved
    with pytest.raises(KitError, match="already a kit called 'PWR'"):
        kits.rename("Little", "PWR")
    with pytest.raises(KitError, match="no kit called 'Nope'"):
        kits.rename("Nope", "X")
    with pytest.raises(KitError, match="the new name"):
        kits.rename("Little", "")
    kits.rename("Little", "Little")  # the same name is not a conflict
    kits.delete("Little")
    assert kits.names() == ["PWR"] and KitRegistry(kits.path).names() == ["PWR"]
    with pytest.raises(KitError, match="no kit called 'Little'"):
        kits.delete("Little")


# ---- the references ---------------------------------------------------------------------------
def test_a_reference_is_replaced_by_the_values_of_the_kit(kits):
    one = kits.resolve({"kit": "PWR", "ref": "R22"})
    assert one == {"name": "R22", "r_ohm": 22, "tol_pct": 1, "power_w": 50, "channel": "202",
                   "kit": "PWR", "ref": "R22"}  # fmt: skip
    assert "note" not in one  # the note stays in the kit
    assert kits.resolve({"r_ohm": 5, "name": "own"}) == {
        "r_ohm": 5,
        "name": "own",
    }  # not a reference
    assert kits.reference("PWR", "R22") == {"kit": "PWR", "ref": "R22"}


def test_what_the_entry_says_wins_over_the_kit(kits):
    entry = {"kit": "PWR", "ref": "R10", "channel": "305", "power_w": 20, "name": "heater"}
    out = kits.resolve(entry)
    assert (out["channel"], out["power_w"], out["name"], out["r_ohm"]) == ("305", 20, "heater", 10)
    assert (out["kit"], out["ref"]) == ("PWR", "R10")  # where it came from


def test_a_default_kit_saves_writing_it_every_time(kits):
    assert kits.resolve({"ref": "R47"}, "PWR")["r_ohm"] == 47
    assert kits.resolve({"kit": "PWR", "ref": "R47"}, "Other")["r_ohm"] == 47  # its own kit wins
    with pytest.raises(KitError, match="names no kit"):
        kits.resolve({"ref": "R47"})


def test_unknown_kits_and_resistors_say_what_there_is(kits):
    with pytest.raises(KitError, match=r"no kit of resistors called 'Nope' \(the kits are: PWR\)"):
        kits.resolve({"kit": "Nope", "ref": "R1"})
    with pytest.raises(KitError, match=r"has no resistor 'R99' \(it has: R10, R22, R47\)"):
        kits.resolve({"kit": "PWR", "ref": "R99"})
    empty = KitRegistry(kits.path.with_name("none.json"))
    with pytest.raises(KitError, match="the kits are: none"):
        empty.resolve({"kit": "PWR", "ref": "R10"})


def test_the_loads_of_a_measurement_are_resolved_through_the_groups(kits):
    loads = [
        {"name": "single", "kit": "PWR", "ref": "R10"},
        {"name": "pair", "parallel": [{"ref": "R22"}, {"ref": "R47", "channel": "9"}]},
        {"name": "mixed", "series": [{"ref": "R10"}, {"parallel": [{"ref": "R22"}, {"r_ohm": 3}]}]},
        {"name": "plain", "r_ohm": 4.7},
    ]
    resolved = kits.resolve_loads(loads, "PWR")
    assert loads[0] == {"name": "single", "kit": "PWR", "ref": "R10"}  # the original is untouched
    parsed = parse_loads(resolved)
    assert [round(x.resistance()[0], 4) for x in parsed] == [
        10, round(1 / (1 / 22 + 1 / 47), 4), round(10 + 1 / (1 / 22 + 1 / 3), 4), 4.7
    ]  # fmt: skip
    assert parsed[0].root.kit == "PWR" and parsed[0].root.ref == "R10"  # kept for the record
    assert parsed[1].channels() == ["202", "9"]  # the relay of the kit, and the one that was given
    assert parsed[0].root.power_w == 50 and parsed[2].resistors()[2].channel == ""
