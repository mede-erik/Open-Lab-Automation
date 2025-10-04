"""
Core module for Lab Automation.

This module contains core functionality including error handling,
data validation, utility functions, database management, and logging.
"""

from .errorhandler import ErrorHandler, ErrorCode, ValidationError, VISAError, FileError, UIError
from .tools import (
    read_json, save_json, save_csv, read_csv, format_datetime, 
    parse_datetime, ensure_directory_exists, get_file_size, 
    is_file_newer, clean_filename, generate_unique_filename
)
from .validator import (
    is_valid_email, is_valid_ip_address, is_valid_port, is_numeric,
    is_positive_number, is_in_range, is_not_empty, is_valid_filename,
    is_date_in_range, is_valid_visa_address, validate_list_not_empty
)
from .logger import Logger
# from .models import Project  # Commented out to avoid psycopg2 dependency
# from .database import DatabaseManager  # Commented out to avoid psycopg2 dependency
from .Translator import Translator
from .LoadInstruments import LoadInstruments

__all__ = [
    # Error handling
    'ErrorHandler', 'ErrorCode', 'ValidationError', 'VISAError', 'FileError', 'UIError',
    
    # Tools
    'read_json', 'save_json', 'save_csv', 'read_csv', 'format_datetime',
    'parse_datetime', 'ensure_directory_exists', 'get_file_size',
    'is_file_newer', 'clean_filename', 'generate_unique_filename',
    
    # Validation
    'is_valid_email', 'is_valid_ip_address', 'is_valid_port', 'is_numeric',
    'is_positive_number', 'is_in_range', 'is_not_empty', 'is_valid_filename',
    'is_date_in_range', 'is_valid_visa_address', 'validate_list_not_empty',
    
    # Other core components
    'Logger', 'Translator', 'LoadInstruments'
    # 'Project', 'DatabaseManager'  # Excluded due to psycopg2 dependency
]