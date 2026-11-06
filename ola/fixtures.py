"""Taking cables, attenuators and adapters out of a transmission measurement. No Qt.

A device is often measured through something that is not part of it: a longer cable on one port,
an adapter, a pad. The VNA is calibrated at the end of its test leads, so what is between that plane
and the device is **in the result**. With the **fixture** already measured (a cable, an attenuator,
an adapter) it is taken out: the measurement then shows the device alone, and the loss of the
fixture is not charged to it. A fixture can be on port 1, on port 2, or on both (``left`` and
``right``).

Two models, in two modes:

* ``matched`` (the simple one): the fixtures are assumed well matched, so each only attenuates and
  delays: ``S21 = S21 measured / (T1 * T2)`` and the reflections are divided by the round trip of
  their own fixture, ``S11 = S11 measured / T1**2``, ``S22 = S22 measured / T2**2``. Needs only the
  transmission ``T`` of each fixture. It is good for a cable, and for a pad of good return loss.
* ``full``: the fixtures are two-ports with their own reflections (``S11``, ``S22``), and the
  measurement is cut in the **transfer matrices**: ``T measured = T1 * T device * T2``, so
  ``T device = inv(T1) * T measured * inv(T2)``. Needs all four S-parameters measured and fixtures
  with their reflections (a Touchstone file ``.s2p``, or the run of an attenuator, which has ``S11``
  and ``S22``). It is exact for any fixture, matched or not.
* ``complex``: the phase is used as well (the corrected S-parameters are complete, the group delay
  of the device alone can be found). ``magnitude``: only the size of the fixture's transmission is
  taken out, the measured phase is kept: enough when only the loss of the fixture is known (and then
  only the ``matched`` model can be used).

Orientation: a fixture file is written **as seen from the VNA**: port 1 is the VNA end, port 2 the
device end, for the fixture on port 1 and also for the one on port 2 (which is turned round here).
Say ``reversed`` for a file written the other way. ``deembed_two_port`` does the maths on the
frequencies of the measurement (the fixture data is interpolated and must cover the sweep);
``load_fixture`` reads a fixture from a cable run, an attenuator run or a Touchstone file.
"""

from __future__ import annotations

import cmath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from . import rf
from .deembed import (
    COVER_TOLERANCE,
    MODES,
    UNITY,
    DeembedError,
    check_spec,
    interpolate,
    _phase_warning,
)

MODELS = ("matched", "full")
Matrix = Tuple[Tuple[complex, complex], Tuple[complex, complex]]


@dataclass
class Fixture:
    """A two-port between the plane of the calibration and the device, as seen from the VNA
    (port 1 at the VNA). ``s11`` and ``s22`` are None for a fixture known only by its
    transmission; ``s12`` is None for a reciprocal one (``s12 = s21``)."""

    freq: List[float]
    s21: List[complex]
    s11: Optional[List[complex]] = None
    s22: Optional[List[complex]] = None
    s12: Optional[List[complex]] = None
    has_phase: bool = True
    source: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def has_reflections(self) -> bool:
        """True if both reflections are known (needed for the ``full`` model)."""
        return self.s11 is not None and self.s22 is not None

    def loss_db(self) -> List[float]:
        """The loss of one passage, in dB."""
        return [-rf.db20(v) for v in self.s21]


# ----- reading a fixture ----------------------------------------------------------------------
def _grid(freq: Sequence[float], source: str) -> None:
    if len(freq) < 2 or any(b <= a for a, b in zip(freq, freq[1:])):
        raise DeembedError(f"{source}: needs at least 2 increasing frequencies")


