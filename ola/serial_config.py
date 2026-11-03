"""Apply serial (RS-232) settings to an open pyvisa resource. Qt-free."""

from __future__ import annotations

from typing import Any, Dict


def apply_serial_settings(resource, cfg: Dict[str, Any]) -> None:
    """Set baud rate, data bits, parity, stop bits and flow control on a pyvisa ASRL resource.

    ``cfg`` uses the keys of the library's serial transport: ``baud``, ``data_bits``,
    ``parity`` (N/E/O), ``stop_bits`` (1, 1.5, 2) and ``flow_control`` (none, xon_xoff,
    rts_cts, dtr_dsr). Missing keys are left as they are. Raises ValueError for a value
    pyvisa does not know.
    """
    from pyvisa import constants as c

    parity = {"N": c.Parity.none, "E": c.Parity.even, "O": c.Parity.odd}
    stop_bits = {1.0: c.StopBits.one, 1.5: c.StopBits.one_and_a_half, 2.0: c.StopBits.two}
    flow = {
        "none": c.ControlFlow.none,
        "xon_xoff": c.ControlFlow.xon_xoff,
        "rts_cts": c.ControlFlow.rts_cts,
        "dtr_dsr": c.ControlFlow.dtr_dsr,
    }
    try:
        if "baud" in cfg:
            resource.baud_rate = int(cfg["baud"])
        if "data_bits" in cfg:
            resource.data_bits = int(cfg["data_bits"])
        if "parity" in cfg:
            resource.parity = parity[str(cfg["parity"]).upper()]
        if "stop_bits" in cfg:
            resource.stop_bits = stop_bits[float(cfg["stop_bits"])]
        if "flow_control" in cfg:
            resource.flow_control = flow[str(cfg["flow_control"]).lower()]
    except KeyError as exc:
        raise ValueError(f"unknown serial setting value: {exc}") from exc


def serial_port_value(text: str) -> str:
    """The port part of a VISA serial address from what a person types.

    ``3`` and ``COM3`` give ``3`` (Windows, NI-VISA numbering); ``/dev/ttyUSB0`` or ``ttyUSB0``
    give ``/dev/ttyUSB0`` (Linux, macOS: pyvisa-py addresses ``ASRL/dev/ttyUSB0::INSTR``).
    Anything else raises ``ValueError``.
    """
    value = text.strip()
    if value.isdigit():
        return value
    if value.upper().startswith("COM") and value[3:].isdigit():
        return value[3:]
    if value.startswith("/dev/") and len(value) > 5:
        return value
    if value.startswith(("tty", "cu.")):
        return "/dev/" + value
    raise ValueError(f"not a serial port: {text!r}")


def serial_address(text: str) -> str:
    """``ASRL<port>::INSTR`` for what a person typed (see ``serial_port_value``)."""
    return f"ASRL{serial_port_value(text)}::INSTR"


def serial_port_of_address(address: str) -> str:
    """The port part of ``ASRL3::INSTR`` or ``ASRL/dev/ttyUSB0::INSTR`` ('' if it is not one)."""
    text = address.strip()
    if not text.upper().startswith("ASRL") or "::" not in text:
        return ""
    return text[4:].split("::")[0]
