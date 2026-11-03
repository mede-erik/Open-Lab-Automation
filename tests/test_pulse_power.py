import pytest

from ola.pulse_power import (
    check_pulse_power,
    max_amplitude,
    max_base_level,
    max_duty,
    pulse_powers,
)


def test_peak_and_average_power():
    peak, average = pulse_powers(amplitude=10, base_level=2, duty=25, voltage=20)
    assert peak == 200 and average == pytest.approx(20 * (2 + 8 * 0.25))


def test_average_is_exceeded_by_a_long_pulse_but_not_the_peak():
    # 20 V x 10 A = 200 W peak (limit 300 W), but 20 V x 9 A average = 180 W...
    assert check_pulse_power(10, 8, 100, 20, 300).exceeded == []
    # ...and a 150 W limit is exceeded by both
    assert check_pulse_power(10, 8, 100, 20, 150).exceeded == ["peak", "average"]
    # a short pulse over a high base: the peak is fine, the average is not
    assert check_pulse_power(10, 10, 50, 20, 150).exceeded == ["peak", "average"]
    assert check_pulse_power(10, 0, 10, 20, 150).exceeded == ["peak"]


def test_no_limit_means_no_check():
    assert check_pulse_power(100, 100, 100, 100, None).exceeded == []


@pytest.mark.parametrize("base,duty", [(0, 100), (0, 10), (2, 50), (5, 0), (0, 50)])
def test_max_amplitude_respects_both_limits(base, duty):
    amp = max_amplitude(base, duty, voltage=20, max_power=200)
    result = check_pulse_power(amp, base, duty, 20, 200 + 1e-9)
    assert result.exceeded == []
    assert amp <= 10 + 1e-9  # peak limit: 200 W / 20 V


def test_max_base_level_and_duty_keep_the_average_within_the_limit():
    base = max_base_level(amplitude=10, duty=50, voltage=20, max_power=150)
    assert base == pytest.approx(5.0)
    assert check_pulse_power(10, base, 50, 20, 150 + 1e-9).average == pytest.approx(150)
    duty = max_duty(amplitude=10, base_level=2, voltage=20, max_power=150)
    assert duty == pytest.approx((7.5 - 2) / 8 * 100)
    assert max_duty(5, 5, 20, 150) == 100.0
