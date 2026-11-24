# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The waveforms of a run, as binary files next to its results (no Qt).

A converter measurement can acquire the waveform of the oscilloscope channels at some of its steps.
A whole acquisition memory is megabytes, so it does not go in the run file (JSON Lines): every
**capture** is a file of its own, in a folder of the run, and the run file keeps only an index of
them. The folder can be deleted at will: the results stay.

* **Where**: ``<run file without .jsonl>_waves/`` next to the run file (``wave_folder``).
* **One file per capture** (``save_capture``): the channels of one oscilloscope acquired together,
  for one step and one acquisition (a settings file: a long view, a rising edge...). They share one
  trigger and one time base, so they can be drawn together. Name:
  ``s<step>_<acquisition>_<oscilloscope>.npz``.
* **Format**: a NumPy ``.npz`` (readable by any program with NumPy, ``allow_pickle=False``), not
  compressed. Arrays: ``voltage_<channel>`` (float32, volts at the probe tip as the instrument gave
  them), ``time`` (float64 seconds, only if the sampling is not regular) and ``meta``, a JSON text
  with ``format_version``, ``step``, ``acquisition``, ``scope``, ``t0`` (time of the first sample
  relative to the trigger), ``dt`` (sample interval), ``points``, ``forced`` (the trigger was forced
  because it did not arrive), ``captured_at`` (seconds since 1970), ``setpoints`` (what the
  converter was set to at that step), ``settings`` (what the file of scope settings said) and
  ``channels`` (for each one the acquisition values: vertical gain, offset, trigger delay...).
* ``index_entry`` is the row that goes in the run file for a capture, and ``load_capture`` reads
  one back. ``estimate_bytes`` is the size to expect, shown before a run starts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

import numpy as np

FORMAT_VERSION = 1
FOLDER_SUFFIX = "_waves"
SAMPLE_BYTES = 4  # float32


class WaveFileError(ValueError):
    """A capture cannot be saved or read; the message says why."""


@dataclass
class Capture:
    """The channels of one oscilloscope, acquired together at one step."""

    step: int
    acquisition: str
    scope: str
    voltages: Dict[str, np.ndarray]  # channel name -> samples (V)
    dt: float  # sample interval (s)
    t0: float = 0.0  # time of the first sample, relative to the trigger (s)
    time_axis: Optional[np.ndarray] = None  # the time of each sample, only if not regular
    forced: bool = False
    captured_at: float = field(default_factory=time.time)
    setpoints: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)
    channels: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def points(self) -> int:
        """Samples in each channel."""
        return len(next(iter(self.voltages.values()))) if self.voltages else 0

    def times(self) -> np.ndarray:
        """The time of every sample (s)."""
        if self.time_axis is not None:
            return self.time_axis
        return self.t0 + self.dt * np.arange(self.points)


def wave_folder(run_path: Union[str, Path]) -> Path:
    """The folder of the waveform files of a run: next to the run file, named like it."""
    path = Path(run_path)
    return path.with_name(path.stem + FOLDER_SUFFIX)


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-") or "x"


def capture_name(step: int, acquisition: str, scope: str) -> str:
    """The file name of a capture: ``s00012_rise_scope1.npz``."""
    return f"s{int(step):05d}_{_safe(acquisition)}_{_safe(scope)}.npz"


_SKIPPED = {"time", "voltage", "points"}  # what ``read_waveform`` gives that is not metadata


def capture_from_reads(
    step: int,
    acquisition: str,
    scope: str,
    reads: Mapping[str, Mapping[str, Any]],
    forced: bool = False,
    setpoints: Optional[Mapping[str, Any]] = None,
    settings: Optional[Mapping[str, Any]] = None,
) -> Capture:
    """A ``Capture`` from the ``read_waveform_full`` results of the channels (``{"CH1": result}``).

    The channels of one capture must have the same number of points and the same sample interval
    (one time base); ``WaveFileError`` otherwise."""
    if not reads:
        raise WaveFileError("a capture needs at least one channel")
    voltages: Dict[str, np.ndarray] = {}
    channels: Dict[str, Dict[str, Any]] = {}
    time_axis: Optional[np.ndarray] = None
    for name, got in reads.items():
        v = np.asarray(got["voltage"], dtype=np.float64)
        if v.size == 0:
            raise WaveFileError(f"channel {name}: no points")
        t = np.asarray(got["time"], dtype=np.float64)
        if t.shape != v.shape:
            raise WaveFileError(f"channel {name}: time and voltage differ in length")
        if time_axis is None:
            time_axis = t
        elif t.shape != time_axis.shape or not np.allclose(
            t, time_axis, rtol=0, atol=abs(float(t[-1] - t[0])) * 1e-9 + 1e-15
        ):
            raise WaveFileError(
                f"channel {name} is not on the time base of the others (the channels of one "
                "capture must be acquired together)"
            )
        voltages[name] = v.astype(np.float32)
        channels[name] = {
            k: val
            for k, val in got.items()
            if k not in _SKIPPED and isinstance(val, (int, float, str, bool))
        }
    assert time_axis is not None
    n = time_axis.size
    t0 = float(time_axis[0])
    dt = float((time_axis[-1] - t0) / (n - 1)) if n > 1 else 0.0
    regular = n < 2 or bool(
        np.allclose(time_axis, t0 + dt * np.arange(n), rtol=0, atol=abs(dt) * 1e-3)
    )
    return Capture(
        step, acquisition, scope, voltages, dt, t0, None if regular else time_axis, forced,
        time.time(), dict(setpoints or {}), dict(settings or {}), channels,
    )  # fmt: skip


