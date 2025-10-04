import logging
import os
from datetime import datetime
from typing import Optional

class Logger:
    """
    Class to handle application logging.
    Writes logs to both console and file in the project folder.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.logger = logging.getLogger('LabAutomation')
        self.logger.setLevel(logging.DEBUG)
        self.current_log_file = None
        self.project_dir = None
        
        # Log formatter
        formatter = logging.Formatter(
            '[%(levelname)s] - %(asctime)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        self.file_handler = None
    
    def set_project_directory(self, project_dir: str):
        """
        Set the project directory and create/update the log file.
        
        Args:
            project_dir: The project directory path
        """
        self.project_dir = project_dir
        
        # Remove old file handler if present
        if self.file_handler:
            self.logger.removeHandler(self.file_handler)
            self.file_handler = None
            
        if project_dir:
            # Create logs folder if it doesn't exist
            logs_dir = os.path.join(project_dir, 'logs')
            os.makedirs(logs_dir, exist_ok=True)
            
            # File name with timestamp
            timestamp = datetime.now().strftime('%Y%m%d')
            log_file = os.path.join(logs_dir, f'lab_automation_{timestamp}.log')
            
            # Create file handler
            self.file_handler = logging.FileHandler(log_file, encoding='utf-8')
            self.file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                '[%(levelname)s] - %(asctime)s - %(message)s',
                datefmt='%H:%M:%S'
            )
            self.file_handler.setFormatter(formatter)
            self.logger.addHandler(self.file_handler)
            self.current_log_file = log_file
            
            self.info(f"Log file created: {log_file}")

    def debug(self, message: str, **kwargs):
        """Log a debug message"""
        self.logger.debug(message, **kwargs)
        
    def info(self, message: str, **kwargs):
        """Log an informational message"""
        self.logger.info(message, **kwargs)
        
    def warning(self, message: str, **kwargs):
        """Log a warning message"""
        self.logger.warning(message, **kwargs)
        
    def error(self, message: str, **kwargs):
        """Log an error message"""
        self.logger.error(message, **kwargs)
        
    def critical(self, message: str, **kwargs):
        """Log a critical error message"""
        self.logger.critical(message, **kwargs)
        
    def get_current_log_file(self) -> Optional[str]:
        """Returns the current log file path"""
        return self.current_log_file
