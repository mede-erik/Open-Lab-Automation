# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What the waveform viewer shows, without any screen (no Qt).

A run that takes waveforms leaves a folder of binary captures (``ola.wavefiles``). The viewer
(``frontend/ui/WaveformView.py``) draws them; everything that decides *what* is drawn is here, so it
is tested without Qt:

* ``WaveIndex`` lists the captures of a run (read from the folder, only their small ``meta``, so a
  run with hundreds of megabytes opens at once) and the results row of each step.
* ``WaveCache`` reads a capture when it is needed and keeps the last few in memory.
* ``decimate`` turns the part of a waveform that is on screen into a few points per pixel column,
  keeping the minimum and the maximum of each column, so a glitch of one sample is never lost and
  zooming in shows the samples (the full waveform is always the one in the file).
* ``shifts_for`` gives the shift of each oscilloscope from ``alignment.json`` (``ola.wave_align``).
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from .wave_align import FILE_NAME, read_alignment
from .wavefiles import Capture, WaveFileError, load_capture, wave_folder


@dataclass
class WaveInfo:
    """One capture file, as far as its ``meta`` says (the samples are not read)."""

    path: Path
    step: int
    acquisition: str
    scope: str
    channels: List[str]
    points: int
    dt: float
    forced: bool
    setpoints: Dict[str, Any]
    signals: Dict[str, str] = field(default_factory=dict)  # channel -> the name of its signal


def read_info(path: Union[str, Path]) -> WaveInfo:
    """The ``meta`` of a capture file, without its samples. ``WaveFileError`` if it is not one."""
    try:
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            names = [k[len("voltage_") :] for k in data.files if k.startswith("voltage_")]
    except (OSError, ValueError, KeyError) as exc:
        raise WaveFileError(f"{path}: not a waveform file ({exc})") from exc
    channels = meta.get("channels") or {}
    return WaveInfo(
        Path(path),
        int(meta["step"]),
        str(meta["acquisition"]),
        str(meta["scope"]),
        names,
        int(meta["points"]),
        float(meta["dt"]),
        bool(meta.get("forced")),
        dict(meta.get("setpoints") or {}),
        {c: str(v["signal"]) for c, v in channels.items() if v.get("signal")},
    )


class WaveIndex:
    """The captures of a run, by step, acquisition and oscilloscope."""

    def __init__(self, run_path: Union[str, Path]):
        self.run_path = Path(run_path)
        self.folder = wave_folder(self.run_path)
        self.items: List[WaveInfo] = []
        self.refresh()

    def refresh(self) -> int:
        """Read the folder again (a run that is still going adds files); returns how many."""
        known = {i.path for i in self.items}
        if self.folder.is_dir():
            for path in sorted(self.folder.glob("*.npz")):
                if path in known:
                    continue
                try:
                    self.items.append(read_info(path))
                except WaveFileError:
                    continue  # a file that is not a capture (or is still being written)
        self.items.sort(key=lambda i: (i.step, i.acquisition, i.scope))
        return len(self.items)

    def steps(self) -> List[int]:
        """The steps that have captures, in order."""
        return sorted({i.step for i in self.items})

    def acquisitions(self, step: Optional[int] = None) -> List[str]:
        """The acquisitions (in the order of their first appearance), of a step or of all."""
        seen: List[str] = []
        for i in self.items:
            if (step is None or i.step == step) and i.acquisition not in seen:
                seen.append(i.acquisition)
        return seen

    def find(self, step: int, acquisition: str) -> List[WaveInfo]:
        """The captures of a step and acquisition, one per oscilloscope."""
        return [i for i in self.items if i.step == step and i.acquisition == acquisition]

    def scopes(self) -> List[str]:
        """The oscilloscopes of the run."""
        return sorted({i.scope for i in self.items})

    def missing(self, rows: Sequence[Mapping[str, Any]]) -> List[str]:
        """The files that the rows of the run file name and are no longer there (the folder can
        be deleted: the results still open)."""
        base = self.run_path.parent
        return [str(r["file"]) for r in rows if r.get("file") and not (base / r["file"]).is_file()]


