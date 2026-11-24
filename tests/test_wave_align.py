# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Aligning two oscilloscopes through a signal they both measure."""

import json

import numpy as np
import pytest

from ola.scope_capture import channel_names
from ola.wave_align import (
    FILE_NAME,
    AlignmentError,
    align,
    align_run,
    export_aligned_csv,
    read_alignment,
    shared_signals,
    signals_of,
)
from ola.wavefiles import Capture, load_capture, save_capture, wave_folder

DT = 1e-7


def pulses(t, centres, width=2e-6):
    """A signal made of pulses with soft edges (what a gate drive looks like), not periodic."""
    out = np.zeros_like(t)
    for c, h in centres:
        out += (
            h / (1 + np.exp(-(t - c + width / 2) / 2e-7)) / (1 + np.exp((t - c - width / 2) / 2e-7))
        )
    return out


SHAPE = [(20e-6, 1.0), (45e-6, 0.6), (51e-6, 1.0), (80e-6, 0.8)]  # the same events, on both


def capture(scope, shift, dt=DT, n=1500, noise=0.01, seed=1, signal="VGS_Q1", extra=True):
    """What an oscilloscope saw if its time axis starts ``shift`` later than the events' clock."""
    rng = np.random.default_rng(seed)
    t0 = -10e-6 - shift
    t = t0 + dt * np.arange(n)
    shape = [(c, h) for c, h in SHAPE]
    v = pulses(t + shift, shape) + rng.normal(0, noise, n)
    voltages = {"CH1": v.astype(np.float32)}
    channels = {"CH1": {"signal": signal}}
    if extra:  # a channel only this oscilloscope has
        voltages["CH2"] = (0.1 * np.sin(2 * np.pi * 1e5 * t)).astype(np.float32)
        channels["CH2"] = {"signal": f"only_{scope}"}
    return Capture(0, "long", scope, voltages, dt, float(t[0]), channels=channels)


def test_the_shift_is_found_to_a_fraction_of_a_sample():
    a, b = capture("osc1", 0.0, seed=1), capture("osc2", 3.37e-6, seed=2)
    found = align(a, b)
    assert found.signal == "VGS_Q1" and (found.channel_a, found.channel_b) == ("CH1", "CH1")
    # b's axis starts 3.37 us later on the events' clock than a's: add the difference to b
    assert found.shift_s == pytest.approx(3.37e-6, abs=DT)
    assert found.quality > 0.95 and found.resolution_s == DT


def test_the_shift_has_the_right_sign_in_both_directions():
    a, b = capture("osc1", 0.0), capture("osc2", -2.2e-6, seed=3)
    assert align(a, b).shift_s == pytest.approx(-2.2e-6, abs=DT)
    assert align(b, a).shift_s == pytest.approx(2.2e-6, abs=DT)  # the other way round
    same = align(a, capture("osc2", 0.0, seed=5))
    assert same.shift_s == pytest.approx(0.0, abs=DT)


def test_oscilloscopes_with_different_sample_intervals_are_aligned_on_the_finer_one():
    a = capture("osc1", 0.0, dt=1e-7, n=1500)
    b = capture("osc2", 1.5e-6, dt=2e-7, n=750, seed=4)  # half the sampling rate, same length
    found = align(a, b)
    assert found.resolution_s == pytest.approx(1e-7)
    assert found.shift_s == pytest.approx(1.5e-6, abs=2e-7)


def test_the_signals_the_captures_share_are_listed_by_name():
    a, b = capture("osc1", 0.0), capture("osc2", 0.0)
    assert signals_of(a) == {"VGS_Q1": "CH1", "only_osc1": "CH2"}
    assert shared_signals(a, b) == ["VGS_Q1"]
    b.channels["CH2"]["signal"] = "only_osc1"  # a second shared name
    assert shared_signals(a, b) == ["VGS_Q1", "only_osc1"]
    with pytest.raises(AlignmentError, match="not measured by both"):
        align(a, b, signal="VDS_Q2")
    unnamed = capture("osc3", 0.0, signal="")
    with pytest.raises(AlignmentError, match="no signal in common"):
        align(a, unnamed.__class__(**{**unnamed.__dict__, "channels": {}}))


