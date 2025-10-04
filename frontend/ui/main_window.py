"""
Main application window for Lab Automation.

This module contains the MainWindow class and related dialog classes
that handle the main UI functionality including project management,
file operations, and instrument configuration.
"""

import os
import json
import uuid
import datetime
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel, QDialog, 
    QPushButton, QHBoxLayout, QComboBox, QFileDialog, QListWidget, 
    QListWidgetItem, QInputDialog, QLineEdit, QMessageBox, QMenu,
    QFormLayout
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QSettings

from frontend.ui.RemoteControlTab import RemoteControlTab
from frontend.ui.SettingsDialog import SettingsDialog
from frontend.core.Translator import Translator
from frontend.ui.EffFileDialog import EffFileDialog
from frontend.ui.WasFileDialog import WasFileDialog
from frontend.ui.InstrumentConfigDialog import InstrumentConfigDialog
from frontend.ui.InstrumentLibraryDialog import InstrumentLibraryDialog
from frontend.ui.HexDecConverterDialog import HexDecConverterDialog
from frontend.core.LoadInstruments import LoadInstruments
from frontend.core.logger import Logger
from frontend.core.errorhandler import ErrorHandler, ErrorCode, ValidationError
from frontend.core.tools import read_json, save_json
class MainWindow(QMainWindow):
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
        self.logger.debug("Translator initialized.")
        
        super().__init__()
        
        self.db = None
        self.db_manager = None
        
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
            self.error_handler.handle_error(e, "Failed to load application info")
            self.appinfo = {"app_name": "Lab Automation", "version": "1.0"}
            
        self.setWindowTitle(self.appinfo.get('app_name', 'Lab Automation'))
        
        # Initialize database connection
        self.logger.debug("Initializing database connection...")
        self.initialize_database_connection()
        
        # Initialize LoadInstruments with error handling
        self.logger.debug("Initializing LoadInstruments...")
        try:
            self.load_instruments = LoadInstruments()
            lib_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'Instruments_LIB', 'instruments_lib.json')
            self.load_instruments.load_instruments(lib_path)
            self.logger.debug(f"LoadInstruments initialized successfully with library: {lib_path}")
        except Exception as e:
            self.logger.error(f"Error initializing LoadInstruments: {e}", exc_info=True)
            self.error_handler.handle_error(e, "Error initializing LoadInstruments")
            self.load_instruments = None
            
        self.tabs = QTabWidget()
        self.logger.debug("QTabWidget created.")
        
        # Pass load_instruments to RemoteControlTab with error checking
        if self.load_instruments is None:
            self.logger.warning("LoadInstruments is None, creating RemoteControlTab with empty instruments")
        
        self.remote_tab = RemoteControlTab(self.load_instruments)
        self.tabs.addTab(self.remote_tab, self.translator.t('remote_control'))
        self.project_files_list = QListWidget()
        self.logger.debug("UI tabs and lists created.")
        
        # Layout: tabs on the left, file list on the right
        central_widget = QWidget()
        main_layout = QHBoxLayout()
        main_layout.addWidget(self.project_files_list, 1)
        main_layout.addWidget(self.tabs, 3)
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
                project_data = read_json(last_project_path)
                self.current_project_dir = os.path.dirname(last_project_path)
                self.current_project_data = project_data
                self.refresh_project_files()
                self.logger.info(f"Successfully loaded last project: {project_data.get('project_name')}")
            except Exception as e:
                self.logger.error(f"Failed to load last project: {last_project_path} - {e}", exc_info=True)
                self.error_handler.handle_error(e, f"Failed to load last project: {last_project_path}")

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
        tools_menu = menubar.addMenu(self.translator.t('tools') if hasattr(self.translator, 't') else 'Tools')
        
        manage_lib_action = QAction(self.translator.t('manage_instrument_library') if hasattr(self.translator, 't') else 'Gestisci libreria strumenti', self)
        manage_lib_action.triggered.connect(self.open_instrument_library_dialog)
        tools_menu.addAction(manage_lib_action)
        
        hexdec_action = QAction("Convertitore Hex/Dec", self)
        hexdec_action.triggered.connect(self.open_hexdec_converter)
        tools_menu.addAction(hexdec_action)
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
                "project_id": project_id,
                "created_at": now,
                "last_opened": now,
                "project_name": project_name.strip(),
                "eff_files": [],
                "inst_file": inst_file,
                "was_files": [],
                "control_variables": [],
                "measure_variables": []
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
            
            self.current_project_dir = dir_path
            self.current_project_data = project_data
            self.refresh_project_files()
            
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
            self.error_handler.handle_error(e, "Failed to create new project")



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
        Apply the selected theme (system, dark, or light).
        :param theme_option: 'system', 'dark', or 'light'
        """
        self.logger.debug(f"[apply_theme] Ricevuto theme_option: {theme_option}")
        print(f"[MainWindow DEBUG] apply_theme chiamato con: {theme_option}")
        
        if theme_option == 'dark':
            print("[MainWindow DEBUG] Applicazione tema SCURO")
            self.set_dark_theme()
        elif theme_option == 'light':
            print("[MainWindow DEBUG] Applicazione tema CHIARO")
            self.set_light_theme()
        elif theme_option == 'system':
            print("[MainWindow DEBUG] Applicazione tema DI SISTEMA")
            # Try to detect system theme
            try:
                from PyQt6.QtGui import QGuiApplication
                from PyQt6.QtCore import Qt
                if hasattr(Qt, 'ColorScheme'):  # Qt 6.5+
                    color_scheme = QGuiApplication.styleHints().colorScheme()
                    print(f"[MainWindow DEBUG] Color scheme sistema: {color_scheme}")
                    if color_scheme == Qt.ColorScheme.Dark:
                        self.set_dark_theme()
                    else:
                        self.set_light_theme()
                else:
                    # Fallback: default to dark if Qt version doesn't support ColorScheme
                    self.logger.warning("System theme detection not supported, defaulting to dark theme.")
                    print("[MainWindow DEBUG] ColorScheme non supportato, uso tema scuro")
                    self.set_dark_theme()
            except Exception as e:
                self.logger.error(f"Error detecting system theme: {e}, defaulting to dark theme.")
                print(f"[MainWindow DEBUG] Errore rilevamento tema sistema: {e}")
                self.set_dark_theme()
        else:
            print(f"[MainWindow DEBUG] Tema sconosciuto: {theme_option}")
        
        # Save the theme preference
        settings = QSettings('LabAutomation', 'App')
        settings.setValue('theme', theme_option)
        print(f"[MainWindow DEBUG] Salvato tema '{theme_option}' in QSettings")

    def set_dark_theme(self):
        """
        Set the application to dark theme using a predefined stylesheet.
        """
        self.logger.debug("Setting dark theme stylesheet.")
        dark_stylesheet = """
            QWidget { background-color: #232629; color: #f0f0f0; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab { background: #232629; color: #f0f0f0; }
            QMenuBar { background-color: #232629; color: #f0f0f0; }
            QMenu { background-color: #232629; color: #f0f0f0; }
            QPushButton { background-color: #444; color: #f0f0f0; border: 1px solid #666; }
        """
        self.setStyleSheet(dark_stylesheet)

    def set_light_theme(self):
        """
        Set the application to light theme (default Qt theme).
        """
        self.logger.debug("Setting light theme (default).")
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
        self.logger.debug("UI translations updated.")

    def initialize_database_connection(self):
        """
        Initialize database connection on application startup.
        """
        try:
            # Try to load existing database configuration
            self.logger.debug("Checking for database configuration file.")
            config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database_config.json')
            if os.path.exists(config_file):
                self.logger.debug(f"Found database config file: {config_file}")
                config = read_json(config_file)
                
                from frontend.core.database import DatabaseManager
                self.db_manager = DatabaseManager(**config)
                
                # Test connection silently
                self.logger.debug("Testing database connection silently...")
                if self.db_manager.test_connection():
                    self.logger.info("Database connection established on startup")
                else:
                    self.logger.warning("Database connection test failed on startup")
                    self.db_manager = None
            else:
                self.logger.debug("No database configuration file found. Skipping DB initialization.")
                
        except Exception as e:
            self.logger.error(f"Failed to initialize database connection: {e}", exc_info=True)
            self.error_handler.handle_error(e, "Failed to initialize database connection")
            self.db_manager = None

    # Placeholder methods - these need to be implemented based on the full original code
    def open_project(self):
        """Open an existing project: select .json file and load its data."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        self.logger.debug("Opening project...")
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.t('open_project'), '', 'Project Files (*.json)')
        if file_path:
            try:
                project_data = read_json(file_path)
                self.current_project_dir = os.path.dirname(file_path)
                self.current_project_data = project_data
                self.refresh_project_files()
                # Salva percorso ultimo progetto
                settings = QSettings('LabAutomation', 'App')
                settings.setValue('last_project_path', file_path)
                self.logger.info(f"Project opened: {file_path}")
            except Exception as e:
                self.logger.error(f"Failed to open project: {file_path} - {e}", exc_info=True)
                QMessageBox.warning(self, self.translator.t('open_project'), f"{self.translator.t('project_open_failed')}: {e}")
        
    def refresh_project_files(self):
        """Refresh the list of project files displayed in the UI."""
        self.project_files_list.clear()
        if not self.current_project_dir or not self.current_project_data:
            return
        files = []
        inst_file = self.current_project_data.get('inst_file')
        if inst_file:
            files.append(inst_file)
        files += self.current_project_data.get('eff_files', [])
        files += self.current_project_data.get('was_files', [])
        for f in files:
            item = QListWidgetItem(f)
            self.project_files_list.addItem(item)
        
        # Aggiorna le variabili del progetto dagli strumenti
        self.update_project_variables()
        
        # Aggiorna RemoteControlTab se serve
        if hasattr(self, 'remote_tab') and inst_file:
            # Qui si può aggiungere logica per aggiornare la tab con il nuovo file strumenti
            pass
    
    def update_project_variables(self):
        """
        Aggiorna le variabili di controllo e misura del progetto basandosi sui canali degli strumenti.
        
        Le variabili di controllo derivano da:
        - Alimentatori (power_supplies)
        - Carichi elettronici (electronic_loads)
        
        Le variabili di misura derivano da:
        - Multimetri (multimeters)
        - Oscilloscopi (oscilloscopes)
        - Datalogger (dataloggers)
        """
        if not self.current_project_dir or not self.current_project_data:
            return
        
        inst_file = self.current_project_data.get('inst_file')
        if not inst_file:
            self.logger.debug("No instruments file in project, skipping variable update")
            return
        
        inst_path = os.path.join(self.current_project_dir, inst_file)
        if not os.path.exists(inst_path):
            self.logger.warning(f"Instruments file not found: {inst_path}")
            return
        
        try:
            # Carica i dati degli strumenti
            inst_data = read_json(inst_path)
            instruments = inst_data.get('instruments', [])
            
            # Strumenti che forniscono variabili di controllo (possono essere impostati)
            control_instrument_types = [
                'power_supply', 'power_supplies', 'alimentatore', 'alimentatori',
                'electronic_load', 'electronic_loads', 'carico_elettronico', 'carichi_elettronici'
            ]
            
            # Strumenti che forniscono variabili di misura (vengono letti)
            measure_instrument_types = [
                'multimeter', 'multimeters', 'multimetro', 'multimetri',
                'oscilloscope', 'oscilloscopes', 'oscilloscopio', 'oscilloscopi',
                'datalogger', 'dataloggers'
            ]
            
            control_variables = []
            measure_variables = []
            
            # Estrai le variabili dai canali degli strumenti
            for instrument in instruments:
                inst_type = instrument.get('instrument_type', '').lower()
                channels = instrument.get('channels', [])
                
                for channel in channels:
                    if not channel.get('enabled', True):
                        continue  # Salta canali disabilitati
                    
                    channel_name = channel.get('name', '').strip()
                    if not channel_name:
                        continue  # Salta canali senza nome
                    
                    # Determina se è una variabile di controllo o di misura
                    if inst_type in control_instrument_types:
                        if channel_name not in control_variables:
                            control_variables.append(channel_name)
                            self.logger.debug(f"Added control variable: {channel_name} from {inst_type}")
                    
                    elif inst_type in measure_instrument_types:
                        if channel_name not in measure_variables:
                            measure_variables.append(channel_name)
                            self.logger.debug(f"Added measure variable: {channel_name} from {inst_type}")
            
            # Aggiorna il progetto solo se ci sono modifiche
            current_control = set(self.current_project_data.get('control_variables', []))
            current_measure = set(self.current_project_data.get('measure_variables', []))
            new_control = set(control_variables)
            new_measure = set(measure_variables)
            
            if current_control != new_control or current_measure != new_measure:
                self.current_project_data['control_variables'] = control_variables
                self.current_project_data['measure_variables'] = measure_variables
                self.save_project_json()
                
                self.logger.info(f"Updated project variables - Control: {control_variables}, Measure: {measure_variables}")
            else:
                self.logger.debug("Project variables unchanged")
        
        except Exception as e:
            self.logger.error(f"Error updating project variables: {e}", exc_info=True)
        
    def add_project_file(self):
        """Add a new project file (.eff or .was) using the AddFileDialog."""
        from PyQt6.QtWidgets import QDialog
        dlg = AddFileDialog(self, self.translator)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            file_type = dlg.type_combo.currentData()
            file_name = dlg.name_edit.text().strip()
            if not file_name:
                return
            if not file_name.endswith(file_type):
                file_name += file_type
            file_path = os.path.join(self.current_project_dir, file_name)
            # Crea file vuoto
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('')
            # Aggiorna struttura dati progetto
            if file_type == '.eff':
                if file_name not in self.current_project_data['eff_files']:
                    self.current_project_data['eff_files'].append(file_name)
            elif file_type == '.was':
                if file_name not in self.current_project_data['was_files']:
                    self.current_project_data['was_files'].append(file_name)
            # Salva json progetto
            self.save_project_json()
            self.refresh_project_files()
        
    def add_existing_file(self):
        """Add an existing file (.eff or .was) to the project from the file system."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        if not self.current_project_dir or not self.current_project_data:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, self.translator.t('add_existing_file'), self.current_project_dir, 'Eff (*.eff);;Was (*.was)')
        if not file_path:
            return
        fname = os.path.basename(file_path)
        dest_path = os.path.join(self.current_project_dir, fname)
        # Copia file solo se non esiste già
        if not os.path.exists(dest_path):
            import shutil
            shutil.copy2(file_path, dest_path)
        if fname.endswith('.eff'):
            if fname not in self.current_project_data['eff_files']:
                self.current_project_data['eff_files'].append(fname)
        elif fname.endswith('.was'):
            if fname not in self.current_project_data['was_files']:
                self.current_project_data['was_files'].append(fname)
        else:
            QMessageBox.warning(self, self.translator.t('add_existing_file'), self.translator.t('unsupported_file_type'))
            return
        self.save_project_json()
        self.refresh_project_files()
    
    def save_project_json(self):
        """
        Save the current project data to the project JSON file.
        """
        if not self.current_project_dir or not self.current_project_data:
            self.logger.warning("Cannot save project JSON: project not loaded")
            return
        
        try:
            import json
            from datetime import datetime
            
            # Aggiorna il timestamp di ultimo accesso
            self.current_project_data['last_opened'] = datetime.now().isoformat()
            
            # Percorso del file JSON del progetto
            project_json_path = os.path.join(
                self.current_project_dir,
                f"{self.current_project_data.get('project_name', 'project')}.json"
            )
            
            # Salva il file JSON
            with open(project_json_path, 'w', encoding='utf-8') as f:
                json.dump(self.current_project_data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Project JSON saved: {project_json_path}")
            
        except Exception as e:
            self.logger.error(f"Error saving project JSON: {e}")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self,
                self.translator.t('error') if self.translator else 'Error',
                f"Failed to save project: {str(e)}"
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
        
        file_name = item.text()
        
        # Conferma eliminazione
        reply = QMessageBox.question(
            self,
            self.translator.t('delete_file') if self.translator else 'Delete File',
            f"Do you want to delete '{file_name}' from the project?\n\n"
            f"Choose:\n"
            f"- Yes: Remove from project list only\n"
            f"- No: Cancel\n"
            f"- Discard: Remove from project AND delete file from disk",
            QMessageBox.StandardButton.Yes | 
            QMessageBox.StandardButton.No | 
            QMessageBox.StandardButton.Discard,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.No:
            return  # Annulla operazione
        
        # Rimuovi dalla lista appropriata
        removed = False
        
        # Controlla se è un file .eff
        if file_name in self.current_project_data.get('eff_files', []):
            self.current_project_data['eff_files'].remove(file_name)
            removed = True
            self.logger.info(f"Removed '{file_name}' from eff_files")
        
        # Controlla se è un file .was
        elif file_name in self.current_project_data.get('was_files', []):
            self.current_project_data['was_files'].remove(file_name)
            removed = True
            self.logger.info(f"Removed '{file_name}' from was_files")
        
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
                            self.translator.t('success') if self.translator else 'Success',
                            f"File '{file_name}' removed from project and deleted from disk"
                        )
                    else:
                        self.logger.warning(f"File not found on disk: {file_path}")
                except Exception as e:
                    self.logger.error(f"Error deleting file from disk: {e}")
                    QMessageBox.warning(
                        self,
                        self.translator.t('error') if self.translator else 'Error',
                        f"File removed from project but could not delete from disk:\n{str(e)}"
                    )
            else:
                QMessageBox.information(
                    self,
                    self.translator.t('success') if self.translator else 'Success',
                    f"File '{file_name}' removed from project"
                )
            
            # Aggiorna la lista dei file
            self.refresh_project_files()
        else:
            self.logger.warning(f"File '{file_name}' not found in project data")
            QMessageBox.warning(
                self,
                self.translator.t('warning') if self.translator else 'Warning',
                f"File '{file_name}' not found in project"
            )
        
    def open_settings(self):
        """Open the settings dialog."""
        self.logger.debug("Open settings dialog requested.")
        if self.settings_dialog is None:
            self.logger.debug("Creating SettingsDialog instance for the first time.")
            self.settings_dialog = SettingsDialog(self, self.translator)
        self.settings_dialog.show()
        
    def open_db_settings(self):
        """Open the database settings dialog to configure database connection parameters."""
        try:
            from frontend.ui.database_config_dialog import DatabaseConfigDialog
            dlg = DatabaseConfigDialog(self)
            dlg.exec()
        except ImportError as e:
            QMessageBox.warning(
                self, 
                "Database Settings", 
                f"Database configuration not available. Missing dependencies: {e}\\n\\nInstall psycopg2 to enable database features."
            )
        
    def show_database_config(self):
        """Show database configuration dialog."""
        try:
            # Qui puoi implementare una finestra di configurazione avanzata del database
            QMessageBox.information(self, "Database Config", "Funzione di configurazione avanzata non ancora implementata.")
        except Exception as e:
            self.logger.error(f"Error showing database config: {e}", exc_info=True)
            QMessageBox.warning(self, "Database Config", f"Errore: {e}")
        
    def edit_project_file(self, item):
        """Open a configuration dialog for the selected file based on its type (.eff, .was, .inst)."""
        if not self.current_project_dir:
            return
        fname = item.text()
        file_path = os.path.join(self.current_project_dir, fname)
        if fname.endswith('.eff'):
            # Passa i dati del progetto corrente alla dialog per le variabili
            dlg = EffFileDialog(file_path, self.translator, self.current_project_data, self)
            dlg.exec()
        elif fname.endswith('.was'):
            # Passa i dati del progetto per recuperare i canali dell'oscilloscopio
            dlg = WasFileDialog(file_path, self.translator, self.current_project_data, self)
            dlg.exec()
        elif fname.endswith('.inst'):
            if self.load_instruments is None:
                QMessageBox.warning(self, "Strumenti", "Libreria strumenti non caricata. Impossibile modificare il file .inst.")
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
        
    def show_file_context_menu(self, pos):
        """Show context menu for project files."""
        item = self.project_files_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        copy_action = menu.addAction(self.translator.t('copy_file_name'))
        # paste_action = menu.addAction(self.translator.t('paste_file'))  # Implementa se serve
        delete_action = menu.addAction(self.translator.t('delete_file'))
        action = menu.exec(self.project_files_list.mapToGlobal(pos))
        if action == copy_action:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(item.text())
        elif action == delete_action:
            self.delete_file(item)


class DatabaseDialog(QDialog):
    """
    Dialog for configuring database connection settings.
    """
    
    def __init__(self, parent=None, translator=None):
        """
        Initialize the database settings dialog.
        
        Args:
            parent: Parent widget
            translator: Translator instance for localization
        """
        super().__init__(parent)
        self.translator = translator
        self.error_handler = ErrorHandler()
        self.logger = Logger()
        self.logger.debug("DatabaseDialog.__init__ started.")
        
        self.setWindowTitle(self.translator.t('database_settings'))
        self.setModal(True)
        
        layout = QVBoxLayout()
        form = QFormLayout()
        
        self.host = QLineEdit()
        self.port = QLineEdit()
        self.user = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
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
        self.logger.debug("DatabaseDialog initialized.")

    def save_db_settings(self):
        """
        Save the database settings and test connection.
        """
        self.logger.debug("Attempting to save database settings.")
        try:
            # Validate inputs
            from frontend.core.validator import (
                is_not_empty, is_valid_port, 
                ValidationError as ValidatorError
            )
            
            self.logger.debug("Validating database form inputs.")
            is_not_empty(self.host.text(), "Database host")
            is_valid_port(self.port.text())
            is_not_empty(self.user.text(), "Database user")
            is_not_empty(self.dbname.text(), "Database name")
            
            # Save settings
            self.logger.debug("Saving database settings to QSettings.")
            settings = QSettings('LabAutomation', 'App')
            settings.setValue('db_host', self.host.text())
            settings.setValue('db_port', self.port.text())
            settings.setValue('db_user', self.user.text())
            settings.setValue('db_password', self.password.text())
            settings.setValue('db_name', self.dbname.text())

            # Test connection
            self.logger.debug("Testing new database connection...")
            from frontend.core.DatabaseManager import DatabaseManager
            db = DatabaseManager(
                host=self.host.text(),
                port=int(self.port.text()),
                dbname=self.dbname.text(), 
                user=self.user.text(),
                password=self.password.text()
            )
            
            db.ensure_connection()
            db.close()
            
            self.logger.info("Database connection successful.")
            QMessageBox.information(self, "Database", "Connessione al database riuscita!")
            self.accept()
            
        except ValidatorError as e:
            self.logger.warning(f"Database settings validation failed: {e}")
            QMessageBox.warning(self, "Validation Error", str(e))
        except Exception as e:
            self.logger.error(f"Database connection failed: {e}", exc_info=True)
            self.error_handler.handle_error(e, "Database connection failed")

    def load_db_settings(self):
        """
        Load database settings from QSettings and populate the input fields.
        """
        self.logger.debug("Loading database settings from QSettings.")
        settings = QSettings('LabAutomation', 'App')
        self.host.setText(settings.value('db_host', 'localhost'))
        self.port.setText(settings.value('db_port', '9090'))
        self.user.setText(settings.value('db_user', ''))
        self.password.setText(settings.value('db_password', ''))
        self.dbname.setText(settings.value('db_name', 'prometheus'))
        self.logger.debug("Database settings loaded into dialog.")


class AddFileDialog(QDialog):
    """
    Dialog for adding a new file (.eff or .was) to the project.
    """
    
    def __init__(self, parent=None, translator=None, naming_settings=None):
        """
        Initialize the add file dialog.
        
        Args:
            parent: Parent widget
            translator: Translator instance
            naming_settings: Naming settings for the project
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
        self.logger.debug("AddFileDialog initialized.")