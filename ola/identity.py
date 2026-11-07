# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Who an instrument is: the identity read from the apparatus, and the snapshot of it that a saved
measurement keeps. No Qt.

**Decided:** the serial number is always read from the instrument (the third field of ``*IDN?``,
or what a driver or the USB descriptor of the device gives); it is never typed by hand. When an
instrument gives none it is ``None`` ("not available"). A manual instrument has no serial: it can
be anything, so nothing is asked for it.

``snapshot(handle)`` is what the header of a run file keeps for each instrument of a measurement
(see ``ola.runs``): the name of that day, the model, the serial number and the calibration that
was applied. It never changes afterwards, whatever happens to the project.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# what instruments answer in the serial field when they have none
NO_SERIAL = {"", "0", "n/a", "na", "none", "-", "--", "unknown", "not available"}


@dataclass(frozen=True)
class Identity:
    """The identity an instrument gives: manufacturer, model, serial number and firmware."""

    manufacturer: str = ""
    model: str = ""
    serial_number: Optional[str] = None
    firmware: str = ""
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Plain values for a JSON file."""
        return asdict(self)


def parse_idn(text: Any) -> Identity:
    """An ``*IDN?`` answer (``manufacturer,model,serial,firmware``) as an ``Identity``."""
    raw = str(text or "").strip()
    parts = [p.strip() for p in raw.split(",", 3)] + ["", "", "", ""]
    serial = parts[2] if parts[2].lower() not in NO_SERIAL else None
    return Identity(parts[0], parts[1], serial, parts[3], raw)


def usb_serial_number(address: str) -> Optional[str]:
    """The serial number a USB serial device (CDC) gives in its USB descriptor, for an address
    like ``ASRL/dev/ttyACM0::INSTR`` or ``ASRL3::INSTR``; None if it has none or cannot be found."""
    text = str(address or "")
    if not text.upper().startswith("ASRL"):
        return None
    port = text[4:].split("::", 1)[0]
    wanted = {port, f"COM{port}"} if port.isdigit() else {port}
    try:
        from serial.tools import list_ports

        for info in list_ports.comports():
            if info.device in wanted and info.serial_number:
                return str(info.serial_number)
    except Exception as exc:  # no pyserial, or the system cannot list its ports
        log.debug("cannot list the serial ports: %s", exc)
    return None


def read_identity(handle: Any, address: str = "") -> Identity:
    """Ask the instrument who it is (``identification_query``). Never raises: an instrument that
    does not answer has an empty identity. For a device whose answer has no serial number the one of
    its USB descriptor is used, if the address is a serial port."""
    identity = Identity()
    try:
        if handle.supports("identification_query"):
            identity = parse_idn(handle.call("identification_query"))
    except Exception as exc:
        log.warning("%s did not tell who it is: %s", getattr(handle, "name", "instrument"), exc)
    if identity.serial_number is None:
        usb = usb_serial_number(address)
        if usb:
            identity = Identity(
                identity.manufacturer, identity.model, usb, identity.firmware, identity.raw
            )
    return identity


def snapshot(handle: Any) -> Dict[str, Any]:
    """What a saved measurement keeps about one instrument handle (name, model, serial,
    calibration). A manual instrument has no serial; a handle that does not know its identity
    (a simulated one) gives only its name."""
    data: Dict[str, Any] = {"name": getattr(handle, "name", "?")}
    if getattr(handle, "is_manual", False):
        data["manual"] = True
        data["type"] = getattr(handle, "instrument_type", None)
        return data
    model_id = getattr(handle, "model_id", None)
    if model_id:
        data["model_id"] = model_id
    identity = getattr(handle, "identity", None)
    if identity is not None:
        data.update(
            manufacturer=identity.manufacturer,
            model=identity.model,
            serial_number=identity.serial_number,
            firmware=identity.firmware,
        )
    calibration = getattr(handle, "calibration", None)
    if calibration:
        data["calibration"] = dict(calibration)
    return data
