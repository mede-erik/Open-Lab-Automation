# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Bode plot: the gain and the phase of a circuit against frequency, with a generator and a scope.

Parameters (``.bod`` file)::

    {"device": {"label": "buck loop"},
     "sweep": {"start_hz": 100, "stop_hz": 1e6, "points": 41, "scale": "log"},
     "source": {"channel": 1, "amplitude_vpp": 0.1, "offset_v": 0},
     "scope": {"input_channel": 1, "output_channel": 2, "probe_attenuation": 1,
               "coupling": "AC", "cycles": 5,                   # the rest is optional
               "memory_depth": 100000, "bandwidth_limit_hz": 0,
               "input_volts_per_div": 0.01, "output_volts_per_div": 0.01},
     "settle_s": 0.5, "capture_wait_s": 0.3, "averages": 1,
     "loop": true, "phase_offset_deg": 0,
     "limits": {"min_phase_margin_deg": 45, "min_gain_margin_db": 6},
     "safety": {"max_amplitude_vpp": 1},
     "confirm_setup": true}

The generator (role ``generator``) feeds the circuit with a sine; channel ``input_channel`` of the
oscilloscope (role ``oscilloscope``) looks at what goes in, ``output_channel`` at what comes out. At
every frequency the generator is set, the scope is set to show ``cycles`` periods, both channels are
read from the **same capture**, and a sine of the known frequency is fitted to each (least squares:
``ola.spectrum.fit_sine``): the gain is the ratio of the amplitudes, the phase the difference of the
phases. The fit gives the gain and the phase even with a lot of noise, and the part of the signal
that is not the sine (noise and distortion) is reported. The vertical scales are **adjusted by
themselves** at every frequency (the output of a circuit changes by decades), starting from the last
one: a trace that clips the screen or fills too little of it is captured again.

The phase is made continuous along the frequency (``phase_deg`` has no jumps of 360 degrees); the
first point is taken in -180 to 180 degrees, or near ``phase_start_deg``, and ``phase_offset_deg``
is added (180 for a loop measured with an inverting injection).

