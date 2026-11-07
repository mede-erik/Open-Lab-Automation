# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""GUI smoke tests: every window and dialog of frontend/ui is built, shown and closed with an
example project, without a display (QT_QPA_PLATFORM=offscreen) and without hardware.

They catch what the engine tests cannot: a dialog that raises while it is built (renamed
attribute, missing translation file, library field read with the wrong shape), or one that
opens an error box on a valid project. Modal boxes and dialogs are replaced by recorders, so
nothing blocks; settings and config files go to a temporary HOME.
"""

from __future__ import annotations

import glob
import importlib
import json
import os
import pkgutil
import re
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
QtCore = pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("pytestqt")

import frontend.ui  # noqa: E402
from tests.conftest import LIBRARY_PATH, REPO  # noqa: E402

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available"),
]

EXAMPLE = os.path.join(REPO, "examples", "test-dcdc-project")
UI_MODULES = sorted(m.name for m in pkgutil.iter_modules(frontend.ui.__path__))


# ---------------------------------------------------------------- isolation


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Temporary HOME and QSettings; modal boxes and dialogs return immediately."""
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(home))
    QSettings = QtCore.QSettings
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(home / "settings"))
    QSettings("LabAutomation", "App").clear()

    shown = []
    QMessageBox = QtWidgets.QMessageBox
    for kind in ("critical", "warning", "information", "question"):

        def box(*args, _kind=kind, **_kwargs):
            shown.append((_kind, " | ".join(str(a) for a in args[1:3])))
            return QMessageBox.StandardButton.Ok

        monkeypatch.setattr(QMessageBox, kind, staticmethod(box))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(("exec", self.text())) or 0)
    monkeypatch.setattr(QtWidgets.QDialog, "exec", lambda self: 0)
    yield shown


@pytest.fixture
def errors(isolated):
    """Error and warning boxes shown during the test."""
    return lambda: [m for m in isolated if m[0] in ("critical", "warning", "exec")]


@pytest.fixture(scope="module")
def deps():
    from frontend.core.LoadInstruments import LoadInstruments
    from frontend.core.Translator import Translator

    li = LoadInstruments()
    assert li.load_instruments(LIBRARY_PATH)
    return li, Translator()


@pytest.fixture
def project(tmp_path):
    """A copy of the DC-DC example project (the GUI may write next to it). Its instruments
    point to localhost, so a test never reaches a real instrument on the lab network."""
    target = tmp_path / "project"
    shutil.copytree(EXAMPLE, target)
    inst_file = target / "test_instruments.inst"
    data = json.loads(inst_file.read_text(encoding="utf-8"))
    for instrument in data["instruments"]:
        if instrument.get("visa_address"):
            instrument["visa_address"] = "TCPIP0::127.0.0.1::inst0::INSTR"
    inst_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target


def _instruments(project):
    with open(project / "test_instruments.inst", encoding="utf-8") as f:
        return json.load(f)["instruments"]


def _first(project, instrument_type):
    return next(i for i in _instruments(project) if i["instrument_type"] == instrument_type)


# ---------------------------------------------------------------- tests


@pytest.mark.parametrize("module", UI_MODULES)
def test_every_ui_module_imports(module):
    importlib.import_module(f"frontend.ui.{module}")


DIALOGS = {
    "AddInstrumentDialog": lambda m, li, tr, p: m.AddInstrumentDialog(li, tr),
    "AddressEditorDialog": lambda m, li, tr, p: m.AddressEditorDialog(
        _first(p, "power_supply"), li
    ),
    "DataloggerConfigDialog": lambda m, li, tr, p: m.DataloggerConfigDialog(
        _first(p, "datalogger"), load_instruments=li
    ),
    "DataloggerInstrumentDialog": lambda m, li, tr, p: m.DataloggerInstrumentDialog(li, tr),
    "DataloggerSlotConfigDialog": lambda m, li, tr, p: m.DataloggerSlotConfigDialog(
        _first(p, "datalogger"), li, tr
    ),
    "EffFileDialog": lambda m, li, tr, p: m.EffFileDialog(str(p / "eff.eff"), tr),
    "ElectronicLoadConfigDialog": lambda m, li, tr, p: m.ElectronicLoadConfigDialog(
        _first(p, "electronic_load"), load_instruments=li
    ),
    "GpibAdapterDialog": lambda m, li, tr, p: m.GpibAdapterDialog(translator=tr),
    "HexDecConverterDialog": lambda m, li, tr, p: m.HexDecConverterDialog(translator=tr),
    "InstFileDialog": lambda m, li, tr, p: m.InstFileDialog(
        str(p / "test_instruments.inst"), li, tr
    ),
    "InstrumentConfigDialog": lambda m, li, tr, p: m.InstrumentConfigDialog(
        str(p / "test_instruments.inst"), li
    ),
    "InstrumentLibraryDialog": lambda m, li, tr, p: m.InstrumentLibraryDialog(li, translator=tr),
    "InstrumentTypeSelectionDialog": lambda m, li, tr, p: m.InstrumentTypeSelectionDialog(li, tr),
    "OscilloscopeConfigDialog": lambda m, li, tr, p: m.OscilloscopeConfigDialog(
        _first(p, "oscilloscope"), tr, load_instruments=li
    ),
    "PowerSupplyConfigDialog": lambda m, li, tr, p: m.PowerSupplyConfigDialog(
        _first(p, "power_supply"), load_instruments=li
    ),
    "PowerSupplyInstrumentDialog": lambda m, li, tr, p: m.PowerSupplyInstrumentDialog(li, tr),
    "RemoteControlTab": lambda m, li, tr, p: m.RemoteControlTab(li),
    "SettingsDialog": lambda m, li, tr, p: m.SettingsDialog(translator=tr),
    "WasFileDialog": lambda m, li, tr, p: m.WasFileDialog(str(p / "osc1.was"), tr),
    "database_config_dialog": lambda m, li, tr, p: m.DatabaseConfigDialog(),
}


