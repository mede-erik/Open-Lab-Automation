# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Calibration kit with parasitics: the model of the standards and the calibration with it."""

import cmath
import math

import pytest

from ola import vna_calibration as cal
from ola.call_errors import InvalidArgumentError
from ola.drivers.litevna import LiteVnaDriver
from tests.litevna_sim import SimLiteVna

# an SMA kit like a real one: fringing capacitance of the open, inductance of the short, offsets
KIT = cal.CalKit(
    open_c0=50.0,
    open_c1=-100.0,
    open_c2=20.0,
    open_delay=30.0,
    open_loss=1.0,
    short_l0=2.0,
    short_l1=-50.0,
    short_delay=30.0,
    short_loss=1.0,
    thru_delay=60.0,
    thru_loss=1.0,
)
SWEEP = {"start_frequency": 1e6, "stop_frequency": 3.001e9, "points": 31}  # step 100 MHz
FREQ = [1e6 + i * 1e8 for i in range(31)]


def test_the_ideal_kit_is_the_ideal_standards():
    assert cal.ideal_reflection("OPEN", FREQ) == [1 + 0j] * 31
    assert cal.ideal_reflection("SHORT", FREQ) == [-1 + 0j] * 31
    assert cal.ideal_reflection("LOAD", FREQ, KIT) == [0j] * 31
    assert cal.ideal_transmission(FREQ) == [1 + 0j] * 31
    assert cal.CalKit().to_dict() == {} and cal.CalKit.from_dict({}) == cal.CalKit()


def test_open_capacitance_and_offset_delay():
    f = 1e9
    c = 50e-15
    x = 2 * math.pi * f * c * 50
    (open_only,) = cal.ideal_reflection("OPEN", [f], cal.CalKit(open_c0=50.0))
    assert open_only == pytest.approx((1 - 1j * x) / (1 + 1j * x))
    # an offset of 100 ps: a round trip of 200 ps = a phase of -2 w td, no loss
    (delayed,) = cal.ideal_reflection("OPEN", [f], cal.CalKit(open_delay=100.0))
    assert cmath.phase(delayed) == pytest.approx(-2 * 2 * math.pi * f * 100e-12)
    assert abs(delayed) == pytest.approx(1.0)
    # a loss makes the reflection smaller
    (lossy,) = cal.ideal_reflection("SHORT", [f], cal.CalKit(short_delay=100.0, short_loss=2.0))
    assert abs(lossy) < 1.0


def test_short_inductance():
    f = 1e9
    z = 1j * 2 * math.pi * f * 2e-12
    (short,) = cal.ideal_reflection("SHORT", [f], cal.CalKit(short_l0=2.0))
    assert short == pytest.approx((z - 50) / (z + 50))


def test_unknown_or_bad_values_are_refused():
    with pytest.raises(InvalidArgumentError):
        cal.CalKit.from_dict({"open_capacity": 1})
    with pytest.raises(InvalidArgumentError):
        cal.CalKit.from_dict({"open_c0": "much"})
    assert cal.CalKit.from_dict({"open_c0": "50"}).open_c0 == 50.0


def gamma(f):
    return 0.4 * (0.6 + 0.3j) * (1 + (f - 1e6) / 3e9)


def calibrated_error(kit_for_driver, standards_kit):
    """Calibrate a simulated analyzer whose standards behave like ``standards_kit``, with the
    driver told about ``kit_for_driver``; the error of the corrected S11 of a device."""
    sim = SimLiteVna()
    driver = LiteVnaDriver(sim)
    driver.call("set_frequency_sweep", SWEEP)
    if kit_for_driver is not None:
        driver.call("set_calibration_kit", {"kit": kit_for_driver.to_dict()})
    driver.call("calibration_begin", {"kind": "ONE_PORT", "port": 1})
    for standard in ("OPEN", "SHORT", "LOAD"):
        reflection = cal.ideal_reflection(standard, FREQ, standards_kit)
        sim.connect(lambda f, r=dict(zip(FREQ, reflection)): r[min(r, key=lambda k: abs(k - f))])
        driver.call("calibration_measure", {"standard": standard, "port": 1})
    driver.call("calibration_apply", {})
    sim.connect(gamma)
    read = driver.call("read_sparameters", {"sparameters": ["S11"]})
    s11 = read["parameters"]["S11"]
    return max(
        abs(complex(re, im) - gamma(f))
        for f, re, im in zip(read["frequency"], s11["real"], s11["imaginary"])
    )


def test_the_kit_removes_the_error_of_non_ideal_standards():
    assert calibrated_error(KIT, KIT) < 1e-4  # told about the real standards
    assert calibrated_error(None, KIT) > 1e-2  # ideal standards assumed: clearly wrong
    assert calibrated_error(None, cal.CalKit()) < 1e-4  # ideal kit, ideal standards
    assert calibrated_error(cal.CalKit(), KIT) > 1e-2  # an ideal kit given explicitly


def test_transmission_with_a_thru_of_known_delay():
    sim = SimLiteVna()
    driver = LiteVnaDriver(sim)
    driver.call("set_frequency_sweep", SWEEP)
    driver.call(
        "set_calibration_kit", {"kit": cal.CalKit(thru_delay=60.0, thru_loss=1.0).to_dict()}
    )
    driver.call("calibration_begin", {"kind": "TRANSMISSION_RESPONSE", "port": 1, "port2": 2})
    thru = cal.ideal_transmission(FREQ, cal.CalKit(thru_delay=60.0, thru_loss=1.0))
    sim.connect_thru(lambda f: thru[min(range(31), key=lambda i: abs(FREQ[i] - f))])
    driver.call("calibration_measure", {"standard": "THRU", "port": 1, "port2": 2})
    driver.call("calibration_apply", {})
    sim.connect_thru(0.25 - 0.1j)
    read = driver.call("read_sparameters", {"sparameters": ["S21"]})
    s21 = read["parameters"]["S21"]
    assert all(
        abs(complex(r, i) - (0.25 - 0.1j)) < 1e-4 for r, i in zip(s21["real"], s21["imaginary"])
    )
