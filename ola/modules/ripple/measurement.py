# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Ripple and noise on a supply output with an oscilloscope.

Parameters (``.rpl`` file)::

    {"device": {"label": "5 V rail", "nominal_v": 5.0},        # nominal_v is optional
     "scope": {"channel": 1, "probe_attenuation": 1, "coupling": "AC",
               "bandwidth_limit_hz": 20e6,                      # 0 = full bandwidth
               "volts_per_div": 0.01, "offset_v": 0,            # optional
               "time_per_div": 2e-6, "memory_depth": 100000,    # optional
               "acquisition": "NORMAL", "bits": 8},             # optional
     "trigger": {"level_v": 0, "slope": "RISE", "mode": "AUTO"},   # optional
     "captures": 1, "capture_wait_s": 0.5,                      # optional
     "conditions": {"currents_a": [0.1, 0.5, 1.0], "settle_s": 1.0},   # optional (a load)
     "spectrum": true, "peaks": 5,
     "limits": {"max_pp_v": 0.05, "max_rms_v": 0.01},           # optional
     "confirm_setup": true}

The scope channel is on the supply output, **AC coupled** and limited to **20 MHz** (the usual
way to quote ripple and noise), with a short ground spring or a coax connection on the probe: a
long ground lead picks up the switching spikes and shows them as ripple. The measurement sets the
channel, reads the whole acquisition memory (``handle.read_waveform_full``) and computes, from the
volts at the probe tip:

* the **peak-to-peak** value, the positive and negative peaks, the **rms** of the AC part and the
  DC level (the mean, not meaningful with AC coupling);
* the **frequency of the ripple** and its harmonics from the spectrum (Hann window), and the
  **noise**: the rms of what is left once the ripple and its harmonics are taken away;
* with ``captures`` above 1 the capture is repeated and the **worst** peak-to-peak is also given;
* with ``conditions`` (a list of load currents and an electronic load bound to the role ``load``)
  one row per current: the ripple as a function of the load. The load is switched off at the end,
  also after an error or a stop;
* a verdict against ``limits`` (``max_pp_v``, ``max_rms_v``): too much ripple is a *result*.

Warnings in the log say when the figures cannot be trusted: the signal clips the screen, only a
few levels of the converter are used (raise the sensitivity), the record holds fewer than five
periods of the ripple, or the sample rate is close to twice the ripple frequency.
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ola import spectrum
from ola.efficiency_spec import Problem
from ola.measurement import Measurement, MeasurementContext, MeasurementError
from ola.run_view import format_si
from ola.vna_common import check_asset, is_number

