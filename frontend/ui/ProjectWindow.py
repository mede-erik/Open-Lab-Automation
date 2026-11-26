# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Window of a project: its measurements, and the actions on them.

A thin layer over ``ola.project_session.ProjectSession`` (which does the work and is tested without
a screen). The list shows every measurement of the project (name, type, file, and the reason if it
cannot be used). On the selected one:

* **New**: choose the type (the measurement modules found) and a name; a file with the extension of
  the type is created in the project folder;
* **Edit** (or double-click): the editor of the type - the efficiency editor for ``.eff``, the form
  built from the module's ``form.json`` if it has one, a JSON editor with validation otherwise;
* **Start measurement**: opens the run window (live table, plot, log, pop-ups) and starts it; the
  results are written to ``runs/`` in the project folder;
* **Rename**, **Remove** (the file is only deleted if you ask);
* the list of the runs already made, with **Export CSV** and **Compare** (the runs of the selected
  measurement, or others added by hand).

The instruments come from the application through ``connect(name, cancel) -> handle`` (or a
``connector_factory(session)`` that builds it for each project); without it the
measurement cannot start and the window says why. Strings:
``frontend/lang/modules/project/<lang>.json``. Try it: ``python -m frontend.ui.ProjectWindow
[project.json]`` (with no argument a demo project with simulated instruments is created in a
temporary folder).
"""

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frontend.ui.layout_utils import FlowLayout
from frontend.ui.efficiency_widgets import text_color
from frontend.core.Translator import Translator
from frontend.ui.module_translator import CatalogTranslator
from ola.form_model import load_form_spec
from ola.measurement import MeasurementError
from ola.project import MeasurementFile, MeasurementRef, Project
from ola.project_session import ProjectSession
from ola.registry import ModuleRegistry, default_registry
from ola.scope_capture import WARN_BYTES
from ola.runs import export_points_csv
from ola.wavefiles import wave_folder
from frontend.core.errorhandler import show_problem

logger = logging.getLogger(__name__)

REFRESH_MS = 1000  # the list of runs is refreshed while a run window is open


class NewMeasurementDialog(QDialog):
    """Asks for the type and the name of a new measurement."""

    def __init__(self, types: list, tr: CatalogTranslator, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr.t("prj_new_title"))
        layout = QVBoxLayout(self)
        self.type_box = QComboBox()
        for info in types:
            self.type_box.addItem(f"{info.name}  ({info.extension})", info.id)
            self.type_box.setItemData(
                self.type_box.count() - 1, info.description, Qt.ItemDataRole.ToolTipRole
            )
        self.name_edit = QLineEdit()
        self.type_box.currentIndexChanged.connect(self._suggest)
        self.description = QLabel()
        self.description.setWordWrap(True)
        self.types = {t.id: t for t in types}
        layout.addWidget(QLabel(tr.t("prj_new_type")))
        layout.addWidget(self.type_box)
        layout.addWidget(self.description)
        layout.addWidget(QLabel(tr.t("prj_new_name")))
        layout.addWidget(self.name_edit)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton(tr.t("prj_ok"))
        cancel = QPushButton(tr.t("prj_cancel"))
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)
        self._suggest()

    def _suggest(self) -> None:
        info = self.types.get(self.type_box.currentData())
        if info is not None:
            self.description.setText(info.description)
            if not self.name_edit.isModified():
                self.name_edit.setText(info.name)

    def chosen(self):
        """``(type_id, name)``."""
        return self.type_box.currentData(), self.name_edit.text().strip()


class JsonParamsDialog(QDialog):
    """Editor of the parameters of a measurement type that has no editor of its own: the
    parameters as JSON, checked by the measurement module before saving."""

    def __init__(
        self, session: ProjectSession, ref: MeasurementRef, tr: CatalogTranslator, parent=None
    ):
        super().__init__(parent)
        self.session, self.ref, self.tr_ = session, ref, tr
        self.file = session.load(ref)
        self.setWindowTitle(f"{tr.t('prj_json_title')} - {ref.name}")
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr.t("prj_json_help")))
        self.edit = QPlainTextEdit(json.dumps(self.file.params, indent=2, ensure_ascii=False))
        self.edit.textChanged.connect(self._check)
        layout.addWidget(self.edit, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        row = QHBoxLayout()
        row.addStretch(1)
        self.save_btn = QPushButton(tr.t("prj_save"))
        close = QPushButton(tr.t("prj_cancel"))
        self.save_btn.clicked.connect(self.save)
        close.clicked.connect(self.reject)
        row.addWidget(self.save_btn)
        row.addWidget(close)
        layout.addLayout(row)
        self._check()

    def _problems(self) -> List[str]:
        """What is wrong with the text now (empty list: it can be saved)."""
        try:
            params = json.loads(self.edit.toPlainText())
        except ValueError as exc:
            return [self.tr_.t("prj_json_invalid", error=exc)]
        if not isinstance(params, dict):
            return [self.tr_.t("prj_json_not_object")]
        try:
            return list(self.session.registry.create(self.ref.type, params).validate())
        except Exception as exc:  # the module refused the parameters
            return [str(exc)]

    def _check(self) -> None:
        problems = self._problems()
        color = text_color("error" if problems else "ok", self)
        text = "<br>".join(problems) if problems else self.tr_.t("prj_json_ok")
        self.message.setText(f"<span style='color:{color}'>{text}</span>")

    def save(self) -> None:
        """Write the file (after a confirmation if the module sees problems)."""
        problems = self._problems()
        if problems:
            answer = QMessageBox.question(
                self, self.windowTitle(), self.tr_.t("prj_save_with_errors", n=len(problems))
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            params = json.loads(self.edit.toPlainText())
        except ValueError:
            return  # not saved: the text is not JSON
        self.file.params = params
        self.file.save(self.session.path(self.ref))
        self.accept()


class ProjectWindow(QMainWindow):
    """The window of a project (see the module docstring)."""

    project_changed = pyqtSignal()  # the project or its list of measurements was (re)drawn

    def __init__(
        self,
        project: Optional[Project] = None,
        translator: Any = None,
        connect: Optional[Callable[..., Any]] = None,
        connector_factory: Optional[Callable[[ProjectSession], Callable[..., Any]]] = None,
        assets: Optional[Any] = None,
        registry: Optional[ModuleRegistry] = None,
        parent: Optional[QWidget] = None,
        wiring_before_run: bool = False,
        on_wiring_preference: Optional[Callable[[bool], None]] = None,
        duts: Optional[Any] = None,
    ):
        super().__init__(parent)
        self.tr_ = CatalogTranslator("project", translator)
        self.wir_ = CatalogTranslator("wiring", translator)
        self.cal_ = CatalogTranslator("calibration", translator)
        # the shared language catalogs (frontend/lang), also when no translator was given
        self.app_t = (translator or Translator()).t
        # show the connection diagram of a measurement before it starts (a tick in that window
        # turns it off; ``on_wiring_preference`` is told so that it can be remembered)
        self.wiring_before_run = wiring_before_run
        self.on_wiring_preference = on_wiring_preference
        self._t = self.tr_.t
        self.translator, self.connect = translator, connect
        self.connector_factory, self.connector = connector_factory, None
        self.assets = assets  # the registry of cables and devices (ola.assets), or None
        self.duts = duts  # the archive of the devices under test (ola.duts), or None
        self.registry = registry or default_registry()
        self.session: Optional[ProjectSession] = None
        self.run_windows: list = []
        self.setWindowTitle(self._t("prj_title"))
        self.resize(980, 640)
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_runs)
        self._timer.start(REFRESH_MS)
        if project is not None:
            self.set_project(project)
        else:
            self._refresh()

    # ================================================================ building the window
    def _build_ui(self) -> None:
        menu = self.menuBar().addMenu(self._t("prj_menu_file"))
        for key, handler in (
            ("prj_new_project", self.new_project),
            ("prj_open_project", self.open_project),
            ("prj_choose_inst", self.choose_instrument_file),
            ("roles_menu", self.map_instruments),
        ):
            action = menu.addAction(self.app_t(key) if key.startswith("roles_") else self._t(key))
            action.triggered.connect(lambda _c=False, h=handler: h())
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        self.header = QLabel()
        self.header.setTextFormat(Qt.TextFormat.RichText)
        self.header.setWordWrap(True)
        root.addWidget(self.header)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                self._t("prj_col_name"),
                self._t("prj_col_type"),
                self._t("prj_col_file"),
                self._t("prj_col_status"),
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _i: self.edit_measurement())
        root.addWidget(self.table, 3)

        row = FlowLayout()  # the buttons go on a new line when the window is narrow
        self.buttons: Dict[str, QPushButton] = {}
        for key, handler in (
            ("prj_new", self.new_measurement),
            ("prj_edit", self.edit_measurement),
            ("prj_run", self.run_measurement),
            ("wir_button", self.show_connections),
            ("cal_button", self.calibrate_analyzer),
            ("prj_rename", self.rename_measurement),
            ("prj_remove", self.remove_measurement),
        ):
            catalog = {"wir_": self.wir_, "cal_": self.cal_}.get(key[:4])
            button = QPushButton(catalog.t(key) if catalog else self._t(key))
            button.clicked.connect(lambda _c=False, h=handler: h())
            self.buttons[key] = button
            row.addWidget(button)
        self.bench_check = QCheckBox(self._t("prj_bench"))
        self.bench_check.setToolTip(self._t("prj_bench_tip"))
        row.addWidget(self.bench_check)
        root.addLayout(row)

        root.addWidget(QLabel(self._t("prj_runs")))
        self.runs_table = QTableWidget(0, 3)
        self.runs_table.setHorizontalHeaderLabels(
            [self._t("prj_run_file"), self._t("prj_run_state"), self._t("prj_run_points")]
        )
        self.runs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.runs_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.runs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.runs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.runs_table.itemSelectionChanged.connect(self._update_buttons)
        root.addWidget(self.runs_table, 2)
        row = QHBoxLayout()
        self.export_btn = QPushButton(self._t("prj_export"))
        self.export_btn.clicked.connect(self.export_run)
        row.addWidget(self.export_btn)
        self.delete_btn = QPushButton(self._t("prj_delete"))
        self.delete_btn.clicked.connect(self.delete_run)
        row.addWidget(self.delete_btn)
        self.waves_btn = QPushButton(self._t("prj_waves"))
        self.waves_btn.clicked.connect(self.show_waves)
        row.addWidget(self.waves_btn)
        self.compare_btn = QPushButton(self._t("prj_compare"))
        self.compare_btn.clicked.connect(self.compare_runs)
        row.addWidget(self.compare_btn)
        row.addStretch(1)
        root.addLayout(row)

    def retranslate(self) -> None:
        """Show the window again in the language of the application (it was changed while the
        window is open). The state is in the session, not in the widgets, so the window is built
        again and filled from the session."""
        lang = getattr(self.translator, "current_lang", None)
        if lang:
            for catalog in (self.tr_, self.wir_, self.cal_):
                catalog.set_language(lang)
        self.app_t = (self.translator or Translator()).t
        bench = self.bench_check.isChecked()
        self.menuBar().clear()
        self._build_ui()  # a new central widget: the old one is deleted by Qt
        self.bench_check.setChecked(bench)
        self.setWindowTitle(
            f"{self._t('prj_title')} - {self.session.project.name}"
            if self.session is not None
            else self._t("prj_title")
        )
        self._refresh()

    # ================================================================ the project
    def set_project(self, project: Project) -> None:
        """Show this project (``connect`` is kept)."""
        self._close_connector()
        self.session = ProjectSession(
            project, self.registry, connect=self.connect, assets=self.assets, duts=self.duts
        )
        if self.connector_factory is not None:  # built for this project, closed when it changes
            self.connector = self.connector_factory(self.session)
            self.session.connect = self.connector
        self.setWindowTitle(f"{self._t('prj_title')} - {project.name}")
        self._refresh()
        # a received project: offer to use your own instruments, once the window is shown. The timer
        # belongs to the window, so it goes away with it (a bare ``QTimer.singleShot`` with a
        # lambda would fire on a window that was already destroyed)
        self._mapping_timer = QTimer(self)
        self._mapping_timer.setSingleShot(True)
        self._mapping_timer.timeout.connect(lambda: self.map_instruments(quiet=True))
        self._mapping_timer.start(0)

    def _close_connector(self) -> None:
        """Close the connections of the previous project (if its connector can close them)."""
        close = getattr(self.connector, "close", None)
        if callable(close):
            close()
        self.connector = None

    def new_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._t("prj_new_project"))
        if not folder:
            return
        name, ok = QInputDialog.getText(
            self, self._t("prj_new_project"), self._t("prj_project_name")
        )
        if not ok or not name.strip():
            return
        project = Project.new(name.strip(), folder)
        if project.path.exists():
            show_problem(
                self,
                self._t("prj_title"),
                self._t("prj_exists", path=str(project.path)),
                code="PROJ-008",
            )
            return
        project.save()
        self.set_project(project)

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self._t("prj_open_project"), "",
            f"{self._t('file_filter_project')} (*.json)",
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        """Open a project file; the reason is shown if it cannot be read (for example the old
        format, which is not supported)."""
        try:
            project = Project.load(path)
        except MeasurementError as exc:
            show_problem(self, self._t("prj_title"), self._t("prj_open_failed", error=exc), code="PROJ-005", exception=exc, level="critical")
            return False
        self.set_project(project)
        return True

    def choose_instrument_file(self) -> None:
        if self.session is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._t("prj_choose_inst"),
            str(self.session.project.directory),
            f"{self._t('file_filter_instruments')} (*.inst)",
        )
        if not path:
            return
        try:
            if Path(path).parent.resolve() != self.session.project.directory.resolve():
                raise MeasurementError(self._t("prj_inst_outside"))
            self.session.set_instrument_file(Path(path).name)
        except MeasurementError as exc:
            show_problem(self, self._t("prj_title"), str(exc), code="PROJ-010", exception=exc)
            return
        self._refresh()

    # ================================================================ the list
    def _selected(self) -> Optional[MeasurementRef]:
        row = self.table.currentRow()
        if self.session is None or not 0 <= row < len(self.session.project.measurements):
            return None
        return self.session.project.measurements[row]

    def show_measurement(self, measurement_id: str) -> None:
        """Redraw the list of measurements (after the project was changed from outside) and
        select this one."""
        self._refresh()
        self._select(measurement_id)

    def ref_for_file(self, file_name: str) -> Optional[MeasurementRef]:
        """The measurement of the open project that lives in this file (None if there is none)."""
        if self.session is None:
            return None
        for ref in self.session.project.measurements:
            if ref.file == file_name:
                return ref
        return None

    def edit_file(self, file_name: str) -> bool:
        """Open the editor of the measurement in this file; False if no measurement uses it."""
        ref = self.ref_for_file(file_name)
        if ref is None:
            return False
        self._select(ref.id)
        self.edit_measurement()
        return True

    def remove_file(self, file_name: str) -> bool:
        """Take the measurement in this file out of the project (asks whether to delete the
        file); False if no measurement uses it."""
        ref = self.ref_for_file(file_name)
        if ref is None:
            return False
        self._select(ref.id)
        self.remove_measurement()
        return True

    def _refresh(self) -> None:
        keep = self._selected().id if self._selected() else None
        self.table.setRowCount(0)
        session = self.session
        if session is None:
            self.header.setText(self._t("prj_no_project"))
        else:
            inst = session.project.inst_file or self._t("prj_no_inst")
            self.header.setText(
                self._t(
                    "prj_header",
                    name=session.project.name,
                    folder=str(session.project.directory),
                    inst=inst,
                    n=len(session.instruments),
                )
            )
            for r in session.rows():
                row = self.table.rowCount()
                self.table.insertRow(row)
                status = r.problem or self._t("prj_ok_status")
                cells = [r.ref.name, r.info.name if r.info else r.ref.type, r.ref.file, status]
                for column, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if column == 3:
                        item.setForeground(
                            QBrush(QColor(text_color("error" if r.problem else "ok", self)))
                        )
                    self.table.setItem(row, column, item)
                if r.ref.id == keep:
                    self.table.selectRow(row)
            self.table.resizeColumnsToContents()
            self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._selection_changed()
        self.project_changed.emit()

    def _selection_changed(self) -> None:
        self._refresh_runs()
        self._update_buttons()

    def _update_buttons(self) -> None:
        ref = self._selected()
        usable = ref is not None and not next(
            (r.problem for r in self.session.rows() if r.ref.id == ref.id), "x"
        )
        self.buttons["prj_new"].setEnabled(self.session is not None)
        self.buttons["prj_edit"].setEnabled(usable)
        self.buttons["prj_run"].setEnabled(usable)
        self.buttons["wir_button"].setEnabled(usable)
        self.buttons["cal_button"].setEnabled(self.session is not None)
        self.buttons["prj_rename"].setEnabled(ref is not None)
        self.buttons["prj_remove"].setEnabled(ref is not None)
        self.export_btn.setEnabled(self._selected_run() is not None)
        run = self._selected_run()
        self.delete_btn.setEnabled(run is not None)
        self.waves_btn.setEnabled(run is not None and wave_folder(run).is_dir())
        self.compare_btn.setEnabled(self.session is not None)  # runs can also be added by hand

    # ================================================================ actions
    def new_measurement(self) -> None:
        if self.session is None:
            return
        dialog = NewMeasurementDialog(self.session.module_types(), self.tr_, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        type_id, name = dialog.chosen()
        try:
            ref = self.session.create(type_id, name)
        except MeasurementError as exc:
            show_problem(self, self._t("prj_title"), str(exc), code="MEAS-009", exception=exc)
            return
        self._refresh()
        self._select(ref.id)

    def _select(self, measurement_id: str) -> None:
        for row, ref in enumerate(self.session.project.measurements):
            if ref.id == measurement_id:
                self.table.selectRow(row)

    def _inst_entries(self) -> Dict[str, Dict[str, Any]]:
        """The instruments of the project's .inst file, by name (what a measurement can use)."""
        from ola.inst_file import load_inst

        project = self.session.project if self.session is not None else None
        if project is None or not project.inst_file:
            return {}
        try:
            entries, _ = load_inst(project.directory / project.inst_file)
        except ValueError:
            return {}
        return {str(e["instance_name"]): e for e in entries if e.get("instance_name")}

    def _library_calls(self, entry: Dict[str, Any]) -> List[Any]:
        """The readings an instrument's model has inside (``ola.readings.Readable``): voltage and
        current of a supply, of a load, the value of a meter... None if it is not in the library."""
        from frontend.ui.connector_setup import default_library_path, load_library
        from ola.readings import readable_calls

        try:
            library = load_library(default_library_path())
        except Exception:  # the window still opens: the calls are typed by hand then
            return []
        key = entry.get("model_id") or entry.get("model") or ""
        model_id = library.resolve_model_id(key) if key else None
        return readable_calls(library, model_id) if model_id else []

    def _load_limits(self, name: str) -> Dict[str, float]:
        """What the library gives for the model of the instrument ``name`` of the project: the
        largest voltage, current and power (``ola.compat.characteristics``); empty if it is not in
        the library."""
        from frontend.ui.connector_setup import default_library_path, load_library
        from ola.compat import characteristics

        entry = self._inst_entries().get(name) or {}
        try:
            library = load_library(default_library_path())
        except Exception:  # the window still opens: nothing is checked then
            return {}
        key = entry.get("model_id") or entry.get("model") or ""
        model_id = library.resolve_model_id(key) if key else None
        return characteristics(library, model_id) if model_id else {}

    def edit_measurement(self) -> None:
        """Open the editor of the selected measurement's type."""
        ref = self._selected()
        if ref is None:
            return
        try:
            if ref.type in ("efficiency", "resistive_efficiency"):
                from frontend.ui.EfficiencyEditorDialog import EfficiencyEditorDialog

                dialog: QDialog = EfficiencyEditorDialog(
                    str(self.session.path(ref)),
                    self.translator,
                    self.session.instruments,
                    parent=self,
                    duts=self.duts,
                )
            elif ref.type == "time_log":
                from frontend.ui.TimeLogEditorDialog import TimeLogEditorDialog

                dialog = TimeLogEditorDialog(
                    str(self.session.path(ref)),
                    self._inst_entries(),
                    validate=lambda params: self.registry.create("time_log", params).validate(),
                    calls=self._library_calls,
                    translator=self.translator,
                    parent=self,
                )
            elif ref.type == "pulse_load":
                from frontend.ui.PulseLoadEditorDialog import PulseLoadEditorDialog

                dialog = PulseLoadEditorDialog(
                    str(self.session.path(ref)),
                    self.registry,
                    ref.type,
                    self.translator,
                    self.session.instruments,
                    role_instruments=self.session.instruments_by_role(self.registry.get(ref.type)),
                    assets=self.assets,
                    parent=self,
                    duts=self.duts,
                    limits=self._load_limits,
                )
            elif load_form_spec(self.registry.get(ref.type)) is not None:
                from frontend.ui.FormEditorDialog import FormEditorDialog

                dialog = FormEditorDialog(
                    str(self.session.path(ref)),
                    self.registry,
                    ref.type,
                    self.translator,
                    self.session.instruments,
                    role_instruments=self.session.instruments_by_role(self.registry.get(ref.type)),
                    assets=self.assets,
                    parent=self,
                    duts=self.duts,
                )
            else:
                dialog = JsonParamsDialog(self.session, ref, self.tr_, self)
        except MeasurementError as exc:
            show_problem(self, self._t("prj_title"), str(exc), code="MEAS-001", exception=exc, level="critical")
            return
        dialog.exec()
        self._refresh()

    def _wiring_dialog(self, ref: MeasurementRef, confirm: bool):
        """The connection-diagram window of a measurement, or None if its module has none (or
        the diagram cannot be built: the reason is shown)."""
        from frontend.ui.WiringDialog import WiringDialog
        from ola.wiring import WiringError

        try:
            diagram = self.session.wiring(ref, self.wir_.lang)
        except (WiringError, MeasurementError) as exc:
            show_problem(self, self._t("prj_title"), self.wir_.t("wir_error", error=exc), code="MEAS-005", exception=exc)
            return None
        if diagram is None:
            return None
        return WiringDialog(
            diagram, self.translator, ref.name, confirm, self.wiring_before_run, parent=self
        )

    def show_connections(self) -> None:
        """Show how the instruments are connected for the selected measurement."""
        ref = self._selected()
        if ref is None:
            return
        dialog = self._wiring_dialog(ref, confirm=False)
        if dialog is None:
            QMessageBox.information(self, self._t("prj_title"), self.wir_.t("wir_none"))
            return
        dialog.exec()

    def calibrate_analyzer(self) -> None:
        """Open the calibration window for the network analyzers of the project."""
        from ola import vna_calibration_flow as flow
        from ola.connection import ConnectionProblem, read_inst_entries

        library = getattr(self.connector, "library", None)
        project = self.session.project
        try:
            if library is None:
                raise ConnectionProblem(self._t("prj_cal_no_library"))
            if not project.inst_file:
                raise ConnectionProblem(self._t("prj_cal_no_inst"))
            entries = read_inst_entries(project.directory / project.inst_file)
        except ConnectionProblem as exc:
            show_problem(
                self,
                self.cal_.t("cal_title"),
                self.cal_.t("cal_no_connection", error=exc),
                code="VISA-001",
                exception=exc,
            )
            return
        analyzers = flow.network_analyzers(library, entries)
        if not analyzers:
            show_problem(self, self.cal_.t("cal_title"), self.cal_.t("cal_no_vna"), code="INST-005")
            return
        from frontend.ui.CalibrationDialog import CalibrationDialog

        CalibrationDialog(
            analyzers,
            library,
            self.connector,
            project.path,
            self.translator,
            parent=self,
            entries=entries,
        ).exec()

    def map_instruments(self, quiet: bool = False) -> None:
        """Let the user name their own instruments where the measurements name instruments that
        are not in the instrument file (a project received from someone else). ``quiet``: say
        nothing when there is nothing to map (used when a project is opened)."""
        if self.session is None:
            return
        from frontend.ui.RolesDialog import RolesDialog

        dialog = RolesDialog(
            self.session,
            getattr(self.connector, "characteristics", None),
            getattr(self.connector, "abilities", None),
            self.translator,
            self,
        )
        if not dialog.gaps:
            if not quiet:
                QMessageBox.information(self, self._t("prj_title"), self.app_t("roles_nothing"))
            return
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._refresh()

    def _check_compatibility(self, ref: MeasurementRef):
        """Compare the instruments now bound to the measurement with the ones of its previous
        runs. Returns ``(go_on, accepted_differences)``: if something is less than before the
        user decides (and a difference that makes the measurement impossible stops it). A failure
        of the check itself never stops a measurement."""
        characteristics_of = getattr(self.connector, "characteristics", None)
        if characteristics_of is None:
            return True, None
        try:
            findings = self.session.compatibility(
                ref, characteristics_of, getattr(self.connector, "abilities", None)
            )
        except Exception as exc:  # the check is a help: it must not prevent the run
            logger.warning("the instruments could not be compared: %s", exc)
            return True, None
        if not findings:
            return True, None
        from frontend.ui.CompatibilityDialog import CompatibilityDialog

        dialog = CompatibilityDialog(findings, self.translator, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False, None
        return True, findings

    def _confirm_wiring(self, ref: MeasurementRef) -> bool:
        """Before a run: show the diagram and ask to start. False if the user cancels."""
        if not self.wiring_before_run:
            return True
        dialog = self._wiring_dialog(ref, confirm=True)
        if dialog is None:
            return True
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        keep = dialog.show_before.isChecked()
        if keep != self.wiring_before_run:
            self.wiring_before_run = keep
            if self.on_wiring_preference is not None:
                self.on_wiring_preference(keep)
        return accepted

    def _confirm_waves(self, ref: MeasurementRef) -> bool:
        """Before a run that takes waveforms: if they will take more than about a gigabyte of
        disk, say how much and ask to start. False if the user cancels."""
        estimate = self.session.wave_estimate(ref)
        if estimate is None or estimate["bytes"] <= WARN_BYTES:
            return True
        answer = QMessageBox.question(
            self,
            self._t("prj_title"),
            self._t(
                "prj_waves_confirm",
                size=f"{estimate['bytes'] / 1e9:.1f} GB",
                waveforms=estimate["waveforms"],
                captures=estimate["captures"],
            ),
        )
        return answer == QMessageBox.StandardButton.Yes

    def run_measurement(self) -> None:
        """Start the selected measurement in a run window."""
        ref = self._selected()
        if ref is None:
            return
        if not self._confirm_wiring(ref):
            return
        if not self._confirm_waves(ref):
            return
        proceed, accepted = self._check_compatibility(ref)
        if not proceed:
            return
        variant = None
        question = self.session.variant_question(ref)
        if question is not None:  # a DUT is named: what is different in it since the last run?
            from frontend.ui.VariantTable import VariantDialog

            asking = VariantDialog(question, self.translator, self)
            if not asking.exec():
                return
            variant = asking.variant()
        try:
            runner, run_file = self.session.build_runner(
                ref,
                accepted_differences=accepted,
                bench=True if self.bench_check.isChecked() else None,  # None: OLA_BENCH decides
                variant=variant,
                # a measurement that fails is deleted when it ends, unless the settings keep it
                keep_failed=QSettings("LabAutomation", "App").value(
                    "keep_failed_runs", False, type=bool
                ),
            )
        except MeasurementError as exc:
            show_problem(self, self._t("prj_title"), self._t("prj_cannot_run", error=exc), code="MEAS-003", exception=exc, level="critical")
            return
        for warning in self.session.calibration_warnings:  # reported, the run is not blocked
            QMessageBox.warning(
                self,
                self._t("prj_title"),
                self._t("prj_calibration_lost", name=warning["instrument"]),
            )
        from frontend.ui.RunWindow import RunWindow

        window = RunWindow(
            runner, self.translator, run_file=str(run_file), title=ref.name, auto_start=True
        )
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.run_windows.append(window)
        window.show()

    def rename_measurement(self) -> None:
        ref = self._selected()
        if ref is None:
            return
        name, ok = QInputDialog.getText(
            self, self._t("prj_rename"), self._t("prj_new_name"), text=ref.name
        )
        if ok and name.strip():
            self.session.rename(ref.id, name)
            self._refresh()

    def remove_measurement(self) -> None:
        ref = self._selected()
        if ref is None:
            return
        box = QMessageBox(self)
        box.setWindowTitle(self._t("prj_remove"))
        box.setText(self._t("prj_confirm_remove", name=ref.name, file=ref.file))
        only = box.addButton(self._t("prj_remove_keep"), QMessageBox.ButtonRole.AcceptRole)
        both = box.addButton(self._t("prj_remove_delete"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(self._t("prj_cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(only)
        box.exec()
        clicked = box.clickedButton()
        if clicked in (only, both):
            self.session.remove(ref.id, delete_file=clicked is both)
            self._refresh()

    # ================================================================ runs
    def _selected_run(self) -> Optional[Path]:
        row = self.runs_table.currentRow()
        paths = getattr(self, "_run_paths", [])
        return paths[row] if 0 <= row < len(paths) else None

    def _check_finished_runs(self) -> None:
        """When a run window has just finished, tell the sidebar: the measurement file gets its
        arrow (and the new run is listed) at once, without waiting for the next check."""
        done = {id(w) for w in self.run_windows if w.model.finished}
        if done != getattr(self, "_finished_windows", set()):
            self._finished_windows = done
            self.project_changed.emit()

    def _refresh_runs(self) -> None:
        self._check_finished_runs()
        ref = self._selected()
        paths = self.session.runs(ref) if (ref and self.session) else []
        summaries = [(p, self.session.describe_run(p)) for p in paths]
        key = [(p.name, s["state"], s["points"]) for p, s in summaries]
        if key == getattr(self, "_runs_key", None):
            return  # nothing changed: keep the selection and the scroll position
        self._runs_key = key
        keep = self._selected_run()
        self._run_paths = paths
        self.runs_table.setRowCount(0)
        for path, summary in summaries:
            row = self.runs_table.rowCount()
            self.runs_table.insertRow(row)
            state = self._t(f"prj_state_{summary['state']}")
            for column, text in enumerate((summary["file"], state, str(summary["points"]))):
                self.runs_table.setItem(row, column, QTableWidgetItem(text))
            if path == keep:
                self.runs_table.selectRow(row)
        self._update_buttons()

    def delete_run(self) -> None:
        """Delete the selected run (its file and its waveform files), after asking."""
        path = self._selected_run()
        if path is not None:
            self.delete_run_path(path)

    def delete_run_path(self, path: Path) -> bool:
        """Delete a run **from the disk** (its file and the folder of its waveforms), after asking
        (the sidebar of the main window uses it too). True if it was deleted."""
        ask = QMessageBox.question(
            self, self._t("prj_delete"), self._t("prj_delete_confirm", file=path.name)
        )
        if ask != QMessageBox.StandardButton.Yes:
            return False
        from ola.runs import delete_run

        try:
            delete_run(path)
        except (OSError, ValueError) as exc:
            show_problem(
                self,
                self._t("prj_title"),
                self._t("prj_delete_failed", file=path.name, error=exc),
                code="AST-004",
                exception=exc,
            )
            return False
        self._runs_key = None  # the list of the runs is read again
        self._refresh_runs()
        self.project_changed.emit()  # the sidebar lists the runs too
        return True

    def run_files(self, file_name: str) -> List[Tuple[Path, str]]:
        """The runs of the measurement in this file, newest first, each with how it ended
        (``finished``, ``stopped``, ``failed``, ``interrupted``): from the last lines of the files
        only, so it is cheap. Empty if no measurement uses the file."""
        ref = self.ref_for_file(file_name)
        if ref is None or self.session is None:
            return []
        from ola.runs import end_state

        return [(p, end_state(p)) for p in self.session.runs(ref)]

    def open_run(self, path: Path) -> bool:
        """Open a run that was made before in the run window: its table, plots, curves, waveforms
        and log, as they were (``ola.run_replay``). False, with the reason shown, if the file
        cannot be read."""
        from frontend.ui.RunWindow import RunWindow
        from ola.run_replay import ReplayError, ReplayRunner

        try:
            runner = ReplayRunner(path)
        except ReplayError as exc:
            show_problem(
                self,
                self._t("prj_title"),
                self._t("prj_open_run_failed", file=path.name, error=exc),
                code="MEAS-007",
                exception=exc,
            )
            return False
        window = RunWindow(runner, self.translator, run_file=str(path), title=path.stem)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.run_windows.append(window)
        window.show()
        window._tick()  # it opens filled, not empty for the first tenth of a second
        return True

    def show_waves(self) -> None:
        """Open the waveforms of the selected run (the binary files next to the run file)."""
        path = self._selected_run()
        if path is None:
            return
        from frontend.ui.WaveformView import WaveformDialog

        self._waves_dialog = WaveformDialog(str(path), self.translator, self)
        self._waves_dialog.show()

    def compare_runs(self) -> None:
        """Open the comparison tool with the runs of the selected measurement."""
        from frontend.ui.CompareDialog import CompareDialog

        paths = [str(p) for p in getattr(self, "_run_paths", [])]
        start = str(self.session.run_dir) if self.session is not None else ""
        self._compare_tool = CompareDialog(paths, self.translator, self, start)
        self._compare_tool.show()

    def export_run(self) -> None:
        path = self._selected_run()
        if path is None:
            return
        target, _ = QFileDialog.getSaveFileName(
            self, self._t("prj_export"), str(path.with_suffix(".csv")), "CSV (*.csv)"
        )
        if not target:
            return
        try:
            n = export_points_csv(path, target)
        except Exception as exc:
            show_problem(
                self,
                self._t("prj_title"),
                self._t("prj_export_failed", error=exc),
                code="MEAS-004",
                exception=exc,
                level="critical",
            )
            return
        QMessageBox.information(
            self, self._t("prj_title"), self._t("prj_export_done", n=n, path=target)
        )

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt name)
        running = [w for w in self.run_windows if not w.model.finished and w.model.state != "idle"]
        if running:
            answer = QMessageBox.question(
                self, self._t("prj_title"), self._t("prj_confirm_close", n=len(running))
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        timer = getattr(self, "_mapping_timer", None)
        if timer is not None:  # a window that is closed does not offer anything any more
            timer.stop()
        for window in running:  # stop them first, so that their own windows do not ask again
            window.runner.stop()
            window.runner.join(15)
            window._tick()
        for window in self.run_windows:
            window.close()
        if any(w.isVisible() for w in self.run_windows):  # a run window refused to close
            event.ignore()
            return
        self._timer.stop()
        self._close_connector()
        event.accept()


def not_connected(name: str, cancel=None):
    """The ``connect`` of an application that cannot reach instruments yet: raises, and the project
    window shows "cannot reach instrument '<name>': ..." instead of starting. Replace it with a
    function that returns the handle of the instrument ``name`` of the project."""
    raise RuntimeError("the connection to the instruments is not available in this build yet")


def demo_project(folder: str):
    """A project with one efficiency measurement for the simulated lab (``DemoLab``); the file
    names the instruments it uses, as the efficiency editor writes it."""
    from ola.demo_lab import INSTRUMENTS, demo_params

    registry = default_registry()
    project = Project.new("Demo", folder)
    ref = project.add_measurement("efficiency", "Demo converter", registry)
    MeasurementFile(
        type="efficiency",
        module_version=registry.get("efficiency").version,
        role_bindings={"instruments": list(INSTRUMENTS)},
        params=demo_params(samples=3, interval_s=0.2),
    ).save(project.directory / ref.file)
    project.save()
    return project


def main(argv: Optional[list] = None) -> int:
    """Open a project (or a demo one with simulated instruments)."""
    from ola.demo_lab import DemoHandle, DemoLab

    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv)
    if argv:
        window = ProjectWindow()
        window.open_path(argv[0])
    else:
        lab = DemoLab(delay_s=0.05)
        folder = tempfile.mkdtemp(prefix="ola_demo_")
        window = ProjectWindow(
            demo_project(folder), connect=lambda name, cancel=None: DemoHandle(name, lab)
        )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
