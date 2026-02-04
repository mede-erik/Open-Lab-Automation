"""
Centralized error handling module for Lab Automation.

This module provides a unified error handling system with standardized error codes
and consistent error reporting across the application.

Error Code Format: [RESOURCE-XXX]
- RESOURCE: 3-4 letter abbreviation identifying the resource/component (e.g., VISA, FILE, DB, NET, VALID)
- XXX: Three-digit progressive number uniquely identifying the error within that resource

Examples:
- [VISA-001]: VISA connection failed
- [FILE-002]: Configuration file not found
- [VALID-005]: Invalid email format
"""
import logging
from enum import Enum
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QObject, pyqtSignal


class ErrorCode(Enum):
    """Standardized error codes for the application"""
    
    # VISA related errors (VISA-XXX)
    VISA_CONNECTION_FAILED = "[VISA-001]"
    VISA_RESOURCE_NOT_FOUND = "[VISA-002]"
    VISA_COMMUNICATION_ERROR = "[VISA-003]"
    VISA_TIMEOUT_ERROR = "[VISA-004]"
    VISA_NOT_AVAILABLE = "[VISA-005]"
    
    # File related errors (FILE-XXX)
    FILE_NOT_FOUND = "[FILE-001]"
    FILE_ACCESS_DENIED = "[FILE-002]"
    FILE_CORRUPT = "[FILE-003]"
    FILE_INVALID_FORMAT = "[FILE-004]"
    
    # Validation related errors (VALID-XXX)
    VALID_INVALID_EMAIL = "[VALID-001]"
    VALID_INVALID_IP = "[VALID-002]"
    VALID_INVALID_PORT = "[VALID-003]"
    VALID_EMPTY_FIELD = "[VALID-004]"
    VALID_OUT_OF_RANGE = "[VALID-005]"
    VALID_INVALID_FORMAT = "[VALID-006]"
    
    # Database related errors (DB-XXX)
    DB_CONNECTION_ERROR = "[DB-001]"
    DB_QUERY_ERROR = "[DB-002]"
    DB_TIMEOUT = "[DB-003]"
    
    # Network related errors (NET-XXX)
    NET_CONNECTION_TIMEOUT = "[NET-001]"
    NET_HOST_UNREACHABLE = "[NET-002]"
    NET_DNS_ERROR = "[NET-003]"
    
    # UI related errors (UI-XXX)
    UI_WIDGET_DELETED = "[UI-001]"
    UI_INVALID_STATE = "[UI-002]"
    UI_TIMER_ERROR = "[UI-003]"
    
    # Datalogger related errors (DL-XXX)
    DL_NO_SLOTS = "[DL-001]"
    DL_INVALID_MODULE = "[DL-002]"
    DL_INCOMPATIBLE_MODULE = "[DL-003]"
    DL_MODULE_NOT_FOUND = "[DL-004]"
    DL_SLOT_EMPTY = "[DL-005]"
    DL_MODULE_DISABLED = "[DL-006]"
    DL_INVALID_SLOT_NUMBER = "[DL-007]"
    DL_CONFIGURATION_ERROR = "[DL-008]"
    
    # Tool related errors (TOOL-XXX)
    TOOL_NO_INSTRUMENT_SELECTED = "[TOOL-001]"
    TOOL_INSTRUMENT_NOT_FOUND = "[TOOL-002]"
    TOOL_MISSING_COMMANDS = "[TOOL-003]"
    TOOL_PARAMETER_EXCEEDS_LIMIT = "[TOOL-004]"
    TOOL_COMMAND_FAILED = "[TOOL-005]"
    TOOL_PULSE_ALREADY_RUNNING = "[TOOL-006]"
    TOOL_MISSING_CAPABILITIES = "[TOOL-007]"
    TOOL_POWER_EXCEEDS_LIMIT = "[TOOL-008]"
    
    # Project related errors (PROJ-XXX)
    PROJ_NOT_FOUND = "[PROJ-001]"
    PROJ_CORRUPT = "[PROJ-002]"
    PROJ_INVALID_FORMAT = "[PROJ-003]"
    PROJ_SAVE_FAILED = "[PROJ-004]"
    PROJ_LOAD_FAILED = "[PROJ-005]"
    PROJ_INCOMPATIBLE_VERSION = "[PROJ-006]"
    PROJ_MISSING_FILES = "[PROJ-007]"
    PROJ_ALREADY_EXISTS = "[PROJ-008]"
    
    # Instrument configuration errors (INST-XXX)
    INST_NOT_SUPPORTED = "[INST-001]"
    INST_INVALID_CONFIG = "[INST-002]"
    INST_DUPLICATE = "[INST-003]"
    INST_INVALID_TYPE = "[INST-004]"
    INST_MISSING_PARAMETERS = "[INST-005]"
    INST_CONNECTION_REQUIRED = "[INST-006]"
    INST_NOT_INITIALIZED = "[INST-007]"
    INST_INCOMPATIBLE_FIRMWARE = "[INST-008]"
    
    # Application configuration errors (CFG-XXX)
    CFG_FILE_MISSING = "[CFG-001]"
    CFG_INVALID_VALUE = "[CFG-002]"
    CFG_INCOMPATIBLE_SETTINGS = "[CFG-003]"
    CFG_PARSE_ERROR = "[CFG-004]"
    CFG_SAVE_FAILED = "[CFG-005]"
    CFG_LOAD_FAILED = "[CFG-006]"
    CFG_RESET_REQUIRED = "[CFG-007]"
    
    # Instrument library errors (LIB-XXX)
    LIB_NOT_FOUND = "[LIB-001]"
    LIB_CORRUPT = "[LIB-002]"
    LIB_MODEL_NOT_FOUND = "[LIB-003]"
    LIB_SERIES_NOT_FOUND = "[LIB-004]"
    LIB_INVALID_STRUCTURE = "[LIB-005]"
    LIB_MISSING_COMMANDS = "[LIB-006]"
    LIB_INCOMPATIBLE_VERSION = "[LIB-007]"
    LIB_UPDATE_FAILED = "[LIB-008]"
    
    # SCPI command specific errors (SCPI-XXX)
    SCPI_COMMAND_NOT_SUPPORTED = "[SCPI-001]"
    SCPI_SYNTAX_ERROR = "[SCPI-002]"
    SCPI_INVALID_RESPONSE = "[SCPI-003]"
    SCPI_PARAMETER_ERROR = "[SCPI-004]"
    SCPI_EXECUTION_ERROR = "[SCPI-005]"
    SCPI_QUERY_INTERRUPTED = "[SCPI-006]"
    SCPI_DEVICE_ERROR = "[SCPI-007]"
    
    # Data acquisition errors (DATA-XXX)
    DATA_CORRUPT = "[DATA-001]"
    DATA_INVALID_FORMAT = "[DATA-002]"
    DATA_ACQUISITION_FAILED = "[DATA-003]"
    DATA_BUFFER_OVERFLOW = "[DATA-004]"
    DATA_SAVE_FAILED = "[DATA-005]"
    DATA_LOAD_FAILED = "[DATA-006]"
    DATA_OUT_OF_RANGE = "[DATA-007]"
    DATA_INCOMPLETE = "[DATA-008]"
    
    # Project database errors (PJDB-XXX)
    PJDB_CONNECTION_FAILED = "[PJDB-001]"
    PJDB_NOT_SPECIFIED = "[PJDB-002]"
    PJDB_QUERY_ERROR = "[PJDB-003]"
    PJDB_TABLE_NOT_FOUND = "[PJDB-004]"
    PJDB_TIMEOUT = "[PJDB-005]"
    PJDB_SCHEMA_ERROR = "[PJDB-006]"
    PJDB_DATA_INTEGRITY = "[PJDB-007]"
    
    # System errors (SYS-XXX)
    SYS_RESOURCE_UNAVAILABLE = "[SYS-001]"
    SYS_INSUFFICIENT_MEMORY = "[SYS-002]"
    SYS_THREAD_ERROR = "[SYS-003]"
    SYS_PERMISSION_DENIED = "[SYS-004]"
    SYS_DEPENDENCY_MISSING = "[SYS-005]"
    SYS_INITIALIZATION_FAILED = "[SYS-006]"
    SYS_UNEXPECTED_ERROR = "[SYS-007]"


