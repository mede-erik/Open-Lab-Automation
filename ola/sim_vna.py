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
``antenna_q``) directly on port 1, as after a calibration at the port. ``filter_type`` puts a
Butterworth filter between the ports (S21 is its response); ``attenuator_db`` (and a
``attenuator_slope_db_per_ghz``) an attenuator instead of the cable. ``noise_db`` adds a little
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
        filter_type: str = "",
        filter_f0_hz: float = 100e6,
        filter_bw_hz: float = 20e6,
        filter_order: int = 4,
        filter_loss_db: float = 0.5,
        attenuator_db: float = 0.0,
        attenuator_slope_db_per_ghz: float = 0.0,
    ):
        self.name = name
        self.length_m = length_m
        self.skin, self.dielectric = loss_db_per_m_at_1ghz, dielectric_db_per_m_per_ghz
        self.velocity_factor, self.mismatch = velocity_factor, mismatch
        self.termination, self.noise_db = termination, noise_db
        self.antenna = (antenna_f0_hz, antenna_r_ohm, antenna_q)
        self.filter = (filter_type, filter_f0_hz, filter_bw_hz, filter_order, filter_loss_db)
        self.attenuator_db, self.attenuator_slope = attenuator_db, attenuator_slope_db_per_ghz
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

    def filter_response(self, f: float) -> complex:
        """S21 of a Butterworth filter (``filter_type``: ``lowpass``, ``highpass``, ``bandpass`` or
        ``bandstop``) of the given order, with ``filter_f0_hz`` as its cut-off or centre, a
        ``filter_bw_hz`` wide pass (or stop) band for the band types, and a flat insertion loss."""
        kind, f0, bw, order, loss_db = self.filter
        if kind == "lowpass":
            s = 1j * f / f0
        elif kind == "highpass":
            s = 1 / (1j * f / f0)
        else:
            x = (f / f0 - f0 / f) * (f0 / bw)
            s = 1j * x if kind == "bandpass" else (1 / (1j * x) if x else complex(math.inf))
        h = 1.0 + 0j  # normalised Butterworth: the poles are on the unit circle
        for k in range(order):
            pole = cmath.exp(1j * math.pi * (2 * k + order + 1) / (2 * order))
            h *= -pole / (s - pole) if s != complex(math.inf) else 0
        return h * 10 ** (-loss_db / 20)

    def transmission(self, f: float) -> complex:
        """What a cable (or the filter, if there is one) does to a signal going through (S21)."""
        if self.filter[0]:
            return self.filter_response(f)
        if self.attenuator_db:  # a fixed attenuator: flat, with a slope, a very short delay
            loss = self.attenuator_db + self.attenuator_slope * f / 1e9
            return cmath.rect(10 ** (-loss / 20), -2 * math.pi * f * 0.1e-9)
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
        # like the call planner: any case, and the aliases of the schema (LIN, LOGARITHMIC)
        word = str(sweep_type).strip().upper()
        sweep_type = {"LIN": "LINEAR", "LOGARITHMIC": "LOG"}.get(word, word).lower()
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

    def s_parameter(self, parameter: str, f: float) -> complex:
        """One S-parameter at frequency ``f``. A cable or filter is reciprocal (S12 = S21); S22 is
        the small mismatch of the connectors."""
        if parameter in ("S21", "S12"):
            return self.transmission(f)
        if parameter == "S11":
            return self.reflection(f)
        return self.mismatch * cmath.exp(-1j * 4 * math.pi * f * self.delay_s())  # S22

    def _read(self, parameter: str) -> Dict[str, Any]:
        if parameter not in ("S11", "S21", "S12", "S22"):
            raise ValueError(
                f"this simulated VNA measures S11, S21, S12 and S22, not {parameter!r}"
            )
        freq = self._frequencies()
        values = []
        for f in freq:
            v = self.s_parameter(parameter, f)
            if self.noise_db:
                v *= 10 ** (self._random.gauss(0, self.noise_db) / 20)
            values.append([v.real, v.imag])
        return {"frequency": freq, "values": values}


class SimAmplifier(SimVna):
    """A VNA with an RF amplifier between its ports.

    The gain is flat around ``f0_hz`` and falls away at the edges of a band ``bw_hz`` wide (a
    Butterworth band-pass of the given ``order``). It **compresses**: the gain depends on the
    power of the source, which is what ``set_sweep(power=...)`` sets, ``gain / (1 + Pout / Psat)``
    with ``Pout`` the output power the gain would give without compression and ``p_sat_dbm`` the
    saturation; the 1 dB compression point is therefore at ``Pout = 0.259 Psat`` (see
    ``p1db_output_dbm``). The input and output mismatch (``s11_mag``, ``s22_mag``) and the reverse
    isolation (``isolation_db``) are constants with a phase that turns with the frequency."""

    def __init__(
        self,
        gain_db: float = 20.0,
        f0_hz: float = 868e6,
        bw_hz: float = 200e6,
        order: int = 2,
        s11_mag: float = 0.2,
        s22_mag: float = 0.15,
        isolation_db: float = 35.0,
        p_sat_dbm: float = 10.0,
        **kwargs: Any,
    ):
        super().__init__(
            filter_type="bandpass", filter_f0_hz=f0_hz, filter_bw_hz=bw_hz, filter_order=order,
            filter_loss_db=-gain_db, **kwargs,
        )  # fmt: skip
        self.gain_db, self.s11_mag, self.s22_mag = gain_db, s11_mag, s22_mag
        self.isolation_db, self.p_sat_dbm = isolation_db, p_sat_dbm

    @property
    def p1db_output_dbm(self) -> float:
        """Output power at the 1 dB compression point (the gain is 1 dB below its small-signal
        value): ``x = Pout_ideal / Psat = 10^0.1 - 1`` and the real output is 1 dB lower."""
        x = 10**0.1 - 1
        return self.p_sat_dbm + 10 * math.log10(x) - 1.0

    @property
    def p1db_input_dbm(self) -> float:
        """Input power at the 1 dB compression point (at the centre of the band)."""
        return self.p1db_output_dbm + 1.0 - self.gain_db

    def compression(self, f: float) -> float:
        """The factor (of the amplitude) the gain is reduced by at the present source power."""
        power = self.sweep.get("power", -30.0)
        small = abs(super().transmission(f)) ** 2
        ideal_out = 10 ** (power / 10) * small
        return math.sqrt(1.0 / (1.0 + ideal_out / 10 ** (self.p_sat_dbm / 10)))

    def transmission(self, f: float) -> complex:
        """S21: the small-signal gain of the band-pass, reduced by the compression."""
        return super().transmission(f) * self.compression(f)

    def s_parameter(self, parameter: str, f: float) -> complex:
        """One S-parameter of the amplifier at frequency ``f``."""
        if parameter == "S21":
            return self.transmission(f)
        if parameter == "S12":
            return cmath.rect(10 ** (-self.isolation_db / 20), -2 * math.pi * f * 1e-9)
        if parameter == "S11":
            return cmath.rect(self.s11_mag, -0.3 - 2 * math.pi * f * 0.2e-9)
        return cmath.rect(self.s22_mag, 0.5 - 2 * math.pi * f * 0.15e-9)
