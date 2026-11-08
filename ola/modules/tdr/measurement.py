# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Where along a cable a fault is: the time domain from the reflection S11 of a VNA.

Parameters (``.tdr`` file)::

    {"device": {"label": "antenna feed"},                          # optional
     "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 1001},   # linear
     "velocity_factor": 0.66, "z0": 50,
     "window": "hann", "pad": 8,                                   # all optional
     "min_reflection": 0.05, "max_distance_m": 60,
     "expected_length_m": 5.0,                                     # optional: the length is known
     "step_response": false, "averages": 1,
     "limits": {"max_fault_reflection": 0.1},
     "confirm_setup": true}

The VNA is calibrated at the plane of the connector the cable goes on (open / short / load, one
port) and the measurement asks for it once; it then reads S11. The line is left **open** or
**shorted** at its far end, or goes to the device: every change of impedance along it gives a
reflection. ``ola.tdr`` turns S11 into the **impulse response** (a peak for each reflection, at its
delay), and each peak into a distance ``d = c * vf * t / 2`` from the plane of the calibration:

* the distance of every reflection, its size ``|rho|`` and sign (**higher impedance**: an open, a
  thinner or damaged spot; **lower impedance**: a short, a crushed spot, a thicker section) and the
  impedance there;
* the **resolution** ``c vf / (2 B)`` (two faults closer than that are one peak: sweep wider) and
  the **range** ``c vf / (2 df)`` (beyond it the reflections wrap round: more points) of the sweep;
* with ``expected_length_m`` and an open or short end, the **velocity factor** that would make the
  distance of the last reflection equal to that length (``velocity_factor_estimate``): how to
  measure the velocity factor of a cable of known length;
* with ``step_response`` the **step response** and the **impedance profile** along the line (it
  needs a sweep that starts at its own step: ``start_hz`` a multiple of ``(stop - start) / (points -
  1)``);
* a verdict: ``limits.max_fault_reflection`` is the largest reflection allowed **before the end** of
  the line (the last peak is the open, the short or the device, and is not a fault).

The cable loss weakens the far reflections (the round trip is twice its loss): a ``rho`` of 0.3 at
the far end of a lossy cable reads less. A fault that is not found is not invented: a peak must be
at least ``min_reflection``."""

from typing import Any, Dict, List

from ola.golden import check_golden_param, recording
from ola import tdr
from ola.efficiency_spec import Problem
from ola.measurement import Measurement, MeasurementContext
from ola.run_view import format_si
from ola.vna_common import acquire, ask_setup, check_asset, check_sweep, is_number

LIMIT_KEYS = ("max_fault_reflection",)
MIN_POINTS = 16
DEFAULT_VF = 0.66


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new time-domain measurement (used by the editor)."""
    return {
        "device": {"label": ""},
        "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 1001},
        "velocity_factor": DEFAULT_VF,
        "z0": 50,
        "window": "hann",
        "min_reflection": 0.05,
        "step_response": False,
        "averages": 1,
        "confirm_setup": True,
    }


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    start, stop = check_sweep(params, out)
    sweep = params.get("sweep") or {}
    if isinstance(sweep, dict):
        if sweep.get("scale", "linear") != "linear":
            out.append(Problem("sweep.scale", "the time domain needs a linear sweep"))
        points = sweep.get("points")
        if is_number(points) and points < MIN_POINTS:
            out.append(Problem("sweep.points", f"at least {MIN_POINTS} points (more is better)"))
    device = params.get("device", {})
    if not isinstance(device, dict) or not isinstance(device.get("label", ""), str):
        out.append(Problem("device", "must be an object with a text 'label'"))
    check_asset(params, "device", out)
    for key, high in (("velocity_factor", 1.0), ("min_reflection", 1.0)):
        if key in params and (not is_number(params[key]) or not 0 < params[key] <= high):
            out.append(Problem(key, f"must be a number above 0 and at most {high:g}"))
    for key in ("z0", "max_distance_m", "expected_length_m"):
        if key in params and (not is_number(params[key]) or params[key] <= 0):
            out.append(Problem(key, "must be a number above 0"))
    if "window" in params and params["window"] not in tdr.WINDOWS:
        out.append(Problem("window", f"must be one of {', '.join(tdr.WINDOWS)}"))
    pad = params.get("pad", 8)
    if not isinstance(pad, int) or isinstance(pad, bool) or not 1 <= pad <= tdr.MAX_PAD:
        out.append(Problem("pad", f"must be a whole number from 1 to {tdr.MAX_PAD}"))
    averages = params.get("averages", 1)
    if not isinstance(averages, int) or isinstance(averages, bool) or not 1 <= averages <= 1000:
        out.append(Problem("averages", "must be a whole number from 1 to 1000"))
    for key in ("step_response", "confirm_setup"):
        if key in params and not isinstance(params[key], bool):
            out.append(Problem(key, "must be true or false"))
    if params.get("step_response") is True and start and stop and is_number(sweep.get("points")):
        step = (stop - start) / (sweep["points"] - 1) if sweep["points"] > 1 else 0
        k0 = round(start / step) if step > 0 else 0
        if step <= 0 or k0 < 1 or abs(start - k0 * step) > tdr.STEP_GRID_TOLERANCE * step:
            out.append(
                Problem(
                    "sweep.start_hz",
                    "the step response needs a sweep that starts at a multiple of its step "
                    f"(the step is {step:g} Hz): for example start at {step:g} Hz",
                )
            )
    limits = params.get("limits")
    if limits is not None:
        if not isinstance(limits, dict):
            out.append(Problem("limits", 'must be an object like {"max_fault_reflection": 0.1}'))
        else:
            for key, value in limits.items():
                if key not in LIMIT_KEYS:
                    out.append(Problem("limits", f"unknown limit {key!r}: use {LIMIT_KEYS[0]}"))
                elif not is_number(value) or not 0 < value < 1:
                    out.append(Problem("limits", f"{key} must be a number between 0 and 1"))
    check_golden_param(params, out)
    return out


