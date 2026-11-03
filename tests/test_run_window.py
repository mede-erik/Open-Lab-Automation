"""Tests of the run window with the simulated lab (no screen needed, see conftest.py)."""

import glob
import json
import os
import re
import time

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from frontend.ui import RunWindow as run_module  # noqa: E402
from frontend.ui.RunWindow import QuestionDialog, RunWindow  # noqa: E402
from ola.demo_lab import INSTRUMENTS, DemoHandle, DemoLab, demo_params  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from ola.runner import Runner  # noqa: E402
from ola.runs import RunWriter  # noqa: E402

LANG_DIR = os.path.join(os.path.dirname(run_module.__file__), "..", "lang", "modules", "run")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make(lab=None, listeners=(), **runner_kw):
    lab = lab or DemoLab()
    m = default_registry(user_dir="/nonexistent").create("efficiency", demo_params(interval_s=0.02))
    handles = [DemoHandle(n, lab) for n in INSTRUMENTS]
    return Runner(m, {"instruments": handles}, listeners=listeners, **runner_kw), lab


def pump(app, condition, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def windows(app):
    opened = []
    yield opened
    for w in opened:
        w.runner.stop()
        w.runner.join(5)
        w._timer.stop()
        w.model.state = "finished"  # so that closing does not ask
        w.close()


def window(windows, runner, **kw):
    w = RunWindow(runner, **kw)
    windows.append(w)
    return w


# ---- translations -----------------------------------------------------------------------------
def _catalogs():
    out = {}
    for path in sorted(glob.glob(os.path.join(LANG_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            out[os.path.basename(path)[:-5]] = json.load(f)
    return out


def test_languages_have_the_same_keys_and_placeholders():
    catalogs = _catalogs()
    assert set(catalogs) >= {"en", "it", "fr", "es", "de"}
    for lang, data in catalogs.items():
        assert set(data) == set(catalogs["en"]), lang
        for key, text in data.items():
            assert text.strip(), (lang, key)
            assert set(re.findall(r"\{(\w+)\}", text)) == set(
                re.findall(r"\{(\w+)\}", catalogs["en"][key])
            ), (lang, key)


def test_every_key_used_by_the_window_exists():
    source = open(run_module.__file__, encoding="utf-8").read()
    used = set(re.findall(r'"(run_[a-z_0-9]+)"', source))
    states = ["idle", "running", "paused", "waiting", "stopping", "finished", "stopped", "failed"]
    used |= {f"run_state_{s}" for s in states}
    used |= {f"run_q_{k}_title" for k in ("verify", "outputs_on", "calibration", "generic")}
    used |= {f"run_choice_{c}" for c in ("retry", "abort", "skip", "continue")}
    assert sorted(used - set(_catalogs()["en"])) == []


# ---- a whole run ------------------------------------------------------------------------------
def test_a_run_fills_table_plot_and_log(app, windows, tmp_path):
    runner, _ = make()
    path = tmp_path / "run.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    w = window(windows, runner, run_file=str(path), auto_start=True)
    assert pump(app, lambda: w.model.finished)
    assert w.model.state == "finished"
    assert w.table.rowCount() == 9 and len(w.model.points) == 9
    assert w.table.columnCount() == len(w.model.columns) + 1
    assert w.progress.value() == 1000
    assert "9" in w.banner.text()
    assert not w.start_btn.isEnabled() and not w.stop_btn.isEnabled()
    assert w.export_btn.isEnabled()
    w.tabs.setCurrentIndex(1)
    w._plot_dirty = True
    w._tick()
    assert (w.x_box.currentData(), w.y_box.currentData()) == ("vin", "efficiency")
    assert len(w.plot.series) == 3  # one line for each iout
    from ola.measurement import Event

    w.model.apply(Event("log", {"level": "warning", "message": "careful <b>"}))
    w._update_log()
    assert "WARNING" in w.log_view.toPlainText() and "careful <b>" in w.log_view.toPlainText()


def test_pause_and_resume(app, windows):
    lab = DemoLab(delay_s=0.02)
    runner, _ = make(lab)
    w = window(windows, runner, auto_start=True)
    assert pump(app, lambda: w.model.state == "running")
    w.toggle_pause()
    assert pump(app, lambda: w.model.state == "paused")
    assert w.pause_btn.text() == w._t("run_resume")
    w.toggle_pause()
    assert pump(app, lambda: w.model.state == "running")
    w.stop()
    assert pump(app, lambda: w.model.finished)
    assert w.model.state == "stopped"


def test_cannot_start_shows_the_reason_and_sends_nothing(app, windows, monkeypatch):
    m = default_registry(user_dir="/nonexistent").create("efficiency", demo_params())
    runner = Runner(m, {})  # no instruments bound
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[2])))
    w = window(windows, runner)
    w.start()
    assert shown and "instruments" in shown[0]
    assert w.model.state == "idle" and w.start_btn.isEnabled()


# ---- pop-ups ----------------------------------------------------------------------------------
def test_a_mismatch_opens_a_popup_and_the_answer_goes_to_the_run(app, windows):
    lab = DemoLab(vin_error=0.2)
    lab.errors_left = 2  # two wrong readings, then fine
    runner, _ = make(lab)
    w = window(windows, runner, auto_start=True)
    assert pump(app, lambda: w._dialog is not None)
    dialog = w._dialog
    assert isinstance(dialog, QuestionDialog)
    assert set(dialog.buttons) == {"retry", "abort", "skip"}
    assert dialog.buttons["abort"].isDefault()  # the safe choice is the default
    assert w.model.state in ("waiting", "running")
    while not w.model.finished:  # the logger is wrong for two readings: answer every question
        if w._dialog is not None:
            w._dialog.buttons["retry"].click()
        pump(app, lambda: w.model.finished or w._dialog is not None, timeout=5)
    assert w.model.state == "finished"
    assert w.model.answers and w.model.answers[0]["choice"] == "retry"


def test_abort_in_the_popup_stops_the_run(app, windows):
    runner, lab = make(DemoLab(vin_error=0.2))
    w = window(windows, runner, auto_start=True)
    assert pump(app, lambda: w._dialog is not None)
    w._dialog.buttons["abort"].click()
    assert pump(app, lambda: w.model.finished)
    assert w.model.state == "stopped"


def test_stopping_closes_the_popup_by_itself(app, windows):
    runner, _ = make(DemoLab(vin_error=0.2))
    w = window(windows, runner, auto_start=True)
    assert pump(app, lambda: w._dialog is not None)
    w.stop()
    assert pump(app, lambda: w._dialog is None and w.model.finished)
    assert w.model.state == "stopped"


def test_the_popup_cannot_be_dismissed_without_an_answer(app):
    q = {
        "id": "q",
        "text": "Sure?",
        "choices": ["continue", "abort"],
        "default": "abort",
        "data": {},
    }
    from frontend.ui.module_translator import CatalogTranslator

    d = QuestionDialog(q, CatalogTranslator("run", lang="en"))
    d.show()
    d.reject()  # Escape
    d.close()  # the X of the window
    assert d.isVisible() and d.chosen is None
    d.close_now()
    assert not d.isVisible()


def test_closing_while_running_asks_first(app, windows, monkeypatch):
    runner, _ = make(DemoLab(delay_s=0.02))
    w = window(windows, runner, auto_start=True)
    assert pump(app, lambda: w.model.state == "running")
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    assert not w.close()
    assert not runner.stop_event.is_set()
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    assert w.close()
    assert runner.stop_event.is_set()


# ---- curves -------------------------------------------------------------------------------------
import cmath  # noqa: E402
import math  # noqa: E402

from ola.measurement import Role  # noqa: E402
from tests.measurement_helpers import Scripted  # noqa: E402

FREQ = [1e6 * 10 ** (k / 20) for k in range(0, 61)]  # 1 MHz .. 1 GHz, logarithmic


def cable_s21(loss_per_ghz_db=1.0, delay_s=5e-9):
    return [
        cmath.rect(10 ** (-loss_per_ghz_db * math.sqrt(f / 1e9) / 20), -2 * math.pi * f * delay_s)
        for f in FREQ
    ]


def trace_runner(limits=None, kind="complex"):
    """A measurement that only produces curves: S21 of a cable and S11 of an antenna."""

    def run(ctx):
        meta = {"xlabel": "Frequency", "x_unit": "Hz", "log_x": True}
        if limits:
            meta["limits"] = limits
        ctx.emit_trace("S21", FREQ, cable_s21(), kind="complex", **meta)
        s11 = [cmath.rect(0.1 + 0.8 * k / 60, -k / 8) for k in range(61)]
        ctx.emit_trace("S11", FREQ, s11, kind="complex", x_unit="Hz")
        ctx.emit_trace("temperature", FREQ, [20.0 + k / 10 for k in range(61)], x_unit="Hz")

    return Runner(Scripted(run, roles=(Role("instruments", "any", required=False),)), {})


def test_curves_appear_in_their_tab_and_switch_view(app, windows):
    runner = trace_runner()
    w = window(windows, runner, auto_start=True)
    assert pump(app, lambda: w.model.finished)
    w._tick()
    assert w.trace_list.count() == 3
    assert w.tabs.currentIndex() == 2  # a measurement of curves only: its curves are shown
    assert w.log_x_box.isChecked()  # the module asked for a logarithmic axis
    assert [w.view_box.itemData(i) for i in range(w.view_box.count())][0] == "magnitude_db"
    assert len(w.trace_plot.curves) == 3 and w.trace_plot.log_x
    # only S21 is shown: untick the others
    for i in (1, 2):
        w.trace_list.item(i).setCheckState(Qt.CheckState.Unchecked)
    assert [c[0] for c in w.trace_plot.curves] == ["S21"]
    w.view_box.setCurrentIndex(w.view_box.findData("loss_db"))
    w._draw_traces()
    assert w.trace_plot.ylabel == "Loss (dB)"
    assert all(y > 0 for y in w.trace_plot.curves[0][2])  # a loss is positive
    w.view_box.setCurrentIndex(w.view_box.findData("smith"))
    w._draw_traces()
    assert w.trace_stack.currentWidget() is w.smith and len(w.smith.curves) == 1


def test_a_real_trace_alone_has_one_view(app, windows):
    runner = trace_runner()
    w = window(windows, runner, auto_start=True)
    assert pump(app, lambda: w.model.finished)
    w._tick()
    for i in (0, 1):
        w.trace_list.item(i).setCheckState(Qt.CheckState.Unchecked)
    assert w.view_box.count() == 1 and w.view_box.itemData(0) == "value"


def test_limits_from_the_measurement_are_drawn_when_the_view_matches(app, windows):
    limits = {"view": "loss_db", "max": [[1e6, 0.5], [1e9, 1.5]]}
    w = window(windows, trace_runner(limits), auto_start=True)
    assert pump(app, lambda: w.model.finished)
    w._tick()
    assert w.trace_plot.limits == []  # the view is magnitude: not the one the limit is for
    w.view_box.setCurrentIndex(w.view_box.findData("loss_db"))
    w._draw_traces()
    assert len(w.trace_plot.limits) == 1 and w.trace_plot.limits[0][2] == [0.5, 1.5]


def test_export_of_curves(app, windows, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QFileDialog

    from ola import rf

    runner = trace_runner()
    path = tmp_path / "run.jsonl"
    runner.add_listener(RunWriter(path, RunWriter.header_for(runner)))
    w = window(windows, runner, run_file=str(path), auto_start=True)
    assert pump(app, lambda: w.model.finished)
    w._tick()
    assert w.touchstone_btn.isEnabled()
    csv_path, s2p = str(tmp_path / "s21.csv"), str(tmp_path / "cable.s2p")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (csv_path, ""))
    )
    w.trace_list.setCurrentRow(0)  # S21
    w.export_trace()
    assert open(csv_path).readline().strip() == "x,re,im,magnitude_db,phase_deg"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (s2p, "")))
    w.export_touchstone_file()
    freq, params, _ = rf.read_touchstone(s2p)
    assert len(freq) == 61 and set(params) == {"S11", "S21", "S12", "S22"}
    assert "Saved" in w.banner.text()


