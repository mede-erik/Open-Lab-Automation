"""
Data validation functions for Lab Automation.

This module contains all functions for input data validation.
Each function performs a specific validation and returns True/False
or raises a ValidationError for detailed error handling.
"""

import re
import ipaddress
from typing import Union, List, Any
from datetime import datetime
from frontend.core.errorhandler import ValidationError, ErrorCode


def is_valid_email(email: str) -> bool:
    """
    Validate email address format.
    
    Args:
        email (str): Email address to validate
        
    Returns:
        bool: True if email is valid
        
    Raises:
        ValidationError: If email format is invalid
    """
    if not email or not isinstance(email, str):
        raise ValidationError(
            ErrorCode.VALID_EMPTY_FIELD,
            "Email address cannot be empty"
        )
    
    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(pattern, email):
        raise ValidationError(
            ErrorCode.VALID_INVALID_EMAIL,
            f"Invalid email format: {email}"
        )
    
    return True


def is_valid_ip_address(ip: str) -> bool:
    """
    Validate IP address (IPv4 or IPv6).
    
    Args:
        ip (str): IP address to validate
        
    Returns:
        bool: True if IP address is valid
        
    Raises:
        ValidationError: If IP address is invalid
    """
    if not ip or not isinstance(ip, str):
        raise ValidationError(
            ErrorCode.VALID_EMPTY_FIELD,
            "IP address cannot be empty"
        )
    
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        raise ValidationError(
            ErrorCode.VALID_INVALID_IP,
            f"Invalid IP address format: {ip}"
        )


def is_valid_port(port: Union[str, int]) -> bool:
    """
    Validate port number (1-65535).
    
    Args:
        port (Union[str, int]): Port number to validate
        
    Returns:
        bool: True if port is valid
        
    Raises:
        ValidationError: If port is invalid
    """
    if port is None or port == "":
        raise ValidationError(
            ErrorCode.VALID_EMPTY_FIELD,
            "Port number cannot be empty"
        )
    
    try:
        port_int = int(port)
    except (ValueError, TypeError):
        raise ValidationError(
            ErrorCode.VALID_INVALID_PORT,
            f"Port must be a number: {port}"
        )
    
    if not (1 <= port_int <= 65535):
        raise ValidationError(
            ErrorCode.VALID_INVALID_PORT,
            f"Port must be between 1 and 65535: {port_int}"
        )
    
    return True


def is_numeric(value: Union[str, int, float]) -> bool:
    """
    Check if value is numeric.
    
    Args:
        value (Union[str, int, float]): Value to check
        
    Returns:
        bool: True if value is numeric
        
    Raises:
        ValidationError: If value is not numeric
    """
    if value is None or value == "":
        raise ValidationError(
            ErrorCode.VALID_EMPTY_FIELD,
            "Value cannot be empty"
        )
    
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        raise ValidationError(
            ErrorCode.VALID_OUT_OF_RANGE,
            f"Value is not numeric: {value}"
        )


def is_positive_number(value: Union[str, int, float]) -> bool:
    """
    Check if value is a positive number.
    
    Args:
        value (Union[str, int, float]): Value to check
        
    Returns:
        bool: True if value is positive
        
    Raises:
        ValidationError: If value is not positive
    """
    if not is_numeric(value):
        return False
    
    num_value = float(value)
    if num_value <= 0:
        raise ValidationError(
            ErrorCode.VALID_OUT_OF_RANGE,
            f"Value must be positive: {num_value}"
        )
    
    return True


def is_in_range(value: Union[str, int, float], min_val: float, max_val: float) -> bool:
    """
    Check if value is within specified range.
    
    Args:
        value (Union[str, int, float]): Value to check
        min_val (float): Minimum allowed value
        max_val (float): Maximum allowed value
        
    Returns:
        bool: True if value is in range
        
    Raises:
        ValidationError: If value is out of range
    """
    if not is_numeric(value):
        return False
    
    num_value = float(value)
    if not (min_val <= num_value <= max_val):
        raise ValidationError(
            ErrorCode.VALID_OUT_OF_RANGE,
            f"Value {num_value} must be between {min_val} and {max_val}"
        )
    
    return True


