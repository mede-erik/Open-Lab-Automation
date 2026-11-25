# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the waveform viewer shows: the index of a run, the cache, the decimation, the shifts."""

import json

import numpy as np
import pytest

from ola.wave_align import align_run
from ola.wave_view import (
    WaveCache,
    WaveIndex,
    decimate,
    describe_row,
    has_alignment,
    read_info,
    results_row,
    shifts_for,
)
from ola.wavefiles import Capture, WaveFileError, save_capture, wave_folder


def make(step, scope, acquisition="long", n=400, shift=0.0, signal="VGS"):
    t = -1e-6 + 1e-8 * np.arange(n) - shift
    v = np.exp(-(((t + shift - 1.5e-6) / 3e-7) ** 2))
    return Capture(
        step,
        acquisition,
        scope,
        {"CH1": v.astype(np.float32), "CH2": (0.5 * v).astype(np.float32)},
        1e-8,
        float(t[0]),
        setpoints={"vin": 9.0 + step},
        channels={"CH1": {"signal": signal}, "CH2": {}},
    )


@pytest.fixture
def run(tmp_path):
    path = tmp_path / "runs" / "m_1.jsonl"
    path.parent.mkdir()
    path.write_text("{}\n")
    for step in (0, 2):
        for scope, shift in (("osc1", 0.0), ("osc2", 4e-8)):
            save_capture(wave_folder(path), make(step, scope, shift=shift))
    save_capture(wave_folder(path), make(2, "osc1", "rise"))
    return path


def test_the_index_lists_the_captures_without_reading_their_samples(run):
    index = WaveIndex(run)
    assert index.steps() == [0, 2] and index.acquisitions() == ["long", "rise"]
    assert index.acquisitions(0) == ["long"] and index.scopes() == ["osc1", "osc2"]
    two = index.find(2, "long")
    assert [i.scope for i in two] == ["osc1", "osc2"]
    info = two[0]
    assert info.channels == ["CH1", "CH2"] and info.points == 400 and info.dt == 1e-8
    assert info.setpoints == {"vin": 11.0} and info.signals == {"CH1": "VGS"} and not info.forced
    assert index.find(0, "rise") == []


def test_a_run_without_waveforms_has_an_empty_index_and_a_new_file_is_found(tmp_path):
    path = tmp_path / "r.jsonl"
    index = WaveIndex(path)
    assert index.items == [] and index.steps() == []
    assert index.refresh() == 0
    save_capture(wave_folder(path), make(0, "osc1"))
    assert index.refresh() == 1 and index.steps() == [0]
    (wave_folder(path) / "junk.npz").write_bytes(b"not a capture")
    assert index.refresh() == 1  # a file that is not a capture is left out
    with pytest.raises(WaveFileError):
        read_info(wave_folder(path) / "junk.npz")


def test_the_files_the_run_names_and_are_gone_are_listed(run):
    index = WaveIndex(run)
    rows = [{"file": "m_1_waves/s00000_long_osc1.npz"}, {"file": "m_1_waves/s00009_x_osc1.npz"}]
    assert index.missing(rows) == ["m_1_waves/s00009_x_osc1.npz"]
    assert index.missing([{"step": 1}]) == []


def test_the_cache_keeps_the_last_ones_only(run):
    index = WaveIndex(run)
    cache = WaveCache(size=2)
    a, b, c = (cache.get(i.path) for i in index.items[:3])
    assert len(cache._items) == 2 and index.items[0].path not in cache._items
    assert cache.get(index.items[2].path) is c  # still there: not read again
    assert cache.get(index.items[0].path) is not a  # it was dropped, read again
    cache.clear()
    assert cache._items == {}
    assert WaveCache(size=0).size == 1


def test_few_samples_are_drawn_as_they_are_and_many_as_a_min_max_envelope():
    t = np.arange(10_000) * 1e-9
    v = np.zeros(10_000)
    v[5000] = 1.0  # a glitch of one sample
    x, y = decimate(t, v, t[0], t[-1], 200)
    assert 2 <= len(x) <= 2 * 200 + 2 and y.max() == 1.0  # the glitch survives
    assert np.all(np.diff(x) >= 0)  # in time order
    x, y = decimate(t, v, 4.99e-6, 5.01e-6, 200)  # zoomed in: the samples themselves
    assert len(x) <= 2 * 200 and y.max() == 1.0 and x[0] <= 4.99e-6 + 1e-9
    assert x[-1] >= 5.01e-6 - 1e-9  # one sample outside on each side: the line reaches the edge
    x, y = decimate(t, v, 1.0, 2.0, 200)  # nothing in the window
    assert len(x) <= 2
    x, y = decimate(t, v, 2.0, 1.0, 200)
    assert len(x) == 0
    x, y = decimate(t[:0], v[:0], 0, 1, 10)
    assert len(x) == 0


def test_the_envelope_of_a_ramp_keeps_both_ends_of_every_column():
    t = np.arange(4000) * 1.0
    x, y = decimate(t, t.copy(), 0, 3999, 100)
    assert len(x) == 200 and y[0] == 0 and y[-1] == 3999
    assert np.all(np.diff(y) > 0)  # a ramp: increasing, min before max in each column


def test_the_shifts_come_from_the_alignment_file(run):
    assert shifts_for(run, 2, "long") == {} and not has_alignment(run)
    entries = align_run(run)
    assert has_alignment(run) and len(entries) == 2
    shifts = shifts_for(run, 2, "long")
    assert shifts["osc1"] == 0.0 and shifts["osc2"] == pytest.approx(4e-8, abs=1.1e-8)
    assert shifts_for(run, 2, "rise") == {}  # one oscilloscope only: nothing to align
    # a pair that could not be aligned is left out, not guessed
    data = json.loads((wave_folder(run) / "alignment.json").read_text(encoding="utf-8"))
    data[0].pop("shift_s")
    data[0]["error"] = "poor"
    (wave_folder(run) / "alignment.json").write_text(json.dumps(data), encoding="utf-8")
    assert shifts_for(run, 0, "long") == {}


def test_a_row_of_the_results_is_found_and_described():
    points = [
        {"vin": 9.0, "efficiency": 91.234567, "n_samples": 2, "elapsed_s": 1.0},
        {"vin": 12.0},
    ]
    assert results_row(points, 0)["vin"] == 9.0 and results_row(points, 5) == {}
    assert results_row(points, -1) == {}
    assert describe_row(points[0]) == "vin = 9, efficiency = 91.235"
    assert describe_row({"a": 1, "b": 2, "c": 3}, limit=2) == "a = 1, b = 2"
    assert describe_row({}) == ""