class ValidationError(Exception):
    """Custom exception for validation errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class VISAError(Exception):
    """Custom exception for VISA-related errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class FileError(Exception):
    """Custom exception for file-related errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class UIError(Exception):
    """Custom exception for UI-related errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class DataloggerError(Exception):
    """Custom exception for datalogger-related errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class ToolError(Exception):
    """Custom exception for tool-related errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class ProjectError(Exception):
    """Custom exception for project-related errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class InstrumentError(Exception):
    """Custom exception for instrument configuration errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class ConfigError(Exception):
    """Custom exception for configuration-related errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class LibraryError(Exception):
    """Custom exception for instrument library errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class SCPIError(Exception):
    """Custom exception for SCPI command errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class DataError(Exception):
    """Custom exception for data acquisition/processing errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class ProjectDatabaseError(Exception):
    """Custom exception for project database errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class SystemError(Exception):
    """Custom exception for system-level errors"""
    def __init__(self, error_code: ErrorCode, message: str = ""):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code.value}: {message}")


class ErrorHandler(QObject):
    """
    Centralized error handler for the application.
    
    Provides methods to handle, log, and display errors consistently.
    """
    
    # Signal emitted when an error occurs
    error_occurred = pyqtSignal(str, str)  # (error_code, message)
    
    def __init__(self, logger=None):
        super().__init__()
        self.logger = logger or logging.getLogger(__name__)
    
    def handle_error(self, exception, user_message="An error occurred", show_dialog=True):
        """
        Handle an exception with consistent logging and user notification.
        Uses structured logging format: LEVEL-CODE-Message
        
        Args:
            exception: The exception that occurred
            user_message: User-friendly message to display
            show_dialog: Whether to show a dialog to the user
        """
        error_code = ""
        technical_message = str(exception)
        
        # Extract error code if it's one of our custom exceptions
        if hasattr(exception, 'error_code'):
            error_code_enum = exception.error_code
            # Remove brackets from error code for structured format
            error_code = error_code_enum.value.strip('[]')
            if hasattr(exception, 'message') and exception.message:
                technical_message = exception.message
        
        # Log with structured format
        if error_code:
            log_message = f"[{error_code}] {technical_message}"
        else:
            log_message = technical_message
        self.logger.error(log_message, exc_info=True)
        
        # Emit signal
        self.error_occurred.emit(error_code, technical_message)
        
        # Show dialog if requested
        if show_dialog:
            self.show_error_dialog(error_code, user_message, technical_message)
    
    def show_error_dialog(self, error_code="", user_message="An error occurred", technical_message=""):
        """
        Show a standardized error dialog to the user.
        
        Args:
            error_code: Standardized error code
            user_message: User-friendly message
            technical_message: Technical details for support
        """
        try:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("Error")
            
            # Construct the message
            if error_code:
                full_message = f"{user_message}\\n\\nError Code: {error_code}"
                if technical_message:
                    full_message += f"\\nDetails: {technical_message}"
            else:
                full_message = user_message
                if technical_message:
                    full_message += f"\\nDetails: {technical_message}"
            
            msg_box.setText(full_message)
            
            if error_code:
                msg_box.setInformativeText("Please contact support with the error code if the problem persists.")
            
            msg_box.exec()
        except Exception as e:
            # Fallback if GUI is not available
            print(f"Error displaying dialog: {e}")
            print(f"Original error: {error_code} {user_message} - {technical_message}")
    
    def handle_visa_error(self, exception, context="VISA operation"):
        """
        Handle VISA-specific errors with appropriate error codes.
        
        Args:
            exception: The VISA exception
            context: Context where the error occurred
        """
        if "VI_ERROR_RSRC_NFOUND" in str(exception):
            visa_error = VISAError(
                ErrorCode.VISA_RESOURCE_NOT_FOUND,
                f"{context}: Resource not found or not available"
            )
        elif "can't connect to server" in str(exception).lower():
            visa_error = VISAError(
                ErrorCode.VISA_CONNECTION_FAILED,
                f"{context}: Unable to connect to instrument server"
            )
        elif "timeout" in str(exception).lower():
            visa_error = VISAError(
                ErrorCode.VISA_TIMEOUT_ERROR,
                f"{context}: Communication timeout"
            )
        else:
            visa_error = VISAError(
                ErrorCode.VISA_COMMUNICATION_ERROR,
                f"{context}: {str(exception)}"
            )
        
        self.handle_error(visa_error, f"Instrument communication error during {context}")
    
    def handle_ui_error(self, exception, context="UI operation"):
        """
        Handle UI-specific errors, particularly widget lifecycle issues.
        
        Args:
            exception: The UI exception
            context: Context where the error occurred
        """
        if "wrapped C/C++ object" in str(exception) and "has been deleted" in str(exception):
            ui_error = UIError(
                ErrorCode.UI_WIDGET_DELETED,
                f"{context}: Widget was deleted while still being accessed"
            )
        else:
            ui_error = UIError(
                ErrorCode.UI_INVALID_STATE,
                f"{context}: {str(exception)}"
            )
        
        self.handle_error(ui_error, f"User interface error during {context}")


# Global error handler instance
_global_error_handler = None


def get_error_handler(logger=None):
    """
    Get the global error handler instance.
    
    Args:
        logger: Optional logger to use (only used on first call)
    
    Returns:
        ErrorHandler: The global error handler instance
    """
    global _global_error_handler
    if _global_error_handler is None:
        _global_error_handler = ErrorHandler(logger)
    return _global_error_handler


def handle_error(exception, user_message="An error occurred", show_dialog=True):
    """
    Convenience function to handle errors using the global error handler.
    
    Args:
        exception: The exception that occurred
        user_message: User-friendly message to display
        show_dialog: Whether to show a dialog to the user
    """
    handler = get_error_handler()
    handler.handle_error(exception, user_message, show_dialog)