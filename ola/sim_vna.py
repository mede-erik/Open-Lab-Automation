"""A simulated vector network analyzer with a cable, to try RF measurements without hardware.

``SimVna`` has the two logical calls the RF measurements use (``set_sweep`` and
``read_sparameter``) and a cable between its ports whose loss, length and velocity factor are
parameters. The loss follows the usual skin-effect law (grows with the square root of the frequency)
plus a term proportional to the frequency (dielectric loss)::

    vna = SimVna(length_m=1.0, loss_db_per_m_at_1ghz=0.6, velocity_factor=0.66)
    vna.call("set_sweep", start_frequency=1e6, stop_frequency=3e9, points=201)
    vna.call("read_sparameter", parameter="S21")   # {"frequency": [...], "values": [[re, im], ...]}

``termination`` says what is on the far end of the cable for S11: ``"thru"`` (connected to the
other port: only a small mismatch is seen), ``"open"`` or ``"short"`` (the signal goes to the end
and back), or ``"antenna"``: a resonant device (``antenna_f0_hz``, ``antenna_r_ohm``,
``antenna_q``) directly on port 1, as after a calibration at the port. ``noise_db`` adds a little
random error to every point; ``calls`` records what was asked.
"""

from __future__ import annotations

import cmath
import math
import random
from typing import Any, Dict, List

SPEED_OF_LIGHT = 299_792_458.0


class SimVna:
    """A VNA with a cable on its ports (see the module docstring)."""

    def __init__(
        self,
        name: str = "vna",
        length_m: float = 1.0,
        loss_db_per_m_at_1ghz: float = 0.6,
        dielectric_db_per_m_per_ghz: float = 0.05,
        velocity_factor: float = 0.66,
        mismatch: float = 0.02,
        termination: str = "thru",
        noise_db: float = 0.0,
        seed: int = 1,
        antenna_f0_hz: float = 868e6,
        antenna_r_ohm: float = 55.0,
        antenna_q: float = 12.0,
    ):
        self.name = name
        self.length_m = length_m
        self.skin, self.dielectric = loss_db_per_m_at_1ghz, dielectric_db_per_m_per_ghz
        self.velocity_factor, self.mismatch = velocity_factor, mismatch
        self.termination, self.noise_db = termination, noise_db
        self.antenna = (antenna_f0_hz, antenna_r_ohm, antenna_q)
        self.sweep: Dict[str, Any] = {}
        self.calls: List[tuple] = []
        self._random = random.Random(seed)

    # ----- the cable --------------------------------------------------------------------------
    def one_way_loss_db(self, f: float) -> float:
        """Loss of the cable for one passage at frequency ``f`` (Hz)."""
        ghz = f / 1e9
        return self.length_m * (self.skin * math.sqrt(ghz) + self.dielectric * ghz)

    def delay_s(self) -> float:
        """Delay of one passage through the cable."""
        return self.length_m / (self.velocity_factor * SPEED_OF_LIGHT)

    def transmission(self, f: float) -> complex:
        """What a cable does to a signal going through it (S21)."""
        return cmath.rect(10 ** (-self.one_way_loss_db(f) / 20), -2 * math.pi * f * self.delay_s())

    def antenna_gamma(self, f: float) -> complex:
        """Reflection coefficient of a simple resonant antenna (a series RLC): matched at its
        resonance, more and more reflective away from it; the higher ``q``, the narrower."""
        f0, r, q = self.antenna
        z = complex(r, q * r * (f / f0 - f0 / f))
        return (z - 50.0) / (z + 50.0)

    def reflection(self, f: float) -> complex:
        """What port 1 sees (S11)."""
        t = self.transmission(f)
        if self.termination == "open":
            return t * t
        if self.termination == "short":
            return -t * t
        if self.termination == "antenna":  # a resonant device on port 1 (after calibration)
            return self.antenna_gamma(f)
        # connected through: only a small mismatch at the connectors, with a ripple
        return self.mismatch * cmath.exp(-1j * 4 * math.pi * f * self.delay_s())

    # ----- the logical calls -----------------------------------------------------------------
    def call(self, name: str, **args: Any) -> Any:
        """Run a logical call (the same interface as an ``InstrumentHandle``)."""
        self.calls.append((name, dict(args)))
        if name == "set_sweep":
            return self._set_sweep(**args)
        if name == "read_sparameter":
            return self._read(args.get("parameter", "S21"))
        raise ValueError(f"{self.name}: unknown call {name!r}")

    def _set_sweep(
        self,
        start_frequency: float,
        stop_frequency: float,
        points: int,
        sweep_type: str = "linear",
        if_bandwidth: float = 1000.0,
        power: float = -10.0,
    ) -> None:
        if not 0 < start_frequency < stop_frequency:
            raise ValueError("the start frequency must be below the stop frequency")
        if points < 2:
            raise ValueError("a sweep needs at least 2 points")
        if sweep_type not in ("linear", "log"):
            raise ValueError(f"unknown sweep type {sweep_type!r}")
        self.sweep = {
            "start": start_frequency, "stop": stop_frequency, "points": points,
            "type": sweep_type, "if_bandwidth": if_bandwidth, "power": power,
        }  # fmt: skip

    def _frequencies(self) -> List[float]:
        s = self.sweep
        if not s:
            raise ValueError("no sweep has been set")
        n = s["points"]
        if s["type"] == "log":
            ratio = (s["stop"] / s["start"]) ** (1 / (n - 1))
            return [s["start"] * ratio**k for k in range(n)]
        return [s["start"] + (s["stop"] - s["start"]) * k / (n - 1) for k in range(n)]

    def _read(self, parameter: str) -> Dict[str, Any]:
        if parameter not in ("S11", "S21"):
            raise ValueError(f"this simulated VNA measures S11 and S21, not {parameter!r}")
        freq = self._frequencies()
        values = []
        for f in freq:
            v = self.transmission(f) if parameter == "S21" else self.reflection(f)
            if self.noise_db:
                v *= 10 ** (self._random.gauss(0, self.noise_db) / 20)
            values.append([v.real, v.imag])
        return {"frequency": freq, "values": values}
