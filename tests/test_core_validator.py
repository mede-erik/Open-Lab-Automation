"""frontend.core.validator: every function returns True or raises ValidationError with the
right [VALID-xxx] code."""

import pytest

from frontend.core import validator as v
from frontend.core.errorhandler import ErrorCode, ValidationError


def _code(func, *args):
    with pytest.raises(ValidationError) as info:
        func(*args)
    return info.value.error_code


@pytest.mark.parametrize("email", ["a@b.co", "first.last+tag@lab-1.example.org"])
def test_valid_email(email):
    assert v.is_valid_email(email) is True


@pytest.mark.parametrize(
    "email,code",
    [
        ("", ErrorCode.VALID_EMPTY_FIELD),
        (None, ErrorCode.VALID_EMPTY_FIELD),
        ("no-at-sign", ErrorCode.VALID_INVALID_EMAIL),
        ("a@b", ErrorCode.VALID_INVALID_EMAIL),
        ("a@b.c", ErrorCode.VALID_INVALID_EMAIL),
    ],
)
def test_invalid_email(email, code):
    assert _code(v.is_valid_email, email) == code


@pytest.mark.parametrize("ip", ["192.168.1.10", "0.0.0.0", "::1", "fe80::1"])
def test_valid_ip(ip):
    assert v.is_valid_ip_address(ip)


@pytest.mark.parametrize(
    "ip,code",
    [
        ("", ErrorCode.VALID_EMPTY_FIELD),
        ("256.1.1.1", ErrorCode.VALID_INVALID_IP),
        ("192.168.1", ErrorCode.VALID_INVALID_IP),
        ("host.local", ErrorCode.VALID_INVALID_IP),
    ],
)
def test_invalid_ip(ip, code):
    assert _code(v.is_valid_ip_address, ip) == code


@pytest.mark.parametrize("port", [1, 5025, "5025", 65535])
def test_valid_port(port):
    assert v.is_valid_port(port)


@pytest.mark.parametrize(
    "port,code",
    [
        (None, ErrorCode.VALID_EMPTY_FIELD),
        ("", ErrorCode.VALID_EMPTY_FIELD),
        (0, ErrorCode.VALID_INVALID_PORT),
        (65536, ErrorCode.VALID_INVALID_PORT),
        ("abc", ErrorCode.VALID_INVALID_PORT),
    ],
)
def test_invalid_port(port, code):
    assert _code(v.is_valid_port, port) == code


def test_numeric_and_positive():
    assert v.is_numeric("1e-3") and v.is_numeric(-2) and v.is_numeric(0.0)
    assert _code(v.is_numeric, "") == ErrorCode.VALID_EMPTY_FIELD
    assert _code(v.is_numeric, "1,5") == ErrorCode.VALID_OUT_OF_RANGE
    assert v.is_positive_number("0.001")
    assert _code(v.is_positive_number, 0) == ErrorCode.VALID_OUT_OF_RANGE
    assert _code(v.is_positive_number, "-1") == ErrorCode.VALID_OUT_OF_RANGE


def test_in_range_includes_the_limits():
    assert v.is_in_range(0, 0, 10) and v.is_in_range("10", 0, 10)
    assert _code(v.is_in_range, 10.0001, 0, 10) == ErrorCode.VALID_OUT_OF_RANGE
    assert _code(v.is_in_range, "x", 0, 10) == ErrorCode.VALID_OUT_OF_RANGE


def test_not_empty():
    assert v.is_not_empty("x")
    for value in ("", "   ", None, 3):
        assert _code(v.is_not_empty, value) == ErrorCode.VALID_EMPTY_FIELD


@pytest.mark.parametrize("name", ["data.csv", "osc 1.was", "CONSOLE.txt"])
def test_valid_filename(name):
    assert v.is_valid_filename(name)


@pytest.mark.parametrize("name", ["a/b.txt", "a:b", "x?.json", "CON", "com1.txt", "nul.inst"])
def test_invalid_filename(name):
    assert _code(v.is_valid_filename, name) == ErrorCode.VALID_INVALID_FORMAT


def test_date_in_range():
    assert v.is_date_in_range("2025-06-15", "2025-01-01", "2025-12-31")
    assert v.is_date_in_range("2025-01-01", "2025-01-01", "2025-12-31")
    assert (
        _code(v.is_date_in_range, "2026-01-01", "2025-01-01", "2025-12-31")
        == ErrorCode.VALID_OUT_OF_RANGE
    )
    assert (
        _code(v.is_date_in_range, "15/06/2025", "2025-01-01", "2025-12-31")
        == ErrorCode.VALID_INVALID_FORMAT
    )


@pytest.mark.parametrize(
    "address",
    [
        "TCPIP0::192.168.1.10::inst0::INSTR",
        "TCPIP::192.168.1.10::INSTR",
        "TCPIP0::scope.lab::hislip0::INSTR",
        "TCPIP0::192.168.1.10::5025::SOCKET",
        "USB0::0x1AB1::0x04CE::DS1ZA123::INSTR",
        "GPIB0::22::INSTR",
        "ASRL3::INSTR",
        "ASRL/dev/ttyUSB0::INSTR",
    ],
)
def test_valid_visa_address(address):
    assert v.is_valid_visa_address(address)


@pytest.mark.parametrize(
    "address",
    ["192.168.1.10", "TCPIP0::192.168.1.10", "GPIB0::abc::INSTR", "USB0::INSTR", "COM3"],
)
def test_invalid_visa_address(address):
    assert _code(v.is_valid_visa_address, address) == ErrorCode.VALID_INVALID_FORMAT


def test_list_not_empty():
    assert v.validate_list_not_empty([0])
    with pytest.raises(ValidationError):
        v.validate_list_not_empty([])