def save_capture(folder: Union[str, Path], capture: Capture) -> Path:
    """Write a capture in ``folder`` (made if it is not there) and return the file. The file is
    written whole or not at all (a temporary file, then renamed). ``WaveFileError`` if the channels
    differ in length."""
    sizes = {len(v) for v in capture.voltages.values()}
    if len(sizes) != 1:
        raise WaveFileError("the channels of a capture must have the same number of points")
    if capture.time_axis is not None and len(capture.time_axis) != capture.points:
        raise WaveFileError("time and voltage differ in length")
    meta = {
        "format_version": FORMAT_VERSION,
        "step": int(capture.step),
        "acquisition": capture.acquisition,
        "scope": capture.scope,
        "t0": capture.t0,
        "dt": capture.dt,
        "points": capture.points,
        "forced": bool(capture.forced),
        "captured_at": capture.captured_at,
        "setpoints": capture.setpoints,
        "settings": capture.settings,
        "channels": capture.channels,
    }
    arrays: Dict[str, Any] = {
        f"voltage_{name}": np.asarray(v, dtype=np.float32) for name, v in capture.voltages.items()
    }
    if capture.time_axis is not None:
        arrays["time"] = np.asarray(capture.time_axis, dtype=np.float64)
    arrays["meta"] = np.array(json.dumps(meta, ensure_ascii=False, default=str))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / capture_name(capture.step, capture.acquisition, capture.scope)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "wb") as f:
        np.savez(f, **arrays)
    os.replace(temp, path)
    return path


def load_capture(path: Union[str, Path]) -> Capture:
    """Read a capture file. ``WaveFileError`` if it is not one, or is of a newer format."""
    try:
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            version = meta.get("format_version", 0)
            if version > FORMAT_VERSION:
                raise WaveFileError(f"{path}: made by a newer version of the program")
            voltages = {
                key[len("voltage_") :]: data[key]
                for key in data.files
                if key.startswith("voltage_")
            }
            axis = data["time"] if "time" in data.files else None
    except WaveFileError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        raise WaveFileError(f"{path}: not a waveform file ({exc})") from exc
    return Capture(
        int(meta["step"]), meta["acquisition"], meta["scope"], voltages, float(meta["dt"]),
        float(meta["t0"]), axis, bool(meta.get("forced")), float(meta.get("captured_at", 0.0)),
        meta.get("setpoints") or {}, meta.get("settings") or {}, meta.get("channels") or {},
    )  # fmt: skip


def index_entry(
    capture: Capture, path: Union[str, Path], run_path: Union[str, Path]
) -> Dict[str, Any]:
    """The row of the run file for a capture: where the file is (relative to the folder of the run
    file, so the project can be moved), what it holds, and the setpoints of the step."""
    folder = wave_folder(run_path)
    try:
        where = str(Path(path).relative_to(folder.parent))
    except ValueError:
        where = str(path)
    return {
        "file": where.replace(os.sep, "/"),
        "step": capture.step,
        "acquisition": capture.acquisition,
        "scope": capture.scope,
        "channels": ",".join(capture.voltages),
        "points": capture.points,
        "dt": capture.dt,
        "forced": capture.forced,
        "bytes": Path(path).stat().st_size if Path(path).exists() else 0,
        **capture.setpoints,
    }


def export_csv(path: Union[str, Path], csv_path: Union[str, Path]) -> int:
    """Write a capture as a CSV file: a ``time`` column (s) and one column per channel (V), the
    header line with the names. Returns the number of rows. The channels share the time base, so
    they share the column."""
    capture = load_capture(path)
    names = list(capture.voltages)
    times = capture.times()
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(["time_s"] + names) + "\n")
        columns = [capture.voltages[n] for n in names]
        for k in range(capture.points):
            f.write(",".join([repr(float(times[k]))] + [repr(float(c[k])) for c in columns]) + "\n")
    return capture.points


def missing_files(index: Sequence[Mapping[str, Any]], run_path: Union[str, Path]) -> Sequence[str]:
    """The files of an index (the rows of ``index_entry``) that are no longer there: the folder
    can be deleted, and the results must still open."""
    base = Path(run_path).parent
    return [row["file"] for row in index if not (base / row["file"]).is_file()]


def delete_waves(run_path: Union[str, Path]) -> int:
    """Delete the folder of the waveforms of a run; returns how many files it had."""
    folder = wave_folder(run_path)
    if not folder.is_dir():
        return 0
    count = sum(1 for p in folder.iterdir() if p.is_file())
    shutil.rmtree(folder)
    return count


def estimate_bytes(points: int, channels: int, captures: int) -> int:
    """The size of the waveform files of a run: ``captures`` captures (steps x acquisitions x
    oscilloscopes) of ``channels`` channels of ``points`` samples, without the small headers."""
    if min(points, channels, captures) < 0:
        raise ValueError("points, channels and captures cannot be negative")
    return int(points) * int(channels) * int(captures) * SAMPLE_BYTES


__all__ = [
    "Capture", "FORMAT_VERSION", "WaveFileError", "capture_from_reads", "capture_name",
    "delete_waves", "estimate_bytes", "export_csv", "index_entry", "load_capture", "missing_files",
    "save_capture", "wave_folder",
]  # fmt: skip
