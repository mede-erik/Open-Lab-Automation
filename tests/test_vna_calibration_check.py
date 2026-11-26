# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A software calibration is only valid for the sweep it was made for: a measurement for another
sweep stops before it starts, with the two sweeps in the message (not at the first reading, after
the questions). A measurement also says in its log when the calibration does not cover a
parameter."""

import types

import pytest

from ola import identity as ident
from ola import vna_calibration_flow as flow
from ola.library import Library
from ola.measurement import MeasurementError
from ola.project_session import ProjectSession
from ola.registry import default_registry
from ola.runner import Runner
from ola.sim_vna import SimVna
from ola.tester import make_handle
from tests.conftest import LIBRARY_PATH
from tests.litevna_sim import SimLiteVna

needs_library = pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available")

SWEEP = {"start": 1e6, "stop": 2e6, "points": 21}  # what the calibration was made for
SAME = {"start_hz": 1e6, "stop_hz": 2e6, "points": 21}
OTHER = {"start_hz": 1e6, "stop_hz": 3e6, "points": 21}


def calibrated_handle():
    """A LiteVNA simulation calibrated for SWEEP (ideal standards), with the snapshot of the
    application that the calibration dialog leaves on the connection."""
    library = Library.load(LIBRARY_PATH)
    sim = SimLiteVna()
    handle = make_handle(library, "VNA_Zenko_LiteVNA67", sim, "VNA")
    handle._instrument.identity = ident.parse_idn("Zenko,LiteVNA,SN42,1.0")
    session = flow.CalibrationSession(handle, "ONE_PORT", 1, None, SWEEP)
    session.start()
    for step, gamma in zip(session.steps, (1, -1, 0)):
        sim.connect(gamma)
        session.measure(step)
    session.finish()
    handle.set_calibration({"file": "calibrations/x.cal.json", "kind": "ONE_PORT", "sweep": SWEEP})
    return handle


@needs_library
def test_a_calibration_for_another_sweep_is_reported_with_both_sweeps():
    handle = calibrated_handle()
    assert flow.sweep_problem(handle, SAME) is None
    text = flow.sweep_problem(handle, OTHER)
    assert "calibrated for 1 MHz - 2 MHz, 21 points" in text
    assert "sweeps 1 MHz - 3 MHz, 21 points" in text
    assert "Calibrate again" in text


@needs_library
def test_nothing_is_reported_without_a_calibration_or_a_comparable_sweep():
    handle = calibrated_handle()
    assert flow.sweep_problem(handle, None) is None
    assert flow.sweep_problem(handle, {"start_hz": 1e6, "stop_hz": 3e6}) is None  # no points
    handle.set_calibration(None)  # nothing applied by the application
    assert flow.sweep_problem(handle, OTHER) is None


class OwnCalibration:
    """An analyzer that keeps its own calibration (no calibration_import): it takes another sweep
    by itself, so the application does not check it."""

    calibration = {"file": "x", "sweep": SWEEP}

    def supports(self, name):
        return name != "calibration_import"


def test_an_instrument_with_its_own_calibration_is_not_checked():
    assert flow.sweep_problem(OwnCalibration(), OTHER) is None


@needs_library
def test_the_run_stops_before_it_starts_when_the_calibration_is_for_another_sweep(tmp_path):
    handle = calibrated_handle()
    session = types.SimpleNamespace(project=types.SimpleNamespace(path=tmp_path / "p.json"))
    ProjectSession._restore_calibrations(session, [handle], {"sweep": dict(SAME)})  # fits: goes on
    with pytest.raises(MeasurementError) as caught:
        ProjectSession._restore_calibrations(session, [handle], {"sweep": dict(OTHER)})
    assert "VNA: The VNA is calibrated for 1 MHz - 2 MHz" in str(caught.value)
    assert "sweeps 1 MHz - 3 MHz" in str(caught.value)


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def cable_run(registry, uncorrected, calibrated=True, mode="transmission"):
    vna = SimVna(
        library_calls=True,
        library_extras=False,
        library_sweep_type=True,
        library_linear_only=True,
        length_m=0.5,
        calibrated=calibrated,
    )
    vna.uncorrected = uncorrected
    params = {
        "mode": mode,
        "sweep": {"start_hz": 1e6, "stop_hz": 1e9, "points": 11, "scale": "linear"},
        "confirm_setup": False,
    }
    if mode == "transmission":
        params["also_s11"] = True
    else:
        params["termination"] = "open"
    measurement = registry.create("cable", params)
    runner = Runner(measurement, {"vna": [vna]})
    runner.start()
    assert runner.join(20)
    events = runner.drain()
    logs = [e.data["message"] for e in events if e.kind == "log"]
    return logs, runner.error


def test_a_cable_between_two_ports_needs_the_thru_calibration(registry):
    logs, error = cable_run(registry, ["S21"])
    assert error is not None
    assert "S21 is not corrected" in str(error) and "thru" in str(error)
    assert "one-port" in str(error)  # it also says what to do instead


def test_the_one_port_mode_does_not_need_the_thru(registry):
    # reflection mode reads S11 only: a one-port calibration is what it needs
    logs, error = cable_run(registry, [], mode="reflection")
    assert error is None


def test_s11_not_corrected_does_not_block_the_s21_cable(registry):
    logs, error = cable_run(registry, ["S11"])
    assert error is None
    assert any("S11 not corrected" in m for m in logs)


def test_no_note_when_everything_is_corrected_and_the_old_note_when_nothing_is(registry):
    assert not any("not corrected" in m for m in cable_run(registry, [])[0])
    logs, _ = cable_run(registry, [], calibrated=False)
    assert any("not calibrated" in m for m in logs)
    assert not any("not corrected" in m for m in logs)
