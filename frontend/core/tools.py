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


def diagnose_connection(visa_address: str) -> dict:
    """
    Perform diagnostic tests on an instrument TCP/IP connection.

    Parses common TCPIP VISA address forms including VXI-11 (::inst0::INSTR),
    HiSLIP (::hislip0::INSTR), and socket (::port::SOCKET) variants.
    Uses Python's built-in ``socket`` module for cross-platform host/port
    reachability – no external tools required.

    Args:
        visa_address: VISA address to diagnose (e.g.
            ``'TCPIP0::192.168.1.100::inst0::INSTR'``).

    Returns:
        Dictionary with diagnostic results containing keys:
        ``visa_address``, ``address_valid``, ``host_resolves``,
        ``host_reachable``, ``port_open``, ``visa_available``,
        ``recommendations``, and optionally ``host``, ``port``,
        ``resolved_addresses``.
    """
    import re
    import socket as _socket

    try:
        import pyvisa as _pv  # noqa: F401
        visa_available = True
    except ImportError:
        visa_available = False

    results: Dict[str, Any] = {
        'visa_address': visa_address,
        'address_valid': False,
        'host_resolves': False,   # True when DNS resolution succeeds
        'host_reachable': False,  # True only when an actual TCP connection succeeds
        'port_open': False,
        'visa_available': visa_available,
        'recommendations': [],
    }

    # Parse VISA address to extract host and port.
    # Accepts all common TCPIP forms:
    #   TCPIP0::host::INSTR                      (VXI-11, port 111)
    #   TCPIP0::host::inst0::INSTR               (VXI-11 named resource)
    #   TCPIP0::host::hislip0[,port]::INSTR      (HiSLIP, port 4880)
    #   TCPIP0::host::<numeric_port>::SOCKET      (raw socket)
    #   TCPIP0::host::<numeric_port>::INSTR       (numeric port)
    try:
        tcpip_pattern = (
            r'^TCPIP\d*::([^:]+)'
            r'(?:::((?:inst\d+)|(?:hislip\d+(?:,\d+)?)|(?:\d+)))?'
            r'::(?:INSTR|SOCKET)$'
        )
        match = re.match(tcpip_pattern, visa_address, re.IGNORECASE)

        if match:
            results['address_valid'] = True
            host = match.group(1)
            resource_seg = match.group(2) or ''  # e.g. 'inst0', 'hislip0', 'hislip0,4880', '5025', ''

            # Determine port from resource segment
            if re.match(r'^\d+$', resource_seg):
                port = int(resource_seg)
            elif resource_seg.lower().startswith('hislip'):
                # HiSLIP may include an explicit port: hislip0,4880
                hislip_match = re.match(r'^hislip\d+(?:,(\d+))?$', resource_seg, re.IGNORECASE)
                if hislip_match and hislip_match.group(1):
                    port = int(hislip_match.group(1))
                else:
                    port = 4880  # HiSLIP default
            else:
                port = 111   # VXI-11 / portmapper default

            results['host'] = host
            results['port'] = port

            # Test 1: Resolve host using Python's socket module (cross-platform)
            try:
                addr_info = _socket.getaddrinfo(host, None)
                resolved = sorted({info[4][0] for info in addr_info if info[4]})
                results['resolved_addresses'] = resolved
                results['host_resolves'] = True
            except _socket.gaierror as e:
                results['host_resolves'] = False
                results['reachability_error'] = str(e)
                results['recommendations'].append(
                    f"Host '{host}' could not be resolved. "
                    f"Check the hostname/IP address and network configuration."
                )
            except Exception as e:
                results['host_resolves'] = False
                results['reachability_error'] = str(e)
                results['recommendations'].append(
                    f"Could not verify host reachability for '{host}': {e}"
                )

            # Test 2: Check if port is open using Python's socket (cross-platform)
            if results['host_resolves']:
                try:
                    with _socket.create_connection((host, port), timeout=3):
                        results['host_reachable'] = True
                        results['port_open'] = True
                except ConnectionRefusedError:
                    # The host responded with a TCP RST, which means the host
                    # is reachable on the network, but the target port/service
                    # is not accepting connections.
                    results['host_reachable'] = True
                    results['port_open'] = False
                    results['recommendations'].append(
                        f"Host {host} responded (TCP RST), but port {port} is refusing connections. "
                        f"Verify VXI-11 service is running on instrument."
                    )
                except (_socket.timeout, TimeoutError):
                    results['port_open'] = False
                    results['recommendations'].append(
                        f"Connection to {host}:{port} timed out. "
                        f"Verify VXI-11 service is running on instrument."
                    )
                except OSError:
                    results['port_open'] = False
                    results['recommendations'].append(
                        f"Port {port} on {host} is closed or filtered. "
                        f"Verify VXI-11 service is running on instrument."
                    )
                except Exception as e:
                    results['port_test_error'] = str(e)
        else:
            results['recommendations'].append(
                f"VISA address format not recognized: {visa_address}\n"
                f"Expected formats:\n"
                f"  TCPIP0::<host>::inst0::INSTR  (VXI-11)\n"
                f"  TCPIP0::<host>::hislip0::INSTR  (HiSLIP)\n"
                f"  TCPIP0::<host>::<port>::SOCKET  (raw socket)"
            )

    except Exception as e:
        results['parse_error'] = str(e)
        results['recommendations'].append(f"Error parsing VISA address: {e}")

    # Add general recommendations
    if not results['visa_available']:
        results['recommendations'].append(
            "PyVISA is not available. Install it with: pip install pyvisa pyvisa-py"
        )

    if results['address_valid'] and not results['host_resolves']:
        host = results.get('host', '?')
        results['recommendations'].append(
            f"Host '{host}' is not reachable. Check:\n"
            "  - Instrument is powered on\n"
            "  - IP address/hostname is correct\n"
            "  - Network cable is connected\n"
            "  - Instrument and PC are on the same network"
        )

    if results['address_valid'] and results['host_reachable'] and not results['port_open']:
        host = results.get('host', '?')
        port = results.get('port', '?')
        results['recommendations'].append(
            f"Port {port} is closed on {host}. Common causes:\n"
            f"  VXI-11 Protocol (port 111):\n"
            f"    - Use format: TCPIP0::{host}::inst0::INSTR\n"
            f"    - Enable VXI-11/LXI service on instrument\n"
            f"    - Check firewall settings\n"
            f"  HiSLIP Protocol (port 4880):\n"
            f"    - Use format: TCPIP0::{host}::hislip0::INSTR\n"
            f"    - Enable HiSLIP service on instrument\n"
            f"  Socket Protocol (custom port):\n"
            f"    - Use format: TCPIP0::{host}::{port}::SOCKET\n"
            f"    - Verify correct port number in instrument settings\n"
            "\n"
            "Try changing the protocol in Address Editor if connection fails."
        )

    if results.get('port_open') and 'inst0' in visa_address.lower():
        host = results.get('host', '?')
        results['recommendations'].append(
            f"Port is open but connection may still fail. If using VXI-11:\n"
            f"  - Ensure RPC portmapper is running on instrument\n"
            f"  - Try HiSLIP protocol instead: TCPIP0::{host}::hislip0::INSTR"
        )

    if results['host_reachable'] and not results['port_open']:
        results['recommendations'].append("Enable remote control/LXI interface on instrument.")
        results['recommendations'].append(
            "Check instrument manual for VXI-11 or SCPI-over-LAN setup."
        )
        results['recommendations'].append("Verify firewall is not blocking the connection.")

    return results