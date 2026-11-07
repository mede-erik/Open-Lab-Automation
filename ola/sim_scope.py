# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A simulated oscilloscope looking at a switching supply, to try measurements without hardware.

``SimScope`` answers the logical calls of an oscilloscope that the ripple measurement uses and
returns the waveform of a supply output: a DC level, a triangular ripple at the switching frequency,
a short spike at every switching edge, and random noise::

    scope = SimScope(dc_v=5.0, ripple_pp_v=0.020, fsw_hz=500e3, noise_rms_v=0.001, spike_v=0.040)
    scope.call("set_channel_coupling", channel_number=1, coupling_type="AC")
    wave = scope.read_waveform_full(1)   # {"time": [...], "voltage": [...], "points": n, ...}

What the scope settings do, as on a real one: **AC** coupling removes the DC level; the **bandwidth
limit** (above 0) shrinks the spikes; the **vertical scale** decides how coarsely the 8 bit
converter resolves the signal (``bits`` of the read) and where the screen clips; the **timebase**
and the **memory depth** decide the sample rate. ``current_a`` (set by a ``SimLoad``) makes the
ripple grow with the load, ``ripple_per_a_v`` volts peak-to-peak per ampere. ``calls`` records
every call; ``captures`` counts the waveforms read.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Tuple

DIVISIONS = 10  # horizontal divisions of the screen
VERTICAL_DIVISIONS = 8


class SimScope:
    """An oscilloscope on a supply output (see the module docstring)."""

    def __init__(
        self,
        name: str = "scope",
        dc_v: float = 5.0,
        ripple_pp_v: float = 0.020,
        fsw_hz: float = 500e3,
        noise_rms_v: float = 0.001,
        spike_v: float = 0.0,
        ripple_per_a_v: float = 0.0,
        default_depth: int = 20000,
        max_depth: int = 1_000_000,
        seed: int = 3,
    ):
        self.name = name
        self.dc_v, self.ripple_pp_v, self.fsw_hz = dc_v, ripple_pp_v, fsw_hz
        self.noise_rms_v, self.spike_v, self.ripple_per_a_v = noise_rms_v, spike_v, ripple_per_a_v
        self.current_a = 0.0
        self.depth, self.max_depth = default_depth, max_depth
        self.settings: Dict[str, Any] = {
            "coupling": "DC", "bandwidth": 0.0, "probe": 1.0, "scale": 1.0, "offset": 0.0,
            "timebase": 1e-3,
        }  # fmt: skip
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.captures = 0
        self.running = False
        self._random = random.Random(seed)

    # ----- the logical calls ------------------------------------------------------------------
    SETTERS = {
        "set_channel_coupling": ("coupling", "coupling_type"),
        "set_channel_bandwidth_limit": ("bandwidth", "bandwidth"),
        "set_probe_attenuation": ("probe", "value"),
        "set_channel_scale": ("scale", "value"),
        "set_channel_offset": ("offset", "value"),
        "set_timebase_scale": ("timebase", "value"),
        "set_acquisition_type": ("acquisition", "acquisition_type"),
        "set_trigger_level": ("trigger_level", "value"),
        "set_trigger_slope": ("trigger_slope", "slope"),
        "set_trigger_mode": ("trigger_mode", "mode"),
        "set_trigger_source": ("trigger_source", "channel_number"),
        "set_channel_state": ("state", "state"),
    }

    def supports(self, name: str) -> bool:
        """True for the calls this simulated scope knows."""
        return name in self.SETTERS or name in (
            "set_acquisition_depth", "run_acquisition", "stop_acquisition", "query_sample_rate",
            "reset",
        )  # fmt: skip

    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call (the same interface as an ``InstrumentHandle``)."""
        self.calls.append((name, dict(args)))
        if name in self.SETTERS:
            key, arg = self.SETTERS[name]
            self.settings[key] = args[arg]
            return None
        if name == "set_acquisition_depth":
            self.depth = min(int(args["depth"]), self.max_depth)
        elif name == "run_acquisition":
            self.running = True
        elif name == "stop_acquisition":
            self.running = False
        elif name == "query_sample_rate":
            return self.sample_rate()
        elif name != "reset":
            raise ValueError(f"{self.name}: unknown call {name!r}")
        return None

    def sample_rate(self) -> float:
        """Samples per second: the memory depth spread over the ten divisions of the screen."""
        return self.depth / (DIVISIONS * self.settings["timebase"])

    # ----- the signal --------------------------------------------------------------------------
    def ripple_pp(self) -> float:
        """Peak-to-peak ripple at the present load."""
        return self.ripple_pp_v + self.ripple_per_a_v * self.current_a

    def read_waveform_full(self, channel_number: int, bits: int = 8, stop: bool = True) -> Any:
        """One capture as ``read_waveform`` gives it: ``time``, ``voltage`` and the acquisition
        values. The scope is left stopped, like the real transfer of the whole memory."""
        if stop:
            self.running = False
        self.captures += 1
        s = self.settings
        n = self.depth
        dt = 1.0 / self.sample_rate()
        phase = self._random.random()
        period = 1.0 / self.fsw_hz
        limited = s["bandwidth"] and s["bandwidth"] < 100e6
        spike = self.spike_v * (0.2 if limited else 1.0)
        half_pp = self.ripple_pp() / 2
        step = s["scale"] * VERTICAL_DIVISIONS / (1 << int(bits))
        low = -s["offset"] - s["scale"] * VERTICAL_DIVISIONS / 2
        high = -s["offset"] + s["scale"] * VERTICAL_DIVISIONS / 2
        time, volts = [], []
        for k in range(n):
            t = k * dt
            x = (t / period + phase) % 1.0
            triangle = (4 * x - 1 if x < 0.5 else 3 - 4 * x) * half_pp
            v = triangle + (spike * math.exp(-x * 60) * (1 if x < 0.1 else 0))
            v += self._random.gauss(0, self.noise_rms_v)
            if s["coupling"] != "AC":
                v += self.dc_v
            v = min(max(v, low), high)
            time.append(t)
            volts.append(round((v - low) / step) * step + low if step > 0 else v)
        return {
            "time": time, "voltage": volts, "points": n, "sample_interval": dt,
            "timebase": s["timebase"], "blocks": 1,
        }  # fmt: skip


class SimLoad:
    """An electronic load that sets the current the ``SimScope`` supply delivers."""

    def __init__(self, scope: SimScope, name: str = "load"):
        self.scope, self.name = scope, name
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.on = False

    def supports(self, name: str) -> bool:
        """True for the calls of a constant-current load used by the ripple measurement."""
        return name in ("set_mode", "set_current_level", "load_on", "load_off")

    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call; ``set_current_level`` changes the load of the supply."""
        self.calls.append((name, dict(args)))
        if name == "set_current_level":
            self.scope.current_a = args["value"] if self.on else 0.0
            self._level = args["value"]
        elif name == "load_on":
            self.on = True
            self.scope.current_a = getattr(self, "_level", 0.0)
        elif name == "load_off":
            self.on = False
            self.scope.current_a = 0.0
        elif name != "set_mode":
            raise ValueError(f"{self.name}: unknown call {name!r}")
        return None
