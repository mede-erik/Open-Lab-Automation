# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The connection-diagram window and its place in the project window (no screen needed)."""

import json
import os

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from frontend.ui import ProjectWindow as project_module  # noqa: E402
from frontend.ui import WiringDialog as dialog_module  # noqa: E402
from frontend.ui.ProjectWindow import ProjectWindow  # noqa: E402
from frontend.ui.WiringDialog import WiringDialog  # noqa: E402
from ola import wiring  # noqa: E402
from ola.project import MeasurementFile, Project  # noqa: E402
from ola.registry import default_registry  # noqa: E402

LANG_DIR = os.path.join(os.path.dirname(dialog_module.__file__), "..", "lang", "modules", "wiring")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


def diagram(registry, module="filter", params=None, names=None):
    raw = wiring.load_wiring(registry.get(module).path)
    return wiring.diagram_for(raw, params or {"filter": {"label": "SAW 868"}}, names or {})


# ---- the window --------------------------------------------------------------------------------
def test_the_window_shows_the_diagram_the_connections_and_the_notes(app, registry):
    d = WiringDialog(diagram(registry, names={"vna": ["LiteVNA"]}), None, "Filter test")
    assert "Filter test" in d.windowTitle()
    assert "How to connect" in d.connections.text()
    assert "Connect the input of the filter (SAW 868) to port 1 of the VNA." in d.connections.text()
    assert "Calibrate the VNA" in d.notes.text() and not d.notes.isHidden()
    assert d.view.drawing is d.drawing and d.view.scale() > 0
    assert d.view.sizeHint().width() > 0 and d.view.minimumHeight() > 0
    d.resize(300, 200)  # a narrow window shrinks the diagram instead of cutting it
    assert d.view.scale() <= dialog_module.PIXELS_PER_MM
    image = d.view.grab()
    assert not image.isNull() and image.width() > 0


def test_a_question_has_start_and_cancel_and_remembers_the_tick(app, registry):
    d = WiringDialog(diagram(registry), None, "x", confirm=True, show_before=True)
    assert d.start_btn.isVisibleTo(d) and d.show_before.isVisibleTo(d)
    assert d.cancel_btn.text() == "Cancel" and d.show_before.isChecked()
    d.show_before.setChecked(False)
    d.start_btn.click()
    assert d.result() == QDialog.DialogCode.Accepted and not d.show_before.isChecked()
    d = WiringDialog(diagram(registry), None, "x", confirm=True)
    d.cancel_btn.click()
    assert d.result() == QDialog.DialogCode.Rejected


def test_viewing_has_only_close(app, registry):
    d = WiringDialog(diagram(registry), None, "x")
    assert not d.start_btn.isVisibleTo(d) and not d.show_before.isVisibleTo(d)
    assert d.cancel_btn.text() == "Close"


def test_save_svg(app, registry, tmp_path):
    d = WiringDialog(diagram(registry, names={"vna": ["LiteVNA"]}), None, "x")
    path = tmp_path / "wiring.svg"
    assert d.save_svg(str(path)) and "LiteVNA" in path.read_text(encoding="utf-8")
    assert str(path) in d.status.text()
    assert not d.save_svg(str(tmp_path / "no" / "such" / "dir.svg"))
    assert "Could not save" in d.status.text()


def test_the_strings_exist_in_every_language_with_the_same_fields():
    import re

    catalogs = {}
    for lang in ("en", "it", "fr", "es", "de"):
        with open(os.path.join(LANG_DIR, f"{lang}.json"), encoding="utf-8") as f:
            catalogs[lang] = json.load(f)
    keys = set(catalogs["en"])
    for lang, cat in catalogs.items():
        assert set(cat) == keys, lang
        for key, text in cat.items():
            same = re.findall(r"\{(\w+)\}", text) == re.findall(r"\{(\w+)\}", catalogs["en"][key])
            assert same, (lang, key)
    with open(dialog_module.__file__, encoding="utf-8") as f:
        used = set(__import__("re").findall(r'"(wir_\w+)"', f.read()))
    with open(project_module.__file__, encoding="utf-8") as f:
        used |= set(__import__("re").findall(r'"(wir_\w+)"', f.read()))
    assert used <= keys, used - keys


