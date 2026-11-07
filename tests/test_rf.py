# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""RF calculations, Touchstone files and the export of traces from a run."""

import cmath
import csv
import math

import pytest

from ola import rf
from ola.measurement import Event
from ola.runs import RunWriter, export_touchstone, export_trace_csv, last_traces


# ---- what the numbers mean ----------------------------------------------------------------------
def test_db_and_losses():
    assert rf.db20(1) == 0
    assert rf.db20(0.1) == pytest.approx(-20)
    assert rf.db20(0) == rf.FLOOR_DB  # no logarithm of zero, no crash
    assert rf.insertion_loss_db([0.5]) == [pytest.approx(6.0206, abs=1e-3)]
    assert rf.return_loss_db([0.1j]) == [pytest.approx(20)]


def test_vswr():
    assert rf.vswr([0]) == [1.0]
    assert rf.vswr([1 / 3]) == [pytest.approx(2.0)]
    assert rf.vswr([-1 / 3]) == [pytest.approx(2.0)]  # the sign does not matter
    assert rf.vswr([1]) == [math.inf]


def test_impedance_and_back():
    assert rf.gamma_to_z([0]) == [50]  # matched
    assert rf.gamma_to_z([1 / 3])[0] == pytest.approx(100)
    assert rf.gamma_to_z([-1])[0] == pytest.approx(0)  # a short
    assert rf.gamma_to_z([1])[0].real == math.inf  # an open
    z = [75 + 25j, 10 - 40j]
    assert rf.gamma_to_z(rf.z_to_gamma(z, 50), 50) == [pytest.approx(v) for v in z]
    assert rf.gamma_to_z([0], z0=75) == [75]


def test_phase_unwrap_removes_the_saw_tooth():
    # a pure delay: phase falls 100 degrees per point, wrapping at 180
    values = [cmath.rect(1, math.radians(-100 * i)) for i in range(8)]
    wrapped = rf.phase_deg(values, unwrap=False)
    assert min(wrapped) > -181 and max(wrapped) > 0  # jumps
    unwrapped = rf.phase_deg(values)
    assert unwrapped == [pytest.approx(-100 * i) for i in range(8)]


def test_group_delay_of_a_cable_and_velocity_factor():
    delay, length = 5e-9, 1.0  # 5 ns in 1 m
    freq = [1e6 * k for k in range(1, 21)]
    s21 = [cmath.rect(0.9, -2 * math.pi * f * delay) for f in freq]
    gd = rf.group_delay_s(freq, s21)
    assert gd == [pytest.approx(delay, rel=1e-6)] * len(freq)
    assert rf.velocity_factor(delay, length) == pytest.approx(0.667, abs=1e-3)
    with pytest.raises(rf.RfError):
        rf.group_delay_s([1e6], [1])
    with pytest.raises(rf.RfError):
        rf.velocity_factor(0, 1)


def test_value_at_and_range():
    freq, y = [1e6, 2e6, 4e6], [0.0, 1.0, 3.0]
    assert rf.value_at(freq, y, 1.5e6) == pytest.approx(0.5)
    assert rf.value_at(freq, y, 4e6) == 3.0
    assert rf.value_at(freq, y, 1e6) == 0.0
    with pytest.raises(rf.RfError, match="outside"):
        rf.value_at(freq, y, 5e6)  # nothing is invented outside the range
    with pytest.raises(rf.RfError):
        rf.value_at(freq, [1.0], 1e6)


def test_crossings_for_the_minus_3_db_points():
    freq = [1, 2, 3, 4, 5]
    y = [-10, -3, 0, -3, -10]
    assert rf.crossings(freq, y, -3) == [2, 4]
    found = rf.crossings(freq, [-10, -6, -1, -6, -10], -3)
    assert found == [pytest.approx(2.6), pytest.approx(3.4)]
    assert rf.crossings(freq, [-10] * 5, -3) == []