Results: the curve ``H`` (complex: gain and phase, shown as a Bode plot), ``gain_db`` and
``phase_deg``, the table ``sweep`` (one row per frequency) and one row in ``points``: the gain at
the lowest frequency, the peak and the **peaking**, the **-3 dB bandwidth** (from the
lowest-frequency gain), and with ``loop`` the **crossover frequency** (where the gain falls through
0 dB), the **phase margin** (180 degrees plus the phase there), the frequency where the phase
reaches -180 degrees and the **gain margin** there, and a verdict against ``limits``. Crossings are
found by interpolating in the logarithm of the frequency. The generator is switched off at the end,
also after an error or a stop, and ``safety.max_amplitude_vpp`` refuses a larger amplitude before
anything is switched on."""

import math
from typing import Any, Dict, List, Sequence, Tuple

from ola import rf, spectrum
from ola.efficiency_spec import Problem
from ola.measurement import Measurement, MeasurementContext, Stopped
from ola.run_view import format_si
from ola.vna_common import check_asset, check_sweep, is_number, sweep_frequencies

COUPLINGS = ("AC", "DC")
LIMIT_KEYS = ("min_phase_margin_deg", "min_gain_margin_db", "min_bandwidth_hz", "max_peaking_db")
FILL = 0.6  # the peak should fill this fraction of the half screen (4 divisions)
TOO_SMALL = 0.15  # below this fraction of the half screen the trace is captured again
TRIES = 6
CLIP_FACTOR = 5.0  # a clipped trace: the scale goes up by this much (the amplitude is not known)
MIN_SAMPLES_PER_CYCLE = 8
NOISY_PCT = 10.0  # what the sine does not explain, in percent of the signal, above which we warn
DEFAULT_CYCLES = 5
MAX_POINTS = 2000
AC_COUPLING_CORNER_HZ = 20.0


def default_params() -> Dict[str, Any]:
    """The starting parameters of a new Bode plot (used by the editor)."""
    return {
        "device": {"label": ""},
        "sweep": {"start_hz": 100, "stop_hz": 1e6, "points": 41, "scale": "log"},
        "source": {"channel": 1, "amplitude_vpp": 0.1, "offset_v": 0},
        "scope": {
            "input_channel": 1, "output_channel": 2, "probe_attenuation": 1,
            "coupling": "AC", "cycles": DEFAULT_CYCLES,
        },  # fmt: skip
        "settle_s": 0.5,
        "capture_wait_s": 0.3,
        "averages": 1,
        "loop": False,
        "confirm_setup": True,
    }


# ----- checking the parameters ----------------------------------------------------------------
def _int(spec: Dict[str, Any], key: str, path: str, low: int, high: int, out: List[Problem]):
    if key in spec:
        v = spec[key]
        if not isinstance(v, int) or isinstance(v, bool) or not low <= v <= high:
            out.append(Problem(f"{path}.{key}", f"must be a whole number from {low} to {high}"))


def _positive(spec: Dict[str, Any], key: str, path: str, unit: str, out: List[Problem], zero=False):
    if key in spec and (not is_number(spec[key]) or spec[key] < 0 or (spec[key] == 0 and not zero)):
        what = "0 or more" if zero else "above 0"
        out.append(Problem(f"{path}.{key}" if path else key, f"must be a number ({unit}) {what}"))


def check_params(params: Dict[str, Any]) -> List[Problem]:
    """Everything wrong with the parameters, each with the path of the field. Does no I/O."""
    out: List[Problem] = []
    start, stop = check_sweep(params, out)
    sweep = params.get("sweep") or {}
    if isinstance(sweep, dict) and is_number(sweep.get("points")) and sweep["points"] > MAX_POINTS:
        out.append(Problem("sweep.points", f"at most {MAX_POINTS} frequencies"))
    device = params.get("device", {})
    if not isinstance(device, dict):
        out.append(Problem("device", "must be an object with a 'label'"))
    elif "label" in device and not isinstance(device["label"], str):
        out.append(Problem("device.label", "the label must be text"))
    check_asset(params, "device", out)
    source = params.get("source")
    if not isinstance(source, dict):
        out.append(Problem("source", "the generator settings are missing"))
    else:
        _int(source, "channel", "source", 1, 16, out)
        _positive(source, "amplitude_vpp", "source", "Vpp", out)
        if "offset_v" in source and not is_number(source["offset_v"]):
            out.append(Problem("source.offset_v", "the offset must be a number (V)"))
    scope = params.get("scope")
    if not isinstance(scope, dict):
        out.append(Problem("scope", "the oscilloscope settings are missing"))
    else:
        _int(scope, "input_channel", "scope", 1, 16, out)
        _int(scope, "output_channel", "scope", 1, 16, out)
        same = scope.get("input_channel", 1) == scope.get("output_channel", 2)
        if same:
            out.append(Problem("scope.output_channel", "must be another channel than the input"))
        if "coupling" in scope and scope["coupling"] not in COUPLINGS:
            out.append(Problem("scope.coupling", f"must be one of {', '.join(COUPLINGS)}"))
        elif (
            scope.get("coupling", "AC") == "AC"
            and start is not None
            and start < AC_COUPLING_CORNER_HZ
        ):
            out.append(
                Problem(
                    "scope.coupling",
                    f"AC coupling adds phase lead below about {AC_COUPLING_CORNER_HZ:g} Hz: use DC "
                    "coupling for a sweep that starts so low",
                    "warning",
                )
            )
        _positive(scope, "probe_attenuation", "scope", "ratio, 10 = 10:1", out)
        _positive(scope, "bandwidth_limit_hz", "scope", "Hz", out, zero=True)
        _positive(scope, "input_volts_per_div", "scope", "V", out)
        _positive(scope, "output_volts_per_div", "scope", "V", out)
        _int(scope, "cycles", "scope", 2, 200, out)
        _int(scope, "memory_depth", "scope", 1, 10**9, out)
    _positive(params, "settle_s", "", "s", out, zero=True)
    _positive(params, "capture_wait_s", "", "s", out, zero=True)
    averages = params.get("averages", 1)
    if not isinstance(averages, int) or isinstance(averages, bool) or not 1 <= averages <= 100:
        out.append(Problem("averages", "must be a whole number from 1 to 100"))
    for key in ("phase_offset_deg", "phase_start_deg"):
        if key in params and not is_number(params[key]):
            out.append(Problem(key, "must be a number (degrees)"))
    for key in ("loop", "confirm_setup"):
        if key in params and not isinstance(params[key], bool):
            out.append(Problem(key, "must be true or false"))
    limits = params.get("limits")
    if limits is not None:
        if not isinstance(limits, dict):
            out.append(Problem("limits", 'must be an object like {"min_phase_margin_deg": 45}'))
        else:
            for key, value in limits.items():
                if key not in LIMIT_KEYS:
                    out.append(
                        Problem("limits", f"unknown limit {key!r}: use {', '.join(LIMIT_KEYS)}")
                    )
                elif not is_number(value):
                    out.append(Problem("limits", f"{key} must be a number"))
            if any(
                k in limits for k in ("min_phase_margin_deg", "min_gain_margin_db")
            ) and not params.get("loop"):
                out.append(
                    Problem(
                        "limits",
                        "the phase and gain margins are found with 'loop': true",
                        "warning",
                    )
                )
    safety = params.get("safety")
    if safety is not None:
        if not isinstance(safety, dict) or set(safety) - {"max_amplitude_vpp"}:
            out.append(Problem("safety", "must be an object: max_amplitude_vpp"))
        elif "max_amplitude_vpp" in safety:
            cap = safety["max_amplitude_vpp"]
            amplitude = (params.get("source") or {}).get("amplitude_vpp", 0.1)
            if not is_number(cap) or cap <= 0:
                out.append(Problem("safety.max_amplitude_vpp", "must be a number of Vpp above 0"))
            elif is_number(amplitude) and amplitude > cap:
                out.append(
                    Problem(
                        "safety.max_amplitude_vpp",
                        f"the generator is set to {amplitude:g} Vpp, above the limit "
                        f"of {cap:g} Vpp",
                    )
                )
    return out


# ----- the numbers ----------------------------------------------------------------------------
def snap_up(value: float) -> float:
    """The next value of the 1-2-5 sequence at or above ``value`` (a vertical scale)."""
    if value <= 0:
        return 1e-3
    decade = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if value <= step * decade * (1 + 1e-9):
            return step * decade
    return 10 * decade


def wrap_deg(angle: float) -> float:
    """An angle in degrees brought to -180 .. 180."""
    a = (angle + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 and angle > 0 else a


def unwrap_deg(phases: Sequence[float], start_deg: float = 0.0) -> List[float]:
    """Phases in degrees made continuous along the frequency: no step above 180 degrees between
    neighbours, and the first one within 180 degrees of ``start_deg``."""
    out: List[float] = []
    for i, p in enumerate(phases):
        if i == 0:
            out.append(p + 360.0 * round((start_deg - p) / 360.0))
        else:
            out.append(p + 360.0 * round((out[-1] - p) / 360.0))
    return out


def crossings_log(freq: Sequence[float], y: Sequence[float], level: float):
    """``(frequency, "rising" | "falling")`` where ``y`` crosses ``level``, interpolating in the
    logarithm of the frequency (the right way on a Bode plot)."""
    found = rf.level_crossings([math.log10(f) for f in freq], list(y), level)
    return [(10**x, d) for x, d in found]


def figures(
    freq: Sequence[float], gain_db: Sequence[float], phase_deg: Sequence[float], loop: bool
) -> Dict[str, Any]:
    """The figures of a Bode plot. No I/O. The ``-3 dB`` bandwidth is where the gain first falls
    3 dB below the gain at the lowest frequency; with ``loop``, the crossover (the gain falls
    through 0 dB), the phase margin, the frequency where the phase reaches -180 degrees and the
    gain margin there."""
    peak = max(range(len(gain_db)), key=gain_db.__getitem__)
    out: Dict[str, Any] = {
        "points": len(freq),
        "start_hz": freq[0],
        "stop_hz": freq[-1],
        "dc_gain_db": gain_db[0],
        "peak_gain_db": gain_db[peak],
        "peak_at_hz": freq[peak],
        "peaking_db": max(0.0, gain_db[peak] - gain_db[0]),
    }
    falling = [f for f, d in crossings_log(freq, gain_db, gain_db[0] - 3.0) if d == "falling"]
    if falling:
        out["bandwidth_3db_hz"] = falling[0]
    if loop:
        zero = [f for f, d in crossings_log(freq, gain_db, 0.0) if d == "falling"]
        if zero:
            fc = zero[0]
            phase = _at(freq, phase_deg, fc)
            out["crossover_hz"] = fc
            out["phase_at_crossover_deg"] = phase
            out["phase_margin_deg"] = 180.0 + phase
        down = [f for f, d in crossings_log(freq, phase_deg, -180.0) if d == "falling"]
        if down:
            out["phase_crossover_hz"] = down[0]
            out["gain_margin_db"] = -_at(freq, gain_db, down[0])
    return out


def _at(freq: Sequence[float], y: Sequence[float], f: float) -> float:
    """``y`` at ``f``, interpolating in the logarithm of the frequency."""
    for (f0, y0), (f1, y1) in zip(zip(freq, y), zip(freq[1:], y[1:])):
        if f0 <= f <= f1:
            x = (math.log10(f) - math.log10(f0)) / (math.log10(f1) - math.log10(f0))
            return y0 + x * (y1 - y0)
    return y[-1] if f > freq[-1] else y[0]


def verdict(summary: Dict[str, Any], limits: Dict[str, float]) -> Tuple[str, List[str]]:
    """``("PASS" | "FAIL", reasons)``; a figure that was not found is a failure of its limit."""
    reasons: List[str] = []
    checks = (
        ("min_phase_margin_deg", "phase_margin_deg", "phase margin", "deg", True),
        ("min_gain_margin_db", "gain_margin_db", "gain margin", "dB", True),
        ("min_bandwidth_hz", "bandwidth_3db_hz", "bandwidth", "Hz", True),
        ("max_peaking_db", "peaking_db", "peaking", "dB", False),
    )
    for key, field, name, unit, lower in checks:
        if key not in limits:
            continue
        value = summary.get(field)
        if value is None:
            if lower:  # no crossing found: the plot never gets there: say so, it is not a pass
                reasons.append(f"no {name} was found in the sweep (limit {limits[key]:g} {unit})")
            continue
        bad = value < limits[key] if lower else value > limits[key]
        if bad:
            word = "below" if lower else "above"
            reasons.append(f"{name} {value:.3g} {unit} {word} {limits[key]:g} {unit}")
    return ("FAIL" if reasons else "PASS"), reasons


def clipped(volts: Sequence[float], scale: float, offset: float = 0.0) -> bool:
    """True if the record touches the top or the bottom of the screen (4 divisions either side of
    the centre, which is ``-offset``)."""
    top, bottom = -offset + 4 * scale, -offset - 4 * scale
    return max(volts) >= top - 1e-9 or min(volts) <= bottom + 1e-9


class Bode(Measurement):
    """Bode plot with a generator and an oscilloscope; see the module docstring."""

    def check(self) -> List[Problem]:
        """The problems of the parameters with the path of each field (for the editor)."""
        return check_params(self.params)

    def validate(self) -> List[str]:
        """The errors as readable sentences."""
        return [str(p) for p in self.check() if p.severity == "error"]

    def setup(self, ctx: MeasurementContext) -> None:
        """Nothing is switched on before the question."""
        self._on = False
        self._no_switch = False

    # ----- running ------------------------------------------------------------------------
    def run(self, ctx: MeasurementContext) -> None:
        """Ask for the connections, step through the frequencies, report."""
        p = self.params
        gen, scope = ctx.instrument("generator"), ctx.instrument("oscilloscope")
        self._no_switch = not self._has_output_switch(gen)
        if p.get("confirm_setup", True) or self._no_switch:
            self._ask_setup(ctx)  # a generator with no output switch is always asked about
        if self._no_switch:
            ctx.log(
                "this generator has no output switch: its output is on from the moment the "
                "amplitude is set and cannot be switched off by the measurement",
                "warning",
            )
        freqs = sweep_frequencies(p["sweep"])
        src, sc = p["source"], p["scope"]
        self._channels = (int(sc.get("input_channel", 1)), int(sc.get("output_channel", 2)))
        self._configure(gen, scope)
        gen.call("set_frequency", channel_number=int(src.get("channel", 1)), value=float(freqs[0]))
        if not self._no_switch:
            gen.call("set_output_state", channel_number=int(src.get("channel", 1)), state=True)
            self._on = True
        rows: List[Dict[str, Any]] = []
        wrapped: List[float] = []
        for number, f in enumerate(freqs, 1):
            ctx.checkpoint()
            gen.call("set_frequency", channel_number=int(src.get("channel", 1)), value=float(f))
            ctx.sleep(float(p.get("settle_s", 0.5)))
            point = self._measure(ctx, scope, f)
            wrapped.append(point["phase_deg"])
            rows.append(point)
            ctx.progress(number, len(freqs), f"{format_si(f, 'Hz')} ({number} of {len(freqs)})")
            self._draw(ctx, rows, wrapped)
        self._report(ctx, rows, wrapped)

    def teardown(self, ctx: MeasurementContext) -> None:
        """The generator output off, whatever happened (or, with no switch, a reminder)."""
        if getattr(self, "_no_switch", False):
            ctx.log("the generator output is still on: switch it off by hand", "warning")
        if getattr(self, "_on", False):
            try:
                ctx.instrument("generator").call(
                    "set_output_state",
                    channel_number=int(self.params["source"].get("channel", 1)),
                    state=False,
                )
            except Exception as exc:
                ctx.log(f"could not switch the generator off: {exc}", "error")

    # ----- the steps ----------------------------------------------------------------------
    @staticmethod
    def _has_output_switch(gen: Any) -> bool:
        """False for a generator model that has no command to switch its output on and off."""
        return not hasattr(gen, "supports") or gen.supports("set_output_state")

    def _ask_setup(self, ctx: MeasurementContext) -> None:
        p = self.params
        if self._no_switch:
            text = (
                "Connect the generator to the input of the circuit and to the oscilloscope "
                f"channel {p['scope'].get('input_channel', 1)}, and the output of the circuit to "
                f"channel {p['scope'].get('output_channel', 2)}. WARNING: this generator has no "
                "command to switch its output on and off, so it is on as soon as the amplitude "
                f"is set ({p['source'].get('amplitude_vpp', 0.1):g} Vpp) and stays on at the end: "
                "switch it off by hand. Continue, or abort (nothing is set)."
            )
            if ctx.ask(text, ["continue", "abort"], default="abort") == "abort":
                raise Stopped()
            return
        text = (
            "Connect the generator to the input of the circuit and to the oscilloscope channel "
            f"{p['scope'].get('input_channel', 1)}, and the output of the circuit to channel "
            f"{p['scope'].get('output_channel', 2)}. The generator is switched on by the "
            f"measurement ({p['source'].get('amplitude_vpp', 0.1):g} Vpp) and switched off at the "
            "end. Then continue."
        )
        if ctx.ask(text, ["continue", "abort"], default="abort") == "abort":
            raise Stopped()

    def _configure(self, gen: Any, scope: Any) -> None:
        p = self.params
        src, sc = p["source"], p["scope"]
        ch = int(src.get("channel", 1))

        def optional(handle: Any, name: str, **args: Any) -> None:
            if not hasattr(handle, "supports") or handle.supports(name):
                handle.call(name, **args)

        if not self._no_switch:
            gen.call("set_output_state", channel_number=ch, state=False)
        optional(gen, "set_waveform_shape", channel_number=ch, shape="SINE")
        optional(gen, "set_offset", channel_number=ch, value=float(src.get("offset_v", 0)))
        gen.call("set_amplitude", channel_number=ch, value=float(src.get("amplitude_vpp", 0.1)))
        self._scale = {}
        first = snap_up(float(src.get("amplitude_vpp", 0.1)) / 2 / (FILL * 4))
        for key, number in zip(("input", "output"), self._channels):
            scope.call("set_channel_state", channel_number=number, state=True)
            scope.call(
                "set_probe_attenuation", channel_number=number,
                value=float(sc.get("probe_attenuation", 1)),
            )  # fmt: skip
            scope.call(
                "set_channel_coupling", channel_number=number,
                coupling_type=sc.get("coupling", "AC"),
            )  # fmt: skip
            if "bandwidth_limit_hz" in sc:
                scope.call(
                    "set_channel_bandwidth_limit", channel_number=number,
                    bandwidth=float(sc["bandwidth_limit_hz"]),
                )  # fmt: skip
            self._scale[number] = float(sc.get(f"{key}_volts_per_div", first))
            scope.call("set_channel_scale", channel_number=number, value=self._scale[number])
        if "memory_depth" in sc:
            optional(scope, "set_acquisition_depth", depth=int(sc["memory_depth"]))

    def _capture(
        self, ctx: MeasurementContext, scope: Any
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        sc = self.params["scope"]
        bits = int(sc.get("bits", 8))
        scope.call("run_acquisition")
        ctx.sleep(float(self.params.get("capture_wait_s", 0.3)))
        a = scope.read_waveform_full(self._channels[0], bits=bits, stop=True)
        b = scope.read_waveform_full(self._channels[1], bits=bits, stop=False)  # the same capture
        return a, b

    def _measure(self, ctx: MeasurementContext, scope: Any, f: float) -> Dict[str, Any]:
        p = self.params
        sc = p["scope"]
        cycles = int(sc.get("cycles", DEFAULT_CYCLES))
        scope.call("set_timebase_scale", value=cycles / f / 10.0)
        gains: List[complex] = []
        info: Dict[str, Any] = {}
        for _ in range(int(p.get("averages", 1))):
            fits, waves = self._fit_pair(ctx, scope, f)
            fi, fo = fits
            dphi = fo["phase_rad"] - fi["phase_rad"]
            ratio = fo["amplitude"] / fi["amplitude"]
            gains.append(complex(ratio * math.cos(dphi), ratio * math.sin(dphi)))
            info = {"fits": fits, "waves": waves}
        h = sum(gains) / len(gains)
        fi, fo = info["fits"]
        dt = info["waves"][0]["sample_interval"] if "sample_interval" in info["waves"][0] else 0
        row = {
            "frequency_hz": f,
            "gain_db": rf.db20(h),
            "phase_deg": math.degrees(math.atan2(h.imag, h.real)),
            "vin_peak_v": fi["amplitude"],
            "vout_peak_v": fo["amplitude"],
            "residual_in_pct": 100 * fi["residual_rms"] / (fi["amplitude"] / math.sqrt(2)),
            "residual_out_pct": 100
            * fo["residual_rms"]
            / max(fo["amplitude"] / math.sqrt(2), 1e-30),
            "input_volts_per_div": self._scale[self._channels[0]],
            "output_volts_per_div": self._scale[self._channels[1]],
            "samples": info["waves"][0]["points"],
        }
        for number, amplitude in zip(self._channels, (fi["amplitude"], fo["amplitude"])):
            self._retarget(
                scope, number, amplitude
            )  # the next frequency starts near the right scale
        if dt and dt * f > 1.0 / MIN_SAMPLES_PER_CYCLE:
            ctx.log(f"{format_si(f, 'Hz')}: fewer than {MIN_SAMPLES_PER_CYCLE} samples a cycle: "
                    "the result is not reliable, raise the memory depth", "warning")  # fmt: skip
        for side, key in (("input", "residual_in_pct"), ("output", "residual_out_pct")):
            if row[key] > NOISY_PCT:
                ctx.log(f"{format_si(f, 'Hz')}: {row[key]:.0f} % of the {side} is not a sine "
                        "(noise or distortion): the gain and the phase are less certain",
                        "warning")  # fmt: skip
        return row

    def _retarget(self, scope: Any, number: int, peak: float) -> None:
        """Set the scale of a channel for a signal whose record reaches ``peak`` volts."""
        want = snap_up(max(peak, 1e-9) / (FILL * 4))
        if want != self._scale[number]:
            self._scale[number] = want
            scope.call("set_channel_scale", channel_number=number, value=want)

    def _fit_pair(self, ctx: MeasurementContext, scope: Any, f: float):
        """Capture both channels and fit the sine; the scales are adjusted and the capture repeated
        if a trace clips the screen or fills too little of it (at most ``TRIES`` times)."""
        for attempt in range(1, TRIES + 1):
            ctx.checkpoint()
            waves = self._capture(ctx, scope)
            fits = []
            again = False
            for wave, number in zip(waves, self._channels):
                volts = list(wave["voltage"])
                dt = wave.get("sample_interval") or (wave["time"][-1] - wave["time"][0]) / (
                    len(volts) - 1
                )
                fit = spectrum.fit_sine(volts, dt, f)
                mean = sum(volts) / len(volts)
                fit["peak"] = max(
                    abs(v - mean) for v in volts
                )  # the noise has to fit the screen too
                fits.append(fit)
                scale = self._scale[number]
                new = None
                if clipped(volts, scale):
                    new = snap_up(scale * CLIP_FACTOR)
                elif fit["peak"] < TOO_SMALL * 4 * scale and attempt < TRIES:
                    new = snap_up(max(fit["peak"], 1e-9) / (FILL * 4))
                    new = new if new < scale else None
                if new is not None and new != scale and attempt < TRIES:
                    self._scale[number] = new
                    scope.call("set_channel_scale", channel_number=number, value=new)
                    again = True
                elif new is not None and clipped(volts, scale):
                    ctx.log(
                        f"{format_si(f, 'Hz')}: the trace on channel {number} still clips the "
                        "screen: use a larger scale or a smaller amplitude",
                        "warning",
                    )
            if not again:
                return fits, waves
        return fits, waves

    def _draw(self, ctx: MeasurementContext, rows: List[Dict[str, Any]], wrapped: List[float]):
        p = self.params
        offset = float(p.get("phase_offset_deg", 0))
        phase = [x + offset for x in unwrap_deg(wrapped, float(p.get("phase_start_deg", 0)))]
        freq = [r["frequency_hz"] for r in rows]
        gain = [r["gain_db"] for r in rows]
        base = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": p["sweep"].get("scale") == "log"}
        h = [
            10 ** (g / 20) * complex(math.cos(math.radians(a)), math.sin(math.radians(a)))
            for g, a in zip(gain, phase)
        ]
        ctx.emit_trace("H", freq, h, kind="complex", **base)
        ctx.emit_trace("gain_db", freq, gain, hidden=True, **dict(base, ylabel="Gain (dB)"))
        ctx.emit_trace("phase_deg", freq, phase, hidden=True, **dict(base, ylabel="Phase (deg)"))

    def _report(self, ctx: MeasurementContext, rows: List[Dict[str, Any]], wrapped: List[float]):
        p = self.params
        offset = float(p.get("phase_offset_deg", 0))
        phase = [x + offset for x in unwrap_deg(wrapped, float(p.get("phase_start_deg", 0)))]
        freq = [r["frequency_hz"] for r in rows]
        gain = [r["gain_db"] for r in rows]
        for row, ph in zip(rows, phase):
            ctx.emit_point({**row, "phase_deg": ph}, table="sweep")
        loop = bool(p.get("loop"))
        summary = {
            "device": (p.get("device") or {}).get("label", ""),
            **figures(freq, gain, phase, loop),
        }
        limits = p.get("limits") or {}
        if limits:
            summary["verdict"], reasons = verdict(summary, limits)
            for why in reasons:
                ctx.log(f"limit exceeded: {why}", "warning")
        text = f"gain {summary['dc_gain_db']:.3g} dB at {format_si(freq[0], 'Hz')}"
        if "bandwidth_3db_hz" in summary:
            text += f", -3 dB at {format_si(summary['bandwidth_3db_hz'], 'Hz')}"
        if "phase_margin_deg" in summary:
            text += (f", crossover {format_si(summary['crossover_hz'], 'Hz')}, "
                     f"phase margin {summary['phase_margin_deg']:.3g} deg")  # fmt: skip
        elif loop:
            ctx.log("the gain never falls through 0 dB in the sweep: no crossover, no phase "
                    "margin (widen the sweep)", "warning")  # fmt: skip
        ctx.log(text)
        ctx.emit_point(summary)