def load_fixture_run(path: Union[str, Path]) -> Fixture:
    """The fixture of a run file: a **cable** measured in transmission (``S21``: matched), in
    reflection (only its size is known) or by its loss; an **attenuator** (``S21``, and its ``S11``
    and ``S22``: a fixture with reflections). ``DeembedError`` for any other run."""
    from .compare import CompareError, load_run

    path = Path(path)
    try:
        run = load_run(path)
    except CompareError as exc:
        raise DeembedError(str(exc)) from exc
    source = path.name
    traces = run.traces
    if run.measurement == "attenuator" and "S21" in traces:
        t = traces["S21"]
        fx = Fixture(list(t["x"]), list(t["y"]), source=source)
        for name, key in (("S11", "s11"), ("S22", "s22")):
            if name in traces:
                setattr(fx, key, list(traces[name]["y"]))
        fx.warnings = _phase_warning(fx.freq, fx.s21)
        return fx
    if run.measurement != "cable":
        raise DeembedError(
            f"{source}: it is a '{run.measurement}' run, not a cable or an attenuator measurement"
        )
    mode = run.params.get("mode", "transmission")
    if mode == "transmission" and "S21" in traces:
        t = traces["S21"]
        fx = Fixture(list(t["x"]), list(t["y"]), source=source)
        fx.warnings = _phase_warning(fx.freq, fx.s21)
        return fx
    if mode == "reflection" and "S11" in traces:  # |T^2| is known, the sign of T is not
        t = traces["S11"]
        size = [complex(abs(v) ** 0.5) for v in t["y"]]
        return Fixture(list(t["x"]), size, has_phase=False, source=source)
    if "loss_db" in traces:
        t = traces["loss_db"]
        return Fixture(
            list(t["x"]), [complex(10 ** (-x / 20)) for x in t["y"]], has_phase=False, source=source
        )
    raise DeembedError(f"{source}: the run has no S21, S11 or loss curve of the cable")


def load_fixture_touchstone(path: Union[str, Path], reversed_file: bool = False) -> Fixture:
    """The fixture of a ``.s2p`` file, port 1 at the VNA (``reversed_file``: port 1 at the device).
    A file without a reverse transmission (``S12`` all 0) is taken as reciprocal."""
    path = Path(path)
    try:
        freq, params, _ = rf.read_touchstone(path)
    except (OSError, rf.RfError) as exc:
        raise DeembedError(str(exc)) from exc
    if "S21" not in params:
        raise DeembedError(f"{path.name}: a fixture needs a two-port file (.s2p)")
    s12 = params.get("S12")
    fx = Fixture(
        freq, params["S21"], params["S11"], params["S22"],
        None if s12 is None or all(v == 0 for v in s12) else s12, source=path.name,
    )  # fmt: skip
    if reversed_file:
        fx = flipped(fx)
    fx.warnings = _phase_warning(freq, fx.s21)
    return fx


def load_fixture(spec: Mapping[str, Any]) -> Fixture:
    """The fixture named by a ``run`` or a ``touchstone`` of ``spec`` (``reversed`` for a file
    written the other way round). ``DeembedError`` if neither."""
    if spec.get("run"):
        return load_fixture_run(spec["run"])
    if spec.get("touchstone"):
        return load_fixture_touchstone(spec["touchstone"], bool(spec.get("reversed")))
    raise DeembedError("the fixture has no 'run', 'touchstone' or registry code to read it from")


def flipped(fx: Fixture) -> Fixture:
    """The same fixture turned round: port 1 and port 2 exchanged."""
    return Fixture(
        fx.freq, fx.s12 if fx.s12 is not None else fx.s21, fx.s22, fx.s11, fx.s21,
        fx.has_phase, fx.source, list(fx.warnings),
    )  # fmt: skip


# ----- the matrices ---------------------------------------------------------------------------
def to_t(s11: complex, s21: complex, s12: complex, s22: complex) -> Matrix:
    """The transfer matrix of a two-port from its S-parameters (``[b1, a1] = T [a2, b2]``), so that
    cascaded two-ports multiply."""
    det = s11 * s22 - s12 * s21
    return ((-det / s21, s11 / s21), (-s22 / s21, 1 / s21))