def is_not_empty(value: str, field_name: str = "Field") -> bool:
    """
    Check if string is not empty or whitespace.
    
    Args:
        value (str): Value to check
        field_name (str): Name of the field for error message
        
    Returns:
        bool: True if value is not empty
        
    Raises:
        ValidationError: If value is empty
    """
    if not value or not isinstance(value, str) or not value.strip():
        raise ValidationError(
            ErrorCode.VALID_EMPTY_FIELD,
            f"{field_name} cannot be empty"
        )
    
    return True


def is_valid_filename(filename: str) -> bool:
    """
    Validate filename (no invalid characters for filesystem).
    
    Args:
        filename (str): Filename to validate
        
    Returns:
        bool: True if filename is valid
        
    Raises:
        ValidationError: If filename is invalid
    """
    if not is_not_empty(filename, "Filename"):
        return False
    
    # Invalid characters for most filesystems
    invalid_chars = '<>:"/\\|?*'
    
    for char in invalid_chars:
        if char in filename:
            raise ValidationError(
                ErrorCode.VALID_INVALID_FORMAT,
                f"Filename contains invalid character '{char}': {filename}"
            )
    
    # Check for reserved names (Windows)
    reserved_names = ['CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4', 
                     'COM5', 'COM6', 'COM7', 'COM8', 'COM9', 'LPT1', 'LPT2', 
                     'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9']
    
    base_name = filename.split('.')[0].upper()
    if base_name in reserved_names:
        raise ValidationError(
            ErrorCode.VALID_INVALID_FORMAT,
            f"Filename uses reserved name: {filename}"
        )
    
    return True


def is_date_in_range(date_str: str, start_date: str, end_date: str, 
                    date_format: str = "%Y-%m-%d") -> bool:
    """
    Check if date is within specified range.
    
    Args:
        date_str (str): Date to check
        start_date (str): Start of range
        end_date (str): End of range
        date_format (str): Date format string
        
    Returns:
        bool: True if date is in range
        
    Raises:
        ValidationError: If date is invalid or out of range
    """
    try:
        date_obj = datetime.strptime(date_str, date_format)
        start_obj = datetime.strptime(start_date, date_format)
        end_obj = datetime.strptime(end_date, date_format)
    except ValueError as e:
        raise ValidationError(
            ErrorCode.VALID_INVALID_FORMAT,
            f"Invalid date format: {e}"
        )
    
    if not (start_obj <= date_obj <= end_obj):
        raise ValidationError(
            ErrorCode.VALID_OUT_OF_RANGE,
            f"Date {date_str} must be between {start_date} and {end_date}"
        )
    
    return True


def is_valid_visa_address(address: str) -> bool:
    """
    Validate VISA instrument address format.
    
    Args:
        address (str): VISA address to validate
        
    Returns:
        bool: True if address format is valid
        
    Raises:
        ValidationError: If address format is invalid
    """
    if not is_not_empty(address, "VISA address"):
        return False
    
    # Common VISA address patterns
    patterns = [
        r'^TCPIP::.+::\d+::SOCKET$',  # TCP/IP Socket
        r'^TCPIP::.+::inst\d*::INSTR$',  # TCP/IP VXI-11
        r'^USB::.+::.+::.+::INSTR$',  # USB
        r'^GPIB::\d+::INSTR$',  # GPIB
        r'^ASRL\d+::INSTR$',  # Serial
    ]
    
    for pattern in patterns:
        if re.match(pattern, address):
            return True
    
    raise ValidationError(
        ErrorCode.VALID_INVALID_FORMAT,
        f"Invalid VISA address format: {address}"
    )


def validate_list_not_empty(items: List[Any], field_name: str = "List") -> bool:
    """
    Check if list is not empty.
    
    Args:
        items (List[Any]): List to check
        field_name (str): Name of the field for error message
        
    Returns:
        bool: True if list is not empty
        
    Raises:
        ValidationError: If list is empty
    """
    if not items or len(items) == 0:
        raise ValidationError(
            ErrorCode.VALID_EMPTY_FIELD,
            f"{field_name} cannot be empty"
        )
    
    return True