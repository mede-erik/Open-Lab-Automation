"""  
Database configuration dialog for PostgreSQL connection settings.This module provides a GUI for configuring database connection parameters
and testing connectivity.
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
                             QPushButton, QLineEdit, QComboBox, QLabel, 
                             QMessageBox, QProgressBar, QGroupBox, QSpinBox, 
                             QCheckBox, QTextEdit)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont
import json
import os
from typing import Dict, Any
from frontend.core.database import DatabaseManager
from frontend.core.logger import Logger
from frontend.core.database_config import get_database_config_manager


class DatabaseTestThread(QThread):
    """
    Background thread for testing database connectivity without blocking UI.
    """
    
    # Signals for communicating with main thread
    test_finished = pyqtSignal(bool, str)  # success, message
    progress_update = pyqtSignal(str)  # status message
    
    def __init__(self, connection_params: Dict[str, Any]):
        """
        Initialize database test thread.
        
        Args:
            connection_params: Database connection parameters
        """
        super().__init__()
        self.connection_params = connection_params
        self.logger = Logger()
    
    def run(self):
        """
        Run database connectivity test in background thread.
        Note: Connects to 'postgres' database for testing since project databases are created separately.
        """
        try:
            self.progress_update.emit("Connecting to database server...")
            
            # Add 'postgres' database for connection test (always exists)
            test_params = self.connection_params.copy()
            test_params['database'] = 'postgres'
            
            # Create database manager with test parameters
            db_manager = DatabaseManager(**test_params)
            
            self.progress_update.emit("Testing connection...")
            
            # Test basic connectivity
            if db_manager.test_connection():
                success_msg = "Connection successful!\nServer is accessible and credentials are valid."
                self.test_finished.emit(True, success_msg)
            else:
                self.test_finished.emit(False, "Connection test failed")
                
        except Exception as e:
            error_msg = f"Connection error: {str(e)}"
            self.logger.error(error_msg)
            self.test_finished.emit(False, error_msg)


class DatabaseConfigDialog(QDialog):
    """
    Dialog for configuring PostgreSQL connection settings.
    Provides interface for connection parameters and testing.
    """
    
    def __init__(self, parent=None):
        """
        Initialize database configuration dialog.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.logger = Logger()
        self.test_thread = None
        
        # Use secure config manager
        self.config_manager = get_database_config_manager()
        
        self.setWindowTitle("Database Configuration")
        self.setMinimumSize(500, 600)
        self.setModal(True)
        
        # Load existing configuration (password will be decrypted automatically)
        self.config = self.config_manager.load_config()
        
        self.init_ui()
        self.load_form_values()
    
    def init_ui(self):
        """
        Initialize user interface components.
        """
        layout = QVBoxLayout(self)
        
        # Connection parameters group
        conn_group = QGroupBox("Connection Parameters")
        conn_layout = QFormLayout(conn_group)
        
        # Host and port
        host_layout = QHBoxLayout()
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5432)
        host_layout.addWidget(self.host_edit, 3)
        host_layout.addWidget(QLabel("Port:"))
        host_layout.addWidget(self.port_spin, 1)
        conn_layout.addRow("Host:", host_layout)
        
        # Username and password
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("dcdc_app")
        conn_layout.addRow("Username:", self.username_edit)
        
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        conn_layout.addRow("Password:", self.password_edit)
        
        # SSL mode checkbox
        self.ssl_checkbox = QCheckBox("Use SSL Connection")
        conn_layout.addRow("Security:", self.ssl_checkbox)
        
        layout.addWidget(conn_group)
        
        # Test connection group
        test_group = QGroupBox("Connection Test")
        test_layout = QVBoxLayout(test_group)
        
        # Test button and progress
        test_btn_layout = QHBoxLayout()
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self.test_connection)
        test_btn_layout.addWidget(self.test_btn)
        test_btn_layout.addStretch()
        test_layout.addLayout(test_btn_layout)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        test_layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Not tested")
        self.status_label.setWordWrap(True)
        test_layout.addWidget(self.status_label)
        
        layout.addWidget(test_group)
        
        # Info label
        info_label = QLabel(
            "Note: This configuration is used for all projects. "
            "Each project will create its own database automatically."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray; font-style: italic; padding: 10px;")
        layout.addWidget(info_label)
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        
        self.save_btn = QPushButton("Save Configuration")
        self.save_btn.clicked.connect(self.save_configuration)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        
        self.apply_btn = QPushButton("Apply & Close")
        self.apply_btn.clicked.connect(self.apply_and_close)
        self.apply_btn.setDefault(True)
        
        button_layout.addStretch()
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.apply_btn)
        
        layout.addLayout(button_layout)
    
    def load_form_values(self):
        """
        Load configuration values into form fields.
        Password is already decrypted by config_manager.load_config().
        """
        self.host_edit.setText(self.config.get('host', ''))
        self.port_spin.setValue(self.config.get('port', 5432))
        self.username_edit.setText(self.config.get('username', ''))
        self.password_edit.setText(self.config.get('password', ''))
        self.ssl_checkbox.setChecked(self.config.get('use_ssl', False))
    
    def get_connection_params(self) -> Dict[str, Any]:
        """
        Get current connection parameters from form.
        Note: Database name is not included here as it's created by each project.
        
        Returns:
            Dictionary containing connection parameters (host, port, username, password, sslmode)
        """
        params = {
            'host': self.host_edit.text().strip() or 'localhost',
            'port': self.port_spin.value(),
            'username': self.username_edit.text().strip() or 'dcdc_app',
            'password': self.password_edit.text()
        }
        
        if self.ssl_checkbox.isChecked():
            params['sslmode'] = 'require'
        
        return params
    
    def test_connection(self):
        """
        Test database connection in background thread.
        """
        if self.test_thread and self.test_thread.isRunning():
            return
        
        # Get connection parameters
        params = self.get_connection_params()
        
        # Start test thread
        self.test_thread = DatabaseTestThread(params)
        self.test_thread.test_finished.connect(self.on_test_finished)
        self.test_thread.progress_update.connect(self.on_progress_update)
        
        # Update UI for testing state
        self.test_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.status_label.setText("Testing connection...")
        
        self.test_thread.start()
    
    def on_progress_update(self, message: str):
        """
        Handle progress updates from test thread.
        
        Args:
            message: Progress status message
        """
        self.status_label.setText(message)
    
    def on_test_finished(self, success: bool, message: str):
        """
        Handle test completion from background thread.
        
        Args:
            success: Whether test was successful
            message: Result message
        """
        # Update UI
        self.test_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        
        if success:
            self.status_label.setText(f"✓ {message}")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText(f"✗ {message}")
            self.status_label.setStyleSheet("color: red;")
    
    def save_configuration(self):
        """
        Save current configuration to secure location with encrypted password.
        Uses DatabaseConfigManager for cross-platform storage.
        """
        try:
            config = {
                'host': self.host_edit.text().strip(),
                'port': self.port_spin.value(),
                'username': self.username_edit.text().strip(),
                'password': self.password_edit.text(),  # Will be encrypted by config_manager
                'use_ssl': self.ssl_checkbox.isChecked()
            }
            
            # Save using secure config manager (encrypts password automatically)
            if self.config_manager.save_config(config):
                self.config = config
                
                # Show success message with config location
                config_location = self.config_manager.get_config_location()
                msg = f"Configuration saved successfully!\n\nLocation: {config_location}\n\nPassword is encrypted for security."
                QMessageBox.information(self, "Success", msg)
                self.logger.info(f"Database configuration saved to {config_location}")
            else:
                raise Exception("Failed to save configuration")
            
        except Exception as e:
            error_msg = f"Failed to save configuration: {str(e)}"
            QMessageBox.critical(self, "Error", error_msg)
            self.logger.error(error_msg)
    
    def apply_and_close(self):
        """
        Apply configuration and close dialog.
        """
        self.save_configuration()
        self.accept()
    
    def get_database_manager(self) -> DatabaseManager:
        """
        Get configured database manager instance.
        
        Returns:
            DatabaseManager instance with current configuration
        """
        return DatabaseManager(**self.get_connection_params())
    
    def closeEvent(self, event):
        """
        Handle dialog close event.
        
        Args:
            event: Close event
        """
        if self.test_thread and self.test_thread.isRunning():
            self.test_thread.quit()
            self.test_thread.wait()
        event.accept()