def from_t(t: Matrix) -> Tuple[complex, complex, complex, complex]:
    """``(s11, s21, s12, s22)`` of a transfer matrix."""
    (t11, t12), (t21, t22) = t
    det = t11 * t22 - t12 * t21
    return t12 / t22, 1 / t22, det / t22, -t21 / t22


def multiply(a: Matrix, b: Matrix) -> Matrix:
    """The product of two 2 x 2 matrices."""
    return (
        (a[0][0] * b[0][0] + a[0][1] * b[1][0], a[0][0] * b[0][1] + a[0][1] * b[1][1]),
        (a[1][0] * b[0][0] + a[1][1] * b[1][0], a[1][0] * b[0][1] + a[1][1] * b[1][1]),
    )


def inverse(m: Matrix) -> Matrix:
    """The inverse of a 2 x 2 matrix."""
    (a, b), (c, d) = m
    det = a * d - b * c
    if abs(det) < 1e-300:
        raise DeembedError("a fixture cannot be inverted (it passes nothing)")
    return ((d / det, -b / det), (-c / det, a / det))


# ----- the correction -------------------------------------------------------------------------
def _complex_at(freq: Sequence[float], values: Sequence[complex], at: Sequence[float]):
    """A smooth complex curve at ``at``: real and imaginary parts interpolated linearly (used for
    reflections, whose phase has no reason to be a smooth ramp)."""
    out, j = [], 0
    for f in at:
        while j < len(freq) - 2 and freq[j + 1] < f:
            j += 1
        x = min(max((f - freq[j]) / (freq[j + 1] - freq[j]), 0.0), 1.0)
        out.append(values[j] + x * (values[j + 1] - values[j]))
    return out


def fixture_at(fx: Fixture, freq: Sequence[float], keep_phase: bool = True) -> Dict[str, List]:
    """The S-parameters of a fixture at the frequencies ``freq``: ``{"S21": [...], "S12": [...],
    "S11": [...], "S22": [...]}`` (a missing reflection is 0, a missing ``S12`` is ``S21``)."""
    zeros = [0j] * len(freq)
    s21 = interpolate(fx.freq, fx.s21, freq, keep_phase)
    return {
        "S21": s21,
        "S12": interpolate(fx.freq, fx.s12, freq, keep_phase) if fx.s12 is not None else s21,
        "S11": _complex_at(fx.freq, fx.s11, freq) if fx.s11 is not None else zeros,
        "S22": _complex_at(fx.freq, fx.s22, freq) if fx.s22 is not None else zeros,
    }


def _cover(fx: Fixture, freq: Sequence[float], name: str) -> None:
    low, high = fx.freq[0], fx.freq[-1]
    span = high - low
    if min(freq) < low - COVER_TOLERANCE * span or max(freq) > high + COVER_TOLERANCE * span:
        raise DeembedError(
            f"the {name} fixture ({fx.source}) was measured from {rf._hz(low)} to {rf._hz(high)}, "
            f"which does not cover the sweep ({rf._hz(min(freq))} to {rf._hz(max(freq))})"
        )
    if any(abs(v) == 0 for v in fx.s21):
        raise DeembedError(f"{fx.source}: the fixture passes nothing at some frequency")


def _clip(value: complex) -> Tuple[complex, bool]:
    return (cmath.rect(UNITY, cmath.phase(value)), True) if abs(value) >= UNITY else (value, False)


