"""Helpers of the interactive instrument tester (scripts/instrument_shell.py). Qt-free.

Select a category, a model and an interface from the library, connect, run logical calls and
self-test the library entries of one instrument. Nothing here talks to the GUI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

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

    resource = pyvisa.ResourceManager().open_resource(address)
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
