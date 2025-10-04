"""
Main entry point for Lab Automation application.

This module initializes the PyQt6 application and creates the main window.
It should remain as simple as possible, handling only application startup.
"""

import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings

# ---------------------------------------------------------------------------
# Dynamic import path bootstrap
# Permette di eseguire questo script anche da fuori la cartella frontend,
# ad esempio: `python frontend/main.py` dalla root del repository.
# In tal caso Python aggiunge solo la root repo a sys.path e il pacchetto
# "ui" non verrebbe trovato. Aggiungiamo quindi la directory di questo file.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
del _THIS_DIR

from frontend.ui.main_window import MainWindow
from frontend.core.Translator import Translator
from frontend.core.logger import Logger


def main():
    """
    Main function to start the PyQt6 application.
    Sets up application name, loads language settings, and shows the main window.
    """
    # Initialize logger
    logger = Logger()
    logger.debug("=================================================")
    logger.debug("    Open Lab Automation application starting...")
    logger.debug("=================================================")
    
    # Create the QApplication instance
    app = QApplication(sys.argv)
    logger.debug("QApplication instance created.")
    
    # Set organization and application name for QSettings
    app.setOrganizationName('LabAutomation')
    app.setApplicationName('Open Lab Automation')
    logger.debug("Organization and AppName set for QSettings.")
    
    # Load language from settings
    settings = QSettings('LabAutomation', 'App')
    lang = settings.value('language', 'it')  # Default to Italian
    logger.debug(f"Loaded language from settings: '{lang}'")
    
    # Create Translator instance
    translator = Translator(default_lang=lang)
    logger.debug("Translator instance created.")
    
    # Create and show the main window
    try:
        logger.debug("Creating main window...")
        window = MainWindow()
        window.show()
        logger.debug("Main window created and shown successfully.")
    except Exception as e:
        from frontend.core.errorhandler import ErrorHandler
        error_handler = ErrorHandler()
        error_handler.handle_error(e, "Failed to create main window")
        logger.critical(f"Critical error during main window creation: {e}", exc_info=True)
        sys.exit(1)
    
    # Start the Qt event loop
    logger.debug("Starting Qt event loop...")
    exit_code = app.exec()
    logger.debug(f"Application exiting with code {exit_code}.")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()