def deembed_two_port(
    freq: Sequence[float],
    measured: Mapping[str, Sequence[complex]],
    left: Optional[Fixture] = None,
    right: Optional[Fixture] = None,
    mode: str = "complex",
    model: str = "matched",
) -> Tuple[Dict[str, List[complex]], Dict[str, Any]]:
    """The device alone: ``measured`` is ``{"S21": [...], "S11": [...], ...}`` (the ones that were
    read), ``left`` the fixture on port 1 and ``right`` the one on port 2 (either may be None).
    Returns ``(corrected, info)``; ``info`` has ``over_unity_points`` (reflections that had to be
    limited just under 1), ``gain_points`` (``|S21| > 1`` after the correction: fine for an
    amplifier, suspicious for a filter or a pad), ``left_loss_db`` / ``right_loss_db`` (mean loss of
    each fixture) and the ``warnings`` of the fixture data. ``DeembedError`` if a fixture does not
    cover the sweep, or the model needs what is not there."""
    if mode not in MODES:
        raise DeembedError(f"mode must be one of {', '.join(MODES)}")
    if model not in MODELS:
        raise DeembedError(f"model must be one of {', '.join(MODELS)}")
    if left is None and right is None:
        raise DeembedError("name at least one fixture, on port 1 or on port 2")
    n = len(freq)
    for name, values in measured.items():
        if len(values) != n:
            raise DeembedError(f"{name}: {len(values)} values for {n} frequencies")
    complex_mode = mode == "complex"
    fixtures = {"left": left, "right": right}
    for side, fx in fixtures.items():
        if fx is None:
            continue
        _cover(fx, freq, "port 1" if side == "left" else "port 2")
        if complex_mode and not fx.has_phase:
            raise DeembedError(
                f"{fx.source} has only the loss of the fixture, not its phase: use the mode "
                "'magnitude'"
            )
    if model == "full":
        _need_full(measured, fixtures, complex_mode)
    at = {s: fixture_at(fx, freq, complex_mode) for s, fx in fixtures.items() if fx is not None}
    out = (
        _full(freq, measured, at, left, right)
        if model == "full"
        else _matched(freq, measured, at, complex_mode)
    )
    info: Dict[str, Any] = {"model": model, "mode": mode, "over_unity_points": 0}
    for side, fx in fixtures.items():
        if fx is not None:
            losses = [-rf.db20(v) for v in at[side]["S21"]]
            info[f"{side}_loss_db"] = sum(losses) / n
            info.setdefault("warnings", []).extend(fx.warnings)
            info.setdefault("sources", {})[side] = fx.source
    for name in ("S11", "S22"):
        if name in out:
            clipped = [_clip(v) for v in out[name]]
            out[name] = [v for v, _ in clipped]
            info["over_unity_points"] += sum(1 for _, c in clipped if c)
    info["gain_points"] = sum(1 for v in out.get("S21", []) if abs(v) > 1.0 + 1e-6)
    info.setdefault("warnings", [])
    return out, info


def _need_full(measured: Mapping[str, Any], fixtures: Mapping[str, Any], complex_mode: bool):
    if not complex_mode:
        raise DeembedError("the full model needs the phase: use the mode 'complex'")
    missing = [n for n in ("S11", "S21", "S12", "S22") if n not in measured]
    if missing:
        raise DeembedError(
            f"the full model needs all four S-parameters measured (missing {', '.join(missing)})"
        )
    for side, fx in fixtures.items():
        if fx is not None and not fx.has_reflections:
            raise DeembedError(
                f"{fx.source} has no reflections (S11, S22): the full model needs a two-port "
                "file or an attenuator measurement; use the matched model for a cable"
            )


def _matched(freq, measured, at, complex_mode):
    """Divide by the transmission of the fixtures (the reflections by the round trip)."""

    def size(v: complex) -> complex:
        return complex(abs(v))

    use = (lambda v: v) if complex_mode else size
    out: Dict[str, List[complex]] = {}
    for name, values in measured.items():
        divisor = [1 + 0j] * len(freq)
        for side, fx in at.items():
            if name == "S21":
                factor = [use(v) for v in fx["S21"]]
            elif name == "S12":
                factor = [use(v) for v in fx["S12"]]
            elif (name == "S11" and side == "left") or (name == "S22" and side == "right"):
                factor = [use(v) * use(v) for v in fx["S21"]]
            else:
                continue
            divisor = [d * f for d, f in zip(divisor, factor)]
        out[name] = [v / d for v, d in zip(values, divisor)]
    return out


