# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Aligning the waveforms of two oscilloscopes after the measurement (no Qt).

Two oscilloscopes only share a time origin if they share a trigger. When they do not, each capture
has its own time axis, and the waveforms of the two cannot be drawn together as they are. If the
same signal is measured by both (a channel with the **same name** on the two oscilloscopes, for
example ``VGS_Q1``: the ``name`` of the channel in the ``.was`` file, kept with the waveform as its
``signal``), that signal is the synchroniser: ``align`` finds how far the time axis of the second
capture must be moved to put the shared signal on the first, from the peak of the cross-correlation
(refined to a fraction of a sample), and says how good the match is. If it is poor the program says
so and does not align.

The shift is **not** written in the waveform files, which stay as they were acquired: ``align_run``
writes ``alignment.json`` in the folder of the run, ``export_aligned_csv`` draws both captures on
the time axis of the first.

The convention: ``shift_s`` is what is **added** to the time of the second capture, so the sample
at time ``t`` of the second is at ``t + shift_s`` on the axis of the first.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from .wavefiles import Capture, WaveFileError, load_capture, wave_folder

MIN_QUALITY = 0.5  # below this correlation the match is not trusted
FILE_NAME = "alignment.json"


class AlignmentError(ValueError):
    """The two captures cannot be aligned; the message says why."""


@dataclass
class Alignment:
    """How to put the second capture on the time axis of the first."""

    signal: str  # the name of the shared signal
    channel_a: str  # its channel on the first capture
    channel_b: str  # and on the second
    shift_s: float  # added to the time of the second capture
    quality: float  # correlation of the shared signal once aligned, 1 = identical
    resolution_s: float  # the sample interval used: the shift is known to about this much

    def as_dict(self) -> Dict[str, Any]:
        """The alignment as plain values (for ``alignment.json``)."""
        return {
            "signal": self.signal,
            "channel_a": self.channel_a,
            "channel_b": self.channel_b,
            "shift_s": self.shift_s,
            "quality": self.quality,
            "resolution_s": self.resolution_s,
        }


def signals_of(capture: Capture) -> Dict[str, str]:
    """The signals a capture measures, ``{signal name: channel}`` (the channels whose ``.was``
    entry has a name; the first channel wins if two have the same name)."""
    found: Dict[str, str] = {}
    for channel, meta in capture.channels.items():
        name = str(meta.get("signal") or "").strip()
        if name and name not in found:
            found[name] = channel
    return found


def shared_signals(a: Capture, b: Capture) -> List[str]:
    """The names of the signals that both captures measure, in the order of the first."""
    other = signals_of(b)
    return [name for name in signals_of(a) if name in other]


def _on_grid(capture: Capture, channel: str, dt: float) -> np.ndarray:
    """The channel on a regular grid of step ``dt`` that starts at the first sample, linearly
    interpolated (a capture whose own step is ``dt`` is returned as it is)."""
    values = np.asarray(capture.voltages[channel], dtype=np.float64)
    times = capture.times()
    if capture.time_axis is None and abs(capture.dt - dt) <= 1e-9 * dt:
        return values
    grid = times[0] + dt * np.arange(int((times[-1] - times[0]) / dt) + 1)
    return np.interp(grid, times, values)


def _normalised(values: np.ndarray) -> np.ndarray:
    centred = values - values.mean()
    spread = centred.std()
    if not np.isfinite(spread) or spread <= 0:
        raise AlignmentError("the shared signal is flat in one of the captures: nothing to match")
    return centred / spread


def align(
    a: Capture,
    b: Capture,
    signal: Optional[str] = None,
    min_quality: float = MIN_QUALITY,
) -> Alignment:
    """How to move the time axis of ``b`` to put the signal both captures measure on ``a``.

    ``signal`` names the shared signal (the first one both have if it is omitted).
    ``AlignmentError`` if there is none, or if the match is poorer than ``min_quality``."""
    shared = shared_signals(a, b)
    if not shared:
        raise AlignmentError(
            "the captures have no signal in common: give the same name to the channel of each "
            "oscilloscope that measures the same signal (the name of the channel in the .was file)"
        )
    if signal is None:
        signal = shared[0]
    elif signal not in shared:
        raise AlignmentError(f"the signal {signal!r} is not measured by both captures")
    ch_a, ch_b = signals_of(a)[signal], signals_of(b)[signal]
    dt = min(a.dt, b.dt)
    if not dt > 0:
        raise AlignmentError("a capture has no sample interval")
    x = _normalised(_on_grid(a, ch_a, dt))
    y = _normalised(_on_grid(b, ch_b, dt))
    n = len(x) + len(y) - 1
    size = 1 << (n - 1).bit_length()
    spectrum = np.fft.rfft(x, size).conj() * np.fft.rfft(y, size)
    corr = np.fft.irfft(spectrum, size)  # corr[L] = sum_k x[k] * y[k + L]
    lags = np.concatenate([np.arange(0, len(y)), np.arange(-len(x) + 1, 0)])
    values = np.concatenate([corr[: len(y)], corr[size - len(x) + 1 :]])
    overlap = np.minimum(len(x), len(y) - lags) - np.maximum(0, -lags)
    overlap = np.maximum(overlap, 1)
    # the correlation of the part that overlaps, as a coefficient; a lag that leaves only a few
    # samples is not trusted
    score = values / overlap
    score[overlap < max(8, 0.1 * min(len(x), len(y)))] = -np.inf
    best = int(np.argmax(score))
    lag = float(lags[best])
    if 0 < best < len(score) - 1 and np.isfinite(score[best - 1]) and np.isfinite(score[best + 1]):
        left, mid, right = score[best - 1], score[best], score[best + 1]
        denominator = left - 2 * mid + right
        if (
            denominator != 0
            and lags[best - 1] == lags[best] - 1
            and lags[best + 1] == lags[best] + 1
        ):
            lag += 0.5 * (left - right) / denominator  # parabola through the peak: a fraction
    quality = float(score[best])
    if quality < min_quality:
        raise AlignmentError(
            f"the signal {signal!r} does not match well enough between the two captures "
            f"(correlation {quality:.2f}, at least {min_quality:.2f} is needed): not aligned"
        )
    shift = (a.times()[0] - b.times()[0]) - lag * dt
    return Alignment(signal, ch_a, ch_b, float(shift), quality, float(dt))


