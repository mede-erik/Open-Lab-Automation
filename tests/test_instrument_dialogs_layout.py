# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The dialogs of the instruments show everything they have to show, for every type of instrument
of the library, in the languages with the longest texts, in a narrow window.

Found by going through them one by one: the titles of the columns of the ports of a network
analyzer ("Porti", "Abiliti"), of the channels of an oscilloscope and of a multimeter ("empo
integrazior") were cut, and the names of the instrument library were cut at 4 letters."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
QtCore = pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("pytestqt")

from tests.conftest import LIBRARY_PATH  # noqa: E402
from tests.ui_audit import audit  # noqa: E402

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available"),
]
SERIAL_MODELS = ("LiteVNA", "HP_3478A", "OWON")
NARROW = (760, 540)  # a small window: the titles must still fit (the panel scrolls instead)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(home))
    settings = QtCore.QSettings
    for fmt in (settings.Format.NativeFormat, settings.Format.IniFormat):
        settings.setPath(fmt, settings.Scope.UserScope, str(home / "settings"))
    settings("LabAutomation", "App").clear()
    monkeypatch.setattr(QtWidgets.QDialog, "exec", lambda self: 0)
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", staticmethod(lambda *a, **k: 0))
    # the usable area of a Full HD screen at a display scale of 125% (the offscreen one is 800x600)
    from frontend.ui import layout_utils

    monkeypatch.setattr(layout_utils, "available_size", lambda widget: QtCore.QSize(1536, 824))
    yield


def settle():
    for _ in range(3):
        QtWidgets.QApplication.processEvents()


def one_of_each(dialog, li):
    """An entry for the first model of every series of the library (some on a serial port, some
    without an address) and two manual instruments."""
    entries = []
    for type_name in li.get_all_types():
        for series in li.get_visible_series(type_name, include_experimental=True)[:4]:
            models = li.get_visible_models(
                type_name, series.get("series_id"), include_experimental=True
            )
            for model in models[:1]:
                model_id = model.get("id") or "x"
                entry = dialog._new_entry(
                    type_name, series.get("series_id"), model_id, model.get("name", ""),
                    model_id.split("_", 1)[-1][:14],
                )
                if any(key in model_id for key in SERIAL_MODELS):
                    entry["visa_address"] = "ASRL3::INSTR"
                elif len(entries) % 3:
                    entry["visa_address"] = f"TCPIP0::192.168.1.{10 + len(entries)}::inst0::INSTR"
                entries.append(entry)
    for kind, name in (("power_supply", "PSU_manual"), ("electronic_load", "LOAD_manual")):
        entries.append({
            "instrument_type": kind, "instance_name": name, "is_manual": True, "num_channels": 1,
            "channels": [{"enabled": True, "name": "CH1", "max_current": 5.0, "max_voltage": 30.0}],
        })
    return entries


def stop_timers(main):
    timer = getattr(getattr(main, "remote_tab", None), "measurement_timer", None)
    if timer is not None:
        timer.stop()


@pytest.mark.parametrize("lang", ["it", "de"])
def test_instrument_dialog_is_not_cut_for_any_type(qtbot, tmp_path, lang):
    from frontend.ui.DataloggerSlotConfigDialog import DataloggerSlotConfigDialog
    from frontend.ui.InstrumentConfigDialog import InstrumentConfigDialog
    from frontend.ui.OscilloscopeConfigDialog import OscilloscopeConfigDialog
    from frontend.ui.main_window import MainWindow

    settings = QtCore.QSettings("LabAutomation", "App")
    settings.setValue("language", lang)
    settings.setValue("show_experimental_instruments", True)
    main = MainWindow()
    qtbot.addWidget(main)
    try:
        li = main.load_instruments
        path = tmp_path / "all.inst"
        path.write_text(json.dumps({"instruments": []}), encoding="utf-8")
        dialog = InstrumentConfigDialog(str(path), li, main)
        entries = one_of_each(dialog, li)
        path.write_text(json.dumps({"instruments": entries}), encoding="utf-8")
        dialog = InstrumentConfigDialog(str(path), li, main)
        qtbot.addWidget(dialog)
        dialog.resize(*NARROW)
        dialog.show()
        settle()
        assert len(dialog.instruments) >= 20
        kinds_seen, found = set(), []
        for row, entry in enumerate(dialog.instruments):
            dialog.list_widget.setCurrentRow(row)
            settle()
            kind = entry.get("instrument_type")
            kinds_seen.add(kind)
            found += [f"{kind} {entry['instance_name']}: {line}" for line in audit(dialog)]
            sub = None
            if kind == "oscilloscope":
                sub = OscilloscopeConfigDialog(entry, dialog.translator, dialog, li)
            elif kind == "datalogger":
                caps = li.get_model_capabilities(kind, entry.get("series", ""), entry["model_id"])
                if caps and caps.get("number_of_slots"):
                    sub = DataloggerSlotConfigDialog(entry, li, dialog.translator, dialog)
            if sub is not None:
                qtbot.addWidget(sub)
                sub.show()
                settle()
                name = f"{kind} {entry['instance_name']} (sub-dialog)"
                found += [f"{name}: {line}" for line in audit(sub)]
                sub.close()
        assert {"network_analyzer", "multimeter", "oscilloscope", "datalogger"} <= kinds_seen
        assert found == [], "\n".join(found)
    finally:
        stop_timers(main)


def test_instrument_library_dialog_shows_the_names(qtbot):
    """The names of the library are in a column wide enough to read them; the other columns are
    in view, not scrolled out of the dialog."""
    from frontend.ui.InstrumentLibraryDialog import InstrumentLibraryDialog
    from frontend.ui.main_window import MainWindow

    QtCore.QSettings("LabAutomation", "App").setValue("language", "it")
    main = MainWindow()
    qtbot.addWidget(main)
    try:
        dialog = InstrumentLibraryDialog(main.load_instruments, main, main.translator)
        qtbot.addWidget(dialog)
        dialog.show()
        settle()
        tree = dialog.tree_widget
        assert tree.columnWidth(0) >= 300
        header = tree.header()
        assert header.sectionSize(1) > 20 and header.sectionSize(2) > 20
        assert tree.viewport().width() >= tree.columnWidth(0) + header.sectionSize(1)
        assert audit(dialog) == []
        assert dialog.windowTitle() == main.translator.t("instrument_library")
    finally:
        stop_timers(main)
