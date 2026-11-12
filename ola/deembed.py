# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Taking a cable out of a measurement: the VSWR of an antenna seen through a cable.

An antenna measured at the end of a cable looks **better matched** than it is: the reflection goes
down the cable and back, so it is weakened by the cable's loss twice. With a cable that was already
measured, the reflection of the antenna alone is recovered by dividing by what the cable does to a
signal that goes to its far end and comes back, ``T(f)**2`` (``T`` is the transmission, S21)::

    Gamma_antenna = S11_measured / T**2

* A cable measured in **transmission** (S21) gives ``T`` with its phase: the correction is complete,
  and the corrected reflection can be used for the impedance and the Smith chart too (mode
  ``"complex"``).
* A cable measured in **reflection** with an open or a short at the far end gives ``T**2`` directly
  (``S11`` of an open, ``-S11`` of a short).
* With only the **loss** of the cable the size is corrected and the phase is not known: enough for
  the VSWR and the return loss, not for the impedance (mode ``"magnitude"``).

The cable is assumed to be **well matched**: its own reflections are not part of the correction.
This holds for a good cable; with a poor connector the correction is an approximation. Where the
corrected reflection would exceed 1 (more than an antenna can reflect: the cable data does not fit,
or the calibration is off) it is limited just under 1 and counted in ``info["over_unity_points"]``.