class Tdr(Measurement):
    """Time domain from S11; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, read S11, find the reflections, report."""
        ctx = recording(ctx, "tdr", self.params)  # with a golden sample: checked at the end
        p = self.params
        handle = ctx.instrument("vna")
        if p.get("confirm_setup", True):
            ask_setup(
                ctx,
                "Connect the line under test to port 1 of the VNA, with its far end open, shorted "
                "or on the device.",
                p["sweep"],
                mode="reflection",
            )
        freq, traces = acquire(ctx, handle, p["sweep"], ["S11"], int(p.get("averages", 1)))
        self._report(ctx, freq, traces["S11"])

    def _report(self, ctx: MeasurementContext, freq: List[float], s11: List[complex]) -> None:
        p = self.params
        vf = float(p.get("velocity_factor", DEFAULT_VF))
        z0 = float(p.get("z0", 50))
        try:
            found = tdr.find_faults(
                freq, s11, vf, z0, float(p.get("min_reflection", 0.05)), p.get("window", "hann"),
                int(p.get("pad", 8)), p.get("max_distance_m"),
            )  # fmt: skip
        except tdr.TdrError as exc:
            from ola.measurement import MeasurementError

            raise MeasurementError(f"time domain: {exc}") from exc
        scale = tdr.C * vf / 2
        ctx.emit_trace(
            "S11", freq, s11, kind="complex", hidden=True, xlabel="Frequency", x_unit="Hz"
        )
        distance = [t * scale for t in found["delays"]]
        meta = {"xlabel": "Distance", "x_unit": "m"}
        ctx.emit_trace(
            "impulse", distance, found["envelope"], **dict(meta, ylabel="Reflection |rho|")
        )
        if p.get("step_response"):
            self._step(ctx, freq, s11, scale, z0, found, meta)
        faults = found["faults"]
        for number, fault in enumerate(faults, 1):
            ctx.emit_point(
                {
                    "number": number,
                    "distance_m": fault["distance_m"],
                    "delay_ns": fault["delay_s"] * 1e9,
                    "reflection": fault["reflection"],
                    "phase_deg": fault["phase_deg"],
                    "kind": fault["kind"],
                    "impedance_ohm": fault["impedance_ohm"],
                },
                table="faults",
            )
        summary = self._summary(faults, found, vf)
        limits = p.get("limits") or {}
        if "max_fault_reflection" in limits:
            before_end = faults[:-1]
            worst = max(before_end, key=lambda f: f["reflection"], default=None)
            cap = limits["max_fault_reflection"]
            summary["verdict"] = "FAIL" if worst and worst["reflection"] > cap else "PASS"
            if worst and worst["reflection"] > cap:
                ctx.log(
                    f"a reflection of {worst['reflection']:.3g} at "
                    f"{format_si(worst['distance_m'], 'm')} is above {cap:g} (before the end)",
                    "warning",
                )
        label = (p.get("device") or {}).get("label", "")
        ctx.log(
            f"{label + ': ' if label else ''}{len(faults)} reflection(s) in "
            f"{format_si(distance[-1], 'm')}, resolution {format_si(found['resolution_m'], 'm')}"
        )
        if not faults:
            ctx.log(
                f"no reflection above {float(p.get('min_reflection', 0.05)):g}: the line is "
                "matched, or the far end is too far or too weak (lower min_reflection)",
                "warning",
            )
        ctx.emit_point({"device": label, **summary})

    def _step(self, ctx, freq, s11, scale, z0, found, meta) -> None:
        delays, step = tdr.step_response(freq, s11, int(self.params.get("pad", 8)))
        limit = len(found["delays"])
        d = [t * scale for t in delays[:limit]]
        ctx.emit_trace("step", d, step[:limit], hidden=True, **dict(meta, ylabel="Step response"))
        profile = tdr.impedance_profile(step[:limit], z0)
        ctx.emit_trace(
            "impedance_ohm", d, profile, hidden=True, **dict(meta, ylabel="Impedance (ohm)")
        )

    def _summary(self, faults: List[Dict[str, Any]], found: Dict[str, Any], vf: float):
        p = self.params
        out: Dict[str, Any] = {
            "reflection_count": len(faults),
            "resolution_m": found["resolution_m"],
            "range_m": found["range_m"],
            "velocity_factor": vf,
        }
        if faults:
            out["first_reflection_m"] = faults[0]["distance_m"]
            out["first_reflection"] = faults[0]["reflection"]
            end = faults[-1]
            out["last_reflection_m"] = end["distance_m"]
            out["last_reflection"] = end["reflection"]
            out["last_kind"] = end["kind"]
            strongest = max(faults, key=lambda f: f["reflection"])
            out["strongest_m"] = strongest["distance_m"]
            out["strongest_reflection"] = strongest["reflection"]
            if is_number(p.get("expected_length_m")) and end["distance_m"] > 0:
                length = float(p["expected_length_m"])
                out["expected_length_m"] = length
                out["length_error_m"] = end["distance_m"] - length
                out["velocity_factor_estimate"] = vf * length / end["distance_m"]
        return out
