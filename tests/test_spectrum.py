# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Spectrum: amplitude of a sine, peaks, noise outside the peaks, with and without numpy."""

import cmath
import math

import pytest

from ola import spectrum

DT = 1e-6


def sine(freq, amp, n=4096, dc=0.0, dt=DT):
    return [dc + amp * math.sin(2 * math.pi * freq * k * dt) for k in range(n)]


@pytest.mark.parametrize("use_numpy", [True, False])
def test_the_amplitude_and_frequency_of_a_sine(use_numpy):
    f, a = spectrum.amplitude_spectrum(sine(100e3, 0.010, dc=5.0), DT, use_numpy=use_numpy)
    ((peak_f, peak_a),) = spectrum.find_peaks(f, a, 3)
    assert peak_f == pytest.approx(100e3, rel=1e-3)
    assert peak_a == pytest.approx(0.010, rel=0.03)  # between two bins: the log parabola corrects
    assert a[0] == 0  # the DC level is removed
    assert f[-1] == pytest.approx(0.5 / DT)  # up to the Nyquist frequency


def test_a_sine_on_a_bin_has_its_exact_amplitude():
    n = 4096
    f0 = 400 / (n * DT)  # exactly bin 400
    f, a = spectrum.amplitude_spectrum(sine(f0, 0.5, n), DT)
    assert max(a) == pytest.approx(0.5, rel=1e-3)


def test_numpy_and_the_plain_transform_agree():
    x = sine(60e3, 1.0) + [0.0] * 0
    fa, a = spectrum.amplitude_spectrum(x, DT, use_numpy=True)
    fb, b = spectrum.amplitude_spectrum(x, DT, use_numpy=False)
    assert fa == pytest.approx(fb) and a == pytest.approx(b, abs=1e-9)


def test_the_plain_fft_equals_the_definition():
    values = [complex(math.sin(k), math.cos(2 * k)) for k in range(16)]
    expected = [
        sum(v * cmath.exp(-2j * math.pi * k * n / 16) for n, v in enumerate(values))
        for k in range(16)
    ]
    assert spectrum.fft(values) == pytest.approx(expected, abs=1e-9)
    with pytest.raises(ValueError, match="power of two"):
        spectrum.fft([1, 2, 3])


def test_two_components_and_the_noise_outside_them():
    x = [a + b for a, b in zip(sine(100e3, 0.010), sine(300e3, 0.004))]
    f, a = spectrum.amplitude_spectrum(x, DT)
    peaks = spectrum.find_peaks(f, a, 5)
    assert [round(p[0] / 1e3) for p in peaks] == [100, 300]  # highest first, nothing else
    assert spectrum.rms_outside(f, a, [p[0] for p in peaks]) < 0.0001  # all of it is in the peaks


def test_a_small_neighbour_of_a_peak_is_leakage_not_a_peak():
    f, a = spectrum.amplitude_spectrum(sine(100.4e3, 1.0), DT)
    assert len(spectrum.find_peaks(f, a, 5)) == 1  # the sidelobes are 30 dB down


def test_noise_outside_the_peaks_is_the_rms_of_the_noise():
    import random

    rng = random.Random(1)
    x = [s + rng.gauss(0, 0.002) for s in sine(100e3, 0.02, n=16384)]
    f, a = spectrum.amplitude_spectrum(x, DT)
    peaks = [p[0] for p in spectrum.find_peaks(f, a, 1)]
    assert spectrum.rms_outside(f, a, peaks) == pytest.approx(0.002, rel=0.15)


def test_edge_cases():
    assert spectrum.power_of_two(5000) == 4096 and spectrum.power_of_two(0) == 0
    with pytest.raises(ValueError, match="at least 8"):
        spectrum.amplitude_spectrum([1.0] * 7, DT)
    with pytest.raises(ValueError, match="above 0"):
        spectrum.amplitude_spectrum([1.0] * 64, 0)
    assert spectrum.find_peaks([0, 1, 2], [0, 0, 0]) == []
    with pytest.raises(ValueError):
        spectrum.find_peaks([0, 1], [0])
    assert spectrum.to_dbv(math.sqrt(2)) == pytest.approx(0)
    assert spectrum.to_dbv(0) < -200  # never log(0)


def test_a_long_record_is_cut_to_a_power_of_two():
    f, a = spectrum.amplitude_spectrum(sine(50e3, 1.0, n=5000), DT)
    assert len(f) == 4096 // 2 + 1
