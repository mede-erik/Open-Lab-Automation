# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""What a calibration corrects (``ola.vna_coverage``) and the warnings a measurement gives when it
reads a parameter that the calibration made with the program does not correct."""

import json
import types

import pytest

from ola import vna_calibration_flow as flow
from ola import vna_coverage as cov
from ola.sim_vna import SimVna
from ola.vna_common import acquire

SWEEP = {"start_hz": 1e6, "stop_hz": 2e6, "points": 5}
ALL = ["S11", "S21", "S12", "S22"]


def test_what_each_kind_corrects():
    assert cov.levels("ONE_PORT", ALL) == {"S11": 3, "S21": 0, "S12": 0, "S22": 0}
    assert cov.levels("REFLECTION_SHORT", ALL)["S11"] == cov.NORMALIZED
    assert cov.levels("TRANSMISSION_RESPONSE", ALL, 1, 2) == {
        "S11": 0, "S21": 1, "S12": 0, "S22": 0,
    }  # fmt: skip
    assert cov.levels("TRANSMISSION_RESPONSE_BOTH", ALL, 1, 2)["S12"] == cov.NORMALIZED
    enhanced = cov.levels("ENHANCED_RESPONSE", ALL, 1, 2)
    assert (enhanced["S11"], enhanced["S21"], enhanced["S12"]) == (cov.FULL, cov.PARTIAL, cov.NONE)
    for kind in cov.TWO_PORT_KINDS:
        assert set(cov.levels(kind, ALL, 1, 2).values()) == {cov.FULL}
    # the numbers are the analyzer's: a one-port calibration of port 2 does not correct S11
    assert cov.levels("ONE_PORT", ["S11", "S22"], 2) == {"S11": 0, "S22": 3}
    # a thru from port 2 to port 1 corrects S12, not S21
    assert cov.levels("TRANSMISSION_RESPONSE", ["S21", "S12"], 2, 1) == {"S21": 0, "S12": 1}
    assert cov.levels("TWO_PORT", ["S11"], 1, None) == {"S11": 0}  # no second port given
    assert set(flow.KINDS) == set(flow.KIND_PLAN)
    for kind in flow.KINDS:  # every kind is known: it corrects something
        assert any(cov.levels(kind, ALL, 1, 2).values()), kind


def test_the_warnings():
    assert cov.problems({}, ["S11"]) == []  # nothing known about the calibration
    assert cov.problems({"kind": "ONE_PORT"}, ["S11"]) == []
    text = cov.problems({"kind": "ONE_PORT", "port": 1}, ["S11", "S21"])
    assert len(text) == 1 and text[0].startswith("S21 is not corrected")
    assert "transmission response" in text[0]
    reverse = cov.problems({"kind": "ENHANCED_RESPONSE", "port": 1, "port2": 2}, ["S12"])
    assert "two-port calibration" in reverse[0]
    weak = cov.problems({"kind": "REFLECTION_OPEN", "port": 1}, ["S11"])
    assert len(weak) == 1 and "directivity and source match" in weak[0]
    # a normalisation of the transmission is common practice for a loss: no warning
    assert cov.problems({"kind": "TRANSMISSION_RESPONSE", "port": 1, "port2": 2}, ["S21"]) == []
    assert cov.problems({"kind": "TWO_PORT", "port": 1, "port2": 2}, ALL) == []


class Ctx:
    """The part of a measurement context that ``acquire`` uses."""

    def __init__(self):
        self.messages = []

    def log(self, text, level="info"):
        self.messages.append((level, text))

    def checkpoint(self):
        pass

    def progress(self, *args):
        pass


def test_a_measurement_warns_about_a_parameter_the_calibration_does_not_correct():
    vna = SimVna()
    vna.calibration = {"kind": "ONE_PORT", "port": 1, "port2": None}
    ctx = Ctx()
    acquire(ctx, vna, SWEEP, ["S11", "S21"])
    warnings = [t for level, t in ctx.messages if level == "warning" and "not corrected" in t]
    assert len(warnings) == 1 and warnings[0].startswith("S21")
    # not repeated when the sweep is repeated (notes=False), and silent without a calibration
    again = Ctx()
    acquire(again, vna, SWEEP, ["S21"], notes=False)
    assert again.messages == []
    plain = Ctx()
    acquire(plain, SimVna(), SWEEP, ["S21"])
    assert not [m for m in plain.messages if "not corrected" in m[1]]


def test_the_kind_a_vna_holds_is_remembered_for_the_measurement(tmp_path):
    record = flow.CalibrationRecord(
        "VNA", "VNA_X", "ENHANCED_RESPONSE", 1, 2, None, ["OPEN@1"], serial_number="SN7"
    )
    project = tmp_path / "p.json"
    project.write_text(json.dumps({"project_name": "p"}), encoding="utf-8")
    path = flow.save_and_attach(record, project)

    class Handle:
        name = "VNA"
        calibration = None
        identity = types.SimpleNamespace(serial_number="SN7")

        def __init__(self, importable):
            self.importable = importable

        def supports(self, call):
            return call == "calibration_import" and self.importable

        def set_calibration(self, info):
            self.calibration = info

    own = Handle(False)  # keeps its calibration itself
    info = flow.note_kept_calibration(own, project)
    assert info["kind"] == "ENHANCED_RESPONSE" and info["port2"] == 2 and info["restored"] is False
    assert info["file"] == f"calibrations/{path.name}" and own.calibration == info
    assert flow.note_kept_calibration(own, project) is None  # already known
    assert flow.note_kept_calibration(Handle(True), project) is None  # software: it is restored
    other = Handle(False)
    other.identity = types.SimpleNamespace(serial_number="SN8")  # another apparatus
    assert flow.note_kept_calibration(other, project) is None


@pytest.mark.parametrize("kind", cov.TWO_PORT_KINDS)
def test_the_two_port_kinds_need_a_second_port(kind):
    assert cov.coverage(kind, 1, None) == {}