class WaveCache:
    """Reads captures when they are asked for and keeps the last ``size`` in memory."""

    def __init__(self, size: int = 6):
        self.size = max(1, size)
        self._items: "OrderedDict[Path, Capture]" = OrderedDict()

    def get(self, path: Union[str, Path]) -> Capture:
        """The capture of a file (``WaveFileError`` if it cannot be read)."""
        key = Path(path)
        if key in self._items:
            self._items.move_to_end(key)
            return self._items[key]
        capture = load_capture(key)
        self._items[key] = capture
        while len(self._items) > self.size:
            self._items.popitem(last=False)
        return capture

    def clear(self) -> None:
        """Forget everything (the files changed)."""
        self._items.clear()


def decimate(
    times: np.ndarray,
    values: np.ndarray,
    x0: float,
    x1: float,
    columns: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """The part of a waveform between ``x0`` and ``x1`` as at most about ``2 * columns`` points:
    the samples themselves if there are few enough, otherwise the minimum and the maximum of each
    of ``columns`` equal slices (in time order inside the slice), so a narrow glitch stays visible.
    A sample just outside on each side is kept so the line reaches the edges."""
    if len(times) == 0 or x1 <= x0:
        return times[:0], values[:0]
    low = max(int(np.searchsorted(times, x0, side="left")) - 1, 0)
    high = min(int(np.searchsorted(times, x1, side="right")) + 1, len(times))
    t, v = times[low:high], values[low:high]
    columns = max(int(columns), 1)
    if len(t) <= 2 * columns:
        return t, v
    edges = np.linspace(0, len(t), columns + 1).astype(int)
    out_t: List[float] = []
    out_v: List[float] = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        chunk = v[a:b]
        i_min, i_max = a + int(np.argmin(chunk)), a + int(np.argmax(chunk))
        for k in sorted({i_min, i_max}):
            out_t.append(float(t[k]))
            out_v.append(float(v[k]))
    return np.asarray(out_t), np.asarray(out_v)


def shifts_for(run_path: Union[str, Path], step: int, acquisition: str) -> Dict[str, float]:
    """The shift of each oscilloscope of a step and acquisition, from ``alignment.json``: the
    reference oscilloscope has 0, the others what ``ola.wave_align`` found (pairs it could not
    align are left out, so they are drawn on their own time axis)."""
    out: Dict[str, float] = {}
    for entry in read_alignment(run_path):
        if entry.get("step") != step or entry.get("acquisition") != acquisition:
            continue
        if "shift_s" in entry:
            out.setdefault(entry["reference"], 0.0)
            out[entry["scope"]] = float(entry["shift_s"])
    return out


def has_alignment(run_path: Union[str, Path]) -> bool:
    """True if ``alignment.json`` exists in the folder of the run."""
    return (wave_folder(run_path) / FILE_NAME).is_file()


def results_row(points: Sequence[Mapping[str, Any]], step: int) -> Dict[str, Any]:
    """The row of the results of a step (the main table), or {} if the step is not there."""
    return dict(points[step]) if 0 <= step < len(points) else {}


def describe_row(row: Mapping[str, Any], limit: int = 12) -> str:
    """The values of a row on one line (``vin = 12, rload = 4.7, efficiency = 91.3``); numbers are
    shortened, the bookkeeping columns left out."""
    skip = {"elapsed_s", "n_samples", "sweep", "point", "index"}
    parts: List[str] = []
    for key, value in row.items():
        if key in skip:
            continue
        if isinstance(value, float):
            value = f"{value:.5g}"
        parts.append(f"{key} = {value}")
        if len(parts) >= limit:
            break
    return ", ".join(parts)
