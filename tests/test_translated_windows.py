# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The windows follow the language of the application.

Found going through the windows with the interface in Italian: the Measurements tab was built
before the saved language was applied (so it stayed English), the instrument-file dialog made a
translator of its own (always English).
"""

import os
import shutil

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
QtCore = pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("pytestqt")

from tests.conftest import LIBRARY_PATH, REPO  # noqa: E402

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available"),
]

EXAMPLE_INST = os.path.join(REPO, "examples", "test-dcdc-project", "test_instruments.inst")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """A temporary HOME and settings (the language is set by each test)."""
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(home))
    QSettings = QtCore.QSettings
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(home / "settings"))
    QSettings("LabAutomation", "App").clear()
    monkeypatch.setattr(QtWidgets.QDialog, "exec", lambda self: 0)
    yield


def window(qtbot, lang):
    from frontend.ui.main_window import MainWindow

    QtCore.QSettings("LabAutomation", "App").setValue("language", lang)
    main = MainWindow()
    qtbot.addWidget(main)
    return main


def stop_timers(main):
    timer = getattr(getattr(main, "remote_tab", None), "measurement_timer", None)
    if timer is not None:
        timer.stop()


def test_measurements_tab_starts_in_the_saved_language(qtbot):
    main = window(qtbot, "it")
    try:
        index = main.tabs.indexOf(main.project_tab)
        assert main.tabs.tabText(index) == main.project_tab.tr_.t("prj_tab") != "Measurements"
        headers = [
            main.project_tab.table.horizontalHeaderItem(c).text()
            for c in range(main.project_tab.table.columnCount())
        ]
        assert "Name" not in headers and "Nome" in headers
    finally:
        stop_timers(main)


def test_measurements_tab_follows_a_language_change(qtbot):
    main = window(qtbot, "en")
    try:
        index = main.tabs.indexOf(main.project_tab)
        assert main.tabs.tabText(index) == "Measurements"
        main.translator.set_language("it")
        main.update_translations()
        assert main.tabs.tabText(index) == "Misure"
        headers = [
            main.project_tab.table.horizontalHeaderItem(c).text()
            for c in range(main.project_tab.table.columnCount())
        ]
        assert "Nome" in headers
        assert main.project_tab.buttons["prj_new"].text() != "New measurement..."
    finally:
        stop_timers(main)


def test_instrument_file_dialog_uses_the_language_of_the_application(qtbot, tmp_path):
    from frontend.ui.InstrumentConfigDialog import InstrumentConfigDialog

    main = window(qtbot, "it")
    try:
        work = tmp_path / "instruments.inst"
        shutil.copy(EXAMPLE_INST, work)
        dialog = InstrumentConfigDialog(str(work), main.load_instruments, main)
        qtbot.addWidget(dialog)
        english = main.translator.__class__()  # a translator that was never told the language
        assert dialog.translator is main.translator
        assert dialog.translator.t("inst_add") != english.t("inst_add")
    finally:
        stop_timers(main)


def test_language_box_shows_the_names_of_the_languages(qtbot):
    from frontend.core.Translator import Translator
    from frontend.ui.SettingsDialog import SettingsDialog

    translator = Translator()
    translator.set_language("it")
    dialog = SettingsDialog(translator=translator)
    qtbot.addWidget(dialog)
    names = [dialog.lang_combo.itemText(i) for i in range(dialog.lang_combo.count())]
    assert "Italiano" in names and "English" in names and "it" not in names
    assert dialog.lang_combo.currentData() == "it"
