"""The registry of cables and devices."""

import json

import pytest

from ola.assets import (
    Asset,
    AssetError,
    AssetRegistry,
    asset_ids_in,
    default_path,
    history,
    normalize_code,
    qr_text,
    read_header,
    snapshots_for,
)
from ola.runs import RunWriter


@pytest.fixture
def registry(tmp_path):
    return AssetRegistry(tmp_path / "assets.json")


# ---- codes ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,code",
    [
        ("CBL-0042", "CBL-0042"), ("OLA:CBL-0042", "CBL-0042"), ("ola:cbl-42", "CBL-0042"),
        (" CBL - 0042 ", "CBL-0042"), ("ant-7", "ANT-0007"), ("DUT-123456", "DUT-123456"),
    ],
)  # fmt: skip
def test_a_code_is_recognised_however_it_arrives(text, code):
    assert normalize_code(text) == code


@pytest.mark.parametrize(
    "text", ["", "CBL0042", "CBL-", "CBL-abc", "CABLE-0001", "OLA:", "12-34", None]
)
def test_what_is_not_a_code_is_refused(text):
    assert normalize_code(text) is None


def test_the_qr_text():
    assert (
        qr_text("CBL-0042") == "OLA:CBL-0042" and normalize_code(qr_text("ADP-0001")) == "ADP-0001"
    )


# ---- creating cards ---------------------------------------------------------------------------
def test_codes_count_up_per_kind(registry):
    a = registry.create("cable", "RG316 SMA-SMA", "1 m", {"length_m": 1.0}, owner="lab")
    b = registry.create("cable", "RG58 N-N")
    c = registry.create("antenna", "whip")
    assert (a.id, b.id, c.id) == ("CBL-0001", "CBL-0002", "ANT-0001")
    assert a.kind == "cable" and a.attributes == {"length_m": 1.0} and a.owner == "lab"
    assert len(a.created) == 10 and a.created[4] == "-"  # a date
    assert [x.id for x in registry.list("cable")] == ["CBL-0001", "CBL-0002"]


def test_every_kind_has_a_prefix_and_suggests_attributes():
    from ola.assets import KINDS, PREFIX_KIND

    assert {v["prefix"] for v in KINDS.values()} == set(PREFIX_KIND)
    assert [n for n, _ in KINDS["cable"]["attributes"]] == ["cable_type", "connectors", "length_m"]


def test_a_code_is_never_given_again_not_even_after_a_deletion(registry):
    registry.create("cable", "a")
    last = registry.create("cable", "b")
    registry.delete(last.id)
    assert registry.create("cable", "c").id == "CBL-0003"  # not CBL-0002 again
    reopened = AssetRegistry(registry.path)
    assert reopened.create("cable", "d").id == "CBL-0004"  # and not after a restart


def test_a_code_written_by_hand_is_not_given_again(tmp_path):
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"assets": [{"id": "CBL-0100", "kind": "cable", "name": "old"}]}))
    assert AssetRegistry(path).create("cable", "new").id == "CBL-0101"


@pytest.mark.parametrize(
    "args,words",
    [
        (("laser", "x"), "unknown kind"),
        (("cable", "   "), "name cannot be empty"),
    ],
)
def test_wrong_cards_say_why(registry, args, words):
    with pytest.raises(AssetError, match=words):
        registry.create(*args)
    assert registry.assets == []  # nothing was added, no code was used
    assert registry.counters == {}


def test_unknown_fields_are_refused(registry):
    with pytest.raises(AssetError, match="unknown field"):
        registry.create("cable", "x", colour="red")


# ---- finding, changing, deleting --------------------------------------------------------------
def test_find_takes_what_a_scanner_gives(registry):
    cable = registry.create("cable", "x")
    for text in ("CBL-0001", "OLA:CBL-0001", "cbl-1", " OLA:CBL-0001 "):
        assert registry.find(text) is cable
    assert registry.find("CBL-0002") is None and registry.get("nonsense") is None


