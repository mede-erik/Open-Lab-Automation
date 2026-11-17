# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The converter under test of an efficiency measurement: a name written in the file, optional. It
is not a card of the registry, so it adds nothing to the header of the runs."""

from ola.assets import asset_ids_in
from ola.efficiency_spec import validate_params
from tests.efficiency_params import good


def test_a_file_without_a_converter_is_valid_and_saves_no_card():
    params = good()
    assert "device" not in params and validate_params(params) == []
    assert asset_ids_in(params) == []


def test_the_converter_is_a_name_written_by_hand():
    params = good()
    params["device"] = {"name": "Boost 12 V-5 V"}
    assert validate_params(params) == []
    assert asset_ids_in(params) == []  # a name is not a code of the registry


def test_a_converter_is_only_a_name():
    params = good()
    params["device"] = {"asset_id": "DUT-0001"}
    assert [p.path for p in validate_params(params)] == ["device"]
    params["device"] = {"name": 3}
    assert [p.path for p in validate_params(params)] == ["device.name"]