def test_a_poor_match_is_refused_not_guessed():
    a = capture("osc1", 0.0)
    b = capture("osc2", 0.0, noise=0.0, seed=2)
    rng = np.random.default_rng(9)
    b.voltages["CH1"] = rng.normal(0, 1, len(b.voltages["CH1"])).astype(
        np.float32
    )  # not the signal
    with pytest.raises(AlignmentError, match="does not match well enough"):
        align(a, b)
    flat = capture("osc2", 0.0)
    flat.voltages["CH1"] = np.zeros_like(flat.voltages["CH1"])
    with pytest.raises(AlignmentError, match="flat"):
        align(a, flat)
    assert align(a, capture("osc2", 1e-6, seed=7), min_quality=0.2).quality > 0.2


def test_a_run_is_aligned_and_the_result_is_written_next_to_the_files(tmp_path):
    run = tmp_path / "runs" / "m_1.jsonl"
    run.parent.mkdir()
    run.write_text("{}\n")
    folder = wave_folder(run)
    for step in (0, 4):
        for scope, shift, seed in (("osc1", 0.0, 1), ("osc2", 2e-6 + step * 1e-7, 2)):
            c = capture(scope, shift, seed=seed)
            c.step = step
            save_capture(folder, c)
    lonely = capture("osc1", 0.0)
    lonely.step, lonely.acquisition = 8, "rise"  # one oscilloscope only: nothing to align
    save_capture(folder, lonely)
    entries = align_run(run)
    assert [(e["step"], e["acquisition"]) for e in entries] == [(0, "long"), (4, "long")]
    assert entries[0]["reference"] == "osc1" and entries[0]["scope"] == "osc2"
    assert entries[0]["shift_s"] == pytest.approx(2e-6, abs=DT)
    assert entries[1]["shift_s"] == pytest.approx(2.4e-6, abs=DT)
    assert all(e["quality"] > 0.9 for e in entries)
    assert json.loads((folder / FILE_NAME).read_text(encoding="utf-8")) == entries
    assert read_alignment(run) == entries
    assert not list(folder.glob("*.tmp"))  # written whole


def test_a_pair_that_cannot_be_aligned_is_said_not_dropped(tmp_path):
    run = tmp_path / "r.jsonl"
    run.write_text("{}\n")
    folder = wave_folder(run)
    save_capture(folder, capture("osc1", 0.0, signal="A"))
    save_capture(folder, capture("osc2", 1e-6, signal="B", seed=2))
    (entry,) = align_run(run)
    assert "no signal in common" in entry["error"] and "shift_s" not in entry
    with pytest.raises(AlignmentError, match="no waveform folder"):
        align_run(tmp_path / "other.jsonl")
    assert read_alignment(tmp_path / "other.jsonl") == []


def test_both_oscilloscopes_can_be_written_on_one_time_axis(tmp_path):
    folder = tmp_path / "w"
    pa = save_capture(folder, capture("osc1", 0.0, seed=1))
    pb = save_capture(folder, capture("osc2", 3e-6, seed=2, n=1200))  # a shorter record
    found = align(load_capture(pa), load_capture(pb))
    out = tmp_path / "both.csv"
    rows = export_aligned_csv(pa, pb, found.shift_s, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert rows == 1500 and len(lines) == 1501  # the time axis of the first
    assert lines[0] == "time_s,osc1.CH1,osc1.CH2,osc2.CH1,osc2.CH2"
    table = [line.split(",") for line in lines[1:]]
    both = [(float(r[1]), float(r[3])) for r in table if r[3] != ""]
    assert len(both) > 1000  # most of the time axes overlap
    a_values, b_values = np.array(both).T
    assert np.corrcoef(a_values, b_values)[0, 1] > 0.95  # the shared signal now agrees
    assert any(r[3] == "" for r in table)  # where the second capture does not reach: empty


def test_the_name_of_a_channel_in_the_settings_file_is_what_the_capture_keeps():
    settings = {
        "channels": [
            {"channel_id": "CH1", "name": "VGS_Q1", "enabled": True},
            {"channel_id": "CH2", "enabled": True},
            {"channel_id": "CH3", "name": "IL", "enabled": False},
        ]
    }
    assert channel_names(settings) == {1: "VGS_Q1", 2: ""}