# ---- in the project window ---------------------------------------------------------------------
@pytest.fixture
def project(tmp_path, registry):
    project = Project.new("P", tmp_path / "proj")
    ref = project.add_measurement("filter", "SAW test", registry)
    params = {
        "filter": {"type": "bandpass", "label": "SAW 868"},
        "sweep": {"start_hz": 8e8, "stop_hz": 9.4e8, "points": 101},
        "confirm_setup": False,
    }
    MeasurementFile(type="filter", role_bindings={"vna": ["lite"]}, params=params).save(
        project.directory / ref.file
    )
    ref2 = project.add_measurement("time_log", "Log", registry)  # a module without a diagram
    MeasurementFile(type="time_log", role_bindings={}, params={}).save(
        project.directory / ref2.file
    )
    project.save()
    return project


class Stub:
    """Stands for the run window: remembers that it was made."""

    made = []

    def __init__(self, *args, **kwargs):
        Stub.made.append(kwargs.get("title"))

    def setAttribute(self, *_):  # noqa: N802
        pass

    def show(self):
        pass


def window(project, registry, **kwargs):
    from ola.sim_vna import SimVna

    return ProjectWindow(
        project, connect=lambda name, cancel=None: SimVna(), registry=registry, **kwargs
    )


def select(w, name):
    for row in range(w.table.rowCount()):
        if w.table.item(row, 0).text() == name:
            w.table.selectRow(row)
            return
    raise AssertionError(name)


def test_the_session_builds_the_diagram_with_the_bound_instrument_names(app, project, registry):
    w = window(project, registry)
    d = w.session.wiring(w.session.project.measurements[0])
    assert d.node("vna").subtitle == "lite" and d.node("dut").title == "SAW 868"
    assert w.session.wiring(w.session.project.measurements[1]) is None  # time_log: none


def test_the_connections_button_shows_the_diagram_or_says_there_is_none(
    app, project, registry, monkeypatch
):
    shown, info = [], []
    monkeypatch.setattr(QDialog, "exec", lambda self: shown.append(self) or 0)
    monkeypatch.setattr(QMessageBox, "information", lambda *a: info.append(a[2]))
    w = window(project, registry)
    select(w, "SAW test")
    assert w.buttons["wir_button"].isEnabled()
    w.buttons["wir_button"].click()
    assert len(shown) == 1 and isinstance(shown[0], WiringDialog) and not info
    assert not shown[0].start_btn.isVisibleTo(shown[0])
    select(w, "Log")
    w.buttons["wir_button"].click()
    assert len(shown) == 1 and info == ["This measurement has no connection diagram."]


def test_the_diagram_is_a_question_before_the_run_when_it_is_on(
    app, project, registry, monkeypatch
):
    monkeypatch.setattr("frontend.ui.RunWindow.RunWindow", Stub)
    answers, saved = [QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted], []
    monkeypatch.setattr(QDialog, "exec", lambda self: answers.pop(0))
    w = window(project, registry, wiring_before_run=True, on_wiring_preference=saved.append)
    select(w, "SAW test")
    Stub.made.clear()
    w.run_measurement()  # Cancel: nothing starts
    assert Stub.made == [] and w.run_windows == []
    w.run_measurement()  # Start
    assert Stub.made == ["SAW test"] and saved == []


def test_the_tick_turns_the_question_off_and_tells_the_application(
    app, project, registry, monkeypatch
):
    monkeypatch.setattr("frontend.ui.RunWindow.RunWindow", Stub)
    saved = []

    def untick(self):
        self.show_before.setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", untick)
    w = window(project, registry, wiring_before_run=True, on_wiring_preference=saved.append)
    select(w, "SAW test")
    w.run_measurement()
    assert saved == [False] and w.wiring_before_run is False
    monkeypatch.setattr(QDialog, "exec", lambda self: pytest.fail("asked again"))
    w.run_measurement()  # no question any more


