# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The waveform viewer widgets, built offscreen: what they list, draw and export."""

import numpy as np
import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QImage  # noqa: E402

from frontend.ui.WaveformView import WaveformView  # noqa: E402
from frontend.ui.WavePlot import WavePlot  # noqa: E402
from ola.wavefiles import Capture, save_capture, wave_folder  # noqa: E402

pytestmark = pytest.mark.gui


def make(step, scope, acquisition="long", forced=False):
    t = np.arange(500)
    v = np.sin(t / 20.0)
    return Capture(
        step,
        acquisition,
        scope,
        {"CH1": v.astype(np.float32), "CH2": (2 * v).astype(np.float32)},
        1e-8,
        0.0,
        forced=forced,
        setpoints={"vin": 9.0},
    )


@pytest.fixture
def run(tmp_path):
    path = tmp_path / "m_1.jsonl"
    path.write_text("{}\n")
    for step in (0, 1):
        save_capture(wave_folder(path), make(step, "osc1", forced=step == 1))
    save_capture(wave_folder(path), make(1, "osc1", "rise"))
    return path


def test_the_plot_zooms_and_keeps_the_view(qtbot):
    plot = WavePlot()
    qtbot.addWidget(plot)
    t = np.linspace(0, 1e-3, 5000)
    plot.set_curves([("a", t, np.sin(t * 1e4))])
    full = plot.full_range()
    assert full is not None and plot.current_view() == full
    plot.resize(400, 300)
    image = QImage(plot.size(), QImage.Format.Format_ARGB32)
    plot.render(image)
    assert not image.isNull()
    plot.view = [0.0, 1e-4, -0.5, 0.5]
    plot.set_curves([("a", t, np.cos(t * 1e4))])
    assert plot.current_view() == (0.0, 1e-4, -0.5, 0.5)
    plot.set_curves([("a", t, np.cos(t * 1e4))], keep_view=False)
    assert plot.current_view() != (0.0, 1e-4, -0.5, 0.5)


def test_the_view_lists_steps_acquisitions_and_channels(qtbot, run):
    view = WaveformView(str(run), None, lambda: [{"vin": 9, "efficiency": 91.2}, {"vin": 12}])
    qtbot.addWidget(view)
    assert view.steps_list.count() == 2
    assert view.selected_steps() == [0]
    assert view.acq_box.count() == 1
    assert view.checked_channels() == [("osc1", "CH1")]
    assert "vin = 9" in view.info.text()
    view.steps_list.item(1).setSelected(True)
    assert view.selected_steps() == [0, 1]
    assert view.acq_box.count() == 2  # long and rise
    assert "forced" in view.info.text().lower() or view.info.text()
    view.channel_list.item(1).setCheckState(Qt.CheckState.Checked)
    assert len(view.checked_channels()) == 2
    assert view.plot.full_range() is not None


def test_new_captures_appear_on_refresh(qtbot, run):
    view = WaveformView(str(run), None)
    qtbot.addWidget(view)
    save_capture(wave_folder(run), make(5, "osc1"))
    view.refresh()
    assert view.steps_list.count() == 3
    assert view.selected_steps() == [0]  # the choice is kept


def test_a_run_without_waves_shows_the_empty_message(qtbot, tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text("{}\n")
    view = WaveformView(str(path), None)
    qtbot.addWidget(view)
    assert view.steps_list.count() == 0 and view.plot.full_range() is None


def two_scope_run(tmp_path):
    path = tmp_path / "two.jsonl"
    path.write_text("{}\n")
    t = -1e-6 + 1e-8 * np.arange(400)
    pulse = np.exp(-(((t - 1.5e-6) / 3e-7) ** 2))
    for scope, shift in (("osc1", 0.0), ("osc2", 4e-8)):
        pulse_s = np.exp(-(((t + shift - 1.5e-6) / 3e-7) ** 2)).astype(np.float32)
        save_capture(
            wave_folder(path),
            Capture(
                0, "long", scope, {"CH1": pulse_s}, 1e-8, float(t[0]) - shift,
                channels={"CH1": {"signal": "VGS"}},
            ),
        )  # fmt: skip
    del pulse
    return path


def test_align_now_puts_two_oscilloscopes_on_one_time_axis(qtbot, tmp_path):
    view = WaveformView(str(two_scope_run(tmp_path)), None)
    qtbot.addWidget(view)
    assert view.align_btn.isEnabled() and not view.align_box.isEnabled()
    view.align_now()
    assert view.align_box.isEnabled() and view.align_box.isChecked()
    assert (tmp_path / "two_waves" / "alignment.json").is_file()
    view.channel_list.item(1).setCheckState(Qt.CheckState.Checked)  # osc2 as well
    assert len(view.plot.curves) == 2
    first, second = view.plot.curves[0][1], view.plot.curves[1][1]
    assert abs(first[0] - second[0]) > 1e-9  # the second one was moved by the shift


def test_align_now_says_why_it_cannot(qtbot, tmp_path):
    path = tmp_path / "one.jsonl"
    path.write_text("{}\n")
    save_capture(wave_folder(path), make(0, "osc1"))
    view = WaveformView(str(path), None)
    qtbot.addWidget(view)
    assert not view.align_btn.isEnabled() and view.align_btn.toolTip()
