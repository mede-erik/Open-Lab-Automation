# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A simulated bench for a Bode plot: a function generator, an oscilloscope and a circuit between.

``SimBodeLab`` is the generator, the scope and the circuit under test::

    lab = SimBodeLab(plant=second_order(dc_gain=10.0, f0_hz=2e3, q=0.8))
    lab.generator.call("set_frequency", channel_number=1, value=1000.0)
    lab.generator.call("set_amplitude", channel_number=1, value=0.1)       # Vpp
    lab.generator.call("set_output_state", channel_number=1, state=True)
    lab.scope.call("run_acquisition")
    wave_in = lab.scope.read_waveform_full(1)   # the generator's sine
    wave_out = lab.scope.read_waveform_full(2, stop=False)   # the same capture, after the circuit

The circuit is a function ``plant(f_hz) -> complex`` (the transfer function): ``second_order``,
``integrator_with_pole`` and ``delay`` build some. The scope shows the **same capture** on its two
channels (``input_channel`` is the generator, ``output_channel`` the circuit output), starts at a
random phase, and behaves like a real one where the measurement needs it: the vertical scale
decides where the screen clips (4 divisions either side of the centre) and how coarsely the 8 bit
converter resolves the signal, the timebase and the memory depth decide the sample rate, AC
coupling removes the DC level, and noise (``noise_v``) is added to both channels. ``log`` records
the calls of the three instruments in order; ``generator_on`` is the output state.
"""

from __future__ import annotations

import cmath
import math
import random
from typing import Any, Callable, Dict, List, Tuple

DIVISIONS = 10
VERTICAL_DIVISIONS = 8
Plant = Callable[[float], complex]


def second_order(dc_gain: float = 1.0, f0_hz: float = 1e3, q: float = 0.707) -> Plant:
    """``dc_gain / (1 + s / (q w0) + (s / w0)^2)``: a low-pass with a resonance of quality ``q``."""

    def h(f: float) -> complex:
        s = 1j * f / f0_hz
        return dc_gain / (1 + s / q + s * s)

    return h


def integrator_with_pole(crossover_hz: float = 1e4, pole_hz: float = 1e5, zero_hz: float = 0.0):
    """A loop-gain-like curve: an integrator that crosses 0 dB at ``crossover_hz`` (before the
    pole), a pole at ``pole_hz`` and an optional zero at ``zero_hz``."""

    def h(f: float) -> complex:
        s = 1j * f
        g = crossover_hz / s / (1 + s / pole_hz) * math.sqrt(1 + (crossover_hz / pole_hz) ** 2)
        if zero_hz:
            g *= 1 + s / zero_hz
        return g

    return h


def delay(seconds: float, gain: float = 1.0) -> Plant:
    """A pure delay with a gain: the phase falls linearly with the frequency."""
    return lambda f: gain * cmath.exp(-2j * math.pi * f * seconds)


class _Instrument:
    def __init__(self, lab: "SimBodeLab", name: str, known: Tuple[str, ...]):
        self.lab, self.name, self.known = lab, name, known
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def supports(self, name: str) -> bool:
        """True for the calls this simulated instrument knows."""
        return name in self.known

    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call (the same interface as an ``InstrumentHandle``)."""
        if name not in self.known:
            raise ValueError(f"{self.name}: unknown call {name!r}")
        self.calls.append((name, dict(args)))
        self.lab.log.append((self.name, name, dict(args)))
        return self.lab.do(self.name, name, args)


GENERATOR_CALLS = (
    "set_waveform_shape", "set_frequency", "set_amplitude", "set_offset", "set_output_state",
)  # fmt: skip
SCOPE_CALLS = (
    "set_channel_state", "set_probe_attenuation", "set_channel_coupling", "set_channel_scale",
    "set_channel_offset", "set_channel_bandwidth_limit", "set_timebase_scale",
    "set_acquisition_depth", "run_acquisition", "stop_acquisition", "query_sample_rate",
)  # fmt: skip