``load_cable`` reads a cable from a run file of the cable measurement or a Touchstone file,
``correct_reflection`` does the division on the frequencies of the measurement (the cable data is
interpolated and must cover the sweep) and ``latest_cable_run`` finds the newest finished cable
measurement of a code of the registry.
"""

from __future__ import annotations

import cmath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from . import rf

MODES = ("complex", "magnitude")
TERMINATIONS = ("open", "short")
UNITY = 0.9999  # a corrected reflection is kept just under 1
COVER_TOLERANCE = 1e-3  # the cable data may stop this fraction short of the sweep's ends
MAX_PHASE_STEP = 2.5  # rad between two points of the cable data: more is too coarse to interpolate


class DeembedError(ValueError):
    """The cable data cannot be used; the message says why."""


@dataclass
class CableData:
    """What a cable does to a reflection at its far end: ``round_trip[i]`` is ``T**2`` at
    ``freq[i]``. ``has_phase`` is False when only the loss is known (the phase is then 0)."""

    freq: List[float]
    round_trip: List[complex]
    has_phase: bool
    source: str
    warnings: List[str] = field(default_factory=list)

    def one_way_loss_db(self) -> List[float]:
        """The loss of one passage through the cable, in dB (half of the round trip)."""
        return [-rf.db20(v) / 2 for v in self.round_trip]


# ----- reading a cable ------------------------------------------------------------------------
def _check_grid(freq: Sequence[float], what: str) -> None:
    if len(freq) < 2:
        raise DeembedError(f"{what}: needs at least 2 frequencies")
    if any(b <= a for a, b in zip(freq, freq[1:])):
        raise DeembedError(f"{what}: the frequencies must increase")


def _phase_warning(freq: Sequence[float], values: Sequence[complex]) -> List[str]:
    steps = [abs(cmath.phase(b / a)) for a, b in zip(values, values[1:]) if a != 0 and b != 0]
    if steps and max(steps) > MAX_PHASE_STEP:
        return [
            "the cable was measured with too few points for its length (its phase turns by "
            "more than 140 degrees between two points): measure it again with more points"
        ]
    return []


def from_loss(freq: Sequence[float], loss_db: Sequence[float], source: str) -> CableData:
    """A cable known only by its one-way loss: the magnitude of the round trip, no phase."""
    _check_grid(freq, source)
    if len(freq) != len(loss_db):
        raise DeembedError(f"{source}: {len(freq)} frequencies but {len(loss_db)} losses")
    return CableData(list(freq), [complex(10 ** (-2 * x / 20)) for x in loss_db], False, source)


def from_transmission(freq: Sequence[float], s21: Sequence[complex], source: str) -> CableData:
    """A cable measured in transmission: the round trip is ``S21**2``."""
    _check_grid(freq, source)
    data = CableData(list(freq), [v * v for v in s21], True, source)
    data.warnings = _phase_warning(freq, list(s21))
    return data


def from_reflection(
    freq: Sequence[float], s11: Sequence[complex], termination: str, source: str
) -> CableData:
    """A cable measured in reflection with an ``open`` (``S11 = T**2``) or a ``short``."""
    _check_grid(freq, source)
    if termination not in TERMINATIONS:
        raise DeembedError(f"{source}: the far end must be 'open' or 'short', not {termination!r}")
    sign = 1 if termination == "open" else -1
    data = CableData(list(freq), [sign * v for v in s11], True, source)
    data.warnings = _phase_warning(freq, data.round_trip)
    return data


def load_cable_run(path: Union[str, Path]) -> CableData:
    """The cable of a run file of the cable measurement. A transmission run gives ``S21``, a
    reflection run its ``S11`` (the termination is in the parameters of the run); a run with
    only a loss curve gives the magnitude. ``DeembedError`` if it is none of these."""
    from .compare import CompareError, load_run

    path = Path(path)
    try:
        run = load_run(path)
    except CompareError as exc:
        raise DeembedError(str(exc)) from exc
    if run.measurement != "cable":
        raise DeembedError(f"{path.name}: it is a '{run.measurement}' run, not a cable measurement")
    source = path.name
    mode = run.params.get("mode", "transmission")
    if mode == "transmission" and "S21" in run.traces:
        t = run.traces["S21"]
        return from_transmission(t["x"], t["y"], source)
    if mode == "reflection" and "S11" in run.traces:
        t = run.traces["S11"]
        return from_reflection(t["x"], t["y"], run.params.get("termination", "open"), source)
    if "loss_db" in run.traces:
        t = run.traces["loss_db"]
        return from_loss(t["x"], t["y"], source)
    raise DeembedError(f"{source}: the run has no S21, S11 or loss curve of the cable")


def load_cable_touchstone(path: Union[str, Path], termination: str = "open") -> CableData:
    """The cable of a Touchstone file: a ``.s2p`` gives ``S21``, a ``.s1p`` its reflection (with the
    far end ``termination``)."""
    path = Path(path)
    try:
        freq, params, _ = rf.read_touchstone(path)
    except (OSError, rf.RfError) as exc:
        raise DeembedError(str(exc)) from exc
    if "S21" in params:
        return from_transmission(freq, params["S21"], path.name)
    return from_reflection(freq, params["S11"], termination, path.name)


def load_cable(spec: Mapping[str, Any]) -> CableData:
    """The cable named by the ``correction.cable`` parameters: ``run`` (a run file of the cable
    measurement) or ``touchstone``. ``DeembedError`` if neither, or the file cannot be read."""
    if spec.get("run"):
        return load_cable_run(spec["run"])
    if spec.get("touchstone"):
        return load_cable_touchstone(spec["touchstone"], spec.get("termination", "open"))
    raise DeembedError("the cable has no 'run', 'touchstone' or registry code to read it from")


def latest_cable_run(
    code: str,
    run_dirs: Iterable[Union[str, Path]],
    kinds: Sequence[str] = ("cable",),
    registry: Optional[Any] = None,
) -> Optional[Path]:
    """The newest **finished** measurement of the registry code ``code`` (a path), or None. By
    default only cable measurements; ``kinds`` can add others (``"attenuator"``: a pad used as a
    fixture). With the ``registry`` the cable is found by its uid too."""
    from .assets import history

    finished = [
        r
        for r in history(code, run_dirs, registry)
        if r.measurement in kinds and r.state == "finished"
    ]
    return finished[-1].path if finished else None


# ----- the correction -------------------------------------------------------------------------
def interpolate(
    freq: Sequence[float], values: Sequence[complex], at: Sequence[float], keep_phase: bool = True
) -> List[complex]:
    """The complex ``values`` of ``freq`` at the frequencies ``at`` (all inside ``freq``): the
    magnitude (in dB) and the unwrapped phase are interpolated linearly. Without ``keep_phase``
    only the magnitude."""
    db = [rf.db20(v) for v in values]
    phase = rf.unwrap_phase([cmath.phase(v) for v in values]) if keep_phase else [0.0] * len(values)
    out: List[complex] = []
    j = 0
    for f in at:
        while j < len(freq) - 2 and freq[j + 1] < f:
            j += 1
        span = freq[j + 1] - freq[j]
        x = min(max((f - freq[j]) / span, 0.0), 1.0)
        out.append(
            cmath.rect(
                10 ** ((db[j] + x * (db[j + 1] - db[j])) / 20),
                phase[j] + x * (phase[j + 1] - phase[j]),
            )
        )
    return out


def correct_reflection(
    freq: Sequence[float], s11: Sequence[complex], cable: CableData, mode: str = "complex"
) -> Tuple[List[complex], Dict[str, Any]]:
    """The reflection of what is behind the cable: ``S11 / T**2`` at ``freq``. Mode ``"complex"``
    needs a cable with phase; ``"magnitude"`` corrects only the size and keeps the measured phase.
    Returns ``(corrected, info)``; ``info`` has ``over_unity_points``, ``mean_one_way_loss_db``
    and the ``warnings`` of the cable. ``DeembedError`` if the cable does not cover the sweep."""
    if mode not in MODES:
        raise DeembedError(f"mode must be one of {', '.join(MODES)}")
    if len(freq) != len(s11):
        raise DeembedError(f"{len(freq)} frequencies but {len(s11)} values")
    if mode == "complex" and not cable.has_phase:
        raise DeembedError(
            f"{cable.source} has only the loss of the cable, not its phase: use the mode "
            "'magnitude' (enough for the VSWR and the return loss, not for the impedance)"
        )
    low, high = cable.freq[0], cable.freq[-1]
    span = high - low
    if min(freq) < low - COVER_TOLERANCE * span or max(freq) > high + COVER_TOLERANCE * span:
        raise DeembedError(
            f"the cable ({cable.source}) was measured from {rf._hz(low)} to {rf._hz(high)}, "
            f"which does not cover the sweep ({rf._hz(min(freq))} to {rf._hz(max(freq))})"
        )
    if any(abs(v) == 0 for v in cable.round_trip):
        raise DeembedError(f"{cable.source}: the cable passes nothing at some frequency")
    t2 = interpolate(cable.freq, cable.round_trip, freq, keep_phase=mode == "complex")
    out: List[complex] = []
    over = 0
    for value, factor in zip(s11, t2):
        if abs(factor) == 0:
            raise DeembedError(f"{cable.source}: the cable passes nothing at some frequency")
        g = value / abs(factor) if mode == "magnitude" else value / factor
        if abs(g) >= UNITY:
            over += 1
            g = cmath.rect(UNITY, cmath.phase(g))
        out.append(g)
    losses = [-rf.db20(v) / 2 for v in t2]
    return out, {
        "over_unity_points": over,
        "mean_one_way_loss_db": sum(losses) / len(losses),
        "warnings": list(cable.warnings),
    }


# ----- the parameters -------------------------------------------------------------------------
def check_spec(spec: Any, path: str, out: List[Any], problem: Any) -> None:
    """Check one description of a cable / fixture (``asset_id``, ``run``, ``touchstone``,
    ``termination``, ``mode``, ``reversed``), appending ``problem(path, message)`` for every wrong
    thing. It is named by ``asset_id`` (a registry code), ``run`` or ``touchstone`` (``asset_id``
    may accompany ``run``: it is the code the run was found by)."""
    from .assets import normalize_code

    if not isinstance(spec, dict):
        out.append(problem(path, "must be an object that names the cable"))
        return
    for key in set(spec) - {"asset_id", "run", "touchstone", "termination", "mode", "reversed"}:
        out.append(problem(f"{path}.{key}", "unknown field"))
    files = [k for k in ("run", "touchstone") if spec.get(k)]
    if len(files) > 1 or not (files or spec.get("asset_id")):
        out.append(
            problem(
                path,
                "name the cable with one of asset_id (its code in the registry), run (a run "
                "file of the cable measurement) or touchstone (a .s1p / .s2p file)",
            )
        )
    if spec.get("asset_id") and not (
        isinstance(spec["asset_id"], str) and normalize_code(spec["asset_id"])
    ):
        out.append(problem(f"{path}.asset_id", "not a code (it looks like CBL-0042)"))
    for key in ("run", "touchstone"):
        if key in spec and not isinstance(spec[key], str):
            out.append(problem(f"{path}.{key}", "must be the path of a file"))
    if spec.get("touchstone") and not str(spec["touchstone"]).lower().endswith((".s1p", ".s2p")):
        out.append(problem(f"{path}.touchstone", "must be a .s1p or .s2p file"))
    if "termination" in spec and spec["termination"] not in TERMINATIONS:
        out.append(problem(f"{path}.termination", f"must be one of {', '.join(TERMINATIONS)}"))
    if "mode" in spec and spec["mode"] not in MODES:
        out.append(problem(f"{path}.mode", f"must be one of {', '.join(MODES)}"))
    if "reversed" in spec and not isinstance(spec["reversed"], bool):
        out.append(problem(f"{path}.reversed", "must be true or false"))


def check_correction(params: Mapping[str, Any], out: List[Any], problem: Any) -> None:
    """Check ``params["correction"]`` of a reflection measurement (optional): an object with a
    ``cable``, appending ``problem(path, message)`` for every wrong thing."""
    correction = params.get("correction")
    if correction is None:
        return
    spec = correction.get("cable") if isinstance(correction, dict) else None
    if not isinstance(spec, dict):
        out.append(problem("correction", "must be an object with a 'cable'"))
        return
    check_spec(spec, "correction.cable", out, problem)


def corrected_reflection_for(
    params: Mapping[str, Any], freq: Sequence[float], s11: Sequence[complex]
) -> Tuple[List[complex], Optional[Dict[str, Any]]]:
    """What a measurement does with its ``correction`` parameter: ``(s11, None)`` unchanged if there
    is none, else ``(corrected, info)`` with the source and the mode added to ``info``."""
    spec = ((params.get("correction") or {}).get("cable")) if params.get("correction") else None
    if not spec:
        return list(s11), None
    cable = load_cable(spec)
    mode = spec.get("mode") or ("complex" if cable.has_phase else "magnitude")
    corrected, info = correct_reflection(freq, s11, cable, mode)
    info.update(source=cable.source, mode=mode, code=spec.get("asset_id", ""))
    return corrected, info


__all__ = [
    "CableData", "DeembedError", "check_correction", "correct_reflection",
    "corrected_reflection_for", "from_loss", "from_reflection", "from_transmission",
    "interpolate", "latest_cable_run", "load_cable", "load_cable_run", "load_cable_touchstone",
]  # fmt: skip