COUPLINGS = ("AC", "DC")
ACQUISITIONS = ("NORMAL", "AVERAGE", "HIRES")
SLOPES = ("RISE", "FALL", "EITHER")
TRIGGER_MODES = ("AUTO", "NORMAL")
LIMIT_KEYS = ("max_pp_v", "max_rms_v")
MAX_CAPTURES = 100
MAX_CONDITIONS = 50
MIN_LEVELS = 20  # fewer distinct converter levels than this: the resolution is the limit
DRAWN_POINTS = 4000  # the waveform shown has at most this many points (a min/max envelope)
SPECTRUM_FLOOR_DBV = -160.0


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new ripple measurement (used by the editor)."""
    return {
        "device": {"label": ""},
        "scope": {
            "channel": 1,
            "probe_attenuation": 1,
            "coupling": "AC",
            "bandwidth_limit_hz": 20e6,
            "bits": 8,
        },
        "captures": 1,
        "spectrum": True,
        "peaks": 5,
        "confirm_setup": True,
    }


def _check_choice(spec: Dict[str, Any], key: str, allowed: Sequence[str], path: str, out):
    if key in spec and (not isinstance(spec[key], str) or spec[key].upper() not in allowed):
        out.append(Problem(f"{path}.{key}", f"must be one of {', '.join(allowed)}"))


def _check_positive(spec: Dict[str, Any], key: str, path: str, out, unit: str, zero_ok=False):
    if key in spec:
        v = spec[key]
        if not is_number(v) or v < 0 or (v == 0 and not zero_ok):
            what = "0 or more" if zero_ok else "above 0"
            out.append(
                Problem(f"{path}.{key}" if path else key, f"must be a number ({unit}) {what}")
            )


def _check_scope(params: Dict[str, Any], out: List[Problem]) -> None:
    scope = params.get("scope")
    if not isinstance(scope, dict):
        out.append(Problem("scope", "the oscilloscope settings are missing"))
        return
    channel = scope.get("channel", 1)
    if not isinstance(channel, int) or isinstance(channel, bool) or not 1 <= channel <= 16:
        out.append(Problem("scope.channel", "must be a whole number from 1"))
    _check_choice(scope, "coupling", COUPLINGS, "scope", out)
    _check_choice(scope, "acquisition", ACQUISITIONS, "scope", out)
    _check_positive(scope, "probe_attenuation", "scope", out, "ratio, 10 = 10:1")
    _check_positive(scope, "bandwidth_limit_hz", "scope", out, "Hz", zero_ok=True)
    _check_positive(scope, "volts_per_div", "scope", out, "V")
    _check_positive(scope, "time_per_div", "scope", out, "s")
    if "offset_v" in scope and not is_number(scope["offset_v"]):
        out.append(Problem("scope.offset_v", "the offset must be a number (V)"))
    for key, low, high in (("memory_depth", 1, 10**9), ("bits", 8, 16)):
        if key in scope and (
            not isinstance(scope[key], int)
            or isinstance(scope[key], bool)
            or not low <= scope[key] <= high
        ):
            out.append(Problem(f"scope.{key}", f"must be a whole number from {low} to {high}"))
    trigger = params.get("trigger")
    if trigger is not None:
        if not isinstance(trigger, dict):
            out.append(Problem("trigger", "must be an object (level_v, slope, mode)"))
        else:
            if "level_v" in trigger and not is_number(trigger["level_v"]):
                out.append(Problem("trigger.level_v", "the level must be a number (V)"))
            _check_choice(trigger, "slope", SLOPES, "trigger", out)
            _check_choice(trigger, "mode", TRIGGER_MODES, "trigger", out)


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    device = params.get("device", {})
    if not isinstance(device, dict):
        out.append(Problem("device", "must be an object with a 'label'"))
    else:
        if "label" in device and not isinstance(device["label"], str):
            out.append(Problem("device.label", "the label must be text"))
        if "nominal_v" in device and not is_number(device["nominal_v"]):
            out.append(Problem("device.nominal_v", "the nominal voltage must be a number (V)"))
    check_asset(params, "device", out)
    _check_scope(params, out)
    captures = params.get("captures", 1)
    if (
        not isinstance(captures, int)
        or isinstance(captures, bool)
        or not 1 <= captures <= MAX_CAPTURES
    ):
        out.append(Problem("captures", f"must be a whole number from 1 to {MAX_CAPTURES}"))
    _check_positive(params, "capture_wait_s", "", out, "s", zero_ok=True)
    cond = params.get("conditions")
    if cond is not None:
        currents = cond.get("currents_a") if isinstance(cond, dict) else None
        if (
            not isinstance(currents, list)
            or not currents
            or len(currents) > MAX_CONDITIONS
            or not all(is_number(c) and c >= 0 for c in currents)
        ):
            out.append(
                Problem(
                    "conditions",
                    f"needs currents_a: 1 to {MAX_CONDITIONS} load currents (A, 0 or more)",
                )
            )
        elif "settle_s" in cond and (not is_number(cond["settle_s"]) or cond["settle_s"] < 0):
            out.append(Problem("conditions.settle_s", "the settling time must be 0 s or more"))
    peaks = params.get("peaks", 5)
    if not isinstance(peaks, int) or isinstance(peaks, bool) or not 1 <= peaks <= 20:
        out.append(Problem("peaks", "must be a whole number from 1 to 20"))
    limits = params.get("limits")
    if limits is not None:
        if not isinstance(limits, dict):
            out.append(Problem("limits", 'must be an object like {"max_pp_v": 0.05}'))
        else:
            for key, value in limits.items():
                if key not in LIMIT_KEYS:
                    out.append(
                        Problem("limits", f"unknown limit {key!r}: use {', '.join(LIMIT_KEYS)}")
                    )
                elif not is_number(value) or value <= 0:
                    out.append(Problem("limits", f"{key} must be a number of volts above 0"))
    for key in ("spectrum", "confirm_setup"):
        if key in params and not isinstance(params[key], bool):
            out.append(Problem(key, "must be true or false"))
    return out


# ----- the numbers ----------------------------------------------------------------------------
def envelope(time: Sequence[float], volts: Sequence[float], limit: int = DRAWN_POINTS):
    """``(x, y)`` of at most ``limit`` points that keep every peak: the record is cut in
    ``limit / 2`` buckets and each gives its lowest and highest value (in time order)."""
    n = len(volts)
    if n <= limit:
        return list(time), list(volts)
    buckets = max(1, limit // 2)
    xs: List[float] = []
    ys: List[float] = []
    for b in range(buckets):
        lo, hi = b * n // buckets, (b + 1) * n // buckets
        chunk = volts[lo:hi]
        if not chunk:
            continue
        i_min = lo + min(range(len(chunk)), key=chunk.__getitem__)
        i_max = lo + max(range(len(chunk)), key=chunk.__getitem__)
        for i in sorted({i_min, i_max}):
            xs.append(time[i])
            ys.append(volts[i])
    return xs, ys


def levels_used(volts: Sequence[float]) -> int:
    """How many different values the record holds (a measure of the converter's resolution)."""
    return len({round(v, 12) for v in volts})


def analyse(
    time: Sequence[float],
    volts: Sequence[float],
    sample_interval_s: Optional[float] = None,
    peaks: int = 5,
    want_spectrum: bool = True,
) -> Dict[str, Any]:
    """The figures of one capture. No I/O. ``summary`` holds the numbers; ``spectrum`` the
    frequencies and amplitudes (or None); ``warnings`` what makes the figures doubtful."""
    n = len(volts)
    if n < 8:
        raise MeasurementError(f"the oscilloscope returned only {n} points")
    dt = sample_interval_s if sample_interval_s else (time[-1] - time[0]) / (n - 1)
    mean = sum(volts) / n
    low, high = min(volts), max(volts)
    rms = math.sqrt(sum((v - mean) ** 2 for v in volts) / n)
    summary: Dict[str, Any] = {
        "samples": n,
        "sample_rate_hz": 1.0 / dt,
        "mean_v": mean,
        "pp_v": high - low,
        "peak_pos_v": high - mean,
        "peak_neg_v": low - mean,
        "rms_v": rms,
    }
    warnings: List[str] = []
    if levels_used(volts) < MIN_LEVELS:
        warnings.append(
            f"only {levels_used(volts)} different levels in the record: the resolution of the "
            "oscilloscope limits the result, raise the sensitivity (a smaller V/div)"
        )
    freqs: List[float] = []
    amps: List[float] = []
    if want_spectrum:
        try:
            freqs, amps = spectrum.amplitude_spectrum(volts, dt)
        except ValueError:
            freqs, amps = [], []
    if freqs:
        found = spectrum.find_peaks(freqs, amps, peaks)
        if found:
            summary["ripple_frequency_hz"] = found[0][0]
            summary["ripple_fundamental_v"] = found[0][1]
            summary["peaks"] = "; ".join(
                f"{format_si(f, 'Hz')} {a * 1000:.3g} mV" for f, a in found
            )
            summary["noise_rms_v"] = spectrum.rms_outside(freqs, amps, [f for f, _ in found])
            record = n * dt
            if record * found[0][0] < 5:
                warnings.append(
                    "fewer than 5 periods of the ripple in the record: slow the timebase or "
                    "raise the memory depth"
                )
            if 1.0 / dt < 5 * found[0][0]:
                warnings.append(
                    "the sample rate is below 5 times the ripple frequency: speed up the timebase"
                )
        else:
            summary["noise_rms_v"] = rms
    return {"summary": summary, "spectrum": (freqs, amps), "warnings": warnings}


def clipped(volts: Sequence[float], scale: Optional[float], offset: float) -> bool:
    """True if the record touches the top or the bottom of the screen (4 divisions either side of
    the centre, which is ``-offset``), so that the peaks are cut off."""
    if not scale:
        return False
    top, bottom = -offset + 4 * scale, -offset - 4 * scale
    return max(volts) >= top - 1e-9 or min(volts) <= bottom + 1e-9


def verdict(row: Dict[str, Any], limits: Dict[str, float]) -> Tuple[str, List[str]]:
    """``("PASS" | "FAIL", reasons)`` of a row against ``max_pp_v`` and ``max_rms_v``."""
    reasons = []
    if "max_pp_v" in limits and row["pp_v"] > limits["max_pp_v"]:
        reasons.append(
            f"peak-to-peak {row['pp_v'] * 1000:.3g} mV above {limits['max_pp_v'] * 1000:.3g} mV"
        )
    if "max_rms_v" in limits and row["rms_v"] > limits["max_rms_v"]:
        reasons.append(
            f"rms {row['rms_v'] * 1000:.3g} mV above {limits['max_rms_v'] * 1000:.3g} mV"
        )
    return ("FAIL" if reasons else "PASS"), reasons


class RippleNoise(Measurement):
    """Ripple and noise of a supply output with an oscilloscope; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Nothing is switched on before the question."""
        self._load_on = False

    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the set-up, configure the scope, capture (for every load current), report."""
        p = self.params
        scope = ctx.instrument("oscilloscope")
        currents = (p.get("conditions") or {}).get("currents_a")
        load = None
        if currents is not None:
            if not ctx.instruments("load"):
                raise MeasurementError("'conditions' needs an electronic load bound to 'load'")
            load = ctx.instrument("load")
        if p.get("confirm_setup", True):
            self._ask_setup(ctx, load is not None)
        self._configure(ctx, scope)
        if load is None:
            self._measure(ctx, scope, None, 0, 1)
            return
        load.call("set_mode", mode="CC")
        total = len(currents)
        for number, current in enumerate(currents, 1):
            ctx.checkpoint()
            load.call("set_current_level", value=float(current))
            if not self._load_on:
                load.call("load_on")
                self._load_on = True
            ctx.sleep(float((p.get("conditions") or {}).get("settle_s", 0)))
            self._measure(ctx, scope, float(current), number, total)

    def teardown(self, ctx: MeasurementContext) -> None:
        """Switch the load off, whatever happened."""
        if getattr(self, "_load_on", False):
            try:
                ctx.instrument("load").call("load_off")
            except Exception as exc:  # the other results are kept; say what was left on
                ctx.log(f"could not switch the load off: {exc}", "error")

    # ----- the steps ----------------------------------------------------------------------
    def _ask_setup(self, ctx: MeasurementContext, with_load: bool) -> None:
        text = (
            "Connect the probe across the output of the supply, as close to the output "
            "capacitor as possible, with the ground spring (no long ground lead: it picks up "
            "the switching spikes) and the 20 MHz limit on. "
        )
        text += "The load is switched on by the measurement. " if with_load else ""
        text += "The supply must be on and stable. Then continue."
        if ctx.ask(text, ["continue", "abort"], default="abort") == "abort":
            from ola.measurement import Stopped

            raise Stopped()

    def _configure(self, ctx: MeasurementContext, scope: Any) -> None:
        p = self.params
        s = p["scope"]
        ch = int(s.get("channel", 1))

        def optional(name: str, **args: Any) -> None:
            if not hasattr(scope, "supports") or scope.supports(name):
                scope.call(name, **args)

        scope.call("set_channel_state", channel_number=ch, state=True)
        scope.call(
            "set_probe_attenuation", channel_number=ch, value=float(s.get("probe_attenuation", 1))
        )
        scope.call(
            "set_channel_coupling", channel_number=ch, coupling_type=s.get("coupling", "AC").upper()
        )
        scope.call(
            "set_channel_bandwidth_limit",
            channel_number=ch,
            bandwidth=float(s.get("bandwidth_limit_hz", 20e6)),
        )
        if "volts_per_div" in s:
            scope.call("set_channel_scale", channel_number=ch, value=float(s["volts_per_div"]))
        if "offset_v" in s:
            scope.call("set_channel_offset", channel_number=ch, value=float(s["offset_v"]))
        if "time_per_div" in s:
            scope.call("set_timebase_scale", value=float(s["time_per_div"]))
        if "acquisition" in s:
            scope.call("set_acquisition_type", acquisition_type=s["acquisition"].upper())
        if "memory_depth" in s:
            optional("set_acquisition_depth", depth=int(s["memory_depth"]))
        trig = p.get("trigger")
        if trig:
            scope.call("set_trigger_source", channel_number=ch)
            if "level_v" in trig:
                scope.call("set_trigger_level", value=float(trig["level_v"]), channel_number=ch)
            if "slope" in trig:
                scope.call("set_trigger_slope", slope=trig["slope"].upper())
            scope.call("set_trigger_mode", mode=trig.get("mode", "AUTO").upper())

    def _capture(self, ctx: MeasurementContext, scope: Any) -> Dict[str, Any]:
        s = self.params["scope"]
        scope.call("run_acquisition")
        ctx.sleep(float(self.params.get("capture_wait_s", 0.5)))
        return scope.read_waveform_full(int(s.get("channel", 1)), bits=int(s.get("bits", 8)))

    def _measure(self, ctx, scope, current: Optional[float], number: int, total: int) -> None:
        p = self.params
        captures = int(p.get("captures", 1))
        best = None
        pps: List[float] = []
        for k in range(1, captures + 1):
            ctx.checkpoint()
            wave = self._capture(ctx, scope)
            result = analyse(
                wave["time"], wave["voltage"], wave.get("sample_interval"),
                int(p.get("peaks", 5)), bool(p.get("spectrum", True)),
            )  # fmt: skip
            pps.append(result["summary"]["pp_v"])
            if best is None or result["summary"]["pp_v"] > best[0]["summary"]["pp_v"]:
                best = (result, wave)
            ctx.progress(
                (number - 1) * captures + k, total * captures, f"capture {k} of {captures}"
            )
        result, wave = best
        self._report(ctx, result, wave, pps, current)

    def _report(self, ctx, result, wave, pps: List[float], current: Optional[float]) -> None:
        p = self.params
        dev = p.get("device") or {}
        s = p["scope"]
        suffix = "" if current is None else f" @ {current:g} A"
        x, y = envelope(wave["time"], wave["voltage"])
        ctx.emit_trace(
            f"waveform{suffix}", x, y, xlabel="Time", x_unit="s", ylabel="Voltage (V)",
        )  # fmt: skip
        freqs, amps = result["spectrum"]
        if freqs:
            db = [max(spectrum.to_dbv(a), SPECTRUM_FLOOR_DBV) for a in amps]
            ctx.emit_trace(
                f"spectrum_dbv{suffix}", freqs[1:], db[1:], xlabel="Frequency", x_unit="Hz",
                ylabel="dBV (rms)", log_x=True, hidden=True,
            )  # fmt: skip
        row: Dict[str, Any] = {"device": dev.get("label", "")}
        if current is not None:
            row["load_current_a"] = current
        row.update(result["summary"])
        if len(pps) > 1:
            row["captures"] = len(pps)
            row["pp_mean_v"] = sum(pps) / len(pps)
            row["pp_worst_v"] = max(pps)
        row["coupling"] = s.get("coupling", "AC").upper()
        row["bandwidth_limit_hz"] = float(s.get("bandwidth_limit_hz", 20e6))
        nominal = dev.get("nominal_v")
        if is_number(nominal) and nominal:
            row["pp_percent_of_nominal"] = 100 * row["pp_v"] / nominal
        limits = p.get("limits") or {}
        if limits:
            row["verdict"], reasons = verdict(row, limits)
            for why in reasons:
                ctx.log(f"limit exceeded{suffix}: {why}", "warning")
        scale = s.get("volts_per_div")
        if clipped(wave["voltage"], scale, float(s.get("offset_v", 0))):
            ctx.log(f"the signal touches the edge of the screen{suffix}: the peaks are cut, "
                    "use a larger V/div or move the offset", "warning")  # fmt: skip
        for warning in result["warnings"]:
            ctx.log(f"{warning}{suffix}", "warning")
        ctx.log(
            f"ripple{suffix}: {row['pp_v'] * 1000:.3g} mV peak-to-peak, "
            f"{row['rms_v'] * 1000:.3g} mV rms"
            + (
                f", at {format_si(row['ripple_frequency_hz'], 'Hz')}"
                if "ripple_frequency_hz" in row
                else ""
            )
        )
        ctx.emit_point(row)
