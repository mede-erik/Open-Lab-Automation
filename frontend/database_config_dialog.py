"""
Database configuration dialog for PostgreSQL/TimescaleDB connection settings.

This module provides a GUI for configuring database connection parameters
and testing connectivity.
"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
                             QLineEdit, QSpinBox, QPushButton, QLabel, QTextEdit,
                             QMessageBox, QGroupBox, QCheckBox, QProgressBar)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont
import json
import os
from typing import Dict, Any
from database import DatabaseManager
from logger import Logger


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
        """
        try:
            self.progress_update.emit("Connecting to database...")
            
            # Create database manager with test parameters
            db_manager = DatabaseManager(**self.connection_params)
            
            self.progress_update.emit("Testing connection...")
            
            # Test basic connectivity
            if db_manager.test_connection():
                self.progress_update.emit("Testing schema...")
                
                # Test schema info retrieval
                schema_info = db_manager.get_schema_info()
                
                success_msg = f"Connection successful!\nTables: {len(schema_info.get('tables', []))}\nHypertables: {len(schema_info.get('hypertables', []))}"
                self.test_finished.emit(True, success_msg)
            else:
                self.test_finished.emit(False, "Connection test failed")
                
        except Exception as e:
            error_msg = f"Connection error: {str(e)}"
            self.logger.error(error_msg)
            self.test_finished.emit(False, error_msg)


class DatabaseConfigDialog(QDialog):
    """
    Dialog for configuring PostgreSQL/TimescaleDB connection settings.
    Provides interface for connection parameters, testing, and schema initialization.
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
        self.db_manager = None
        
        self.setWindowTitle("Database Configuration")
        self.setMinimumSize(500, 600)
        self.setModal(True)
        
        # Load existing configuration
        self.config_file = os.path.join(os.path.dirname(__file__), 'database_config.json')
        self.config = self.load_config()
        
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
        
        # Database name
        self.database_edit = QLineEdit()
        self.database_edit.setPlaceholderText("dcdc_measurements")
        conn_layout.addRow("Database:", self.database_edit)
        
        # Username and password
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("dcdc_app")
        conn_layout.addRow("Username:", self.username_edit)
        
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
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
        
        # Schema management group
        schema_group = QGroupBox("Schema Management")
        schema_layout = QVBoxLayout(schema_group)
        
        schema_btn_layout = QHBoxLayout()
        self.init_schema_btn = QPushButton("Initialize Schema")
        self.init_schema_btn.clicked.connect(self.initialize_schema)
        self.init_schema_btn.setEnabled(False)
        
        self.schema_info_btn = QPushButton("View Schema Info")
        self.schema_info_btn.clicked.connect(self.show_schema_info)
        self.schema_info_btn.setEnabled(False)
        
        schema_btn_layout.addWidget(self.init_schema_btn)
        schema_btn_layout.addWidget(self.schema_info_btn)
        schema_layout.addLayout(schema_btn_layout)
        
        # Schema status
        self.schema_status = QTextEdit()
        self.schema_status.setMaximumHeight(100)
        self.schema_status.setReadOnly(True)
        schema_layout.addWidget(self.schema_status)
        
        layout.addWidget(schema_group)
        
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
    
    def load_config(self) -> Dict[str, Any]:
        """
        Load database configuration from file.
        
        Returns:
            Dictionary containing configuration data
        """
        default_config = {
            'host': 'localhost',
            'port': 5432,
            'database': 'dcdc_measurements',
            'username': 'dcdc_app',
            'password': '',
            'use_ssl': False
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # Merge with defaults to handle missing keys
                    default_config.update(config)
                    self.logger.debug("Loaded database configuration from file")
            return default_config
        except Exception as e:
            self.logger.warning(f"Failed to load database config: {str(e)}")
            return default_config
    
    def load_form_values(self):
        """
        Load configuration values into form fields.
        """
        self.host_edit.setText(self.config.get('host', ''))
        self.port_spin.setValue(self.config.get('port', 5432))
        self.database_edit.setText(self.config.get('database', ''))
        self.username_edit.setText(self.config.get('username', ''))
        self.password_edit.setText(self.config.get('password', ''))
        self.ssl_checkbox.setChecked(self.config.get('use_ssl', False))
    
    def get_connection_params(self) -> Dict[str, Any]:
        """
        Get current connection parameters from form.
        
        Returns:
            Dictionary containing connection parameters
        """
        params = {
            'host': self.host_edit.text().strip() or 'localhost',
            'port': self.port_spin.value(),
            'database': self.database_edit.text().strip() or 'dcdc_measurements',
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
            self.init_schema_btn.setEnabled(True)
            self.schema_info_btn.setEnabled(True)
            
            # Store successful connection params
            self.db_manager = DatabaseManager(**self.get_connection_params())
        else:
            self.status_label.setText(f"✗ {message}")
            self.status_label.setStyleSheet("color: red;")
            self.init_schema_btn.setEnabled(False)
            self.schema_info_btn.setEnabled(False)
            self.db_manager = None
    
    def initialize_schema(self):
        """
        Initialize database schema with tables and indexes.
        """
        if not self.db_manager:
            QMessageBox.warning(self, "Warning", "Please test connection first")
            return
        
        reply = QMessageBox.question(
            self, "Initialize Schema",
            "This will create database tables and indexes.\nAre you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.schema_status.append("Initializing database schema...")
                success = self.db_manager.initialize_database()
                
                if success:
                    self.schema_status.append("✓ Schema initialized successfully")
                    self.logger.info("Database schema initialized successfully")
                else:
                    self.schema_status.append("✗ Schema initialization failed")
                    self.logger.error("Database schema initialization failed")
                    
            except Exception as e:
                error_msg = f"Schema initialization error: {str(e)}"
                self.schema_status.append(f"✗ {error_msg}")
                self.logger.error(error_msg)
    
    def show_schema_info(self):
        """
        Display current schema information.
        """
        if not self.db_manager:
            QMessageBox.warning(self, "Warning", "Please test connection first")
            return
        
        try:
            schema_info = self.db_manager.get_schema_info()
            
            info_text = "Current Schema Information:\n\n"
            
            # Tables
            tables = schema_info.get('tables', [])
            info_text += f"Tables ({len(tables)}):\n"
            for table in tables:
                info_text += f"  - {table['table_name']} ({table['table_type']})\n"
            
            # Hypertables
            hypertables = schema_info.get('hypertables', [])
            if hypertables:
                info_text += f"\nHypertables ({len(hypertables)}):\n"
                for ht in hypertables:
                    info_text += f"  - {ht['hypertable_name']} ({ht['num_dimensions']} dimensions)\n"
            
            self.schema_status.clear()
            self.schema_status.append(info_text)
            
        except Exception as e:
            error_msg = f"Failed to get schema info: {str(e)}"
            self.schema_status.append(f"✗ {error_msg}")
            self.logger.error(error_msg)
    
    def save_configuration(self):
        """
        Save current configuration to file.
        """
        try:
            config = {
                'host': self.host_edit.text().strip(),
                'port': self.port_spin.value(),
                'database': self.database_edit.text().strip(),
                'username': self.username_edit.text().strip(),
                'password': self.password_edit.text(),
                'use_ssl': self.ssl_checkbox.isChecked()
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            
            self.config = config
            QMessageBox.information(self, "Success", "Configuration saved successfully!")
            self.logger.info("Database configuration saved")
            
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