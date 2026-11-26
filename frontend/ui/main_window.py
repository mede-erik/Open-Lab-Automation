# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""
Main application window for Lab Automation.

This module contains the MainWindow class and related dialog classes
that handle the main UI functionality including project management,
file operations, and instrument configuration.
"""

import os
from pathlib import Path
import json
import uuid
import datetime
import logging

logger = logging.getLogger('frontend.ui.main_window')
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel, QDialog, 
    QPushButton, QHBoxLayout, QComboBox, QFileDialog, QListWidget, 
    QListWidgetItem, QInputDialog, QLineEdit, QMessageBox, QMenu,
    QSplitter
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QSettings, QTimer

from frontend.ui.RemoteControlTab import RemoteControlTab
from frontend.ui.ProjectFilesList import RUN_ROLE, RUNS_ROLE, ProjectFilesList
from frontend.ui.ProjectWindow import ProjectWindow, not_connected
from frontend.ui.connector_setup import default_library_path, make_connector
from frontend.ui.SettingsDialog import SettingsDialog
from frontend.core.Translator import Translator
from frontend.ui.WasFileDialog import WasFileDialog
from frontend.ui.InstrumentConfigDialog import InstrumentConfigDialog
from frontend.ui.InstrumentLibraryDialog import InstrumentLibraryDialog
from frontend.ui.HexDecConverterDialog import HexDecConverterDialog
from frontend.ui.GpibAdapterDialog import GpibAdapterDialog
from frontend.ui.CompareDialog import CompareDialog
from frontend.ui.AssetsDialog import AssetsDialog
from frontend.ui.DutsDialog import DutsDialog
from ola.assets import AssetError, AssetRegistry
from ola.duts import DutRegistry
from ola.duts import default_path as default_duts_path
from ola.measurement import MeasurementError
from ola.project import LEGACY_KEYS, Project
from ola.assets import default_path as default_assets_path
from frontend.ui.module_translator import CatalogTranslator
from frontend.ui.PulseGeneratorDialog import PulseGeneratorDialog
from frontend.core.LoadInstruments import LoadInstruments, get_library_path
from frontend.core.logger import Logger
from frontend.core.errorhandler import ErrorHandler
from frontend.core.tools import read_json, save_json
from frontend.core.errorhandler import settings_translator, show_problem
class MainWindow(QMainWindow):
    def reload_remote_tab_instruments(self):
        """
        Ricarica gli strumenti nella RemoteControlTab dal file .inst corrente del progetto.
        """
        if not self.current_project_dir or not self.current_project_data:
            return
        inst_file = self.current_project_data.get('inst_file')
        if not inst_file:
            self.logger.debug("No instruments file in project, skipping reload")
            return
        inst_path = os.path.join(self.current_project_dir, inst_file)
        if not os.path.exists(inst_path):
            self.logger.warning(f"Instruments file not found: {inst_path}")
            return
        if hasattr(self, 'remote_tab'):
            self.remote_tab.load_instruments(inst_path)
    """
    Main application window. Handles project management, file operations, instrument configuration,
    and main UI tabs (remote control, project files, etc.).
    """
    
    def __init__(self):
        """
        Initialize the main window, load app info, and set up UI components.
        """
        self.logger = Logger()
        self.logger.debug("MainWindow.__init__ started.")
        # Initialize translator early
        self.translator = Translator()
        # The saved language is applied now, before any tab is built: the tabs read the language
        # when they are created (the Measurements tab stayed English because it was built first)
        self.translator.set_language(
            QSettings('LabAutomation', 'App').value('language', self.translator.current_lang))
        self.logger.debug("Translator initialized.")
        super().__init__()
        # Initialize error handler
        self.error_handler = ErrorHandler()
        self.logger.debug("ErrorHandler initialized.")
        # Load app info from JSON
        appinfo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'appinfo.json')
        try:
            self.appinfo = read_json(appinfo_path)
            self.logger.debug(f"App info loaded: {self.appinfo.get('app_name')} v{self.appinfo.get('version')}")
        except Exception as e:
            self.logger.error(f"Failed to load appinfo.json: {e}", exc_info=True)
            self.error_handler.handle_error(
                e, settings_translator().t("err_appinfo_failed"), code="CFG-006")
            self.appinfo = {"app_name": "Lab Automation", "version": "1.0"}
            
        self.setWindowTitle(self.appinfo.get('app_name', 'Lab Automation'))
        
        
        # Initialize LoadInstruments with error handling
        self.logger.debug("Initializing LoadInstruments...")
        try:
            self.load_instruments = LoadInstruments()
            lib_path = get_library_path()
            if not self.load_instruments.load_instruments(lib_path):
                raise FileNotFoundError(f"Instrument library not found or invalid: {lib_path}")
            self.logger.debug(f"LoadInstruments initialized successfully with library: {lib_path}")
        except Exception as e:
            self.logger.error(f"Error initializing LoadInstruments: {e}", exc_info=True)
            self.error_handler.handle_error(
                e, settings_translator().t("err_library_failed"), code="LIB-001")
            self.load_instruments = None
            
        self.tabs = QTabWidget()
        self.logger.debug("QTabWidget created.")
        
        # Pass load_instruments to RemoteControlTab with error checking
        if self.load_instruments is None:
            self.logger.warning("LoadInstruments is None, creating RemoteControlTab with empty instruments")
        
        self.remote_tab = RemoteControlTab(self.load_instruments)
        self.remote_tab.project_source = self.open_project_source
        self.tabs.addTab(self.remote_tab, self.translator.t('remote_control'))
        
        # Tab "Measurements": the projects of format 2 (measurements, editors, run window).
        # The instruments are reached through the library and the project's .inst file
        # (frontend/ui/connector_setup.py); `not_connected` is the fallback if that is not possible.
        self.assets = self._open_assets()  # the registry of cables and devices (or None)
        self.duts = self._open_duts()  # the archive of the devices under test (or None)
        self.project_tab = ProjectWindow(
            translator=self.translator,
            assets=self.assets,
            duts=self.duts,
            connect=not_connected,
            connector_factory=lambda session: make_connector(
                session, default_library_path(), self.translator, self
            ),
            wiring_before_run=self._wiring_preference(),
            on_wiring_preference=self._save_wiring_preference,
        )
        self.project_tab.project_changed.connect(self.refresh_project_files)
        self.tabs.addTab(self.project_tab, self.project_tab.tr_.t('prj_tab'))

        self.project_files_list = ProjectFilesList()
        self.project_files_list.arrow_clicked.connect(self.toggle_runs)
        self._expanded_runs = set()  # the measurement files whose runs are listed under them
        self._runs_signature = None
        # runs are made and deleted while the program is open: the open lists follow them
        self._runs_timer = QTimer(self)
        self._runs_timer.setInterval(2000)
        self._runs_timer.timeout.connect(self._check_runs)
        self._runs_timer.start()
        self.logger.debug("UI tabs and lists created.")
        
        # Layout: tabs on the right, file list on the left
        central_widget = QWidget()
        main_layout = QHBoxLayout()
        
        # Create a splitter to make the file list resizable
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self.project_files_list)
        self.splitter.addWidget(self.tabs)
        
        # The file list is narrow, the tabs take the rest; the border can be moved. (The sizes were
        # computed from the window before it was shown, 1/7 of a 640 px window: names were cut.)
        self.project_files_list.setMinimumWidth(150)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 1000])

        main_layout.addWidget(self.splitter)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        
        self.current_project_dir = None
        self.current_project_data = None
        self.settings_dialog = None
        
        self.logger.debug("Initializing menu...")
        self.init_menu()
        self.logger.debug("Loading settings...")
        self.load_settings()
        self.logger.debug("Updating translations...")
        self.update_translations()
        
        self.project_files_list.itemDoubleClicked.connect(self.edit_project_file)
        
        # Always start maximized/fullscreen
        self.logger.debug("Maximizing window.")
        self.showMaximized()
        
        # Open last project if available
        self.logger.debug("Checking for last opened project.")
        settings = QSettings('LabAutomation', 'App')
        last_project_path = settings.value('last_project_path', '', type=str)
        if last_project_path and os.path.isfile(last_project_path):
            self.logger.debug(f"Found last project at: {last_project_path}")
            try:
                project_data = self._open_project_path(last_project_path)
                self.logger.set_project_directory(self.current_project_dir)
                self.logger.info(f"Successfully loaded last project: {project_data.get('project_name')}")
            except Exception as e:
                self.logger.error(f"Failed to load last project: {last_project_path} - {e}", exc_info=True)
                self.error_handler.handle_error(
                    e, settings_translator().t("err_last_project_failed").format(path=last_project_path),
                    code="PROJ-005")

                self.logger.set_project_directory(self.current_project_dir)
        self.project_files_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.project_files_list.customContextMenuRequested.connect(self.show_file_context_menu)
        self.logger.debug("MainWindow.__init__ finished.")

    def init_menu(self):
        """
        Initialize the menubar and its menus/actions.
        """
        self.logger.debug("Initializing menubar.")
        menubar = self.menuBar()
        menubar.clear()
        
        # Project menu
        project_menu = menubar.addMenu(self.translator.t('project'))
        
        new_project_action = QAction(self.translator.t('create_new_project'), self)
        new_project_action.triggered.connect(self.create_new_project)
        project_menu.addAction(new_project_action)
        
        open_project_action = QAction(self.translator.t('open_project'), self)
        open_project_action.triggered.connect(self.open_project)
        project_menu.addAction(open_project_action)
        
        add_file_action = QAction(self.translator.t('add_file'), self)
        add_file_action.triggered.connect(self.add_project_file)
        project_menu.addAction(add_file_action)
        
        add_existing_action = QAction(self.translator.t('add_existing_file'), self)
        add_existing_action.triggered.connect(self.add_existing_file)
        project_menu.addAction(add_existing_action)
        
        # Settings menu
        settings_menu = menubar.addMenu(self.translator.t('settings'))
        
        settings_action = QAction(self.translator.t('open_settings'), self)
        settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(settings_action)
        
        
        # Help menu
        help_menu = menubar.addMenu(self.translator.t('help'))
        
        info_action = QAction(self.translator.t('about_software'), self)
        info_action.triggered.connect(self.show_software_info)
        help_menu.addAction(info_action)
        
        # Tools menu
        tools_menu = menubar.addMenu(self.translator.t('tools'))
        
        manage_lib_action = QAction(self.translator.t('manage_instrument_library'), self)
        manage_lib_action.triggered.connect(self.open_instrument_library_dialog)
        tools_menu.addAction(manage_lib_action)
        
        hexdec_action = QAction(self.translator.t('hex_dec_converter'), self)
        hexdec_action.triggered.connect(self.open_hexdec_converter)
        tools_menu.addAction(hexdec_action)
        
        # Compare saved results (two cables, a filter before and after...)
        compare_action = QAction(CatalogTranslator("compare", self.translator).t("cmp_menu"), self)
        compare_action.triggered.connect(self.open_compare_tool)
        tools_menu.addAction(compare_action)
        
        # Cables and devices: codes, cards and labels
        assets_action = QAction(CatalogTranslator("assets", self.translator).t("ast_menu"), self)
        assets_action.triggered.connect(self.open_assets_tool)
        tools_menu.addAction(assets_action)

        # DUT: the devices under test (antennas, filters, converters...), with codes and versions
        duts_action = QAction(CatalogTranslator("duts", self.translator).t("dut_menu"), self)
        duts_action.triggered.connect(self.open_duts_tool)
        tools_menu.addAction(duts_action)
        
        # Kits of resistors (the power resistors of the bench, used in many measurements)
        resistors_action = QAction(
            CatalogTranslator("resistors", self.translator).t("res_menu"), self
        )
        resistors_action.triggered.connect(self.open_resistor_kits_tool)
        tools_menu.addAction(resistors_action)

        # GPIB adapters (Keysight 82357B, NI GPIB-USB-HS, Prologix, AR488...): set up and scan
        gpib_action = QAction(CatalogTranslator("gpib", self.translator).t("gpb_menu"), self)
        gpib_action.triggered.connect(self.open_gpib_adapter_tool)
        tools_menu.addAction(gpib_action)
        
        # Pulse Generator Tool
        pulse_gen_action = QAction(self.translator.t('pulse_generator_tool'), self)
        pulse_gen_action.triggered.connect(self.open_pulse_generator)
        tools_menu.addAction(pulse_gen_action)
        
        self.logger.debug("Menubar initialized.")

    def show_software_info(self):
        """
        Show information about the software in a message box.
        """
        self.logger.debug("Showing software info dialog.")
        info = self.appinfo
        text = f"<b>{info.get('app_name','')}</b><br>Version: {info.get('version','')}<br>Author: {info.get('author','')}<br>"
        repo = info.get('repository','')
        if repo:
            text += f"<br><a href='{repo}'>Repository</a>"
        
        msg = QMessageBox(self)
        msg.setWindowTitle(self.translator.t('about_software'))
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def create_new_project(self):
        """
        Create a new project: select folder, enter project name, and create .json and .inst files.
        """
        self.logger.debug("Starting new project creation...")
        
        dir_path = QFileDialog.getExistingDirectory(self, self.translator.t('select_project_folder'))
        if not dir_path:
            self.logger.warning("New project creation cancelled: No directory selected.")
            return
            
        self.logger.debug(f"Selected directory: {dir_path}")
        
        project_name, ok = QInputDialog.getText(self, self.translator.t('project'), self.translator.t('enter_project_name'))
        if not ok or not project_name.strip():
            self.logger.warning("New project creation cancelled: No project name entered.")
            return
            
        try:
            project_id = str(uuid.uuid4())
            now = datetime.datetime.now().isoformat()
            self.logger.debug(f"Creating project: {project_name} (ID: {project_id})")
            
            # Load naming settings
            self.logger.debug("Loading naming settings for new project.")
            settings = QSettings('LabAutomation', 'App')
            adv_naming = settings.value('advanced_naming', False, type=bool)
            adv_inst = settings.value('advanced_naming_inst', False, type=bool)
            
            # Create file names
            inst_base = project_name.strip()
            if adv_naming and adv_inst:
                inst_file = f"{inst_base}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.inst"
            else:
                inst_file = f"{inst_base}.inst"
            
            json_file = f"{inst_base}.json"
            self.logger.debug(f"Generated filenames: project='{json_file}', instruments='{inst_file}'")
            
            # Create project data
            project_data = {
                "format_version": 2,
                "measurements": [],
                "project_id": project_id,
                "created_at": now,
                "last_opened": now,
                "project_name": project_name.strip(),
                "inst_file": inst_file,
                "scope_settings": None
            }
            
            # Save project file
            project_file = os.path.join(dir_path, json_file)
            self.logger.debug(f"Saving project file to: {project_file}")
            save_json(project_data, project_file)
            
            # Create instruments file
            inst_data = {"instruments": []}
            inst_path = os.path.join(dir_path, inst_file)
            self.logger.debug(f"Saving instruments file to: {inst_path}")
            save_json(inst_data, inst_path)
            
            self._open_project_path(project_file)
            self.logger.set_project_directory(self.current_project_dir)
            
            self.logger.debug(f"Project '{project_name}' created successfully in '{dir_path}'.")
            QMessageBox.information(self, self.translator.t('project'), 
                                  self.translator.t('project_created')+f'\\n{dir_path}')
            
            # Save last project path
            settings.setValue('last_project_path', project_file)
            
            # Ask if add file now
            self.logger.debug("Asking user to add a file to the new project.")
            reply = QMessageBox.question(self, self.translator.t('add_file'), 
                                       self.translator.t('add_file_now'), 
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.logger.debug("User chose to add a file now.")
                self.add_project_file()
            else:
                self.logger.debug("User chose not to add a file now.")
                
        except Exception as e:
            self.logger.error(f"Failed to create new project: {e}", exc_info=True)
            self.error_handler.handle_error(
                e, settings_translator().t("err_new_project_failed"), code="PROJ-004")



    def load_settings(self):
        """
        Load settings from QSettings and apply them to the application.
        """
        self.logger.debug("Loading application settings.")
        settings = QSettings('LabAutomation', 'App')
        lang = settings.value('language', self.translator.current_lang)
        theme = settings.value('theme', 'dark', type=str)  # Default: dark
        
        self.logger.debug(f"Setting language to '{lang}'.")
        self.translator.set_language(lang)
        
        self.logger.debug(f"Applying theme: {theme}")
        self.apply_theme(theme)
        self.logger.debug("Settings loaded.")

    def apply_theme(self, theme_option):
        """
        Apply the selected theme (system, dark, light, modern_dark, dark_modern, ultra_modern, ultra_modern_dark).
        :param theme_option: 'system', 'dark', 'light', 'modern_dark', 'dark_modern', 'ultra_modern', 'ultra_modern_dark'
        """
        logger.debug(f"apply_theme({theme_option})")
        
        # Map theme names to QSS files
        theme_files = {
            'dark': 'dark_theme.qss',
            'light': 'light_theme.qss'
            # 'modern_dark': 'modern_dark.qss',
            # 'dark_modern': 'dark_modern.qss'
        }
        
        if theme_option == 'system':
            try:
                from PyQt6.QtGui import QGuiApplication
                from PyQt6.QtCore import Qt
                if hasattr(Qt, 'ColorScheme'):
                    color_scheme = QGuiApplication.styleHints().colorScheme()
                    logger.debug(f"System color scheme: {color_scheme}")
                    if color_scheme == Qt.ColorScheme.Dark:
                        self.load_theme_file('dark_theme.qss')
                    else:
                        self.load_theme_file('light_theme.qss')
                else:
                    logger.warning("System theme detection not supported, defaulting to dark")
                    self.load_theme_file('dark_theme.qss')
            except Exception as e:
                logger.error(f"System theme detection failed: {e}, defaulting to dark")
                self.load_theme_file('dark_theme.qss')
        elif theme_option in theme_files:
            logger.debug(f"Applying theme: {theme_option}")
            self.load_theme_file(theme_files[theme_option])
        else:
            logger.warning(f"Unknown theme: {theme_option}, defaulting to dark")
            self.load_theme_file('dark_theme.qss')
        
        settings = QSettings('LabAutomation', 'App')
        settings.setValue('theme', theme_option)

    def load_theme_file(self, theme_filename):
        """
        Load and apply a QSS theme file from the assets/styles directory.
        :param theme_filename: Name of the QSS file (e.g., 'dark_theme.qss')
        """
        logger.debug(f"Loading theme file: {theme_filename}")
        
        # Build path to theme file
        styles_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'assets', 'styles'
        )
        theme_path = os.path.join(styles_dir, theme_filename)
        
        # Load and apply the stylesheet
        try:
            if os.path.exists(theme_path):
                with open(theme_path, 'r', encoding='utf-8') as f:
                    stylesheet = f.read()
                    # The icons of the theme (arrows) are found by their real path
                    icons_dir = os.path.join(os.path.dirname(styles_dir), 'icons').replace('\\', '/')
                    stylesheet = stylesheet.replace('@ICONS@', icons_dir)
                    self.setStyleSheet(stylesheet)
                    # The themes are style sheets, so the Qt palette does not say whether the
                    # background is dark: the code that picks a text colour reads this instead
                    app = QApplication.instance()
                    if app is not None:
                        app.setProperty('ola_dark_theme', theme_filename.startswith('dark'))
                    logger.info(f"Theme '{theme_filename}' applied ({len(stylesheet)} chars)")
            else:
                logger.warning(f"Theme file not found: {theme_path}, using defaults")
                self.setStyleSheet("")
        except Exception as e:
            logger.error(f"Error loading theme file {theme_filename}: {e}")
            self.setStyleSheet("")
    
    def update_translations(self):
        """
        Update the UI texts and menus according to the current language.
        """
        self.logger.debug("Updating UI translations.")
        self.setWindowTitle(self.appinfo.get('app_name', 'Lab Automation'))
        self.tabs.setTabText(0, self.translator.t('remote_control'))
        self.init_menu()
        self.remote_tab.update_translation(self.translator)
        # the Measurements tab: its texts and its tab title
        self.project_tab.retranslate()
        self.tabs.setTabText(self.tabs.indexOf(self.project_tab), self.project_tab.tr_.t('prj_tab'))
        self.logger.debug("UI translations updated.")

    def confirm_project_upgrade(self, path) -> bool:
        """Ask before an old project file is changed: the file is copied to a ``.bkp`` next to it
        first. True to go on. Tests replace this method to give the answer."""
        backup = Project.backup_path(path)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.translator.t("project_upgrade_title"))
        box.setText(
            self.translator.t("project_upgrade_question")
            .replace("{name}", os.path.basename(str(path)))
            .replace("{backup}", backup.name)
        )
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        return box.exec() == QMessageBox.StandardButton.Yes

    def show_upgrade_report(self, report) -> None:
        """Say what became of the efficiency files of an old project (one line each, with what
        is still to do). Tests replace this method."""
        lines = []
        for item in report:
            head = self.translator.t(
                "project_upgrade_converted" if item.converted else "project_upgrade_kept"
            ).replace("{file}", item.file)
            lines.append(head + "".join(f"\n    - {note}" for note in item.notes))
        QMessageBox.information(
            self, self.translator.t("project_upgrade_title"), "\n".join(lines)
        )

    def _open_project_path(self, path):
        """Open a project file in both views: the Project menu and file list (this window) and the
        Measurements tab. A project of the first format is upgraded in place after the user agrees (a copy is kept in
        ``.bkp``; it keeps every key and gains an empty list of measurements). Returns the data of the project."""
        if Project.needs_upgrade(path):
            if not self.confirm_project_upgrade(path):
                raise MeasurementError(self.translator.t("project_upgrade_declined"))
            report = []
            Project.upgrade_legacy(path, report=report)  # copies the file to ``.bkp`` first
            if report:
                self.show_upgrade_report(report)
        self._loaded_inst_path = None
        data = read_json(path)
        self.current_project_dir = os.path.dirname(path)
        self.current_project_data = data
        self.project_tab.open_path(path)  # redraws the tab, which refreshes the file list
        self.refresh_project_files()
        return data

    # Placeholder methods - these need to be implemented based on the full original code
    def open_project(self):
        """Open an existing project: select .json file and load its data."""
        from PyQt6.QtWidgets import QFileDialog
        self.logger.debug("Opening project...")
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.t('open_project'), '',
            f"{self.translator.t('file_filter_project')} (*.json)")
        if file_path:
            try:
                self._open_project_path(file_path)
                # Salva percorso ultimo progetto
                settings = QSettings('LabAutomation', 'App')
                settings.setValue('last_project_path', file_path)
                self.logger.info(f"Project opened: {file_path}")
            except Exception as e:
                self.logger.error(f"Failed to open project: {file_path} - {e}", exc_info=True)
                show_problem(self, self.translator.t('open_project'), f"{self.translator.t('project_open_failed')}: {e}", code="PROJ-005", exception=e)
        
    def open_project_source(self):
        """What the remote control needs to know about the open project (see
        ``RemoteControlTab.project_source``): its folder, instruments file and active scope
        settings, or None if no project is open."""
        session = self.project_tab.session
        if not self.current_project_dir or not self.current_project_data or session is None:
            return None
        return {
            "dir": self.current_project_dir,
            "project_file": str(session.project.path),  # where the saved calibrations are listed
            "inst_file": self.current_project_data.get('inst_file'),
            # the files that are on, in order, each with the oscilloscope it is for ('' = every one)
            "scope_settings": [
                {"file": f, "scope": session.project.scope_target(f)}
                for f in session.project.active_scope_files()
            ],
        }

    def refresh_project_files(self):
        """Refresh the list of project files displayed in the UI."""
        self.project_files_list.clear()
        self._runs_signature = None
        if not self.current_project_dir or not self.current_project_data:
            return
        files = []
        inst_file = self.current_project_data.get('inst_file')
        if inst_file:
            files.append(inst_file)
        session = self.project_tab.session
        if session is not None:  # the measurements of the project (every type)
            files += [m.file for m in session.project.measurements]
        project = session.project if session is not None else None
        disabled = set()
        if project is not None:  # the settings of the oscilloscopes: project definition files
            for entry in project.scope_settings:
                if entry['file'] not in files:
                    files.append(entry['file'])
                if not entry['enabled']:
                    disabled.add(entry['file'])
        for f in files:
            item = QListWidgetItem(f)
            if f in disabled:  # kept in the project, but not the one that is applied
                font = item.font()
                font.setItalic(True)
                item.setFont(font)
                item.setToolTip(self.translator.t('scope_file_disabled'))
            target = project.scope_target(f) if project is not None else ''
            if target:  # a file for one oscilloscope: the tooltip says which
                tip = self.translator.t('scope_file_for').format(scope=target)
                item.setToolTip((item.toolTip() + ' ' if item.toolTip() else '') + tip)
            self.project_files_list.addItem(item)
            self._add_run_rows(item, f)
        
        # Aggiorna RemoteControlTab caricando gli strumenti dal file .inst
        if hasattr(self, 'remote_tab') and inst_file:
            inst_path = os.path.join(self.current_project_dir, inst_file)
            if getattr(self, '_loaded_inst_path', None) == inst_path:
                return  # already shown (the list is redrawn at every change of the measurements)
            if os.path.exists(inst_path):
                self._loaded_inst_path = inst_path
                self.logger.info(f"Loading instruments in RemoteControlTab: {inst_path}")
                self.remote_tab.load_instruments(inst_path)
            else:
                self.logger.warning(f"Instruments file not found: {inst_path}")
    
    def _run_path(self, item):
        """The run file of a row of the list that stands for a run (None for the other rows)."""
        path = item.data(RUN_ROLE)
        return Path(path) if path else None

    def _add_run_rows(self, item, file_name):
        """A measurement file that has runs gets an arrow; when it is open, its runs are listed under
        it, newest first, each with the name of its file (double click to open it)."""
        runs = self.project_tab.run_files(file_name)
        if not runs:
            return
        opened = file_name in self._expanded_runs
        item.setData(RUNS_ROLE, opened)
        tip = self.translator.t('sidebar_runs_tip').format(n=len(runs))
        item.setToolTip((item.toolTip() + ' ' if item.toolTip() else '') + tip)
        if not opened:
            return
        for path, state in runs:
            row = QListWidgetItem('      ' + path.name)
            row.setData(RUN_ROLE, str(path))
            label = self.project_tab.tr_.t(f'prj_state_{state}')
            row.setToolTip(self.translator.t('sidebar_run_tip').format(state=label))
            font = row.font()
            font.setItalic(state != 'finished')  # a run that did not finish is in italics
            row.setFont(font)
            self.project_files_list.addItem(row)

    def toggle_runs(self, item):
        """The arrow of a measurement file: show or hide the runs under it."""
        name = item.text()
        if name in self._expanded_runs:
            self._expanded_runs.discard(name)
        else:
            self._expanded_runs.add(name)
        self.refresh_project_files()

    def _check_runs(self):
        """Redraw the list if the runs of a measurement of the project changed (a run was made,
        ended or deleted since). The files with the runs shown are watched with the state of each
        run; the others only for having runs or not, which is what their arrow depends on."""
        session = self.project_tab.session
        if session is None or not self.current_project_dir:
            return
        signature = []
        for ref in session.project.measurements:
            if ref.file in self._expanded_runs:
                signature.append((ref.file, tuple(self.project_tab.run_files(ref.file))))
            else:
                signature.append((ref.file, bool(session.runs(ref))))
        signature = tuple(signature)
        if signature != self._runs_signature:
            self.refresh_project_files()
            self._runs_signature = signature

    def add_project_file(self):
        """Add a new file to the project: a measurement of any type, or oscilloscope settings."""
        from PyQt6.QtWidgets import QDialog
        if not self.current_project_dir or not self.current_project_data:
            show_problem(self, self.translator.t('add_file'), self.translator.t('no_project_open'), code="PROJ-009")
            return
        session = self.project_tab.session
        types = session.module_types() if session is not None else []
        dlg = AddFileDialog(self, self.translator, measurement_types=types)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        kind = dlg.type_combo.currentData()
        file_name = dlg.name_edit.text().strip()
        if not file_name:
            return
        try:
            if kind == '.was':  # oscilloscope settings: still a plain file listed in the project
                if not file_name.endswith('.was'):
                    file_name += '.was'
                file_path = os.path.join(self.current_project_dir, file_name)
                if os.path.exists(file_path):
                    show_problem(self, self.translator.t('add_file'), self.translator.t('file_exists').format(name=file_name), code="FILE-005")
                    return
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write('')
                session.project.add_scope_file(file_name)
                self.save_project_json()
                self.refresh_project_files()
            else:  # a measurement of the chosen type (the tab redraws and refreshes the list)
                ref = session.create(kind, file_name)
                self.project_tab.show_measurement(ref.id)
        except MeasurementError as e:
            show_problem(self, self.translator.t('add_file'), str(e), code="MEAS-009", exception=e)

    def add_existing_file(self):
        """Add an existing file (a measurement of any type, or oscilloscope settings) to the project."""
        if not self.current_project_dir or not self.current_project_data:
            return
        session = self.project_tab.session
        extensions = sorted({t.extension for t in session.module_types()}) if session is not None else []
        patterns = ' '.join(f'*{e}' for e in extensions + ['.was'])
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.translator.t('add_existing_file'), self.current_project_dir,
            f'{self.translator.t("project_files")} ({patterns})')
        if not file_path:
            return
        fname = os.path.basename(file_path)
        dest_path = os.path.join(self.current_project_dir, fname)
        ext = os.path.splitext(fname)[1].lower()
        if ext not in extensions and ext != '.was':
            show_problem(self, self.translator.t('add_existing_file'), self.translator.t('unsupported_file_type'), code="FILE-004")
            return
        try:
            if os.path.abspath(file_path) != os.path.abspath(dest_path) and not os.path.exists(dest_path):
                import shutil
                shutil.copy2(file_path, dest_path)
            if ext == '.was':
                session.project.add_scope_file(fname)
                self.save_project_json()
                self.refresh_project_files()
            else:
                ref = session.adopt(fname)
                self.project_tab.show_measurement(ref.id)
        except MeasurementError as e:
            show_problem(self, self.translator.t('add_existing_file'), str(e), code="MEAS-010", exception=e)

    def save_project_json(self):
        """
        Save the data of the Project menu (instrument file, oscilloscope files, variables) in the
        project file. The file is also written by the Measurements tab, so this only overlays its own
        keys on what is on disk: the list of measurements and the other keys are never touched.
        """
        if not self.current_project_dir or not self.current_project_data:
            self.logger.warning("Cannot save project JSON: project not loaded")
            return
        try:
            from datetime import datetime
            session = self.project_tab.session
            path = str(session.project.path) if session is not None else os.path.join(
                self.current_project_dir, f"{self.current_project_data.get('project_name', 'project')}.json")
            try:
                on_disk = read_json(path)
            except Exception:
                on_disk = {}
            if not isinstance(on_disk, dict):
                on_disk = {}
            self.current_project_data['last_opened'] = datetime.now().isoformat()
            for key in ('last_opened', 'inst_file'):
                if key in self.current_project_data:
                    on_disk[key] = self.current_project_data[key]
            if session is not None:  # the settings of the oscilloscopes come from the project
                project = session.project
                on_disk['scope_settings'] = [dict(e) for e in project.scope_settings]
                for old_key in LEGACY_KEYS:  # keys of the early projects: no longer written
                    on_disk.pop(old_key, None)
                self.current_project_data['scope_settings'] = on_disk['scope_settings']
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(on_disk, f, indent=2, ensure_ascii=False)
            if session is not None:
                session.project.inst_file = on_disk.get('inst_file')
            self.logger.info(f"Project JSON saved: {path}")
        except Exception as e:
            self.logger.error(f"Error saving project JSON: {e}")
            show_problem(
                self,
                self.translator.t('error'),
                f"{self.translator.t('mw_project_save_failed')}\n{e}",
                code="PROJ-004",
                exception=e,
                level="critical",
            )

    def delete_file(self, item):
        """
        Delete a file from the project (removes from list and optionally from disk).
        
        Args:
            item: QListWidgetItem representing the file to delete
        """
        if not self.current_project_dir or not self.current_project_data:
            self.logger.warning("Cannot delete file: project not loaded")
            return
        
        from PyQt6.QtWidgets import QMessageBox
        
        run = self._run_path(item)
        if run is not None:  # a run: after asking, it is deleted from the disk
            self.project_tab.delete_run_path(run)
            return

        file_name = item.text()

        # A measurement of the project: the Measurements tab asks and removes it
        if self.project_tab.remove_file(file_name):
            return

        # Conferma eliminazione
        reply = QMessageBox.question(
            self,
            self.translator.t('delete_file'),
            self.translator.t('mw_delete_file_question').format(file=file_name),
            QMessageBox.StandardButton.Yes | 
            QMessageBox.StandardButton.No | 
            QMessageBox.StandardButton.Discard,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.No:
            return  # Annulla operazione
        
        # Rimuovi dalla lista appropriata
        removed = False
        
        # oscilloscope settings (.was)
        session = self.project_tab.session
        if session is not None and file_name in session.project.scope_file_names():
            session.project.remove_scope_file(file_name)
            removed = True
            self.logger.info(f"Removed '{file_name}' from the scope settings of the project")
        
        # Controlla se è il file .inst
        elif file_name == self.current_project_data.get('inst_file'):
            self.current_project_data['inst_file'] = None
            removed = True
            self.logger.info(f"Removed '{file_name}' from inst_file")
        
        if removed:
            # Salva il progetto aggiornato
            self.save_project_json()
            
            # Se l'utente ha scelto "Discard", elimina anche il file fisico
            if reply == QMessageBox.StandardButton.Discard:
                file_path = os.path.join(self.current_project_dir, file_name)
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        self.logger.info(f"Deleted file from disk: {file_path}")
                        QMessageBox.information(
                            self,
                            self.translator.t('success'),
                            self.translator.t('mw_file_removed_deleted').format(file=file_name)
                        )
                    else:
                        self.logger.warning(f"File not found on disk: {file_path}")
                except Exception as e:
                    self.logger.error(f"Error deleting file from disk: {e}")
                    show_problem(
                        self,
                        self.translator.t('error'),
                        f"{self.translator.t('mw_file_not_deleted')}\n{e}",
                        code="FILE-002",
                        exception=e,
                    )
            else:
                QMessageBox.information(
                    self,
                    self.translator.t('success'),
                    self.translator.t('mw_file_removed').format(file=file_name)
                )
            
            # Aggiorna la lista dei file
            self.refresh_project_files()
        else:
            self.logger.warning(f"File '{file_name}' not found in project data")
            show_problem(
                self,
                self.translator.t('warning'),
                self.translator.t('mw_file_not_in_project').format(file=file_name),
                code="PROJ-007",
            )
        
    def open_settings(self):
        """Open the settings dialog."""
        self.logger.debug("Open settings dialog requested.")
        if self.settings_dialog is None:
            self.logger.debug("Creating SettingsDialog instance for the first time.")
            self.settings_dialog = SettingsDialog(self, self.translator)
        self.settings_dialog.show()
        
    def edit_project_file(self, item):
        """Open the editor of the selected file: a measurement, the oscilloscope settings (.was) or
        the instruments (.inst)."""
        if not self.current_project_dir:
            return
        run = self._run_path(item)
        if run is not None:  # a run of a measurement: it opens in the run window
            self.project_tab.open_run(run)
            return
        fname = item.text()
        file_path = os.path.join(self.current_project_dir, fname)
        if self.project_tab.edit_file(fname):  # a measurement: the editor of its type
            return
        if fname.endswith('.was'):
            # Passa i dati del progetto per recuperare i canali dell'oscilloscopio
            dlg = WasFileDialog(file_path, self.translator, self.current_project_data, self)
            dlg.exec()
        elif fname.endswith('.inst'):
            if self.load_instruments is None:
                show_problem(self, self.translator.t('instrument_library'), self.translator.t('mw_library_not_loaded'), code="LIB-001")
                return
            dlg = InstrumentConfigDialog(file_path, self.load_instruments, self)
            dlg.exec()
        # (Altri tipi possono essere aggiunti in futuro)
        
    def open_instrument_library_dialog(self):
        """Open the instrument library manager dialog."""
        dlg = InstrumentLibraryDialog(self.load_instruments, self, self.translator)
        dlg.exec()
        
    def open_hexdec_converter(self):
        """Open the hex/dec converter dialog."""
        dlg = HexDecConverterDialog(self)
        dlg.exec()
    
    def _open_assets(self):
        """The registry of cables and devices, or None if its file is damaged (the program still
        works: the cards are just not available until the file is repaired)."""
        try:
            return AssetRegistry()
        except AssetError as exc:
            self.logger.error(f"Registry of cables and devices not available: {exc}")
            return None

    def open_assets_tool(self):
        """Open the window of the cables and devices (cards, labels, history)."""
        if self.assets is None:
            assets_tr = CatalogTranslator("assets", self.translator)
            error = f"{default_assets_path()} ({assets_tr.t('ast_unreadable')})"
            text = assets_tr.t("ast_open_failed", error=error)
            show_problem(self, "Open Lab Automation", text, code="AST-003")
            return

        def run_dirs():  # the runs folder of the project that is open now
            session = getattr(self.project_tab, "session", None)
            return [session.run_dir] if session is not None else []

        self._assets_tool = AssetsDialog(self.assets, self.translator, run_dirs, self)
        self._assets_tool.show()

    def _open_duts(self):
        """The archive of the devices under test, or None if its file is damaged. The antennas,
        filters and generic devices that are still cards of the registry of components move to it
        (``DutRegistry.migrate_from``: keeping their identity and, as an old code, the code on the
        label already stuck on them)."""
        try:
            duts = DutRegistry()
            moved = duts.migrate_from(self.assets) if self.assets is not None else []
        except (AssetError, OSError) as exc:
            self.logger.error(f"DUT archive not available: {exc}")
            return None
        if moved:
            self.logger.info(f"{len(moved)} antenna, filter or generic card(s) moved to the DUTs")
            text = CatalogTranslator("duts", self.translator).t("dut_migrated", n=len(moved))
            QMessageBox.information(self, "Open Lab Automation", text)
        return duts

    def open_duts_tool(self):
        """Open the DUT window (the archive of the devices under test: cards, versions, labels)."""
        if self.duts is None:
            error = (
                f"{default_duts_path()} "
                f"({CatalogTranslator('assets', self.translator).t('ast_unreadable')})"
            )
            text = CatalogTranslator("duts", self.translator).t("dut_open_failed", error=error)
            show_problem(self, "Open Lab Automation", text, code="AST-003")
            return

        def run_dirs():  # the runs folder of the project that is open now
            session = getattr(self.project_tab, "session", None)
            return [session.run_dir] if session is not None else []

        self._duts_tool = DutsDialog(self.duts, self.translator, run_dirs, self)
        self._duts_tool.show()

    def open_resistor_kits_tool(self):
        """Open the window of the kits of resistors."""
        from frontend.ui.ResistorKitsDialog import ResistorKitsDialog
        from ola.resistor_kits import KitError, KitRegistry, default_path

        tr = CatalogTranslator("resistors", self.translator)
        try:
            registry = KitRegistry()
        except KitError as exc:
            self.logger.error(f"Kits of resistors not available: {exc}")
            show_problem(
                self,
                "Open Lab Automation",
                tr.t("res_open_failed", error=f"{default_path()}: {exc}"),
                code="CFG-006",
                exception=exc,
            )
            return
        self._resistors_tool = ResistorKitsDialog(registry, self.translator, self)
        self._resistors_tool.show()

    @staticmethod
    def _wiring_preference() -> bool:
        """Whether the connection diagram is shown before every measurement (on by default)."""
        value = QSettings('LabAutomation', 'App').value('show_wiring_before_run', True)
        return str(value).lower() not in ('false', '0')

    @staticmethod
    def _save_wiring_preference(value: bool) -> None:
        """Remember the tick of the connection diagram window."""
        QSettings('LabAutomation', 'App').setValue('show_wiring_before_run', bool(value))

    def open_compare_tool(self):
        """Open the tool that compares saved results; it starts in the runs folder of the open
        project (frontend/ui/CompareDialog.py)."""
        session = getattr(self.project_tab, "session", None)
        start = str(session.run_dir) if session is not None else ""
        self._compare_tool = CompareDialog(translator=self.translator, parent=self, start_dir=start)
        self._compare_tool.show()

    def open_gpib_adapter_tool(self):
        """Open the tool that configures the GPIB adapters, checks their drivers and scans the bus
        (frontend/ui/GpibAdapterDialog.py)."""
        tool = getattr(self, "_gpib_tool", None)
        if tool is not None and tool.isVisible():
            tool.raise_()
            tool.activateWindow()
            return
        self._gpib_tool = GpibAdapterDialog(translator=self.translator, parent=self)
        self._gpib_tool.show()

    def open_pulse_generator(self):
        """Open the electronic load pulse generator tool."""
        # Check if project is open
        if not self.current_project_dir:
            show_problem(
                self,
                self.translator.t('warning'),
                self.translator.t('no_project_open'),
                code="PROJ-009",
            )
            return
        
        try:
            dlg = PulseGeneratorDialog(
                self.current_project_dir,
                self.load_instruments,
                self.translator,
                self
            )
            dlg.exec()
        except Exception as e:
            self.logger.error(f"Error opening pulse generator: {e}")
            show_problem(
                self,
                self.translator.t('error'),
                f"{self.translator.t('mw_pulse_generator_failed')}\n{e}",
                code="TOOL-005",
                exception=e,
                level="critical",
            )
    
    def show_file_context_menu(self, pos):
        """Show context menu for project files."""
        item = self.project_files_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        run = self._run_path(item)
        if run is not None:  # a run: open it, copy its name or delete it
            open_action = menu.addAction(self.translator.t('sidebar_run_open'))
            copy_run = menu.addAction(self.translator.t('copy_file_name'))
            delete_run = menu.addAction(self.translator.t('sidebar_run_delete'))
            action = menu.exec(self.project_files_list.mapToGlobal(pos))
            if action == open_action:
                self.project_tab.open_run(run)
            elif action == copy_run:
                from PyQt6.QtWidgets import QApplication
                QApplication.clipboard().setText(run.name)
            elif action == delete_run:
                self.project_tab.delete_run_path(run)
            return
        copy_action = menu.addAction(self.translator.t('copy_file_name'))
        runs_action = None
        if item.data(RUNS_ROLE) is not None:  # a measurement that has runs
            runs_action = menu.addAction(self.translator.t(
                'sidebar_runs_hide' if item.data(RUNS_ROLE) else 'sidebar_runs_show'))
        # paste_action = menu.addAction(self.translator.t('paste_file'))  # Implementa se serve
        scope = self._scope_entry(item.text())
        toggle_action = up_action = down_action = target_action = None
        if scope is not None:  # the settings of the oscilloscopes: on or off, their order, their scope
            toggle_action = menu.addAction(
                self.translator.t('scope_file_disable' if scope['enabled'] else 'scope_file_enable'))
            up_action = menu.addAction(self.translator.t('scope_file_up'))
            down_action = menu.addAction(self.translator.t('scope_file_down'))
            target_action = menu.addAction(self.translator.t('scope_file_target'))
        delete_action = menu.addAction(self.translator.t('delete_file'))
        action = menu.exec(self.project_files_list.mapToGlobal(pos))
        if action is None:
            return
        if action == copy_action:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(item.text())
        elif action == delete_action:
            self.delete_file(item)
        elif runs_action is not None and action == runs_action:
            self.toggle_runs(item)
        elif action == target_action:
            self.choose_scope_target(item.text())
        elif action in (toggle_action, up_action, down_action):
            self.change_scope_file(item.text(), 'toggle' if action == toggle_action
                                   else ('up' if action == up_action else 'down'))

    def choose_scope_target(self, file_name):
        """Ask which oscilloscope a scope settings file is for (or every one)."""
        session = self.project_tab.session
        if session is None or self._scope_entry(file_name) is None:
            return
        everyone = self.translator.t('scope_target_all')
        choices = [everyone] + list(session.instruments)
        current = session.project.scope_target(file_name)
        index = choices.index(current) if current in choices else 0
        choice, ok = QInputDialog.getItem(
            self, self.translator.t('scope_file_target'), file_name, choices, index, False)
        if ok:
            self.set_scope_target(file_name, '' if choice == everyone else choice)

    def set_scope_target(self, file_name, scope):
        """The oscilloscope a scope settings file is for (``''``: every oscilloscope)."""
        if self._scope_entry(file_name) is None:
            return
        self.project_tab.session.project.set_scope_target(file_name, scope)
        self.save_project_json()
        self.refresh_project_files()

    def _scope_entry(self, file_name):
        """The entry of a scope settings file of the open project, or None."""
        session = self.project_tab.session
        if session is None:
            return None
        return next((e for e in session.project.scope_settings if e['file'] == file_name), None)

    def change_scope_file(self, file_name, what):
        """Switch a scope settings file on or off (``toggle``) or move it in the order
        (``up``, ``down``); the file itself is never touched."""
        entry = self._scope_entry(file_name)
        if entry is None:
            return
        project = self.project_tab.session.project
        if what == 'toggle':
            project.set_scope_enabled(file_name, not entry['enabled'])
        else:
            project.move_scope_file(file_name, -1 if what == 'up' else 1)
        self.save_project_json()
        self.refresh_project_files()


class AddFileDialog(QDialog):
    """
    Dialog for adding a new file (a measurement of any type, or .was) to the project.
    """
    
    def __init__(self, parent=None, translator=None, naming_settings=None, measurement_types=()):
        """
        Initialize the add file dialog.
        
        Args:
            parent: Parent widget
            translator: Translator instance
            naming_settings: Naming settings for the project
            measurement_types: the measurement modules (ModuleInfo) the project can hold
        """
        super().__init__(parent)
        self.translator = translator
        self.naming_settings = naming_settings or {
            'custom_naming': False, 
            'eff_naming': False, 
            'was_naming': False, 
            'inst_naming': False
        }
        self.logger = Logger()
        self.logger.debug("AddFileDialog.__init__ started.")
        
        self.setWindowTitle(self.translator.t('add_file'))
        self.setModal(True)
        
        layout = QVBoxLayout()
        
        self.type_combo = QComboBox()
        for info in measurement_types:  # one entry per measurement type, e.g. "Cable (.cbl)"
            self.type_combo.addItem(f"{info.name} ({info.extension})", info.id)
        self.type_combo.addItem(self.translator.t('oscilloscope_settings'), '.was')
        
        self.name_edit = QLineEdit()
        
        layout.addWidget(QLabel(self.translator.t('file_type')))
        layout.addWidget(self.type_combo)
        layout.addWidget(QLabel(self.translator.t('file_name')))
        layout.addWidget(self.name_edit)
        
        add_btn = QPushButton(self.translator.t('add'))
        add_btn.clicked.connect(self.accept)
        layout.addWidget(add_btn)
        
        self.setLayout(layout)
        self.logger.debug("AddFileDialog initialized.")