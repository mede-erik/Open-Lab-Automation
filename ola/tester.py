"""Helpers of the interactive instrument tester (scripts/instrument_shell.py). Qt-free.

Select a category, a model and an interface from the library, connect, run logical calls and
self-test the library entries of one instrument. Nothing here talks to the GUI.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .call_errors import CallError
from .call_planner import plan_call
from .instrument import Instrument
from .instrument_handle import InstrumentHandle
from .library import Library

CATEGORY_LABELS = {
    "power_supplies_series": "Power supply",
    "dataloggers_series": "Datalogger",
    "switch_units_series": "Switch unit",
    "datalogger_modules": "Datalogger module",
    "multimeters_series": "Multimeter",
    "oscilloscopes_series": "Oscilloscope",
    "electronic_loads_series": "Electronic load",
}


def categories(library: Library) -> List[Tuple[str, str]]:
    """(key, label) of the categories that have at least one model."""
    out = []
    for key, series_list in library.categories.items():
        if isinstance(series_list, list) and any(s.get("models") for s in series_list):
            out.append((key, CATEGORY_LABELS.get(key, key)))
    return out


def models_of(library: Library, category: str) -> List[Tuple[str, str, str]]:
    """(model_id, name, series_id) of a category."""
    return [
        (m["id"], m.get("name", m["id"]), s.get("series_id", ""))
        for s in library.categories.get(category, [])
        for m in s.get("models", []) or []
    ]


def interfaces(library: Library, model_id: str) -> List[Dict[str, Any]]:
    """Ways to reach a model: the library connection types, with their transports."""
    ref = library.find_model(model_id)
    out = []
    for conn in ref.model.get("interface", {}).get("supported_connection_types", []) if ref else []:
        out.append(
            {
                "type": conn.get("type", "?"),
                "example": conn.get("address_format_example", ""),
                "transports": conn.get("transports", []) or [],
                "notes": conn.get("notes", ""),
            }
        )
    return out


def parse_value(text: str) -> Any:
    """'5' -> 5, '0.5' -> 0.5, 'true' -> True, '"x"' or 'x' -> 'x'."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def open_visa(
    address: str,
    library: Library,
    model_id: str,
    timeout_ms: int = 5000,
    serial_override: Optional[Dict[str, Any]] = None,
):
    """Open a VISA resource (USB-TMC, GPIB, VXI-11, ASRL...) and wrap it for the executor.
    Serial resources get the library settings (plus ``serial_override``)."""
    import pyvisa

    from ._visa import VisaConnection
    from .serial_config import apply_serial_settings

    # 'ASRL/dev/ttyUSB0::INSTR' is a pyvisa-py style address (NI-VISA numbers its ports ASRL1...)
    first = "@py" if address.upper().startswith("ASRL/") else ""
    try:
        resource = pyvisa.ResourceManager(first).open_resource(address)
    except pyvisa.errors.VisaIOError:
        # the default backend (e.g. NI-VISA) may not know this resource: try pyvisa-py
        resource = pyvisa.ResourceManager("@py").open_resource(address)
    resource.timeout = timeout_ms
    connection = VisaConnection(resource, address, timeout_ms, pyvisa)
    if address.upper().startswith("ASRL"):
        cfg = dict(library.serial_settings(model_id))
        cfg.update(serial_override or {})
        apply_serial_settings(resource, cfg)
        connection.set_terminators(
            cfg.get("write_termination", "\n"), cfg.get("read_termination", "\n")
        )
    return connection


def visa_diagnostics() -> str:
    """What is available for VISA connections: pyserial, backends and the resources they see."""
    lines = []
    try:
        import serial

        lines.append(f"pyserial {serial.__version__}: installed")
    except ImportError:
        lines.append(
            "pyserial is NOT installed: serial ports (ASRL) do not work with pyvisa-py "
            "(pip install pyserial)"
        )
    try:
        import pyvisa
    except ImportError:
        return "\n".join(lines + ["pyvisa is NOT installed (pip install pyvisa pyvisa-py)"])
    for backend in ("", "@py"):
        label = backend or "default"
        try:
            rm = pyvisa.ResourceManager(backend)
            # serial and USB only: scanning GPIB with some backends prints a lot of noise
            found = list(rm.list_resources("ASRL?*::INSTR")) + list(
                rm.list_resources("USB?*::INSTR")
            )
            lines.append(f"backend {label} ({rm.visalib}): {found}")
        except Exception as exc:
            lines.append(f"backend {label}: {type(exc).__name__}: {exc}")
    return "\n".join(lines)


def serial_port_from_address(address: str) -> str:
    """'ASRL/dev/ttyUSB1::INSTR' -> '/dev/ttyUSB1'; 'ASRL3::INSTR' -> 'COM3' on Windows."""
    body = address.strip()
    if body.upper().startswith("ASRL"):
        body = body[4:].split("::")[0]
    if body.isdigit():
        return f"COM{body}" if os.name == "nt" else f"/dev/ttyS{max(int(body) - 1, 0)}"
    return body


@dataclass
class ProbeResult:
    baud: int
    flow_control: str
    parity: str
    answer: str


