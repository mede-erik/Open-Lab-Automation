# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The editor of a pulse file: the preview of the pulse, and the limits of the load (the current
and the power) that bring the parameter changed last back within them, as the old tool did."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui import PulseLoadEditorDialog as editor_module  # noqa: E402
from frontend.ui.PulseLoadEditorDialog import PulseLoadEditorDialog  # noqa: E402
from ola.project import MeasurementFile  # noqa: E402
from ola.pulse_load import default_params  # noqa: E402
from ola.registry import default_registry  # noqa: E402

LIMITS = {"max_current": 5.0, "max_power": 100.0}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.fixture
def boxes(monkeypatch):
    """The messages of the editor, as (text, code)."""
    seen = []
    monkeypatch.setattr(
        editor_module, "show_problem",
        lambda parent, title, text, code=None, **kw: seen.append((text, code)),
    )  # fmt: skip
    return seen


def make(app, registry, tmp_path, limits=LIMITS, translator=None, **params):
    path = tmp_path / "x.pls"
    MeasurementFile(
        type="pulse_load", role_bindings={"load": ["EL1"]}, params={**default_params(), **params}
    ).save(path)
    dialog = PulseLoadEditorDialog(
        str(path), registry, "pulse_load", translator, instruments=["EL1"],
        limits=(lambda name: limits if name == "EL1" else {}),
    )  # fmt: skip
    return dialog, path


def type_in(dialog, path, text):
    dialog.rows[path].widget.setText(text)  # the widgets of the numbers are line edits


def test_the_preview_shows_the_pulse_and_follows_the_fields(app, registry, tmp_path, boxes):
    dialog, _ = make(app, registry, tmp_path)
    (label, xs, ys), = dialog.preview.curves
    assert max(ys) == pytest.approx(1.0) and min(ys) == pytest.approx(0.0)
    type_in(dialog, "amplitude_a", "3")
    assert max(dialog.preview.curves[0][2]) == pytest.approx(3.0)
    type_in(dialog, "width_us", "")  # a value that is not there: nothing is drawn
    assert dialog.preview.curves == []
    dialog.dirty = False
    dialog.close()


def test_a_current_above_the_load_is_brought_back_with_a_message(app, registry, tmp_path, boxes):
    dialog, _ = make(app, registry, tmp_path, voltage_v=0.0)
    type_in(dialog, "amplitude_a", "8")
    assert dialog.model.get("amplitude_a") == 5.0
    assert len(boxes) == 1 and boxes[0][1] == "TOOL-004" and "8" in boxes[0][0]
    dialog.dirty = False
    dialog.close()


def test_the_power_corrects_the_parameter_changed_last(app, registry, tmp_path, boxes):
    limits = {"max_current": 10.0, "max_power": 100.0}
    dialog, _ = make(app, registry, tmp_path, limits=limits, voltage_v=20.0)
    type_in(dialog, "amplitude_a", "5")  # 5 A x 20 V = 100 W peak: still at the limit
    assert dialog.model.get("amplitude_a") == 5.0 and boxes == []
    type_in(dialog, "amplitude_a", "8")  # 160 W: the amplitude is brought to the largest safe one
    assert dialog.model.get("amplitude_a") == 5.0
    assert len(boxes) == 1 and boxes[0][1] == "TOOL-008" and "100" in boxes[0][0]
    assert dialog.rows["amplitude_a"].widget.text() == "5 A"  # the field shows the corrected value
    dialog.dirty = False
    dialog.close()


def test_the_voltage_corrects_the_amplitude(app, registry, tmp_path, boxes):
    dialog, _ = make(app, registry, tmp_path, amplitude_a=5.0, voltage_v=10.0)
    type_in(dialog, "voltage_v", "40")  # 200 W: lower the current, the voltage is the circuit's
    assert dialog.model.get("amplitude_a") < 5.0 and dialog.model.get("voltage_v") == 40.0
    assert boxes and boxes[-1][1] == "TOOL-008"
    dialog.dirty = False
    dialog.close()


def test_without_the_limits_of_the_load_nothing_is_corrected(app, registry, tmp_path, boxes):
    dialog, _ = make(app, registry, tmp_path, limits={}, voltage_v=40.0)
    type_in(dialog, "amplitude_a", "50")
    assert dialog.model.get("amplitude_a") == 50 and boxes == []
    dialog.dirty = False
    dialog.close()


def test_the_edited_file_is_saved(app, registry, tmp_path, boxes):
    dialog, path = make(app, registry, tmp_path, voltage_v=12.0)
    type_in(dialog, "frequency_hz", "500")
    assert dialog.save()
    assert MeasurementFile.load(path).params["frequency_hz"] == 500
    dialog.dirty = False
    dialog.close()


@pytest.mark.parametrize("lang", ["it", "de"])
def test_nothing_is_cut_at_the_smallest_size(app, registry, tmp_path, boxes, lang):
    from frontend.core.Translator import Translator
    from tests.ui_audit import audit

    dialog, _ = make(app, registry, tmp_path, translator=Translator(default_lang=lang))
    dialog.show()
    dialog.resize(dialog.minimumSizeHint())
    for _ in range(3):
        QApplication.processEvents()
    assert audit(dialog) == []
    dialog.dirty = False
    dialog.close()