# ---- a run -------------------------------------------------------------------------------------
def _groups(folder: Path) -> Dict[Tuple[int, str], List[Tuple[Path, Capture]]]:
    """The captures of a folder grouped by step and acquisition."""
    groups: Dict[Tuple[int, str], List[Tuple[Path, Capture]]] = {}
    for path in sorted(folder.glob("*.npz")):
        try:
            capture = load_capture(path)
        except WaveFileError:
            continue
        groups.setdefault((capture.step, capture.acquisition), []).append((path, capture))
    return groups


def align_run(run_path: Union[str, Path], min_quality: float = MIN_QUALITY) -> List[Dict[str, Any]]:
    """Align the oscilloscopes of every step and acquisition of a run that has two or more with a
    signal in common: the first oscilloscope (in the order of the file names) is the reference.
    The result is written to ``alignment.json`` in the folder of the waveforms and returned: one
    entry per pair, with ``step``, ``acquisition``, ``reference`` and ``scope`` (the oscilloscopes),
    ``file_a`` and ``file_b``, and either the alignment (``signal``, ``shift_s``, ``quality``,
    ``resolution_s``) or ``error`` (why it was not aligned). ``AlignmentError`` if the folder
    has no waveforms."""
    folder = wave_folder(run_path)
    if not folder.is_dir():
        raise AlignmentError("the run has no waveform folder (deleted, or none was taken)")
    entries: List[Dict[str, Any]] = []
    for (step, acquisition), found in sorted(_groups(folder).items()):
        if len(found) < 2:
            continue
        (path_a, first), rest = found[0], found[1:]
        for path_b, other in rest:
            entry: Dict[str, Any] = {
                "step": step,
                "acquisition": acquisition,
                "reference": first.scope,
                "scope": other.scope,
                "file_a": path_a.name,
                "file_b": path_b.name,
            }
            try:
                entry.update(align(first, other, None, min_quality).as_dict())
            except AlignmentError as exc:
                entry["error"] = str(exc)
            entries.append(entry)
    if not any(_groups(folder).values()):
        raise AlignmentError("the folder has no waveforms")
    target = folder / FILE_NAME
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, target)
    return entries


def read_alignment(run_path: Union[str, Path]) -> List[Dict[str, Any]]:
    """The entries of ``alignment.json`` of a run (empty if it has not been made)."""
    path = wave_folder(run_path) / FILE_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def export_aligned_csv(
    path_a: Union[str, Path],
    path_b: Union[str, Path],
    shift_s: float,
    csv_path: Union[str, Path],
) -> int:
    """Write two captures on one time axis, that of the first: ``time_s``, the channels of the
    first as ``<scope>.<channel>`` and those of the second, moved by ``shift_s`` and interpolated
    on the same times (empty where the second capture does not reach). Returns the rows."""
    a, b = load_capture(path_a), load_capture(path_b)
    times = a.times()
    moved = b.times() + shift_s
    names = [f"{a.scope}.{c}" for c in a.voltages] + [f"{b.scope}.{c}" for c in b.voltages]
    columns: List[np.ndarray] = [np.asarray(v, dtype=np.float64) for v in a.voltages.values()]
    inside = (times >= moved[0]) & (times <= moved[-1])
    for values in b.voltages.values():
        columns.append(np.where(inside, np.interp(times, moved, np.asarray(values)), np.nan))
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(["time_s"] + names) + "\n")
        for k in range(len(times)):
            cells = [repr(float(times[k]))] + [
                "" if np.isnan(c[k]) else repr(float(c[k])) for c in columns
            ]
            f.write(",".join(cells) + "\n")
    return len(times)


__all__ = [
    "Alignment", "AlignmentError", "FILE_NAME", "MIN_QUALITY", "align", "align_run",
    "export_aligned_csv", "read_alignment", "shared_signals", "signals_of",
]  # fmt: skip
