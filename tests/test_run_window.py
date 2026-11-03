"""Tests of the run window with the simulated lab (no screen needed, see conftest.py)."""

import glob
import json
import os
import re
import time

import pytest

pytest.importorskip("PyQt6")

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
    used |= {f"run_q_{k}_title" for k in ("verify", "outputs_on", "generic")}
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