def probe_serial(
    port: str,
    command: str = "*IDN?",
    bauds: Sequence[int] = (57600, 9600, 19200, 38400, 115200, 4800, 2400, 1200),
    flows: Sequence[str] = ("xon_xoff", "none", "dtr_dsr", "rts_cts"),
    parities: Sequence[str] = ("N",),
    timeout: float = 1.0,
    terminator: str = "\n",
    progress: Callable[[str], None] = lambda s: None,
    stop_at_first: bool = True,
) -> List[ProbeResult]:
    """Find the serial settings an instrument answers to: for every baud rate / flow control /
    parity send ``command`` and see whether anything comes back. Uses pyserial directly (no
    VISA), so close any other connection to the port first. 'E' and 'O' parity use 7 data bits,
    'N' uses 8 (the convention of the instruments' menus)."""
    import serial

    found: List[ProbeResult] = []
    for parity in parities:
        for baud in bauds:
            for flow in flows:
                progress(f"  trying {baud} baud, parity {parity}, flow {flow} ...")
                try:
                    ser = serial.Serial(
                        port,
                        baudrate=baud,
                        bytesize=8 if parity == "N" else 7,
                        parity=parity,
                        stopbits=1,
                        timeout=timeout,
                        write_timeout=timeout,
                        xonxoff=(flow == "xon_xoff"),
                        rtscts=(flow == "rts_cts"),
                        dsrdtr=(flow == "dtr_dsr"),
                    )
                except (serial.SerialException, ValueError, OSError) as exc:
                    raise RuntimeError(f"cannot open {port}: {exc}") from exc
                try:
                    ser.reset_input_buffer()
                    ser.write((command + terminator).encode())
                    reply = ser.readline()
                finally:
                    ser.close()
                if reply:
                    text = reply.decode(errors="replace").strip()
                    found.append(ProbeResult(baud, flow, parity, text))
                    if stop_at_first:
                        return found
    return found


def open_raw_socket(host: str, port: int, timeout_ms: int = 5000):
    from .transport import open_tcp

    return open_tcp(host, port, timeout_ms)


def open_simulated(answer: str = "1"):
    """A fake instrument that answers every query with ``answer`` (no hardware)."""
    from .sim import SimTransport

    return SimTransport(lambda cmd: answer)


def make_handle(library: Library, model_id: str, connection, name: str = "instrument"):
    return InstrumentHandle(name, library, model_id, Instrument(name, connection))


def call_spec(library: Library, model_id: str, call: str) -> Optional[Dict[str, Any]]:
    ref = library.find_model(model_id)
    schema = library.schema(ref.category) if ref else None
    return (schema or {}).get("calls", {}).get(call)


def model_calls(library: Library, model_id: str) -> List[Dict[str, Any]]:
    """Calls the model defines, with their schema information."""
    commands = library.commands(model_id) or {}
    out = []
    for name in sorted(commands):
        spec = call_spec(library, model_id, name) or {}
        out.append(
            {
                "name": name,
                "requirement": spec.get("requirement", "extra"),
                "kind": spec.get("kind", "set" if commands[name].get("set") else "query"),
                "args": spec.get("args", {}),
                "description": spec.get("description") or commands[name].get("description", ""),
            }
        )
    return out


def missing_mandatory(library: Library, model_id: str) -> List[str]:
    ref = library.find_model(model_id)
    schema = library.schema(ref.category) if ref else None
    if not schema:
        return []
    commands = library.commands(model_id) or {}
    return [
        n
        for n, c in schema["calls"].items()
        if c["requirement"] == "mandatory" and n not in commands
    ]


@dataclass
class TestResult:
    call: str
    status: str  # ok | fail | skip
    detail: str


def self_test(
    library: Library,
    model_id: str,
    handle,
    channel: int = 1,
    include_writes: bool = False,
    confirm: Optional[Callable[[str], bool]] = None,
    log: Callable[[str], None] = lambda s: None,
) -> List[TestResult]:
    """Run the calls of the model that need no unknown argument.

    Queries are always tried (``channel_number`` = ``channel``). Calls that write to the
    instrument (kind set/action) only with ``include_writes`` and after ``confirm`` agrees;
    set calls need their own value, so they are skipped. Returns one result per call.
    """
    results: List[TestResult] = []
    for info in model_calls(library, model_id):
        name, kind, args = info["name"], info["kind"], info["args"]
        call_args: Dict[str, Any] = {}
        unknown = []
        for arg, spec in args.items():
            if arg == "channel_number":
                call_args[arg] = channel
            elif spec.get("required", True) and "default" not in spec:
                unknown.append(arg)
        if kind == "query" and not unknown:
            pass
        elif kind == "action" and not unknown and include_writes:
            if confirm is not None and not confirm(f"send '{name}'?"):
                results.append(TestResult(name, "skip", "not confirmed"))
                continue
        else:
            reason = f"needs {unknown}" if unknown else "writes to the instrument (use --writes)"
            results.append(TestResult(name, "skip", reason))
            continue
        try:
            value = handle.call(name, **call_args)
            results.append(TestResult(name, "ok", "" if value is None else repr(value)))
        except CallError as exc:
            results.append(TestResult(name, "fail", str(exc)))
        except Exception as exc:  # transport problems etc.
            results.append(TestResult(name, "fail", f"{type(exc).__name__}: {exc}"))
        log(f"{name}: {results[-1].status} {results[-1].detail}")
    return results


def describe_plan(
    library: Library, model_id: str, call: str, args: Dict[str, Any], readback: bool = False
) -> List[str]:
    """The commands a call would send, without sending them."""
    plan = plan_call(library, model_id, call, args, readback=readback)
    if plan.access == "driver":
        return [f"driver {plan.driver['function']}({plan.driver['args']})"]
    return [s.get("text", s["op"]) if s["op"] != "read" else "(read)" for s in plan.steps]