@pytest.mark.parametrize("name", sorted(DIALOGS))
def test_dialog_opens_without_errors(qtbot, deps, project, errors, name):
    li, tr = deps
    module = importlib.import_module(f"frontend.ui.{name}")
    widget = DIALOGS[name](module, li, tr, project)
    qtbot.addWidget(widget)
    widget.show()
    QtWidgets.QApplication.processEvents()
    assert widget.isVisible()
    widget.close()
    assert errors() == []


def _ui_imports(text):
    """Names of the frontend.ui modules a source text imports."""
    names = set(re.findall(r"frontend\.ui\.(\w+)", text))
    for group in re.findall(r"from frontend\.ui import \(?([\w\s,]+)\)?", text):
        names |= {n.strip() for n in group.split(",") if n.strip()}
    return names & set(UI_MODULES)


def test_every_ui_module_is_tested():
    """Every file of frontend/ui must be exercised by a test: opened above, imported by a test
    file of its own (tests/test_project_window.py, ...), or used by a module that is."""
    here = os.path.abspath(__file__)
    covered = set(DIALOGS) | {"__init__", "main_window", "PulseGeneratorDialog"}
    for path in glob.glob(os.path.join(REPO, "tests", "test_*.py")):
        if os.path.abspath(path) != here:
            with open(path, encoding="utf-8") as f:
                covered |= _ui_imports(f.read())
    ui_dir = os.path.dirname(frontend.ui.__file__)
    while True:  # modules used by covered modules are exercised through them
        used = set()
        for name in covered & set(UI_MODULES):
            with open(os.path.join(ui_dir, f"{name}.py"), encoding="utf-8") as f:
                used |= _ui_imports(f.read())
        if used <= covered:
            break
        covered |= used
    assert set(UI_MODULES) - covered == set()


def test_pulse_generator_with_a_library_load(qtbot, deps, project, errors, library):
    """The pulse tool needs an electronic load of the library that supports the dynamic
    calls; build a project with one and check the tool accepts it."""
    from frontend.ui import PulseGeneratorDialog as module

    li, tr = deps
    candidates = [
        (s["series_id"], m)
        for s in library.categories.get("electronic_loads_series", [])
        for m in s["models"]
        if all(c in library.commands(m["id"]) for c in module.REQUIRED_CALLS)
    ]
    if not candidates:
        pytest.skip("no library electronic load supports the pulse calls")
    series_id, model = candidates[0]
    load = {
        "instrument_type": "electronic_load",
        "instance_name": "LOAD",
        "name": "LOAD",
        "series": series_id,
        "model": model["name"],
        "model_id": model["id"],
        "num_channels": 1,
        "visa_address": "TCPIP0::127.0.0.1::inst0::INSTR",
        "channels": [{"name": "ILOAD", "channel_id": "1", "enabled": True}],
    }
    (project / "test_instruments.inst").write_text(
        json.dumps({"instruments": [load]}), encoding="utf-8"
    )
    dialog = module.PulseGeneratorDialog(str(project), li, tr)
    qtbot.addWidget(dialog)
    dialog.show()
    assert errors() == []
    assert dialog.instrument_combo.count() == 1
    dialog.close()


def test_main_window_opens_a_project(qtbot, project, errors, monkeypatch):
    from frontend.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    project_file = str(project / "Test DC-DC Converter.json")
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (project_file, "Project Files (*.json)")),
    )
    window.open_project()
    QtWidgets.QApplication.processEvents()
    assert window.current_project_dir == str(project)
    assert window.current_project_data["project_name"]
    listed = [
        window.project_files_list.item(i).text() for i in range(window.project_files_list.count())
    ]
    assert "test_instruments.inst" in listed and "osc1.was" in listed
    assert QtCore.QSettings("LabAutomation", "App").value("last_project_path") == project_file
    # the remote panel polls the instruments with a timer that has no parent: stop it, or it
    # keeps polling during the next tests
    timer = getattr(getattr(window, "remote_tab", None), "measurement_timer", None)
    if timer is not None:
        timer.stop()
    window.close()
    assert errors() == []


def test_tools_menu_opens_the_gpib_adapters_tool(qtbot, errors):
    from frontend.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    menus = {a.text(): a.menu() for a in window.menuBar().actions() if a.menu()}
    tools = next(m for m in menus.values() if any("GPIB" in a.text() for a in m.actions()))
    action = next(a for a in tools.actions() if "GPIB" in a.text())
    action.trigger()
    QtWidgets.QApplication.processEvents()
    tool = window._gpib_tool
    assert tool.isVisible()
    action.trigger()  # a second click brings the same window forward
    assert window._gpib_tool is tool
    tool.close()
    assert errors() == []
