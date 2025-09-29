import os
import json
from LoadInstruments import LoadInstruments

import uuid
import datetime
from PyQt5.QtWidgets import (
     QMainWindow, QTabWidget, QApplication ,QWidget, QVBoxLayout, QLabel, QAction, QDialog, QPushButton, QHBoxLayout, QComboBox, QCheckBox, QFileDialog, QListWidget, QListWidgetItem, QSplitter, QRadioButton, QButtonGroup, QSpinBox, QGroupBox, QFormLayout, QTextEdit, QSizePolicy, QInputDialog, QLineEdit, QTableWidget, QTableWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt, QSettings, QTimer
import pyvisa
from RemoteControlTab import RemoteControlTab
from SettingsDialog import SettingsDialog
from  Translator  import Translator
from EffFileDialog  import EffFileDialog
from WasFileDialog import WasFileDialog
from InstrumentConfigDialog import InstrumentConfigDialog
from InstrumentLibraryDialog import InstrumentLibraryDialog
from HexDecConverterDialog import HexDecConverterDialog


# =========================
# MainWindow
# =========================
class MainWindow(QMainWindow):
    """
    Main application window. Handles project management, file operations, instrument configuration,
    and main UI tabs (remote control, project files, etc.).
    """
    def __init__(self):
        """
        Initialize the main window, load app info, and set up UI components.
        """
        self.db = None
        self.db_manager = None
        # Initialize logger
        from logger import Logger
        self.logger = Logger()
        
        # Load app info from JSON
        appinfo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'appinfo.json')
        with open(appinfo_path, encoding='utf-8') as f:
            self.appinfo = json.load(f)
            self.logger.info(f"App info loaded: {self.appinfo.get('app_name')} v{self.appinfo.get('version')}")
            
        self.translator = Translator()
        super().__init__()
        self.setWindowTitle(self.appinfo.get('app_name', 'Lab Automation'))
        
        # Initialize database connection
        self.initialize_database_connection()
        
        # Initialize LoadInstruments with error handling
        try:
            self.load_instruments = LoadInstruments()
            lib_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Instruments_LIB', 'instruments_lib.json')
            self.load_instruments.load_instruments(lib_path)
            self.logger.info(f"LoadInstruments initialized successfully with library: {lib_path}")
        except Exception as e:
            self.logger.error(f"Error initializing LoadInstruments: {str(e)}")
            print(f"ERRORE LoadInstruments: {str(e)}")
            self.load_instruments = None
        self.tabs = QTabWidget()
        # Pass load_instruments to RemoteControlTab with error checking
        if self.load_instruments is None:
            self.logger.warning("LoadInstruments is None, creating RemoteControlTab with empty instruments")
        self.remote_tab = RemoteControlTab(self.load_instruments)
        self.tabs.addTab(self.remote_tab, self.translator.t('remote_control'))
        self.project_files_list = QListWidget()
        # Layout: tabs on the left, file list on the right
        central_widget = QWidget()
        main_layout = QHBoxLayout()
        main_layout.addWidget(self.project_files_list, 1)
        main_layout.addWidget(self.tabs, 3)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
        self.current_project_dir = None
        self.current_project_data = None
        self.init_menu()
        self.settings_dialog = SettingsDialog(self, self.translator)
        self.load_settings()
        self.update_translations()
        self.project_files_list.itemDoubleClicked.connect(self.edit_project_file)
        # Always start maximized/fullscreen
        self.showMaximized()
        # --- Open last project if available ---
        settings = QSettings('LabAutomation', 'App')
        last_project_path = settings.value('last_project_path', '', type=str)
        if last_project_path and os.path.isfile(last_project_path):
            try:
                with open(last_project_path, 'r', encoding='utf-8') as f:
                    project_data = json.load(f)
                self.current_project_dir = os.path.dirname(last_project_path)
                self.current_project_data = project_data
                self.refresh_project_files()
            except Exception:
                pass

        self.project_files_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.project_files_list.customContextMenuRequested.connect(self.show_file_context_menu)

    def init_menu(self):
        """
        Initialize the menubar and its menus/actions.
        """
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
        # New entry: add existing file
        add_existing_action = QAction(self.translator.t('add_existing_file'), self)
        add_existing_action.triggered.connect(self.add_existing_file)
        project_menu.addAction(add_existing_action)
        # Settings menu
        settings_menu = menubar.addMenu(self.translator.t('settings'))
        settings_action = QAction(self.translator.t('open_settings'), self)
        settings_action.triggered.connect(self.open_settings)
        settings_menu.addAction(settings_action)
        db_action = QAction(self.translator.t('database_settings'), self)
        db_action.triggered.connect(self.open_db_settings)
        settings_menu.addAction(db_action)
        # Database configuration action
        db_config_action = QAction("Database Configuration", self)
        db_config_action.triggered.connect(self.show_database_config)
        settings_menu.addAction(db_config_action)
        # Help menu
        help_menu = menubar.addMenu(self.translator.t('help'))
        info_action = QAction(self.translator.t('about_software'), self)
        info_action.triggered.connect(self.show_software_info)
        help_menu.addAction(info_action)
        # Tools menu
        tools_menu = menubar.addMenu(self.translator.t('tools') if hasattr(self.translator, 't') else 'Tools')
        manage_lib_action = QAction(self.translator.t('manage_instrument_library') if hasattr(self.translator, 't') else 'Gestisci libreria strumenti', self)
        manage_lib_action.triggered.connect(self.open_instrument_library_dialog)
        tools_menu.addAction(manage_lib_action)
        # --- Aggiungi convertitore Hex/Dec ---
        hexdec_action = QAction("Convertitore Hex/Dec", self)
        hexdec_action.triggered.connect(self.open_hexdec_converter)
        tools_menu.addAction(hexdec_action)

    def show_software_info(self):
        """
        Show information about the software in a message box.
        """
        from PyQt5.QtWidgets import QMessageBox
        info = self.appinfo
        text = f"<b>{info.get('app_name','')}</b><br>Version: {info.get('version','')}<br>Author: {info.get('author','')}<br>"
        repo = info.get('repository','')
        if repo:
            text += f"<br><a href='{repo}'>Repository</a>"
        msg = QMessageBox(self)
        msg.setWindowTitle(self.translator.t('about_software'))
        msg.setTextFormat(Qt.RichText)
        msg.setText(text)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec_()

    def create_new_project(self):
        """
        Create a new project: select folder, enter project name, and create .json and .inst files.
        """
        from PyQt5.QtWidgets import QFileDialog, QMessageBox, QInputDialog
        self.logger.info("Starting new project creation...")
        dir_path = QFileDialog.getExistingDirectory(self, self.translator.t('select_project_folder'))
        if dir_path:
            self.logger.debug(f"Selected directory: {dir_path}")
            project_name, ok = QInputDialog.getText(self, self.translator.t('project'), self.translator.t('enter_project_name'))
            if not ok or not project_name.strip():
                self.logger.info("Project creation cancelled")
                return
            project_id = str(uuid.uuid4())
            now = datetime.datetime.now().isoformat()
            self.logger.info(f"Creating project: {project_name} (ID: {project_id})")
            # Load naming settings
            settings = QSettings('LabAutomation', 'App')
            adv_naming = settings.value('advanced_naming', False, type=bool)
            adv_inst = settings.value('advanced_naming_inst', False, type=bool)
            # .inst file name = project name
            inst_base = project_name.strip()
            if adv_naming and adv_inst:
                inst_file = f"{inst_base}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.inst"
            else:
                inst_file = f"{inst_base}.inst"
            # .json file name = project name
            json_file = f"{inst_base}.json"
            project_data = {
                "project_id": project_id,
                "created_at": now,
                "last_opened": now,
                "project_name": project_name.strip(),
                "eff_files": [],
                "inst_file": inst_file,
                "was_files": []
            }
            project_file = os.path.join(dir_path, json_file)
            with open(project_file, 'w', encoding='utf-8') as f:
                json.dump(project_data, f, indent=2)
            inst_data = {"instruments": []}
            inst_path = os.path.join(dir_path, inst_file)
            with open(inst_path, 'w', encoding='utf-8') as f:
                json.dump(inst_data, f, indent=2)
            self.current_project_dir = dir_path
            self.current_project_data = project_data
            self.refresh_project_files()
            QMessageBox.information(self, self.translator.t('project'), self.translator.t('project_created')+f'\n{dir_path}')
            # Salva percorso ultimo progetto
            settings.setValue('last_project_path', project_file)
            # Ask if add file now
            reply = QMessageBox.question(self, self.translator.t('add_file'), self.translator.t('add_file_now'), QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.add_project_file()

    def open_project(self):
        """
        Open an existing project: select .json file and load its data.
        """
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        self.logger.info("Opening project...")
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.t('open_project'), '', 'Project Files (*.json)')
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    project_data = json.load(f)
                self.current_project_dir = os.path.dirname(file_path)
                self.logger.info(f"Opening project: {project_data.get('project_name', '')} from {file_path}")
                self.current_project_data = project_data
                # Set log directory
                self.logger.set_project_directory(self.current_project_dir)
                
                # Load or create database project entry
                self.sync_project_with_database()
                self.refresh_project_files()
                QMessageBox.information(self, self.translator.t('project'), self.translator.t('project_opened')+f'\n{project_data.get("project_name", "")}')
                # Salva percorso ultimo progetto
                settings = QSettings('LabAutomation', 'App')
                settings.setValue('last_project_path', file_path)
            except Exception as e:
                QMessageBox.warning(self, self.translator.t('project'), str(e))

    def refresh_project_files(self):
        """
        Refresh the list of project files displayed in the UI.
        Also updates the remote control tab with the current .inst file.
        """
        self.project_files_list.clear()
        if not self.current_project_dir or not self.current_project_data:
            return
        # Project files list
        files = []
        files.append(self.current_project_data.get('inst_file'))
        files += self.current_project_data.get('eff_files', [])
        files += self.current_project_data.get('was_files', [])
        for f in files:
            if f:
                item = QListWidgetItem(f)
                self.project_files_list.addItem(item)
        # Update remote control tab with instrument controls
        inst_file = self.current_project_data.get('inst_file')
        if inst_file:
            inst_path = os.path.join(self.current_project_dir, inst_file)
            try:
                self.remote_tab.load_instruments(inst_path)
                self.logger.info(f"Instruments loaded from: {inst_path}")
            except Exception as e:
                error_msg = f"Errore caricamento strumenti da {inst_path}: {str(e)}"
                self.logger.error(error_msg)
                print(f"ERRORE: {error_msg}")
                # Show error to user
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Errore Strumenti", error_msg)

    def add_project_file(self):
        """
        Add a new project file (.eff or .was) using the AddFileDialog.
        """
        dlg = AddFileDialog(self, self.translator)
        if dlg.exec_() == QDialog.Accepted:
            if self.current_project_data and self.current_project_dir:
                file_type = dlg.type_combo.currentData()
                file_name = dlg.name_edit.text().strip()
                import datetime
                now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                # Load naming settings
                settings = QSettings('LabAutomation', 'App')
                adv_naming = settings.value('advanced_naming', False, type=bool)
                adv_eff = settings.value('advanced_naming_eff', False, type=bool)
                adv_was = settings.value('advanced_naming_was', False, type=bool)
                new_file = None
                if file_type == '.eff':
                    if adv_naming and adv_eff:
                        eff_file = f"{file_name}_{now}.eff"
                    else:
                        eff_file = f"{file_name}.eff"
                    eff_data = {"type": "efficiency", "data": {}}
                    with open(os.path.join(self.current_project_dir, eff_file), 'w', encoding='utf-8') as f:
                        json.dump(eff_data, f, indent=2)
                    if eff_file not in self.current_project_data['eff_files']:
                        self.current_project_data['eff_files'].append(eff_file)
                    new_file = eff_file
                elif file_type == '.was':
                    if adv_naming and adv_was:
                        was_file = f"{file_name}_{now}.was"
                    else:
                        was_file = f"{file_name}.was"
                    was_data = {"type": "oscilloscope_settings", "settings": {}}
                    with open(os.path.join(self.current_project_dir, was_file), 'w', encoding='utf-8') as f:
                        json.dump(was_data, f, indent=2)
                    if was_file not in self.current_project_data['was_files']:
                        self.current_project_data['was_files'].append(was_file)
                    new_file = was_file
                # Save project update
                # Search for the project json file by project name
                json_file = f"{self.current_project_data['project_name']}.json"
                json_path = os.path.join(self.current_project_dir, json_file)
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(self.current_project_data, f, indent=2)
                self.refresh_project_files()

    def add_existing_file(self):
        """
        Add an existing file (.eff or .was) to the project from the file system.
        """
        from PyQt5.QtWidgets import QFileDialog, QMessageBox
        if not self.current_project_dir or not self.current_project_data:
            QMessageBox.warning(self, self.translator.t('project'), self.translator.t('no_project_open'))
            return
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.t('add_existing_file'), self.current_project_dir, 'Eff (*.eff);;Was (*.was)')
        if not file_path:
            return
        fname = os.path.basename(file_path)
        if fname.endswith('.eff'):
            if fname not in self.current_project_data['eff_files']:
                self.current_project_data['eff_files'].append(fname)
        elif fname.endswith('.was'):
            if fname not in self.current_project_data['was_files']:
                self.current_project_data['was_files'].append(fname)
        else:
            QMessageBox.warning(self, self.translator.t('add_existing_file'), self.translator.t('file_type_not_allowed'))
            return
        # Update project json file
        project_file = [f for f in os.listdir(self.current_project_dir) if f.endswith('.json') and self.current_project_data['project_id'] in open(os.path.join(self.current_project_dir, f), encoding='utf-8').read()]
        if project_file:
            with open(os.path.join(self.current_project_dir, project_file[0]), 'w', encoding='utf-8') as f:
                json.dump(self.current_project_data, f, indent=2)
        self.refresh_project_files()

    def open_settings(self):
        """
        Open the settings dialog to configure application preferences.
        """
        self.settings_dialog.load_settings()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def open_db_settings(self):
        """
        Open the database settings dialog to configure database connection parameters.
        """
        dlg = DatabaseDialog(self, self.translator)
        dlg.exec_()

    def set_dark_theme(self):
        """
        Set the application to dark theme using a predefined stylesheet.
        """
        dark_stylesheet = """
            QWidget { background-color: #232629; color: #f0f0f0; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab { background: #232629; color: #f0f0f0; }
            QMenuBar { background-color: #232629; color: #f0f0f0; }
            QMenu { background-color: #232629; color: #f0f0f0; }
            QPushButton { background-color: #444; color: #f0f0f0; border: 1px solid #666; }
        """
        self.setStyleSheet(dark_stylesheet)
        settings = QSettings('LabAutomation', 'App')
        settings.setValue('dark_theme', True)

    def load_settings(self):
        """
        Load settings from QSettings and apply them to the application.
        """
        settings = QSettings('LabAutomation', 'App')
        lang = settings.value('language', self.translator.current_lang)
        dark = settings.value('dark_theme', False, type=bool)
        adv_naming = settings.value('advanced_naming', False, type=bool)
        adv_inst = settings.value('advanced_naming_inst', False, type=bool)
        adv_eff = settings.value('advanced_naming_eff', False, type=bool)
        adv_was = settings.value('advanced_naming_was', False, type=bool)
        self.translator.set_language(lang)
        if dark:
            self.set_dark_theme()
        self.naming_settings = {
            'advanced_naming': adv_naming,
            'advanced_naming_inst': adv_inst,
            'advanced_naming_eff': adv_eff,
            'advanced_naming_was': adv_was
        }

    def update_translations(self):
        """
        Update the UI texts and menus according to the current language.
        """
        self.setWindowTitle(self.appinfo.get('app_name', 'Lab Automation'))
        self.tabs.setTabText(0, self.translator.t('remote_control'))
        self.init_menu()
        self.remote_tab.update_translation(self.translator)

    def edit_project_file(self, item):
        """
        Open a configuration dialog for the selected file based on its type (.eff, .was, .inst).
        :param item: QListWidgetItem clicked.
        """
        if not self.current_project_dir:
            return
        fname = item.text()
        file_path = os.path.join(self.current_project_dir, fname)
        if fname.endswith('.eff'):
            dlg = EffFileDialog(file_path, self.translator, self)
            dlg.exec_()
        elif fname.endswith('.was'):
            dlg = WasFileDialog(file_path, self.translator, self)
            dlg.exec_()
        elif fname.endswith('.inst'):
            dlg = InstrumentConfigDialog(file_path, self.load_instruments, self)
            # Aggiorna live mentre si salva dal dialog, se il file corrisponde al progetto aperto
            try:
                dlg.instruments_changed.connect(self.update_remote_control_if_current_project)
            except Exception:
                pass
            if dlg.exec_() == QDialog.Accepted:
                # Ricarica gli strumenti nel RemoteControlTab se il file corrisponde al progetto attuale
                self.update_remote_control_if_current_project(file_path)
            elif hasattr(dlg, 'instruments_modified') and dlg.instruments_modified:
                # Anche se il dialog è stato chiuso senza OK, se ci sono state modifiche, aggiorna
                self.update_remote_control_if_current_project(file_path)
        # (Other types can be added in the future)

    def update_remote_control_if_current_project(self, inst_file_path):
        """
        Aggiorna il RemoteControlTab se il file .inst modificato appartiene al progetto corrente.
        """
        if not self.current_project_data or not self.current_project_dir:
            return
            
        # Ottieni il file .inst del progetto corrente
        current_inst_file = self.current_project_data.get('inst_file')
        if not current_inst_file:
            return
            
        # Costruisci il path completo del file .inst del progetto corrente
        current_inst_path = os.path.join(self.current_project_dir, current_inst_file)
        
        # Confronta i path normalizzati
        if os.path.normpath(inst_file_path) == os.path.normpath(current_inst_path):
            # Il file modificato è quello del progetto corrente, ricarica il RemoteControlTab
            try:
                self.remote_tab.load_instruments(inst_file_path)
                self.logger.info(f"RemoteControlTab aggiornato dopo modifica di: {inst_file_path}")
                print(f"INFO: RemoteControlTab aggiornato dopo modifica strumenti")
            except Exception as e:
                error_msg = f"Errore aggiornamento RemoteControlTab: {str(e)}"
                self.logger.error(error_msg)
                print(f"ERRORE: {error_msg}")

    def open_instrument_library_dialog(self):
        """
        Open the instrument library manager dialog.
        """
        dlg = InstrumentLibraryDialog(self.load_instruments, self, self.translator)
        dlg.exec_()

    def open_hexdec_converter(self):
        dlg = HexDecConverterDialog(self)
        dlg.exec_()
    
    def show_database_config(self):
        """
        Show database configuration dialog.
        """
        try:
            from database_config_dialog import DatabaseConfigDialog
            dialog = DatabaseConfigDialog(self)
            
            if dialog.exec_() == QDialog.Accepted:
                # Update database manager with new configuration
                self.db_manager = dialog.get_database_manager()
                self.logger.info("Database configuration updated")
                
                # Test connection and log result
                if self.db_manager.test_connection():
                    self.logger.info("Database connection established successfully")
                else:
                    self.logger.warning("Database connection test failed")
                    
        except Exception as e:
            self.logger.error(f"Failed to open database configuration dialog: {str(e)}")
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to open database configuration: {str(e)}")
    
    def sync_project_with_database(self):
        """
        Synchronize current project with database entry.
        Creates database entry if it doesn't exist.
        """
        if not self.db_manager or not self.current_project_data:
            return
        
        try:
            from models import Project
            
            # Create project instance
            project = Project(self.db_manager)
            
            # Try to load existing project by name
            project_name = self.current_project_data.get('project_name', '')
            if not project_name:
                self.logger.warning("Project has no name, skipping database sync")
                return
            
            if not project.load_by_name(project_name):
                # Project doesn't exist in database, create it
                description = self.current_project_data.get('description', '')
                parametri_globali = {
                    'project_id': self.current_project_data.get('project_id'),
                    'created_with_version': self.current_project_data.get('version'),
                    'project_dir': self.current_project_dir
                }
                
                if project.create(project_name, description, parametri_globali):
                    self.logger.info(f"Created database entry for project: {project_name}")
                else:
                    self.logger.error(f"Failed to create database entry for project: {project_name}")
            else:
                self.logger.debug(f"Project already exists in database: {project_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to sync project with database: {str(e)}")
    
    def initialize_database_connection(self):
        """
        Initialize database connection on application startup.
        """
        try:
            # Try to load existing database configuration
            config_file = os.path.join(os.path.dirname(__file__), 'database_config.json')
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                from database import DatabaseManager
                self.db_manager = DatabaseManager(**config)
                
                # Test connection silently
                if self.db_manager.test_connection():
                    self.logger.info("Database connection established on startup")
                else:
                    self.logger.warning("Database connection test failed on startup")
                    self.db_manager = None
            else:
                self.logger.debug("No database configuration file found")
                
        except Exception as e:
            self.logger.warning(f"Failed to initialize database connection: {str(e)}")
            self.db_manager = None

    def show_file_context_menu(self, pos):
        from PyQt5.QtWidgets import QMenu, QApplication
        item = self.project_files_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        copy_action = menu.addAction(self.translator.t('copy_file_name'))
        paste_action = menu.addAction(self.translator.t('paste_file'))
        delete_action = menu.addAction(self.translator.t('delete_file'))
        action = menu.exec_(self.project_files_list.mapToGlobal(pos))
        if action == copy_action:
            QApplication.clipboard().setText(item.text())
        elif action == paste_action:
            self.paste_file()
        elif action == delete_action:
            self.delete_file(item)

    def paste_file(self):
        from PyQt5.QtWidgets import QMessageBox
        clipboard = QApplication.clipboard().text()
        if not clipboard or not self.current_project_dir:
            return
        src_path = os.path.join(self.current_project_dir, clipboard)
        if not os.path.isfile(src_path):
            QMessageBox.warning(self, "Errore", "File da incollare non trovato.")
            return
        base, ext = os.path.splitext(clipboard)
        new_name = base + "_copy" + ext
        dst_path = os.path.join(self.current_project_dir, new_name)
        i = 1
        while os.path.exists(dst_path):
            new_name = f"{base}_copy{i}{ext}"
            dst_path = os.path.join(self.current_project_dir, new_name)
            i += 1
        import shutil
        shutil.copy2(src_path, dst_path)
        # Aggiorna lista nel progetto
        if ext == '.eff' and new_name not in self.current_project_data['eff_files']:
            self.current_project_data['eff_files'].append(new_name)
        elif ext == '.was' and new_name not in self.current_project_data['was_files']:
            self.current_project_data['was_files'].append(new_name)
        elif ext == '.inst':
            self.current_project_data['inst_file'] = new_name
        # Salva json
        self.save_project_json()
        self.refresh_project_files()

    def delete_file(self, item):
        from PyQt5.QtWidgets import QMessageBox
        fname = item.text()
        if not self.current_project_dir:
            return
        file_path = os.path.join(self.current_project_dir, fname)
        reply = QMessageBox.question(self, "Delete file", f"Do you want to delete file {fname}?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.logger.info(f"Deleting file: {fname}")
            try:
                os.remove(file_path)
                self.logger.debug(f"File deleted: {file_path}")
            except Exception as e:
                self.logger.error(f"Error while deleting file {fname}: {str(e)}")
                pass
            # Remove from project
            if fname in self.current_project_data.get('eff_files', []):
                self.current_project_data['eff_files'].remove(fname)
                self.logger.debug(f"Removed {fname} from eff_files list")
            if fname in self.current_project_data.get('was_files', []):
                self.current_project_data['was_files'].remove(fname)
                self.logger.debug(f"Removed {fname} from was_files list")
            if fname == self.current_project_data.get('inst_file'):
                self.current_project_data['inst_file'] = ''
                self.logger.debug(f"Removed {fname} as inst_file")
            self.save_project_json()
            self.refresh_project_files()

    def save_project_json(self):
        if not self.current_project_dir or not self.current_project_data:
            return
        json_file = f"{self.current_project_data['project_name']}.json"
        json_path = os.path.join(self.current_project_dir, json_file)
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(self.current_project_data, f, indent=2)


# =========================
# DatabaseDialog
# =========================
class DatabaseDialog(QDialog):
    """
    Dialog for configuring database connection settings.
    """
    def __init__(self, parent=None, translator=None):
        """
        Initialize the database settings dialog with input fields for host, port, user, password, and database name.
        :param parent: Parent widget.
        :param translator: Translator instance.
        """
        super().__init__(parent)
        self.translator = translator
        self.setWindowTitle(self.translator.t('database_settings'))
        self.setModal(True)
        layout = QVBoxLayout()
        from PyQt5.QtWidgets import QLineEdit, QFormLayout
        form = QFormLayout()
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.dbname = QLineEdit()
        form.addRow(self.translator.t('db_host'), self.host)
        form.addRow(self.translator.t('db_port'), self.port)
        form.addRow(self.translator.t('db_user'), self.user)
        form.addRow(self.translator.t('db_password'), self.password)
        form.addRow(self.translator.t('db_name'), self.dbname)
        layout.addLayout(form)
        save_btn = QPushButton(self.translator.t('save'))
        save_btn.clicked.connect(self.save_db_settings)
        layout.addWidget(save_btn)
        self.setLayout(layout)
        self.load_db_settings()

    def save_db_settings(self):
        """
        Save the database settings to QSettings and initialize database connection.
        """
        settings = QSettings('LabAutomation', 'App')
        settings.setValue('db_host', self.host.text())
        settings.setValue('db_port', self.port.text())
        settings.setValue('db_user', self.user.text())
        settings.setValue('db_password', self.password.text())
        settings.setValue('db_name', self.dbname.text())

        # Verifica la connessione al database
        try:
            from DatabaseManager import DatabaseManager
            db = DatabaseManager(
                host=self.host.text(),
                port=int(self.port.text()),
                dbname=self.dbname.text(), 
                user=self.user.text(),
                password=self.password.text()
            )
            db.ensure_connection()
            db.close()
            QMessageBox.information(self, "Database", "Connessione al database riuscita!")
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Errore Database", f"Errore di connessione:\n{str(e)}")
            return

    def load_db_settings(self):
        """
        Load database settings from QSettings and populate the input fields.
        """
        settings = QSettings('LabAutomation', 'App')
        self.host.setText(settings.value('db_host', 'localhost'))
        self.port.setText(settings.value('db_port', '9090'))
        self.user.setText(settings.value('db_user', ''))
        self.password.setText(settings.value('db_password', ''))
        self.dbname.setText(settings.value('db_name', 'prometheus'))


# =========================
# AddFileDialog
# =========================
class AddFileDialog(QDialog):
    """
    Dialog for adding a new file (.eff or .was) to the project.
    """
    def __init__(self, parent=None, translator=None, naming_settings=None):
        """
        Initialize the add file dialog with file type and name input fields.
        :param parent: Parent widget.
        :param translator: Translator instance.
        :param naming_settings: Naming settings for the project.
        """
        super().__init__(parent)
        self.translator = translator
        self.naming_settings = naming_settings or {'custom_naming': False, 'eff_naming': False, 'was_naming': False, 'inst_naming': False}
        self.setWindowTitle(self.translator.t('add_file'))
        self.setModal(True)
        layout = QVBoxLayout()
        from PyQt5.QtWidgets import QComboBox, QLineEdit, QLabel
        self.type_combo = QComboBox()
        self.type_combo.addItem(self.translator.t('efficiency_settings'), '.eff')
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

    def create_file(self):
        """
        Create a new file (.eff or .was) in the selected project folder with default content.
        """
        import datetime
        import uuid
        file_type = self.type_combo.currentText()
        file_name = self.name_edit.text().strip()
        if not file_name:
            return
        dir_path = QFileDialog.getExistingDirectory(self, self.translator.t('select_project_folder'))
        if not dir_path:
            return
        project_id = file_name if file_type == '.was' else str(uuid.uuid4())
        now = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        if file_type == '.eff':
            eff_file = os.path.join(dir_path, f"{project_id}_{now}.eff")
            eff_data = {"type": "efficiency", "data": {}}
            with open(eff_file, 'w', encoding='utf-8') as f:
                json.dump(eff_data, f, indent=2)
        elif file_type == '.was':
            was_file = os.path.join(dir_path, f"{project_id}_{now}.was")
            was_data = {"type": "oscilloscope_settings", "settings": {}}
            with open(was_file, 'w', encoding='utf-8') as f:
                json.dump(was_data, f, indent=2)
        self.accept()

"""
Main function DON'T TOUCH
"""

def main():
    """
    Main function to start the PyQt5 application.
    Sets up application name, loads language settings, and shows the main window.
    """
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)  # Create the QApplication instance
    # Set organization and application name for QSettings
    app.setOrganizationName('LabAutomation')
    app.setApplicationName('Open Lab Automation')
    # Load language from settings
    settings = QSettings('LabAutomation', 'App')
    lang = settings.value('language', 'it')  # Default to Italian
    translator = Translator(default_lang=lang)  # Create Translator instance
    window = MainWindow()  # Create and show the main window
    window.show()
    sys.exit(app.exec_())  # Start the Qt event loop

if __name__ == "__main__":
    main()