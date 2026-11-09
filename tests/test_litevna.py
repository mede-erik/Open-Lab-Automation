# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import os

import pytest

from ola.call_errors import (
    CallNotSupportedError,
    InvalidArgumentError,
    ValueNotHandledError,
)
from ola.call_planner import plan_call
from ola.drivers import driver_for
from ola.drivers.litevna import LiteVnaDriver
from ola.instrument import Instrument
from ola.instrument_handle import InstrumentHandle
from ola.library import Library
from tests.litevna_sim import SimLiteVna
from ola.tester import make_handle

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = [
    os.path.join(HERE, "Instruments_LIB", "instruments_lib.json"),
    os.path.join(os.path.dirname(HERE), "Instruments_LIB", "instruments_lib.json"),
]
LIB = next((p for p in CANDIDATES if os.path.isfile(p)), None)
needs_library = pytest.mark.skipif(
    LIB is None or "calibration_begin" not in (open(LIB).read() if LIB else ""),
    reason="library with the VNA category not available",
)


def driver(sim=None):
    sim = sim or SimLiteVna()
    return LiteVnaDriver(sim), sim


def test_identification():
    d, _ = driver()
    assert d.call("identification_query", {}) == "Zenko,LiteVNA,0,hardware 7 firmware 1.5"
    with pytest.raises(Exception):
        LiteVnaDriver(SimLiteVna(variant=0x05)).call("identification_query", {})


def test_sweep_registers_are_start_step_points():
    d, sim = driver()
    d.call("set_frequency_sweep", {"start_frequency": 1e6, "stop_frequency": 1.1e6, "points": 11})
    assert sim._value("s", 8, 0x00) == 1_000_000
    assert sim._value("s", 8, 0x10) == 10_000  # (stop - start) / (points - 1)
    assert sim._value("p", 2, 0x20) == 11
    for bad in (
        {"start_frequency": 2e6, "stop_frequency": 1e6, "points": 5},
        {"start_frequency": 1e6, "stop_frequency": 2e6, "points": 70000},
        {"start_frequency": 1e6, "stop_frequency": 1e6 + 1, "points": 50},
    ):
        with pytest.raises(InvalidArgumentError):
            d.call("set_frequency_sweep", bad)


def test_channel_select_and_unhandled_parameters():
    d, sim = driver()
    sim.e00, sim.e11, sim.t = 0j, 0j, 1 + 0j
    d.call("set_frequency_sweep", {"start_frequency": 1e6, "stop_frequency": 2e6, "points": 3})
    for chosen, code in ((["S11"], 1), (["S21"], 2), (["S21", "S11"], 0)):
        d.call("read_sparameters", {"sparameters": chosen})
        assert sim.regs[0x44] == code
    for bad in (["S12"], ["S11", "S22"]):
        with pytest.raises(ValueNotHandledError):
            d.call("read_sparameters", {"sparameters": bad})


def test_read_sparameters_divides_by_the_reference_whatever_the_phase():
    d, sim = driver()
    sim.connect(lambda f: 0.5)  # a constant reflection coefficient, ideal analyzer
    sim.e00, sim.e11, sim.t = 0j, 0j, 1 + 0j
    d.call("set_frequency_sweep", {"start_frequency": 1e6, "stop_frequency": 1.4e6, "points": 5})
    d.call("run_sweep", {})
    result = d.call("read_sparameters", {"sparameters": ["S11"]})
    assert list(result["frequency"]) == [1e6, 1.1e6, 1.2e6, 1.3e6, 1.4e6]
    s11 = result["parameters"]["S11"]
    assert list(result["parameters"]) == ["S11"] and result["calibrated"] is False
    assert all(abs(r - 0.5) < 1e-5 for r in s11["real"]) and all(
        abs(i) < 1e-5 for i in s11["imaginary"]
    )


def test_the_sweep_is_synchronised_on_index_zero():
    d, sim = driver()
    sim.start_after_clear = 3  # the FIFO starts in the middle of a sweep
    sim.e00, sim.e11, sim.t = 0j, 0j, 1 + 0j
    sim.connect(lambda f: f / 2e6)  # different value at each frequency
    d.call("set_frequency_sweep", {"start_frequency": 1e6, "stop_frequency": 1.4e6, "points": 5})
    result = d.call("read_sparameters", {"sparameters": ["S11"]})  # runs the sweep itself
    assert [round(r, 4) for r in result["parameters"]["S11"]["real"]] == [0.5, 0.55, 0.6, 0.65, 0.7]


GAMMA = lambda f: 0.3 * (1 + (f - 1e6) / 1e6) * (0.8 - 0.4j)  # noqa: E731  the "device under test"


def calibrate(d, sim):
    d.call("set_frequency_sweep", {"start_frequency": 1e6, "stop_frequency": 2e6, "points": 21})
    d.call("calibration_begin", {"kind": "ONE_PORT", "port": 1})
    for standard, gamma in (("OPEN", 1), ("SHORT", -1), ("LOAD", 0)):
        sim.connect(gamma)
        d.call("calibration_measure", {"standard": standard, "port": 1})
    d.call("calibration_apply", {})
    d.call("calibration_begin", {"kind": "TRANSMISSION_RESPONSE", "port": 1, "port2": 2})
    sim.connect_thru(1 + 0j)
    d.call("calibration_measure", {"standard": "THRU", "port": 1, "port2": 2})
    d.call("calibration_apply", {})