def test_the_smith_chart_reads_impedance_under_the_mouse(app):
    from frontend.ui.trace_plot import SmithChart

    chart = SmithChart()
    chart.set_curves([("S11", [0.0, 1 / 3], [0.0, 0.0])])
    assert "Z = 50 + j0 ohm" in chart.readout(0.01, 0.0)
    assert "Z = 100 + j0 ohm" in chart.readout(0.33, 0.0)
    assert SmithChart().readout(0, 0) is None


def test_the_trace_plot_reads_values_and_ignores_a_log_axis_with_zero(app):
    from frontend.ui.trace_plot import TracePlot

    plot = TracePlot()
    plot.set_curves([("a", [1e6, 2e6], [1.0, 2.0])], x_unit="Hz", log_x=True)
    assert plot.log_x and plot.readout(1.9e6) == ["a: 2  @ 2 MHz"]
    plot.set_curves([("a", [0.0, 2e6], [1.0, 2.0])], x_unit="Hz", log_x=True)
    assert not plot.log_x  # zero cannot be on a logarithmic axis


def test_a_cable_run_in_the_window_shows_the_loss_and_asks_about_calibration(app, windows):
    """The whole path: the cable measurement, its question pop-up, and the curves it makes."""
    from ola.registry import default_registry
    from ola.sim_vna import SimVna
    from tests.test_cable import PARAMS

    p = dict(PARAMS, confirm_setup=True, limits={"max": 3.0}, also_s11=True)
    m = default_registry(user_dir="/nonexistent").create("cable", p)
    w = window(windows, Runner(m, {"vna": [SimVna(length_m=2.0)]}), auto_start=True)
    assert pump(app, lambda: w._dialog is not None)
    from PyQt6.QtWidgets import QLabel

    labels = [lab.text() for lab in w._dialog.findChildren(QLabel)]
    assert any("calibrated" in text for text in labels)  # the question of the measurement
    assert any("Sweep:" in text and "1 MHz" in text for text in labels)  # the structured summary
    w._dialog.buttons["continue"].click()
    assert pump(app, lambda: w.model.finished)
    w._tick()
    assert w.model.state == "finished"
    shown = [c[0] for c in w.trace_plot.curves]
    assert shown == ["loss_db"]  # the raw S-parameters and the delay start hidden
    assert len(w.trace_plot.limits) == 1  # the limit of the measurement is drawn
    assert w.trace_list.count() >= 5 and w.touchstone_btn.isEnabled() is False  # no run file here
    row = w.model.points[0]
    assert row["verdict"] == "PASS" and row["cable"] == "RG58 #3"


