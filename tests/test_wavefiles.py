# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The binary files of the waveforms of a run: format, index, and what happens if they are gone."""

import json

import numpy as np
import pytest

from ola import wavefiles
from ola.sim_scope import SimScope
from ola.wavefiles import (
    WaveFileError,
    capture_from_reads,
    capture_name,
    delete_waves,
    estimate_bytes,
    index_entry,
    load_capture,
    missing_files,
    save_capture,
    wave_folder,
)


def scope_reads(*channels, depth=2000):
    scope = SimScope(default_depth=depth)
    return {f"CH{c}": scope.read_waveform_full(c) for c in channels}


def test_a_capture_is_saved_and_read_back(tmp_path):
    reads = scope_reads(1, 2)
    capture = capture_from_reads(
        7, "rise", "scope1", reads, forced=True,
        setpoints={"vin": 12.0, "rload": 4.7}, settings={"file": "rise.was"},
    )  # fmt: skip
    path = save_capture(tmp_path / "waves", capture)
    assert path.name == "s00007_rise_scope1.npz" and path.is_file()
    back = load_capture(path)
    assert (back.step, back.acquisition, back.scope, back.forced) == (7, "rise", "scope1", True)
    assert back.setpoints == {"vin": 12.0, "rload": 4.7} and back.settings == {"file": "rise.was"}
    assert list(back.voltages) == ["CH1", "CH2"] and back.points == capture.points
    for name, got in reads.items():
        assert back.voltages[name].dtype == np.float32
        assert np.allclose(back.voltages[name], got["voltage"], rtol=1e-6, atol=1e-9)
    assert back.time_axis is None  # regular sampling: only the first time and the interval
    assert np.allclose(back.times(), reads["CH1"]["time"], rtol=0, atol=back.dt * 1e-3)
    assert back.channels["CH1"]["timebase"] == reads["CH1"]["timebase"]  # acquisition values kept


def test_the_time_is_stored_only_when_the_sampling_is_not_regular(tmp_path):
    reads = scope_reads(1)
    t = np.array(reads["CH1"]["time"])
    t[len(t) // 2 :] += 5e-7  # a gap in the middle (a segmented memory)
    reads["CH1"]["time"] = list(t)
    capture = capture_from_reads(0, "long", "s", reads)
    assert capture.time_axis is not None
    back = load_capture(save_capture(tmp_path, capture))
    assert np.allclose(back.times(), t) and back.time_axis is not None


def test_channels_must_share_one_time_base():
    reads = scope_reads(1, 2)
    reads["CH2"]["time"] = [x * 2 for x in reads["CH2"]["time"]]
    with pytest.raises(WaveFileError, match="time base"):
        capture_from_reads(0, "a", "s", reads)
    short = scope_reads(1, 2)
    short["CH2"] = {**short["CH2"], "time": short["CH2"]["time"][:10], "voltage": [0.0] * 10}
    with pytest.raises(WaveFileError):
        capture_from_reads(0, "a", "s", short)
    with pytest.raises(WaveFileError, match="at least one"):
        capture_from_reads(0, "a", "s", {})
    with pytest.raises(WaveFileError, match="no points"):
        capture_from_reads(0, "a", "s", {"CH1": {"time": [], "voltage": []}})


def test_a_file_is_complete_or_not_there(tmp_path):
    capture = capture_from_reads(1, "a", "s", scope_reads(1))
    path = save_capture(tmp_path, capture)
    assert [p.name for p in tmp_path.iterdir()] == [path.name]  # no temporary file left
    bad = capture_from_reads(1, "a", "s", scope_reads(1))
    bad.voltages["CH9"] = bad.voltages["CH1"][:5]
    with pytest.raises(WaveFileError, match="same number"):
        save_capture(tmp_path / "other", bad)
    assert not (tmp_path / "other").exists() or not list((tmp_path / "other").iterdir())


def test_a_file_that_is_not_a_capture_or_is_newer_is_refused(tmp_path):
    (tmp_path / "x.npz").write_bytes(b"not a file")
    with pytest.raises(WaveFileError, match="not a waveform file"):
        load_capture(tmp_path / "x.npz")
    np.savez(tmp_path / "y.npz", voltage_CH1=np.zeros(3, dtype=np.float32))  # no meta
    with pytest.raises(WaveFileError):
        load_capture(tmp_path / "y.npz")
    capture = capture_from_reads(1, "a", "s", scope_reads(1))
    path = save_capture(tmp_path, capture)
    with np.load(path) as data:
        arrays = {k: data[k] for k in data.files}
    meta = json.loads(str(arrays["meta"]))
    meta["format_version"] = wavefiles.FORMAT_VERSION + 1
    arrays["meta"] = np.array(json.dumps(meta))
    np.savez(tmp_path / "newer.npz", **arrays)
    with pytest.raises(WaveFileError, match="newer"):
        load_capture(tmp_path / "newer.npz")


def test_names_are_safe_and_the_folder_is_next_to_the_run_file(tmp_path):
    assert capture_name(3, "fall edge/1", "Scope A:1") == "s00003_fall-edge-1_Scope-A-1.npz"
    assert capture_name(12, "", "!!") == "s00012_x_x.npz"
    run = tmp_path / "runs" / "eff_20261123_101500_ab12.jsonl"
    assert wave_folder(run) == tmp_path / "runs" / "eff_20261123_101500_ab12_waves"


def test_the_index_says_where_the_file_is_and_survives_the_folder_being_deleted(tmp_path):
    run = tmp_path / "runs" / "m_1.jsonl"
    run.parent.mkdir()
    run.write_text("{}\n")
    rows = []
    for step in (0, 2):
        capture = capture_from_reads(
            step, "long", "scope1", scope_reads(1, 2), setpoints={"vin": 9.0 + step}
        )
        path = save_capture(wave_folder(run), capture)
        rows.append(index_entry(capture, path, run))
    assert rows[0]["file"] == "m_1_waves/s00000_long_scope1.npz"  # relative: the project can move
    assert rows[1]["vin"] == 11.0 and rows[0]["channels"] == "CH1,CH2" and rows[0]["bytes"] > 0
    assert missing_files(rows, run) == []
    assert delete_waves(run) == 2
    assert missing_files(rows, run) == [r["file"] for r in rows]  # the results are still there
    assert run.is_file() and delete_waves(run) == 0


def test_the_size_is_estimated_before_a_run():
    # 5 steps, 3 acquisitions, 2 oscilloscopes, 2 channels each, 1 M points
    assert estimate_bytes(1_000_000, 2, 5 * 3 * 2) == 240_000_000  # 30 captures of 8 MB
    assert estimate_bytes(0, 4, 10) == 0
    with pytest.raises(ValueError):
        estimate_bytes(-1, 1, 1)


def test_the_file_is_about_as_big_as_the_estimate(tmp_path):
    capture = capture_from_reads(0, "a", "s", scope_reads(1, 2, depth=10_000))
    path = save_capture(tmp_path, capture)
    assert 0.95 < path.stat().st_size / estimate_bytes(capture.points, 2, 1) < 1.1