class SimBodeLab:
    """The generator, the scope and the circuit between them (see the module docstring)."""

    def __init__(
        self,
        plant: Plant = None,
        input_channel: int = 1,
        output_channel: int = 2,
        noise_v: float = 0.0005,
        depth: int = 5000,
        max_scope_hz: float = 100e6,
        max_generator_hz: float = 20e6,
        scope_delay_s: float = 0.0,
        seed: int = 11,
    ):
        self.plant = plant or second_order()
        self.input_channel, self.output_channel = input_channel, output_channel
        self.noise_v, self.depth = noise_v, depth
        self.max_scope_hz, self.max_generator_hz = max_scope_hz, max_generator_hz
        self.scope_delay_s = scope_delay_s  # an extra delay of the output channel (a long probe)
        self.frequency, self.amplitude_vpp, self.offset = 1000.0, 0.1, 0.0
        self.generator_on = False
        self.shape = "SINE"
        self.channels: Dict[int, Dict[str, Any]] = {}
        self.timebase = 1e-3
        self.log: List[Tuple[str, str, Dict[str, Any]]] = []
        self.captures = 0
        self._random = random.Random(seed)
        self.generator = _Instrument(self, "generator", GENERATOR_CALLS)
        self.scope = _SimScope(self, "oscilloscope", SCOPE_CALLS)

    def channel(self, number: int) -> Dict[str, Any]:
        """The settings of a scope channel (defaults like a freshly reset scope)."""
        return self.channels.setdefault(
            number, {"scale": 1.0, "offset": 0.0, "coupling": "DC", "probe": 1.0, "state": True}
        )

    def do(self, instrument: str, call: str, args: Dict[str, Any]) -> Any:
        """Run one call."""
        if instrument == "generator":
            if call == "set_frequency":
                if args["value"] > self.max_generator_hz:
                    raise ValueError(f"the generator does not go above {self.max_generator_hz} Hz")
                self.frequency = float(args["value"])
            elif call == "set_amplitude":
                self.amplitude_vpp = float(args["value"])
            elif call == "set_offset":
                self.offset = float(args["value"])
            elif call == "set_waveform_shape":
                self.shape = str(args["shape"]).upper()
            elif call == "set_output_state":
                self.generator_on = bool(args["state"])
            return None
        ch = self.channel(args["channel_number"]) if "channel_number" in args else None
        mapping = {
            "set_channel_scale": ("scale", "value"),
            "set_channel_offset": ("offset", "value"),
            "set_channel_coupling": ("coupling", "coupling_type"),
            "set_probe_attenuation": ("probe", "value"),
            "set_channel_state": ("state", "state"),
            "set_channel_bandwidth_limit": ("bandwidth", "bandwidth"),
        }
        if call in mapping and ch is not None:
            ch[mapping[call][0]] = args[mapping[call][1]]
        elif call == "set_timebase_scale":
            self.timebase = float(args["value"])
        elif call == "set_acquisition_depth":
            self.depth = int(args["depth"])
        elif call == "query_sample_rate":
            return self.depth / (DIVISIONS * self.timebase)
        return None

    # ----- the signals ------------------------------------------------------------------------
    def input_amplitude(self) -> float:
        """Peak amplitude of the generator's sine (0 with the output off)."""
        return self.amplitude_vpp / 2 if self.generator_on else 0.0

    def waveform(self, number: int, capture: Dict[str, Any], bits: int) -> Dict[str, Any]:
        """The samples of one channel of the capture."""
        s = self.channel(number)
        n, dt = self.depth, DIVISIONS * self.timebase / self.depth
        f = self.frequency
        h = self.plant(f)
        if number == self.input_channel:
            amp, phase = self.input_amplitude(), 0.0
        elif number == self.output_channel:
            amp = self.input_amplitude() * abs(h)
            phase = cmath.phase(h) - 2 * math.pi * f * self.scope_delay_s
        else:
            amp, phase = 0.0, 0.0
        if f > self.max_scope_hz:  # beyond the bandwidth of the scope: nothing arrives
            amp = 0.0
        dc = self.offset * (1.0 if number == self.input_channel else abs(self.plant(1.0)))
        step = s["scale"] * VERTICAL_DIVISIONS / (1 << int(bits))
        half = s["scale"] * VERTICAL_DIVISIONS / 2
        low, high = -s["offset"] - half, -s["offset"] + half
        volts = []
        for k in range(n):
            v = amp * math.cos(2 * math.pi * f * k * dt + phase + capture["phase"])
            v += self._random.gauss(0, self.noise_v)
            if s["coupling"] != "AC":
                v += dc
            v = min(max(v, low), high)
            volts.append(round((v - low) / step) * step + low if step > 0 else v)
        return {
            "time": [k * dt for k in range(n)], "voltage": volts, "points": n,
            "sample_interval": dt, "timebase": self.timebase, "blocks": 1,
        }  # fmt: skip


class _SimScope(_Instrument):
    """The scope: ``run_acquisition`` starts a capture, ``read_waveform_full`` reads it (the first
    read stops it, the next ones with ``stop=False`` read the same capture)."""

    def __init__(self, lab: SimBodeLab, name: str, known: Tuple[str, ...]):
        super().__init__(lab, name, known)
        self._capture: Dict[str, Any] = {"phase": 0.0}

    def call(self, name: str, **args: Any) -> Any:
        """Run a call; ``run_acquisition`` makes a new capture (a new random starting phase)."""
        if name == "run_acquisition":
            self._capture = {"phase": self.lab._random.random() * 2 * math.pi}
            self.lab.captures += 1
        return super().call(name, **args)

    def read_waveform_full(self, channel_number: int, bits: int = 8, stop: bool = True) -> Any:
        """One channel of the capture, as ``read_waveform`` gives it."""
        self.lab.log.append((self.name, "read_waveform_full", {"channel_number": channel_number}))
        return self.lab.waveform(channel_number, self._capture, bits)