def test_update_changes_a_card_but_not_its_code_or_kind(registry):
    cable = registry.create("cable", "x")
    registry.update(cable.id, name="  y", notes="n", attributes={"length_m": 2})
    assert (cable.name, cable.notes, cable.attributes) == ("  y", "n", {"length_m": 2})
    with pytest.raises(AssetError, match="code and the kind are fixed"):
        registry.update(cable.id, id="CBL-9999")
    with pytest.raises(AssetError, match="code and the kind are fixed"):
        registry.update(cable.id, kind="antenna")
    with pytest.raises(AssetError, match="name cannot be empty"):
        registry.update(cable.id, name=" ")
    with pytest.raises(AssetError, match="no cable or device"):
        registry.update("CBL-0099", name="z")


def test_a_retired_card_stays_but_is_not_offered(registry):
    old, new = registry.create("cable", "old"), registry.create("cable", "new")
    registry.update(old.id, retired=True)
    assert len(registry.list()) == 2 and [a.id for a in registry.list(include_retired=False)] == [
        new.id
    ]
    assert registry.choices("cable") == ["CBL-0002 - new"]


def test_delete_removes_the_card(registry):
    cable = registry.create("cable", "x")
    registry.delete(cable.id)
    assert registry.find(cable.id) is None
    with pytest.raises(AssetError, match="no cable or device"):
        registry.delete(cable.id)


# ---- the file ---------------------------------------------------------------------------------
def test_the_registry_survives_a_restart_with_everything(registry):
    registry.create("cable", "RG316", "1 m cable", {"length_m": 1.0, "connectors": "SMA-SMA"},
                    manufacturer="m", serial="s1", owner="o", notes="n")  # fmt: skip
    again = AssetRegistry(registry.path)
    card = again.find("CBL-0001")
    assert (card.name, card.description, card.manufacturer, card.serial) == (
        "RG316",
        "1 m cable",
        "m",
        "s1",
    )
    assert card.attributes == {"length_m": 1.0, "connectors": "SMA-SMA"}


def test_keys_the_program_does_not_know_are_kept(tmp_path):
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({
        "format_version": 1, "site": "lab 2", "counters": {"CBL": 5},
        "assets": [
            {"id": "CBL-0005", "kind": "cable", "name": "x", "calibration_due": "2027-01-01"}
        ],
    }))  # fmt: skip
    reg = AssetRegistry(path)
    reg.create("cable", "y")
    saved = json.loads(path.read_text())
    assert saved["site"] == "lab 2"
    assert saved["assets"][0]["calibration_due"] == "2027-01-01"


def test_saving_keeps_the_previous_file_and_leaves_no_temporary(registry):
    registry.create("cable", "first")
    registry.create("cable", "second")
    backup = registry.path.with_name("assets.json.bak")
    assert len(json.loads(backup.read_text())["assets"]) == 1  # the version before the last save
    assert not registry.path.with_name("assets.json.tmp").exists()


def test_a_damaged_file_is_reported_and_not_overwritten(tmp_path):
    path = tmp_path / "assets.json"
    path.write_text("{ broken")
    with pytest.raises(AssetError, match="cannot read the registry"):
        AssetRegistry(path)
    assert path.read_text() == "{ broken"  # left for the user to repair
    path.write_text(json.dumps([1, 2]))
    with pytest.raises(AssetError, match="not a registry"):
        AssetRegistry(path)
    path.write_text(json.dumps({"format_version": 99, "assets": []}))
    with pytest.raises(AssetError, match="newer version"):
        AssetRegistry(path)
    path.write_text(json.dumps({"assets": [{"kind": "cable"}]}))
    with pytest.raises(AssetError, match="without a code"):
        AssetRegistry(path)


def test_the_default_file_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("OLA_ASSETS_FILE", str(tmp_path / "shared.json"))
    assert default_path() == tmp_path / "shared.json"
    assert AssetRegistry().path == tmp_path / "shared.json"
    monkeypatch.delenv("OLA_ASSETS_FILE")
    assert default_path().name == "assets.json" and ".open_lab_automation" in str(default_path())