def test_without_the_preference_or_a_diagram_the_run_starts_at_once(
    app, project, registry, monkeypatch
):
    monkeypatch.setattr("frontend.ui.RunWindow.RunWindow", Stub)
    monkeypatch.setattr(QDialog, "exec", lambda self: pytest.fail("asked"))
    w = window(project, registry)  # off by default: the tests and scripts are not stopped
    select(w, "SAW test")
    Stub.made.clear()
    w.run_measurement()
    assert Stub.made == ["SAW test"]
    w = window(project, registry, wiring_before_run=True)
    select(w, "Log")  # on, but the module has no diagram
    w.run_measurement()
    assert Stub.made == ["SAW test", "Log"]


def test_a_broken_diagram_file_is_reported_and_does_not_block_the_run(
    app, project, registry, monkeypatch
):
    monkeypatch.setattr("frontend.ui.RunWindow.RunWindow", Stub)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warned.append(a[2]))
    monkeypatch.setattr(QDialog, "exec", lambda self: pytest.fail("asked"))
    w = window(project, registry, wiring_before_run=True)
    monkeypatch.setattr(
        w.session, "wiring", lambda *a, **k: (_ for _ in ()).throw(wiring.WiringError("bad file"))
    )
    select(w, "SAW test")
    Stub.made.clear()
    w.run_measurement()
    assert Stub.made == ["SAW test"] and "bad file" in warned[0]


def test_the_main_window_remembers_the_preference(app):
    pytest.importorskip("psycopg2")  # the main window needs the database layer
    from frontend.ui.main_window import MainWindow

    from PyQt6.QtCore import QSettings

    settings = QSettings("LabAutomation", "App")
    before = settings.value("show_wiring_before_run")
    try:
        MainWindow._save_wiring_preference(False)
        assert MainWindow._wiring_preference() is False
        MainWindow._save_wiring_preference(True)
        assert MainWindow._wiring_preference() is True
    finally:
        if before is None:
            settings.remove("show_wiring_before_run")
        else:
            settings.setValue("show_wiring_before_run", before)


# ---- pictures and steps in the window ----------------------------------------------------------
def write_svg(path, text="drawn"):
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100" viewBox="0 0 200 100">'
        f'<rect width="200" height="100" fill="#eef"/><text x="10" y="50">{text}</text></svg>',
        encoding="utf-8",
    )


def test_a_picture_replaces_the_drawn_diagram(app, registry, tmp_path):
    write_svg(tmp_path / "mine.svg")
    raw = {
        "nodes": [{"id": "a", "title": "A"}],
        "steps": ["Do it"],
        "images": [{"file": "mine.svg"}],
    }
    d = WiringDialog(wiring.diagram_for(raw, {}, None, "en", tmp_path), None, "x")
    assert d.picture is not None and d.picture.ok and d.view is None
    assert d.picture.natural_size().width() == 200 and d.picture.sizeHint().width() == 200
    assert not d.save_btn.isVisibleTo(d)  # nothing drawn by the program to save
    assert "Do it" in d.connections.text()
    image = d.picture.grab()
    assert not image.isNull()
    d.picture.resize(400, 400)  # a square window: the 2:1 picture keeps its proportions
    assert not d.picture.grab().isNull()


