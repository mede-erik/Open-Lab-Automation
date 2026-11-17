# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The pulse generator tool: the loads of the project are listed by name, the plot has the colours
of the theme and fills its panel, and nothing is cut.

Found on a real display: the plot was white on the dark theme, its title was covered by the label
of the peak, the radio buttons were not on one line, and the loads were listed as "Unnamed" (the
name of an instrument in the .inst file is ``instance_name``)."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
QtCore = pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("pytestqt")
pytest.importorskip("matplotlib")

from tests.conftest import LIBRARY_PATH  # noqa: E402
from tests.ui_audit import audit  # noqa: E402

pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(LIBRARY_PATH is None, reason="instrument library not available"),
]


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
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", staticmethod(lambda *a, **k: 0))
    from frontend.ui import layout_utils

    monkeypatch.setattr(layout_utils, "available_size", lambda widget: QtCore.QSize(1536, 824))
    yield


def project(tmp_path, loads):
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "p.inst").write_text(json.dumps({"instruments": loads}), encoding="utf-8")
    (folder / "p.json").write_text(
        json.dumps({"project_name": "p", "inst_file": "p.inst", "format_version": 2,
                    "measurements": []}), encoding="utf-8")
    return str(folder)


REAL_LOAD = {
    "instrument_type": "electronic_load", "instance_name": "LOAD1",
    "series": "Siglent_SDL1000X_E_Series", "model": "Siglent SDL1030X-E",
    "model_id": "EL_Siglent_SDL1030X_E",
    "visa_address": "TCPIP0::192.168.1.55::inst0::INSTR", "num_channels": 1,
    "channels": [{"enabled": True, "name": "Iout", "max_current": 30.0, "max_voltage": 150.0}],
}
MANUAL_LOAD = {
    "instrument_type": "electronic_load", "instance_name": "LOAD_manual", "is_manual": True,
    "num_channels": 1, "channels": [{"enabled": True, "name": "Iman"}],
}


def open_dialog(qtbot, folder, theme="dark", lang="it"):
    from frontend.ui.PulseGeneratorDialog import PulseGeneratorDialog
    from frontend.ui.main_window import MainWindow

    settings = QtCore.QSettings("LabAutomation", "App")
    settings.setValue("language", lang)
    settings.setValue("theme", theme)
    main = MainWindow()
    qtbot.addWidget(main)
    dialog = PulseGeneratorDialog(folder, main.load_instruments, main.translator, main)
    qtbot.addWidget(dialog)
    dialog.show()
    for _ in range(3):
        QtWidgets.QApplication.processEvents()
    return main, dialog


def stop(main):
    timer = getattr(getattr(main, "remote_tab", None), "measurement_timer", None)
    if timer is not None:
        timer.stop()


def test_loads_are_listed_by_their_name_and_a_manual_load_is_not_offered(qtbot, tmp_path):
    main, dialog = open_dialog(qtbot, project(tmp_path, [REAL_LOAD, MANUAL_LOAD]))
    try:
        combo = dialog.instrument_combo
        names = [combo.itemText(i) for i in range(combo.count())]
        assert names == ["LOAD1 (Siglent SDL1030X-E)"]
    finally:
        stop(main)


@pytest.mark.parametrize("theme, dark", [("dark", True), ("light", False)])
def test_plot_has_the_colours_of_the_theme_and_fills_its_panel(qtbot, tmp_path, theme, dark):
    main, dialog = open_dialog(qtbot, project(tmp_path, [REAL_LOAD]), theme=theme)
    try:
        figure_colour = dialog.figure.get_facecolor()[:3]
        assert (sum(figure_colour) / 3 < 0.5) is dark  # a dark plot on the dark theme
        assert dialog.canvas.height() >= dialog.canvas.parentWidget().height() - 60
        assert dialog.ax.get_title() == ""  # the label above the plot is the title
        assert dialog.ax.get_ylim()[1] > 1.0  # room above the pulse for the label of the peak
        assert dialog.instrument_info_label.isVisible()
    finally:
        stop(main)


def test_pulse_state_is_not_shown_as_an_error_when_stopped(qtbot, tmp_path):
    main, dialog = open_dialog(qtbot, project(tmp_path, [REAL_LOAD]))
    try:
        assert dialog.status_label.property("class") == "muted"
    finally:
        stop(main)


@pytest.mark.parametrize("lang", ["it", "de"])
@pytest.mark.parametrize("with_load", [True, False])
def test_nothing_is_cut_with_or_without_a_load(qtbot, tmp_path, lang, with_load):
    main, dialog = open_dialog(
        qtbot, project(tmp_path, [REAL_LOAD] if with_load else []), lang=lang
    )
    try:
        dialog.resize(dialog.minimumSizeHint())  # the smallest the window can be
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
        assert audit(dialog) == []
        if not with_load:
            assert dialog.instrument_combo.count() == 0 and not dialog.instrument_combo.isEnabled()
            assert dialog.instrument_info_label.text() == main.translator.t("no_load_available")
    finally:
        stop(main)
