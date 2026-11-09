# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import pytest

from ola.serial_config import serial_address, serial_port_of_address, serial_port_value


@pytest.mark.parametrize(
    "typed,port",
    [
        ("3", "3"),
        ("COM3", "3"),
        ("com12", "12"),
        ("/dev/ttyUSB0", "/dev/ttyUSB0"),
        ("ttyACM1", "/dev/ttyACM1"),
        ("cu.usbserial-1410", "/dev/cu.usbserial-1410"),
        ("  /dev/ttyS0 ", "/dev/ttyS0"),
    ],
)
def test_port_value(typed, port):
    assert serial_port_value(typed) == port


@pytest.mark.parametrize("typed", ["", "COM", "USB0", "/dev/", "port 3", "3a"])
def test_not_a_port(typed):
    with pytest.raises(ValueError):
        serial_port_value(typed)


def test_address_round_trip():
    assert serial_address("/dev/ttyUSB0") == "ASRL/dev/ttyUSB0::INSTR"
    assert serial_address("COM3") == "ASRL3::INSTR"
    for typed in ("5", "/dev/ttyUSB2"):
        assert serial_port_value(serial_port_of_address(serial_address(typed))) == typed
    assert serial_port_of_address("TCPIP0::1.2.3.4::inst0::INSTR") == ""