def test_an_asset_is_a_plain_round_trip():
    asset = Asset("CBL-0001", "cable", "x", attributes={"a": 1}, extra={"z": 9})
    assert Asset.from_dict(asset.to_dict()).to_dict() == asset.to_dict()
    assert asset.snapshot() == asset.to_dict() and asset.snapshot() is not asset.to_dict()


# ---- the cards and the measurements -----------------------------------------------------------
def test_the_codes_a_measurement_file_names():
    params = {
        "cable": {"label": "x", "asset_id": "cbl-3"},
        "device": {"asset_id": "OLA:ANT-0002"},
        "filter": {"asset_id": "CBL-0003"},  # the same code twice: once
        "sweep": {"asset_id": "CBL-0009"},  # not a place for it
    }
    assert asset_ids_in(params) == ["CBL-0003", "ANT-0002"]
    assert asset_ids_in({}) == [] and asset_ids_in({"cable": "x", "device": {"asset_id": 5}}) == []


def make_run(folder, name, params, state="finished", stamp="20261103_100000"):
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}_{stamp}.jsonl"
    writer = RunWriter(path, {"run_id": name, "measurement": "cable", "params": params})
    writer.close() if state is None else None
    if state:
        writer._write({"kind": "end", "state": state, "error": None})
        writer.close()
    return path


def test_history_finds_the_runs_of_a_cable_by_the_code_in_their_header(tmp_path):
    runs = tmp_path / "runs"
    a = make_run(runs, "a", {"cable": {"asset_id": "CBL-0001"}}, stamp="20261103_100000")
    make_run(runs, "other", {"cable": {"asset_id": "CBL-0002"}}, stamp="20261103_110000")
    c = make_run(
        runs, "c", {"cable": {"asset_id": "cbl-1"}}, state="stopped", stamp="20261103_120000"
    )
    make_run(runs, "unnamed", {"cable": {"label": "no code"}}, stamp="20261103_130000")
    d = make_run(
        runs, "d", {"cable": {"asset_id": "CBL-0001"}}, state=None, stamp="20261102_090000"
    )
    found = history("OLA:CBL-0001", [runs, tmp_path / "missing"])
    assert [r.path for r in found] == [d, a, c]  # oldest first
    assert [r.state for r in found] == ["interrupted", "finished", "stopped"]
    assert found[1].measurement == "cable" and found[1].when == "2026-11-03 10:00"


def test_history_ignores_files_that_are_not_runs(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "junk.jsonl").write_text("not json\n")
    (runs / "empty.jsonl").write_text("")
    (runs / "other.jsonl").write_text(json.dumps({"kind": "point"}) + "\n")
    assert history("CBL-0001", [runs]) == []
    assert read_header(runs / "junk.jsonl") is None and read_header(runs / "nothing.jsonl") is None


def test_history_reads_only_the_first_line_of_a_big_run(tmp_path):
    runs = tmp_path / "runs"
    path = make_run(runs, "big", {"cable": {"asset_id": "CBL-0001"}})
    with open(path, "a") as f:
        f.write(json.dumps({"kind": "point", "values": {"x": 1}}) + "\n")
    assert read_header(path)["params"]["cable"]["asset_id"] == "CBL-0001"
    assert len(history("CBL-0001", [runs])) == 1


def test_a_snapshot_is_the_card_as_it_was(registry):
    cable = registry.create("cable", "RG316", attributes={"length_m": 1.0})
    params = {"cable": {"asset_id": "CBL-0001"}, "device": {"asset_id": "CBL-0777"}}
    snap = snapshots_for(params, registry)
    assert list(snap) == ["CBL-0001"]  # the unknown code is left out
    registry.update(cable.id, name="renamed")
    assert snap["CBL-0001"]["name"] == "RG316" and snap["CBL-0001"]["attributes"] == {
        "length_m": 1.0
    }
    assert snapshots_for(params, None) == {}