def test_span_text():
    assert rf.span_text([1e6, 6e9] + [2e6] * 399) == "1 MHz .. 6 GHz, 401 points"
    assert rf.span_text([]) is None


# ---- Touchstone ---------------------------------------------------------------------------------
FREQ = [1e6, 2e6, 3e6]
S11 = [0.1 + 0.05j, 0.2 - 0.1j, 0.3j]
S21 = [0.9 - 0.1j, 0.8 - 0.2j, 0.7 - 0.3j]


@pytest.mark.parametrize("fmt", ["RI", "MA", "DB"])
@pytest.mark.parametrize("unit", ["HZ", "MHZ", "GHZ"])
def test_touchstone_round_trip_two_ports(tmp_path, fmt, unit):
    path = tmp_path / "x.s2p"
    rf.write_touchstone(path, FREQ, {"S11": S11, "S21": S21}, fmt=fmt, unit=unit, comment="a cable")
    freq, params, z0 = rf.read_touchstone(path)
    assert freq == [pytest.approx(f) for f in FREQ] and z0 == 50
    assert params["S11"] == [pytest.approx(v, abs=1e-6) for v in S11]
    assert params["S21"] == [pytest.approx(v, abs=1e-6) for v in S21]
    for missing in ("S12", "S22"):  # not measured: zero (a dB file stores it as -300 dB)
        assert params[missing] == [pytest.approx(0, abs=1e-12)] * 3
    assert path.read_text().startswith("! a cable")


def test_touchstone_one_port_and_reference_impedance(tmp_path):
    path = tmp_path / "antenna.s1p"
    rf.write_touchstone(path, FREQ, {"S11": S11}, z0=75)
    freq, params, z0 = rf.read_touchstone(path)
    assert z0 == 75 and list(params) == ["S11"]
    assert params["S11"] == [pytest.approx(v) for v in S11]


def test_touchstone_header_and_defaults(tmp_path):
    path = tmp_path / "x.s1p"
    rf.write_touchstone(path, FREQ, {"S11": S11}, fmt="MA", unit="MHZ")
    assert "# MHZ S MA R 50" in path.read_text()
    # a file with no option line uses the standard defaults: GHz, magnitude/angle, 50 ohm
    plain = tmp_path / "plain.s1p"
    plain.write_text("! no option line\n1.0 0.5 90\n")
    freq, params, z0 = rf.read_touchstone(plain)
    assert freq == [1e9] and z0 == 50 and params["S11"][0] == pytest.approx(0.5j)


def test_touchstone_errors(tmp_path):
    with pytest.raises(rf.RfError, match="format"):
        rf.write_touchstone(tmp_path / "x.s1p", FREQ, {"S11": S11}, fmt="XX")
    with pytest.raises(rf.RfError, match="unit"):
        rf.write_touchstone(tmp_path / "x.s1p", FREQ, {"S11": S11}, unit="THZ")
    with pytest.raises(rf.RfError, match="S11"):
        rf.write_touchstone(tmp_path / "x.s1p", FREQ, {})
    with pytest.raises(rf.RfError):
        rf.write_touchstone(tmp_path / "x.s1p", FREQ, {"S11": S11[:2]})  # different lengths
    bad = tmp_path / "bad.s2p"
    bad.write_text("# HZ S RI R 50\n1 0 0 0 0\n")
    with pytest.raises(rf.RfError, match="fit rows"):
        rf.read_touchstone(bad)
    with pytest.raises(rf.RfError, match="only .s1p and .s2p"):
        rf.read_touchstone(tmp_path / "x.s3p")


# ---- from a run file ----------------------------------------------------------------------------
def make_run(tmp_path, repeat_s21=False):
    """A run file with S11 and S21 traces, written the way the runner writes it."""
    path = tmp_path / "run.jsonl"
    writer = RunWriter(path, {"run_id": "r", "measurement": "test"})

    def trace(name, values, kind="complex"):
        y = rf.to_pairs(values) if kind == "complex" else list(values)
        writer(Event("trace", {"name": name, "trace_kind": kind, "x": FREQ, "y": y, "meta": {}}))

    if repeat_s21:
        trace("S21", [0.1] * 3)  # an earlier sweep, replaced by the next one
    trace("S11", S11)
    trace("S21", S21)
    trace("temperature", [20.0, 21.0, 22.0], kind="real")
    writer(Event("state", {"state": "finished"}))
    return path