def test_a_filter_run_shows_s21_in_db_with_its_mask(app, windows):
    """The filter's S21 is the visible curve, in dB, with the mask dashed on top of it."""
    from ola.registry import default_registry
    from ola.sim_vna import SimVna

    p = {
        "filter": {"type": "lowpass", "label": "LPF"},
        "sweep": {"start_hz": 1e6, "stop_hz": 400e6, "points": 200, "scale": "linear"},
        "limits": {"bands": [{"from": 250e6, "to": 400e6, "max": -30}]},
        "confirm_setup": False,
    }
    m = default_registry(user_dir="/nonexistent").create("filter", p)
    w = window(
        windows,
        Runner(m, {"vna": [SimVna(filter_type="lowpass", filter_f0_hz=100e6)]}),
        auto_start=True,
    )
    assert pump(app, lambda: w.model.finished)
    w._tick()
    assert w.model.state == "finished"
    assert w.view_box.currentData() == "magnitude_db"
    assert [c[0] for c in w.trace_plot.curves] == ["S21"]
    assert len(w.trace_plot.limits) == 1 and w.trace_plot.ylabel == "Magnitude (dB)"
    assert w.model.points[0]["verdict"] == "PASS" and "cutoff_hz" in w.model.points[0]


def test_frequencies_in_the_table_are_written_with_their_unit():
    from frontend.ui.RunWindow import number

    assert number(868e6, "peak_at_hz") == "868 MHz" and number(2.4e9, "f_high_hz") == "2.4 GHz"
    assert number(868e6, "vin") == "8.68e+08"  # only the columns that are frequencies
    assert number(True) == "True" and number(None) == "" and number("PASS") == "PASS"
    assert number(0.5, "loss_db") == "0.5"


def test_an_antenna_run_opens_on_the_smith_chart(app, windows):
    """The antenna measurement asks for the Smith chart: the window opens on it."""
    from ola.registry import default_registry
    from ola.sim_vna import SimVna

    p = {
        "sweep": {"start_hz": 800e6, "stop_hz": 950e6, "points": 200, "scale": "linear"},
        "confirm_setup": False,
    }
    m = default_registry(user_dir="/nonexistent").create("antenna", p)
    w = window(windows, Runner(m, {"vna": [SimVna(termination="antenna")]}), auto_start=True)
    assert pump(app, lambda: w.model.finished)
    w._tick()
    assert w.view_box.currentData() == "smith" and w.trace_stack.currentWidget() is w.smith
    assert [c[0] for c in w.smith.curves] == ["S11"] and len(w.smith.curves[0][1]) == 200
    w.view_box.setCurrentIndex(w.view_box.findData("magnitude_db"))  # the user can still change it
    w._draw_traces()
    assert w.view_box.currentData() == "magnitude_db"