def _full(freq, measured, at, left, right):
    """The transfer-matrix de-embedding, point by point."""
    out: Dict[str, List[complex]] = {k: [] for k in ("S11", "S21", "S12", "S22")}
    for i in range(len(freq)):
        t = to_t(measured["S11"][i], measured["S21"][i], measured["S12"][i], measured["S22"][i])
        if left is not None:
            a = at["left"]
            t = multiply(inverse(to_t(a["S11"][i], a["S21"][i], a["S12"][i], a["S22"][i])), t)
        if right is not None:  # turned round: its port 1 is at the device
            b = at["right"]
            t = multiply(t, inverse(to_t(b["S22"][i], b["S12"][i], b["S21"][i], b["S11"][i])))
        s11, s21, s12, s22 = from_t(t)
        for key, value in (("S11", s11), ("S21", s21), ("S12", s12), ("S22", s22)):
            out[key].append(value)
    return out


# ----- the parameters -------------------------------------------------------------------------
PORTS = ("port1", "port2")


def check_fixtures(params: Mapping[str, Any], out: List[Any], problem: Any) -> None:
    """Check ``params["correction"]`` of a transmission measurement (optional): ``port1`` and / or
    ``port2`` naming a fixture each, ``mode`` and ``model``."""
    correction = params.get("correction")
    if correction is None:
        return
    if not isinstance(correction, dict) or not any(k in correction for k in PORTS):
        out.append(problem("correction", "must be an object with a 'port1' and / or a 'port2'"))
        return
    for key in set(correction) - set(PORTS) - {"mode", "model"}:
        out.append(problem(f"correction.{key}", "unknown field"))
    for port in PORTS:
        if port in correction:
            check_spec(correction[port], f"correction.{port}", out, problem)
    if "mode" in correction and correction["mode"] not in MODES:
        out.append(problem("correction.mode", f"must be one of {', '.join(MODES)}"))
    if "model" in correction and correction["model"] not in MODELS:
        out.append(problem("correction.model", f"must be one of {', '.join(MODELS)}"))


def wanted_parameters(params: Mapping[str, Any], default: Sequence[str]) -> List[str]:
    """The S-parameters a measurement must read: ``default``, or all four when the correction is
    the ``full`` model (it needs them all)."""
    correction = params.get("correction") or {}
    if correction.get("model") == "full":
        return ["S21", "S11", "S12", "S22"]
    return list(default)


def correct_traces(
    params: Mapping[str, Any], freq: Sequence[float], traces: Mapping[str, Sequence[complex]]
) -> Tuple[Dict[str, List[complex]], Optional[Dict[str, Any]]]:
    """What a transmission measurement does with its ``correction``: ``(traces, None)`` unchanged
    if there is none, else the corrected S-parameters and the ``info`` (with the ``sources``)."""
    correction = params.get("correction")
    if not correction:
        return {k: list(v) for k, v in traces.items()}, None
    sides = {}
    for key, side in (("port1", "left"), ("port2", "right")):
        if correction.get(key):
            sides[side] = load_fixture(correction[key])
    fixtures_have_phase = all(fx.has_phase for fx in sides.values())
    mode = correction.get("mode") or ("complex" if fixtures_have_phase else "magnitude")
    model = correction.get("model") or "matched"
    corrected, info = deembed_two_port(
        freq, traces, sides.get("left"), sides.get("right"), mode, model
    )
    info["codes"] = {
        side: correction[key].get("asset_id", "")
        for key, side in (("port1", "left"), ("port2", "right"))
        if correction.get(key)
    }
    return corrected, info


__all__ = [
    "Fixture", "check_fixtures", "correct_traces", "deembed_two_port", "flipped", "fixture_at",
    "from_t", "inverse", "load_fixture", "load_fixture_run", "load_fixture_touchstone",
    "multiply", "to_t", "wanted_parameters",
]  # fmt: skip