def test_the_latest_trace_of_each_name_is_used(tmp_path):
    path = make_run(tmp_path, repeat_s21=True)
    traces = last_traces(path)
    assert sorted(traces) == ["S11", "S21", "temperature"]
    assert rf.from_pairs(traces["S21"]["y"])[0] == pytest.approx(0.9 - 0.1j)


def test_export_a_complex_trace_to_csv(tmp_path):
    path = make_run(tmp_path)
    out = tmp_path / "s21.csv"
    assert export_trace_csv(path, out, "S21") == 3
    rows = list(csv.reader(open(out)))
    assert rows[0] == ["x", "re", "im", "magnitude_db", "phase_deg"]
    assert float(rows[1][1]) == pytest.approx(0.9) and float(rows[1][2]) == pytest.approx(-0.1)
    assert float(rows[1][3]) == pytest.approx(rf.db20(0.9 - 0.1j))
    assert float(rows[1][4]) == pytest.approx(math.degrees(cmath.phase(0.9 - 0.1j)))


def test_export_a_real_trace_to_csv(tmp_path):
    path = make_run(tmp_path)
    out = tmp_path / "t.csv"
    export_trace_csv(path, out, "temperature")
    assert list(csv.reader(open(out)))[1:] == [
        ["1000000.0", "20.0"],
        ["2000000.0", "21.0"],
        ["3000000.0", "22.0"],
    ]


def test_csv_needs_a_name_when_there_are_several_traces(tmp_path):
    path = make_run(tmp_path)
    with pytest.raises(ValueError, match="choose a name"):
        export_trace_csv(path, tmp_path / "x.csv")
    with pytest.raises(ValueError, match="no trace named"):
        export_trace_csv(path, tmp_path / "x.csv", "S99")


def test_export_touchstone_from_a_run(tmp_path):
    path = make_run(tmp_path)
    out = tmp_path / "cable.s2p"
    assert export_touchstone(path, out) == 3  # S11 and S21 found by name
    freq, params, _ = rf.read_touchstone(out)
    assert params["S21"] == [pytest.approx(v) for v in S21]
    one = tmp_path / "only21.s2p"
    export_touchstone(path, one, names={"S21": "S21"})
    assert rf.read_touchstone(one)[1]["S11"] == [0j] * 3


def test_export_touchstone_errors(tmp_path):
    path = make_run(tmp_path)
    with pytest.raises(ValueError, match="not complex"):
        export_touchstone(path, tmp_path / "x.s1p", names={"S11": "temperature"})
    empty = tmp_path / "empty.jsonl"
    RunWriter(empty, {"run_id": "e"}).close()
    with pytest.raises(ValueError, match="no S-parameter"):
        export_touchstone(empty, tmp_path / "x.s1p")


# ---- bands --------------------------------------------------------------------------------------
def test_bands_where_the_curve_is_below_a_level():
    freq = [1, 2, 3, 4, 5, 6]
    vswr = [4.0, 1.5, 1.2, 1.8, 3.0, 1.5]
    bands = rf.bands_where(freq, vswr, 2.0)
    assert bands[0] == (pytest.approx(1 + 2 / 2.5), pytest.approx(4 + 0.2 / 1.2))  # 1.8 .. 4.17
    assert bands[1] == (pytest.approx(5 + 1 / 1.5), 6)  # runs to the end of the sweep
    assert len(bands) == 2


