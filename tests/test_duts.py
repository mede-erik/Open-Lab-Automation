# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The archive of the devices under test: cards, versions, the file, the migration."""

import json

import pytest

from ola.assets import AssetError, AssetRegistry
from ola.duts import CATEGORIES, Dut, DutRegistry, default_path
from ola.labels import PRESETS, build_drawing


@pytest.fixture
def archive(tmp_path):
    return DutRegistry(tmp_path / "duts.json")


@pytest.fixture
def components(tmp_path):
    return AssetRegistry(tmp_path / "assets.json")


# ---- the cards ---------------------------------------------------------------------------------
def test_every_category_has_the_dut_prefix_and_one_sequence_of_codes(archive):
    assert set(CATEGORIES) == {"antenna", "filter", "converter", "generic"}
    codes = [archive.create(k, f"device {k}").id for k in CATEGORIES]
    assert codes == ["DUT-0001", "DUT-0002", "DUT-0003", "DUT-0004"]


def test_a_dut_has_a_name_a_category_and_no_version_unless_given(archive):
    dut = archive.create("converter", " Pippo ", "boost 12 V to 5 V", {"max_power_w": 20.0})
    assert (dut.name, dut.category, dut.kind) == ("Pippo", "converter", "converter")
    assert dut.attributes == {"max_power_w": 20.0} and dut.versions == []
    assert archive.current_version(dut.id) is None


def test_a_code_is_never_given_again(archive):
    first = archive.create("generic", "one")
    archive.delete(first.id)
    assert archive.create("generic", "two").id == "DUT-0002"


def test_wrong_input_is_refused_with_a_sentence(archive):
    with pytest.raises(AssetError, match="unknown kind"):
        archive.create("cable", "a cable is a component")
    with pytest.raises(AssetError, match="name cannot be empty"):
        archive.create("generic", "  ")
    with pytest.raises(AssetError, match="no device under test"):
        archive.get("DUT-0042") or archive.update("DUT-0042", name="x")


def test_a_scanned_or_typed_code_finds_the_card(archive):
    dut = archive.create("antenna", "868 MHz whip")
    for text in ("DUT-0001", "OLA:DUT-0001", "ola:dut-1", " dut - 0001 "):
        assert archive.find(text) is dut
    assert archive.find("DUT-0002") is None


# ---- the versions ------------------------------------------------------------------------------
def test_a_version_is_free_text_and_the_latest_one_in_use_is_current(archive):
    dut = archive.create("converter", "Pippo", version="rev A")
    archive.add_version(dut.id, "RFB", "new inductor")
    archive.add_version(dut.id, "V01")
    assert archive.versions_of(dut.id) == ["rev A", "RFB", "V01"]
    assert archive.current_version(dut.id) == "V01"
    assert archive.versions_of(dut.id)[1:] == ["RFB", "V01"]


def test_a_version_cannot_be_empty_or_written_twice(archive):
    dut = archive.create("converter", "Pippo", version="rev A")
    with pytest.raises(AssetError, match="cannot be empty"):
        archive.add_version(dut.id, "  ")
    with pytest.raises(AssetError, match="already has the version"):
        archive.add_version(dut.id, " REV a ")
    assert archive.has_version(dut.id, "Rev A") and not archive.has_version(dut.id, "rev B")


def test_a_retired_version_stays_but_is_not_current(archive):
    dut = archive.create("converter", "Pippo", version="rev A")
    archive.add_version(dut.id, "rev B")
    archive.retire_version(dut.id, "rev B")
    assert archive.versions_of(dut.id) == ["rev A", "rev B"]
    assert archive.versions_of(dut.id, include_retired=False) == ["rev A"]
    assert archive.current_version(dut.id) == "rev A"
    archive.retire_version(dut.id, "REV B", retired=False)
    assert archive.current_version(dut.id) == "rev B"
    with pytest.raises(AssetError, match="no version"):
        archive.retire_version(dut.id, "rev Z")


# ---- the file ----------------------------------------------------------------------------------
def test_the_file_keeps_the_cards_the_versions_and_the_unknown_keys(tmp_path):
    path = tmp_path / "duts.json"
    archive = DutRegistry(path)
    dut = archive.create("filter", "SAW 868", version="rev A", serial="42")
    archive.add_version(dut.id, "rev B", "new layout")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["assets"][0]["lab_note"] = "bench 2"  # a key a later version may add
    data["something_else"] = 1
    path.write_text(json.dumps(data), encoding="utf-8")

    again = DutRegistry(path)
    card = again.get("DUT-0001")
    assert isinstance(card, Dut) and card.uid == dut.uid and card.serial == "42"
    assert again.versions_of(card.id) == ["rev A", "rev B"]
    again.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["assets"][0]["lab_note"] == "bench 2" and saved["something_else"] == 1
    assert (tmp_path / "duts.json.bak").is_file()  # the previous version is kept


def test_a_damaged_file_is_reported_and_not_overwritten(tmp_path):
    path = tmp_path / "duts.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(AssetError, match="cannot read the registry"):
        DutRegistry(path)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_a_version_without_a_label_in_the_file_is_left_out(tmp_path):
    path = tmp_path / "duts.json"
    card = {"id": "DUT-0001", "kind": "generic", "name": "x", "uid": "u1",
            "versions": [{"label": "A"}, {"date": "2026-01-01"}, "B"]}  # fmt: skip
    path.write_text(json.dumps({"format_version": 1, "assets": [card]}), encoding="utf-8")
    assert DutRegistry(path).versions_of("DUT-0001") == ["A"]


