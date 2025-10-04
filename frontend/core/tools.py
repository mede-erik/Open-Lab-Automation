"""
Generic and reusable utility functions for Lab Automation.

This module contains utility functions that are used across multiple parts
of the application. Functions here should be generic and not depend on
the state of any specific window.
"""

import json
import csv
import os
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path


def read_json(file_path: str) -> Dict[str, Any]:
    """
    Read and parse a JSON file.
    
    Args:
        file_path (str): Path to the JSON file
        
    Returns:
        Dict[str, Any]: Parsed JSON data
        
    Raises:
        FileNotFoundError: If the file doesn't exist
        json.JSONDecodeError: If the file is not valid JSON
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in file {file_path}: {e}")


def save_json(data: Dict[str, Any], file_path: str) -> None:
    """
    Save data to a JSON file.
    
    Args:
        data (Dict[str, Any]): Data to save
        file_path (str): Path where to save the file
        
    Raises:
        PermissionError: If write access is denied
        OSError: If there's an OS-related error
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except (PermissionError, OSError) as e:
        raise OSError(f"Could not save file {file_path}: {e}")


def save_csv(data: List[List[str]], file_path: str, headers: Optional[List[str]] = None) -> None:
    """
    Save data to a CSV file.
    
    Args:
        data (List[List[str]]): Data rows to save
        file_path (str): Path where to save the file
        headers (Optional[List[str]]): Optional headers for the CSV
        
    Raises:
        PermissionError: If write access is denied
        OSError: If there's an OS-related error
    """
    try:
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            if headers:
                writer.writerow(headers)
            
            writer.writerows(data)
    except (PermissionError, OSError) as e:
        raise OSError(f"Could not save CSV file {file_path}: {e}")


def read_csv(file_path: str, has_headers: bool = True) -> tuple:
    """
    Read data from a CSV file.
    
    Args:
        file_path (str): Path to the CSV file
        has_headers (bool): Whether the first row contains headers
        
    Returns:
        tuple: (headers, data) if has_headers=True, else (None, data)
        
    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"CSV file not found: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            data = list(reader)
            
            if has_headers and data:
                headers = data[0]
                data = data[1:]
                return headers, data
            else:
                return None, data
    except Exception as e:
        raise Exception(f"Error reading CSV file {file_path}: {e}")


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format a datetime object to string.
    
    Args:
        dt (datetime): Datetime object to format
        format_str (str): Format string
        
    Returns:
        str: Formatted datetime string
    """
    return dt.strftime(format_str)


def parse_datetime(dt_str: str, format_str: str = "%Y-%m-%d %H:%M:%S") -> datetime:
    """
    Parse a datetime string to datetime object.
    
    Args:
        dt_str (str): Datetime string to parse
        format_str (str): Format string
        
    Returns:
        datetime: Parsed datetime object
        
    Raises:
        ValueError: If the string doesn't match the format
    """
    try:
        return datetime.strptime(dt_str, format_str)
    except ValueError as e:
        raise ValueError(f"Invalid datetime format '{dt_str}': {e}")


def ensure_directory_exists(directory_path: str) -> None:
    """
    Ensure that a directory exists, create it if it doesn't.
    
    Args:
        directory_path (str): Path to the directory
        
    Raises:
        PermissionError: If directory creation is denied
        OSError: If there's an OS-related error
    """
    try:
        Path(directory_path).mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError) as e:
        raise OSError(f"Could not create directory {directory_path}: {e}")


def get_file_size(file_path: str) -> int:
    """
    Get the size of a file in bytes.
    
    Args:
        file_path (str): Path to the file
        
    Returns:
        int: File size in bytes
        
    Raises:
        FileNotFoundError: If the file doesn't exist
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    return os.path.getsize(file_path)


def is_file_newer(file1: str, file2: str) -> bool:
    """
    Check if file1 is newer than file2.
    
    Args:
        file1 (str): Path to the first file
        file2 (str): Path to the second file
        
    Returns:
        bool: True if file1 is newer than file2
        
    Raises:
        FileNotFoundError: If either file doesn't exist
    """
    if not os.path.exists(file1):
        raise FileNotFoundError(f"File not found: {file1}")
    if not os.path.exists(file2):
        raise FileNotFoundError(f"File not found: {file2}")
    
    return os.path.getmtime(file1) > os.path.getmtime(file2)


def clean_filename(filename: str) -> str:
    """
    Clean a filename by removing invalid characters.
    
    Args:
        filename (str): Original filename
        
    Returns:
        str: Cleaned filename
    """
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    return filename.strip()


def generate_unique_filename(base_path: str, extension: str = "") -> str:
    """
    Generate a unique filename by appending a number if the file exists.
    
    Args:
        base_path (str): Base path without extension
        extension (str): File extension (with or without dot)
        
    Returns:
        str: Unique filename
    """
    if extension and not extension.startswith('.'):
        extension = '.' + extension
    
    filename = base_path + extension
    counter = 1
    
    while os.path.exists(filename):
        filename = f"{base_path}_{counter}{extension}"
        counter += 1
    
    return filename