def test_bands_where_edge_cases():
    freq = [1, 2, 3]
    assert rf.bands_where(freq, [1, 1, 1], 2) == [(1, 3)]  # all of it
    assert rf.bands_where(freq, [3, 3, 3], 2) == []  # none of it
    assert rf.bands_where(freq, [3, 1, 3], 2) == [(pytest.approx(1.5), pytest.approx(2.5))]
    assert rf.bands_where(freq, [1, 3, 1], 2, below=False) == [
        (pytest.approx(1.5), pytest.approx(2.5))
    ]
    assert rf.bands_where([3, 2, 1], [3, 1, 1], 2) == [(1, pytest.approx(2.5))]  # unsorted input
    with pytest.raises(rf.RfError):
        rf.bands_where([1, 2], [1], 2)


def test_level_crossings_have_a_direction():
    freq = [1, 2, 3, 4, 5]
    y = [-10, -1, 0, -1, -10]  # a band-pass shape
    assert rf.level_crossings(freq, y, -3) == [
        (pytest.approx(1 + 7 / 9), "rising"),
        (pytest.approx(4 + 2 / 9), "falling"),
    ]
    assert rf.level_crossings([1, 2, 3], [0, -5, -10], -3) == [(pytest.approx(1.6), "falling")]
    assert rf.level_crossings(freq, [-10] * 5, -3) == []
    unsorted = rf.level_crossings(
        [3, 1, 2], [-10, -10, 0], -3
    )  # the order of input does not matter
    assert unsorted == [(pytest.approx(1.7), "rising"), (pytest.approx(2.3), "falling")]
    with pytest.raises(rf.RfError):
        rf.level_crossings([1, 2], [1], 0)


# ---- stability of a two-port --------------------------------------------------------------------
def test_a_matched_unilateral_amplifier_is_unconditionally_stable():
    st = rf.two_port_stability([0.1], [10.0], [0.0], [0.1])  # no reverse transmission
    assert st["k"] == [1e9] and st["delta"] == [pytest.approx(0.01)]
    assert st["mu"][0] > 1 and st["mu_prime"][0] > 1


def test_k_and_mu_of_a_known_transistor():
    """A textbook case: S11 0.6 at -60 deg, S21 2 at 50, S12 0.05 at 26, S22 0.5 at -60."""
    s11, s21 = cmath.rect(0.6, math.radians(-60)), cmath.rect(2.0, math.radians(50))
    s12, s22 = cmath.rect(0.05, math.radians(26)), cmath.rect(0.5, math.radians(-60))
    st = rf.two_port_stability([s11], [s21], [s12], [s22])
    det = s11 * s22 - s12 * s21
    k = (1 - 0.36 - 0.25 + abs(det) ** 2) / (2 * 0.05 * 2.0)
    assert st["k"][0] == pytest.approx(k) and st["delta"][0] == pytest.approx(abs(det))
    assert (st["k"][0] > 1 and st["delta"][0] < 1) == (st["mu"][0] > 1)  # the two tests agree


def test_an_unstable_two_port():
    st = rf.two_port_stability([1.05], [3.0], [0.2], [1.05])  # reflective ports and feedback
    assert st["k"][0] < 1 and st["mu"][0] < 1 and st["mu_prime"][0] < 1


@pytest.mark.parametrize("k", [0.3, 0.9, 1.5, 3.0])
def test_k_and_mu_agree_on_stability_over_many_cases(k):
    """mu > 1 exactly when K > 1 and |delta| < 1: vary S12 to sweep K."""
    s11, s22, s21 = 0.5 * cmath.exp(-1j), 0.4 * cmath.exp(0.5j), 4.0
    s12 = 0.03 * k**-1  # smaller reverse transmission, larger K
    st = rf.two_port_stability([s11], [s21], [s12], [s22])
    assert (st["k"][0] > 1 and st["delta"][0] < 1) == (st["mu"][0] > 1)


def test_stability_needs_matching_lengths():
    with pytest.raises(rf.RfError):
        rf.two_port_stability([0.1], [1.0, 2.0], [0.0], [0.1])