def test_the_file_is_named_by_the_environment_or_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("OLA_DUTS_FILE", str(tmp_path / "shared" / "duts.json"))
    assert default_path() == tmp_path / "shared" / "duts.json"
    assert DutRegistry().path == tmp_path / "shared" / "duts.json"
    monkeypatch.delenv("OLA_DUTS_FILE")
    assert default_path().name == "duts.json" and ".open_lab_automation" in str(default_path())


def test_the_card_saved_with_a_run_has_its_versions(archive):
    dut = archive.create("converter", "Pippo", version="rev A")
    snapshot = dut.snapshot()
    archive.add_version(dut.id, "rev B")
    assert [v["label"] for v in snapshot["versions"]] == ["rev A"]  # what it was that day
    assert snapshot["uid"] == dut.uid and snapshot["kind"] == "converter"


# ---- the migration from the components ---------------------------------------------------------
def test_antennas_filters_and_generic_devices_move_and_the_components_stay(archive, components):
    cable = components.create("cable", "RG316", attributes={"length_m": 1.0})
    antenna = components.create("antenna", "868 MHz whip")
    flt = components.create("filter", "SAW 868")
    other = components.create("other", "Pippo board")
    ids = {c.id: c.uid for c in (cable, antenna, flt, other)}
    assert (antenna.id, flt.id, other.id) == ("ANT-0001", "FLT-0001", "DUT-0001")

    moved = archive.migrate_from(components)

    assert [d.name for d in moved] == ["868 MHz whip", "SAW 868", "Pippo board"]
    assert [d.category for d in moved] == ["antenna", "filter", "generic"]
    assert [d.uid for d in moved] == [ids["ANT-0001"], ids["FLT-0001"], ids["DUT-0001"]]
    assert {d.id for d in moved} == {"DUT-0001", "DUT-0002", "DUT-0003"}
    assert [c.id for c in AssetRegistry(components.path).assets] == ["CBL-0001"]  # saved
    assert len(DutRegistry(archive.path).assets) == 3  # saved


def test_a_generic_card_keeps_its_code_and_the_others_get_the_next_ones(archive, components):
    components.create("antenna", "whip")  # ANT-0001, first in the file
    components.create("other", "board")  # DUT-0001, already a DUT code
    archive.migrate_from(components)
    assert archive.get("DUT-0001").name == "board"  # kept
    assert archive.get("DUT-0002").name == "whip"  # the next number after the highest kept


def test_an_old_code_still_finds_the_card_so_a_stuck_label_works(archive, components):
    antenna = components.create("antenna", "868 MHz whip")
    archive.migrate_from(components)
    card = archive.find("OLA:ANT-0001")
    assert card is not None and card.uid == antenna.uid and card.id == "DUT-0001"
    assert card.former_codes == ["ANT-0001"]
    assert archive.get("ANT-0002") is None


def test_the_data_of_the_card_goes_with_it(archive, components):
    components.create(
        "filter", "SAW 868", "868 MHz band pass", {"frequency": 868e6}, serial="7", owner="lab"
    )
    components.update("FLT-0001", retired=True)
    archive.migrate_from(components)
    card = archive.get("DUT-0001")
    assert (card.description, card.serial, card.owner) == ("868 MHz band pass", "7", "lab")
    assert card.attributes == {"frequency": 868e6} and card.retired and card.created


def test_migrating_again_moves_nothing_and_a_stop_in_the_middle_loses_nothing(archive, components):
    components.create("antenna", "whip")
    assert len(archive.migrate_from(components)) == 1
    assert archive.migrate_from(components) == []
    # the archive was written, the components were not (a stop in the middle): the card is
    # in both files, and doing it again only takes it out of the components
    components.create("filter", "SAW")
    first = archive.migrate_from(components)
    assert len(first) == 1
    backup = AssetRegistry(components.path)
    backup.assets.append(Dut.from_dict({**first[0].to_dict(), "id": "FLT-0001", "kind": "filter"}))
    backup.save()
    assert archive.migrate_from(AssetRegistry(components.path)) == []
    assert AssetRegistry(components.path).assets == []
    assert len(archive.assets) == 2


def test_a_dut_code_taken_by_another_device_is_not_reused(archive, components):
    archive.create("converter", "already here")  # DUT-0001 in the archive
    components.create("other", "from the components")  # DUT-0001 there too
    archive.migrate_from(components)
    assert archive.get("DUT-0001").name == "already here"
    moved = archive.get("DUT-0002")
    assert moved.name == "from the components" and moved.former_codes == ["DUT-0001"]


def test_nothing_to_move_changes_no_file(archive, components):
    components.create("cable", "RG316")
    assert archive.migrate_from(components) == []
    assert not archive.path.exists()


# ---- the labels of the components print a DUT --------------------------------------------------
def test_the_label_of_a_component_prints_a_dut_as_it_is(archive):
    dut = archive.create("converter", "Pippo", "boost 12 V to 5 V", version="rev A", serial="42")
    drawing = build_drawing(next(iter(PRESETS.values())), dut)
    text = " ".join(getattr(item, "text", "") for item in drawing.items)
    assert "DUT-0001" in text and "Pippo" in text
    assert any(type(item).__name__ == "QR" for item in drawing.items)
