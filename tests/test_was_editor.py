# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The editor of the .was files without a window: reading, form values, saving."""

import json

import pytest

from ola.was_calls import check_was
from ola.was_editor import (
    WasEditor,
    channels_of,
    oscilloscopes,
    parse_level,
    parse_time,
)


@pytest.mark.parametrize(
    "text, seconds",
    [("1ms", 1e-3), ("100us", 1e-4), ("2 µs", 2e-6), ("5n", 5e-9), ("1e-3", 1e-3),
     ("0,5", 0.5), ("1ks", 1000.0), ("3ps", 3e-12), ("2s", 2.0)],
)  # fmt: skip
def test_the_times_people_type_are_read(text, seconds):
    assert parse_time(text) == pytest.approx(seconds)


def test_what_is_not_a_time_or_a_level_is_none():
    assert parse_time("abc") is None and parse_time("") is None
    assert parse_level("1,5") == 1.5 and parse_level("x") is None and parse_level(None) is None


def test_a_missing_or_broken_file_starts_empty(tmp_path):
    assert WasEditor.load(tmp_path / "none.was").data["channels"] == []
    bad = tmp_path / "bad.was"
    bad.write_text("{not json")
    assert WasEditor.load(bad).data["type"] == "oscilloscope_settings"
    bad.write_text("[1, 2]")
    assert WasEditor.load(bad).data["settings"] == {}


def test_the_form_values_go_in_the_file_and_come_back(tmp_path):
    editor = WasEditor()
    editor.apply(
        reset=False,
        time_text="100us",
        channels=[
            {"channel_id": "CH1", "name": "VGS", "enabled": True, "volt_per_div": "2V"},
            {"channel_id": "CH2", "name": "off", "enabled": False, "volt_per_div": "1V"},
        ],
        trigger={"source": "CH1", "slope": "FALL", "mode": "NORM", "level": 1.5},
    )
    assert editor.data["reset"] is False and editor.data["settings"][
        "time_per_div"
    ] == pytest.approx(1e-4)
    assert [c["channel_id"] for c in editor.data["channels"]] == ["CH1"]  # only the enabled ones
    path = tmp_path / "a.was"
    editor.save(path)
    again = WasEditor.load(path)
    assert again.data == editor.data and check_was(again.data) == check_was(editor.data)
    form = again.form()
    assert form["reset"] is False and float(form["time_per_div"]) == pytest.approx(1e-4)
    assert form["channels"] == {"CH1": (True, "2V")} and form["trigger"]["slope"] == "FALL"


def test_reset_is_written_only_when_it_is_not_the_default():
    editor = WasEditor({"reset": False})
    editor.apply(True, "", [], None)
    assert "reset" not in editor.data
    assert editor.form()["reset"] is True


def test_a_time_that_does_not_parse_keeps_the_old_one():
    editor = WasEditor({"settings": {"time_per_div": 0.002}})
    editor.apply(True, "oops", [], None)
    assert editor.data["settings"]["time_per_div"] == 0.002


def test_the_json_text_is_taken_back_only_if_it_is_an_object():
    editor = WasEditor()
    editor.set_text(json.dumps({"channels": []}))
    assert editor.data == {"channels": []}
    for bad in ("{", "[1]"):
        with pytest.raises(ValueError):
            editor.set_text(bad)
    assert editor.data == {"channels": []}  # unchanged
    assert json.loads(editor.text()) == editor.data


def test_the_oscilloscopes_of_the_instrument_file(tmp_path):
    inst = tmp_path / "p.inst"
    inst.write_text(
        json.dumps(
            {
                "instruments": [
                    {"instrument_type": "multimeter", "instance_name": "DMM"},
                    {"instrument_type": "oscilloscope", "instance_name": "osc1",
                     "model": "SDS", "channels": [{"channel_id": "CH1"}]},
                    {"instrument_type": "oscilloscopes", "instance_name": "osc2"},
                ]
            }
        )
    )  # fmt: skip
    scopes = oscilloscopes(inst)
    assert [s["instance_name"] for s in scopes] == ["osc1", "osc2"]
    assert scopes[0]["model_id"] == "SDS"
    assert channels_of(scopes, "osc1") == [{"channel_id": "CH1"}]
    assert channels_of(scopes, "nope") == [{"channel_id": "CH1"}]  # the first one
    assert channels_of([], "osc1") == []
    assert oscilloscopes(tmp_path / "missing.inst") == [] and oscilloscopes(None) == []