def test_a_raster_picture_is_shown_too(app, tmp_path):
    from PyQt6.QtGui import QColor, QImage

    image = QImage(300, 150, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    assert image.save(str(tmp_path / "mine.png"))
    view = dialog_module.ImageView(str(tmp_path / "mine.png"))
    assert view.ok and view.natural_size().width() == 300
    view.resize(600, 300)
    grabbed = view.grab().toImage()
    assert grabbed.pixelColor(300, 150) == QColor("steelblue")  # the picture fills the view


def test_a_picture_that_cannot_be_read_falls_back_to_the_drawing_and_says_so(
    app, registry, tmp_path
):
    (tmp_path / "broken.svg").write_text("this is not an svg", encoding="utf-8")
    (tmp_path / "broken.png").write_bytes(b"not a png")
    raw = {"nodes": EXAMPLE_NODES, "images": [{"file": "broken.svg"}]}
    d = WiringDialog(wiring.diagram_for(raw, {}, None, "en", tmp_path), None, "x")
    assert d.picture is None and d.view is not None and "broken.svg" in d.status.text()
    raw = {"nodes": EXAMPLE_NODES, "images": [{"file": "broken.png"}]}
    d = WiringDialog(wiring.diagram_for(raw, {}, None, "en", tmp_path), None, "x")
    assert d.picture is None and "cannot be read" in d.status.text()


def test_a_missing_picture_is_reported_in_the_window(app, tmp_path):
    raw = {"nodes": EXAMPLE_NODES, "images": [{"file": "gone.svg"}]}
    d = WiringDialog(wiring.diagram_for(raw, {}, None, "en", tmp_path), None, "x")
    assert d.view is not None and "picture not found: gone.svg" in d.status.text()


def test_without_steps_the_links_are_listed_and_steps_without_a_drawing_work(app):
    raw = {"nodes": EXAMPLE_NODES, "links": [{"from": "a.p", "to": "b.q", "label": "lead"}]}
    d = WiringDialog(wiring.diagram_for(raw, {}), None, "x")
    assert "Connections" in d.connections.text() and "A P -&gt; B Q (lead)" in d.connections.text()
    only = WiringDialog(wiring.diagram_for({"steps": ["Connect it", "Then that"]}, {}), None, "x")
    assert only.view is None and only.picture is None and not only.save_btn.isVisibleTo(only)
    assert "<ol><li>Connect it</li><li>Then that</li></ol>" in only.connections.text()


def test_the_step_list_of_the_efficiency_is_in_the_window(app, registry):
    from ola.demo_lab import demo_params

    raw = wiring.load_wiring(registry.get("efficiency").path)
    d = WiringDialog(wiring.diagram_for(raw, demo_params(), {}, "en"), None, "Efficiency")
    text = d.connections.text()
    assert text.count("<li>") == len(d.diagram.steps) >= 6
    assert "channel 101 of daq1 to «vin»" in text


def test_the_command_line_shows_a_module(app, registry, monkeypatch, tmp_path, capsys):
    shown = []
    monkeypatch.setattr(WiringDialog, "show", lambda self: shown.append(self))
    monkeypatch.setattr(QApplication, "exec", lambda *a: 0)
    assert (
        dialog_module.main([]) == 2
        and "python -m frontend.ui.WiringDialog" in capsys.readouterr().out
    )
    assert dialog_module.main(["filter", "it"]) == 0
    assert "Connetti" in shown[0].diagram.steps[0] or "Collega" in shown[0].diagram.steps[0]
    file = tmp_path / "m.eff"
    file.write_text(
        json.dumps({"params": {"filter": {"label": "SAW"}}, "role_bindings": {"vna": "lite"}})
    )
    assert dialog_module.main(["filter", str(file)]) == 0
    assert (
        shown[1].diagram.node("vna").subtitle == "lite"
        and shown[1].diagram.node("dut").title == "SAW"
    )
    assert dialog_module.main(["ripple", "en"]) == 0
    assert dialog_module.main(["nosuchmodule"]) == 1
    assert "unknown measurement type" in capsys.readouterr().out


EXAMPLE_NODES = [
    {"id": "a", "title": "A", "at": [0, 0], "ports": [{"id": "p", "side": "right", "label": "P"}]},
    {"id": "b", "title": "B", "at": [1, 0], "ports": [{"id": "q", "side": "left", "label": "Q"}]},
]