def test_software_calibration_recovers_the_device_under_test():
    d, sim = driver()
    calibrate(d, sim)
    sim.connect(GAMMA)
    sim.connect_thru(lambda f: 0.25 - 0.1j)
    corrected = d.call("read_sparameters", {"sparameters": ["S11", "S21"]})
    assert corrected["calibrated"] is True
    for n, f in enumerate(corrected["frequency"]):
        s11 = complex(
            corrected["parameters"]["S11"]["real"][n],
            corrected["parameters"]["S11"]["imaginary"][n],
        )
        s21 = complex(
            corrected["parameters"]["S21"]["real"][n],
            corrected["parameters"]["S21"]["imaginary"][n],
        )
        assert abs(s11 - GAMMA(f)) < 1e-4
        assert abs(s21 - (0.25 - 0.1j)) < 1e-4
    d.call("set_correction_state", {"state": False})
    raw = d.call("read_sparameters", {"sparameters": ["S11", "S21"]})
    assert raw["calibrated"] is False
    assert (
        abs(
            complex(raw["parameters"]["S11"]["real"][0], raw["parameters"]["S11"]["imaginary"][0])
            - GAMMA(1e6)
        )
        > 1e-3
    )


def test_calibration_needs_its_standards_and_the_same_sweep():
    d, sim = driver()
    d.call("set_frequency_sweep", {"start_frequency": 1e6, "stop_frequency": 2e6, "points": 5})
    with pytest.raises(InvalidArgumentError):  # begin first
        d.call("calibration_apply", {})
    d.call("calibration_begin", {"kind": "ONE_PORT", "port": 1})
    with pytest.raises(InvalidArgumentError):  # no standards yet
        d.call("calibration_apply", {})
    with pytest.raises(InvalidArgumentError):  # THRU is not a ONE_PORT standard
        d.call("calibration_measure", {"standard": "THRU", "port": 1, "port2": 2})
    with pytest.raises(ValueNotHandledError):  # one source port only, no two-port calibration
        d.call("calibration_begin", {"kind": "TWO_PORT", "port": 1, "port2": 2})
    with pytest.raises(ValueNotHandledError):
        d.call("calibration_begin", {"kind": "ONE_PORT", "port": 2})
    calibrate(d, sim)
    d.call("set_frequency_sweep", {"start_frequency": 1e6, "stop_frequency": 3e6, "points": 5})
    with pytest.raises(InvalidArgumentError):  # the correction is for another sweep
        d.call("read_sparameters", {"sparameters": ["S11"]})
    d.call("calibration_clear", {})
    assert d.call("read_sparameters", {"sparameters": ["S11"]})["calibrated"] is False


def test_sweep_must_be_defined_first_and_unknown_functions_are_refused():
    d, _ = driver()
    with pytest.raises(InvalidArgumentError):
        d.call("read_sparameters", {"sparameters": ["S11"]})
    with pytest.raises(CallNotSupportedError):
        d.call("set_source_power", {})


@needs_library
def test_the_library_models_work_through_the_handle():
    library = Library.load(LIB)
    sim = SimLiteVna()
    sim.e00, sim.e11, sim.t = 0j, 0j, 1 + 0j
    sim.connect(0.25)
    handle = make_handle(library, "VNA_Zenko_LiteVNA67", sim, "vna")
    assert handle.call("identification_query").startswith("Zenko,LiteVNA")
    handle.call("set_frequency_sweep", start_frequency=1e6, stop_frequency=2e6, points=3)
    result = handle.call("read_sparameters", sparameters=["S11"])
    assert list(result["frequency"]) == [1e6, 1.5e6, 2e6]
    # the schema rejects a wrong value before the driver; the driver rejects S12 for this model
    with pytest.raises(InvalidArgumentError):
        handle.call("read_sparameters", sparameters=["S99"])
    with pytest.raises(ValueNotHandledError):
        handle.call("read_sparameters", sparameters="S11,S12")
    with pytest.raises(ValueNotHandledError):
        handle.call("calibration_begin", kind="TWO_PORT", port=1, port2=2)
    with pytest.raises(CallNotSupportedError):
        handle.call("set_source_power", value=0)
    ref = library.find_model("VNA_Zenko_LiteVNA67")
    assert ref.model["experimental"] is True
    assert isinstance(driver_for(library, "VNA_Zenko_LiteVNA67", sim), LiteVnaDriver)
    assert driver_for(library, "OSC_Siglent_SDS824X_HD", sim) is None
    plan = plan_call(
        library,
        "VNA_Zenko_LiteVNA67",
        "set_frequency_sweep",
        {"start_frequency": 1e6, "stop_frequency": 2e6, "points": 3},
    )
    assert plan.access == "driver" and plan.driver["function"] == "set_frequency_sweep"
    assert isinstance(handle, InstrumentHandle) and isinstance(handle._instrument, Instrument)


def test_litevna_sweeps_linearly_only():
    d, _ = driver()
    d.call("set_sweep_type", {"sweep_type": "LINEAR"})
    with pytest.raises(ValueNotHandledError):
        d.call("set_sweep_type", {"sweep_type": "LOG"})
