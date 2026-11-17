# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The converter under test of an efficiency measurement: a card of the registry (``device``)."""

import pytest

from ola.assets import AssetRegistry, asset_ids_in, snapshots_for
from ola.efficiency_spec import validate_params
from tests.efficiency_params import good


@pytest.fixture
def registry(tmp_path):
    reg = AssetRegistry(tmp_path / "assets.json")
    reg.create("other", "Buck converter 12 V to 5 V", "converter under test")
    return reg


def test_a_device_card_is_a_valid_key_of_the_file():
    params = good()
    params["device"] = {"asset_id": "DUT-0001"}
    assert validate_params(params) == []


def test_a_device_is_a_code_and_nothing_else():
    params = good()
    params["device"] = {"asset_id": "buck one"}
    assert [p.path for p in validate_params(params)] == ["device.asset_id"]
    params["device"] = {"asset_id": "DUT-0001", "note": "lab bench 2"}
    assert [p.path for p in validate_params(params)] == ["device"]


def test_the_device_of_the_file_is_saved_with_the_results(registry):
    params = good()
    params["device"] = {"asset_id": "ola:dut-1"}  # a scan or a typed code, any spelling
    assert asset_ids_in(params) == ["DUT-0001"]
    cards = snapshots_for(params, registry)
    assert cards["DUT-0001"]["name"] == "Buck converter 12 V to 5 V"


def test_a_code_the_registry_does_not_have_is_left_out(registry):
    params = good()
    params["device"] = {"asset_id": "DUT-0099"}
    assert asset_ids_in(params) == ["DUT-0099"]
    assert snapshots_for(params, registry) == {}
