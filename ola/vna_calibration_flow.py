# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Guided calibration of a vector network analyzer, the same for every VNA.

A calibration is a list of steps: connect a standard, measure it. ``CalibrationSession`` walks
through them with the logical calls ``calibration_begin``, ``calibration_measure`` and
``calibration_apply``, so it works for an instrument that calibrates itself (Siglent, R&S) and for
one whose driver calibrates in software (LiteVNA). The terminal tool and, later, a window use the
same session; the instructions are plain English and carry the standard and the ports so that a
user interface can translate them.

A finished calibration is saved as a ``.cal.json`` file next to the project (``save_record``) and
listed in the project file (``attach_to_project``). An instrument that keeps its calibration itself
loses it when it is switched off: the record then only says when and how it was made. A software
calibration also stores its data and can be restored (``restore``) for the same frequency sweep.

No Qt, no terminal here.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .call_errors import CallError, CallNotSupportedError, InvalidArgumentError
from .fileio import atomic_write_json

KINDS = ("ONE_PORT", "TRANSMISSION_RESPONSE", "TWO_PORT")
KIND_TEXT = {
    "ONE_PORT": "one port (reflection): OPEN, SHORT and LOAD on a port",
    "TRANSMISSION_RESPONSE": "transmission response: a THRU between two ports",
    "TWO_PORT": "two ports (full): OPEN, SHORT and LOAD on both ports and a THRU",
}
RECORD_FORMAT = 1

# questions of the terminal tool for the values of a calibration kit: (field, text); the units are
# those of the usual kit files (see ``ola.vna_calibration.CalKit``)
KIT_BASIC = [
    ("open_c0", "OPEN: capacitance C0 (fF)"),
    ("open_c1", "OPEN: C1 (1e-27 F/Hz)"),
    ("open_c2", "OPEN: C2 (1e-36 F/Hz^2)"),
    ("open_c3", "OPEN: C3 (1e-45 F/Hz^3)"),
    ("open_delay", "OPEN: offset delay (ps)"),
    ("short_l0", "SHORT: inductance L0 (pH)"),
    ("short_l1", "SHORT: L1 (1e-24 H/Hz)"),
    ("short_l2", "SHORT: L2 (1e-33 H/Hz^2)"),
    ("short_l3", "SHORT: L3 (1e-42 H/Hz^3)"),
    ("short_delay", "SHORT: offset delay (ps)"),
    ("thru_delay", "THRU: delay (ps)"),
]
KIT_ADVANCED = [
    ("open_loss", "OPEN: offset loss (Gohm/s)"),
    ("open_z0", "OPEN: offset impedance (ohm)"),
    ("short_loss", "SHORT: offset loss (Gohm/s)"),
    ("short_z0", "SHORT: offset impedance (ohm)"),
    ("thru_loss", "THRU: loss (Gohm/s)"),
    ("thru_z0", "THRU: impedance (ohm)"),
]

_FREQUENCY = re.compile(r"^\s*([0-9.]+(?:e[+-]?\d+)?)\s*([kmg]?)(?:hz)?\s*$", re.IGNORECASE)
_MULTIPLIER = {"": 1.0, "k": 1e3, "m": 1e6, "g": 1e9}


def parse_frequency(text: str) -> float:
    """'1e6', '100k', '2.4G', '6 GHz' -> Hz. Raises ValueError for anything else."""
    match = _FREQUENCY.match(str(text))
    if not match:
        raise ValueError(f"not a frequency: {text!r}")
    return float(match.group(1)) * _MULTIPLIER[match.group(2).lower()]


def supported_kinds(library, model_id: str) -> List[str]:
    """The calibration kinds of a model (its ``calibration_kinds``; all kinds if it gives none)."""
    ref = library.find_model(model_id)
    kinds = (ref.model.get("capabilities", {}) if ref else {}).get("calibration_kinds")
    return [k for k in KINDS if k in (kinds or KINDS)]


def parse_sweep(start: str, stop: str, points: Any) -> Dict[str, float]:
    """The sweep of a calibration from what the user typed ('1M', '2.4G', ...).

    Raises ``InvalidArgumentError`` (CALL-003) with a message for the user if a value is wrong."""
    try:
        first, last = parse_frequency(start), parse_frequency(stop)
    except ValueError as exc:
        raise InvalidArgumentError(f"{exc} (examples: 1M, 100k, 2.4G)") from exc
    if first <= 0 or last <= first:
        raise InvalidArgumentError("the stop frequency must be higher than the start frequency")
    try:
        count = int(points)
    except (TypeError, ValueError) as exc:
        raise InvalidArgumentError(f"not a number of points: {points!r}") from exc
    if count < 2:
        raise InvalidArgumentError("a sweep needs at least 2 points")
    return {"start": first, "stop": last, "points": count}


def supports_kit(library, model_id: str) -> bool:
    """True if the model accepts the values of a calibration kit (``set_calibration_kit``)."""
    return "set_calibration_kit" in (library.commands(model_id) or {})


@dataclass(frozen=True)
class CalibrationStep:
    """One standard to connect and measure."""

    standard: str
    port: int
    port2: Optional[int] = None

    @property
    def text(self) -> str:
        """What the operator has to do."""
        if self.standard == "THRU":
            return f"Connect a THRU (cable) between port {self.port} and port {self.port2}"
        article = {"OPEN": "the OPEN", "SHORT": "the SHORT", "LOAD": "the 50 ohm LOAD"}
        return f"Connect {article[self.standard]} to port {self.port}"


def plan_steps(kind: str, port: int, port2: Optional[int] = None) -> List[CalibrationStep]:
    """The standards of a calibration kind, in the order they are measured."""
    if kind not in KINDS:
        raise InvalidArgumentError(f"unknown calibration kind {kind!r}", call="calibration_begin")
    if kind != "ONE_PORT" and (port2 is None or port2 == port):
        raise InvalidArgumentError(
            f"calibration {kind} needs two different ports", call="calibration_begin"
        )
    if kind == "ONE_PORT":
        return [CalibrationStep(s, port) for s in ("OPEN", "SHORT", "LOAD")]
    if kind == "TRANSMISSION_RESPONSE":
        return [CalibrationStep("THRU", port, port2)]
    steps = [CalibrationStep(s, p) for p in (port, port2) for s in ("OPEN", "SHORT", "LOAD")]
    return steps + [CalibrationStep("THRU", port, port2)]


@dataclass
class CalibrationRecord:
    """What is saved about a calibration."""

    instrument: str
    model_id: str
    kind: str
    port: int
    port2: Optional[int]
    sweep: Optional[Dict[str, float]]
    standards: List[str]
    kit: Optional[Dict[str, float]] = None  # values of the calibration kit; None: ideal standards
    serial_number: Optional[str] = None  # the apparatus it was made for (read from the instrument)
    date: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    data: Optional[Dict[str, Any]] = None  # software calibration: restorable
    note: str = (
        "An instrument that keeps its calibration loses it when it is switched off: "
        "calibrate again after switching on."
    )
    format: int = RECORD_FORMAT


class CalibrationSession:
    """The steps of one calibration of one VNA (``handle`` is an instrument handle)."""

    def __init__(
        self,
        handle,
        kind: str,
        port: int = 1,
        port2: Optional[int] = None,
        sweep: Optional[Dict[str, float]] = None,
        kit: Optional[Dict[str, float]] = None,
    ):
        self.handle, self.kind, self.port, self.port2, self.sweep = handle, kind, port, port2, sweep
        self.kit = kit or None  # values of a real calibration kit; ideal standards if empty
        self.steps = plan_steps(kind, port, port2)
        self.measured: List[CalibrationStep] = []
        self.applied = False

    def start(self) -> None:
        """Set the sweep (a calibration is valid for one sweep) and choose the calibration."""
        if self.sweep:
            self.handle.call(
                "set_frequency_sweep",
                start_frequency=self.sweep["start"],
                stop_frequency=self.sweep["stop"],
                points=int(self.sweep["points"]),
            )
        if self.kit is not None:  # CALL-001 if the instrument takes its kit from its own settings
            self.handle.call("set_calibration_kit", kit=self.kit)
        args = {"kind": self.kind, "port": self.port}
        if self.port2 is not None:
            args["port2"] = self.port2
        self.handle.call("calibration_begin", **args)

    def measure(self, step: CalibrationStep) -> None:
        """Measure the standard that is connected."""
        args = {"standard": step.standard, "port": step.port}
        if step.port2 is not None:
            args["port2"] = step.port2
        self.handle.call("calibration_measure", **args)
        if step not in self.measured:
            self.measured.append(step)

    @property
    def complete(self) -> bool:
        """True when every standard has been measured."""
        return all(s in self.measured for s in self.steps)

    def finish(self) -> None:
        """Compute the calibration and switch the correction on."""
        if not self.complete:
            raise InvalidArgumentError("some standards have not been measured yet")
        self.handle.call("calibration_apply")
        try:
            self.handle.call("set_correction_state", state=True)
        except CallNotSupportedError:
            pass  # the instrument turns the correction on itself
        self.applied = True

    def record(self, instrument_name: str, model_id: str) -> CalibrationRecord:
        """The record of the finished calibration (with the data of a software calibration)."""
        data = None
        if self.handle.supports("calibration_export"):
            try:
                data = self.handle.call("calibration_export")
            except CallError:
                data = None
        identity = getattr(self.handle, "identity", None)
        return CalibrationRecord(
            instrument=instrument_name,
            serial_number=getattr(identity, "serial_number", None),
            model_id=model_id,
            kind=self.kind,
            port=self.port,
            port2=self.port2,
            sweep=self.sweep,
            kit=self.kit,
            standards=[
                f"{s.standard}@{s.port}" + (f"-{s.port2}" if s.port2 else "") for s in self.steps
            ],
            data=data,
        )


def load_kit(path) -> Dict[str, float]:
    """Read the values of a calibration kit from a JSON file (a dict of ``CalKit`` fields)."""
    from .vna_calibration import CalKit

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not a JSON object")
        return CalKit.from_dict(raw).to_dict()
    except (OSError, ValueError) as exc:
        raise InvalidArgumentError(f"cannot read the calibration kit {path}: {exc}") from exc


def save_kit(path, kit: Dict[str, float]) -> None:
    """Write the values of a calibration kit to a JSON file."""
    atomic_write_json(path, kit)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "vna"


def save_record(record: CalibrationRecord, directory) -> Path:
    """Write the record as ``<instrument>_<serial>_<date>.cal.json`` in ``directory`` (no serial in
    the name if there is none); a file that exists is never overwritten."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = re.sub(r"[^0-9]", "", record.date)
    serial = f"_{_slug(record.serial_number)}" if record.serial_number else ""
    path = directory / f"{_slug(record.instrument)}{serial}_{stamp}.cal.json"
    counter = 2
    while path.exists():  # never overwrite another calibration (two in the same second)
        path = directory / f"{_slug(record.instrument)}{serial}_{stamp}_{counter}.cal.json"
        counter += 1
    atomic_write_json(path, asdict(record))
    return path


def load_record(path) -> CalibrationRecord:
    """Read a ``.cal.json`` file."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("format") != RECORD_FORMAT:
            raise ValueError(f"format {raw.get('format')!r} is not supported")
        return CalibrationRecord(**raw)
    except (OSError, ValueError, TypeError) as exc:
        raise InvalidArgumentError(f"cannot read the calibration file {path}: {exc}") from exc


def attach_to_project(project_path, record_path, record: CalibrationRecord) -> None:
    """List the calibration in the project file (key ``calibrations``, the newest per apparatus --
    the same instrument name and serial number -- replaces the older one). Other keys of the
    project file are kept. ``InvalidArgumentError`` if the record is not inside the project folder
    (a project never names a file outside itself)."""
    project_path = Path(project_path)
    raw = json.loads(project_path.read_text(encoding="utf-8"))
    try:  # always a path inside the project folder: the project must stay movable and shareable
        relative = Path(record_path).resolve().relative_to(project_path.resolve().parent).as_posix()
    except ValueError:
        raise InvalidArgumentError(
            f"the calibration file {record_path} must be inside the project folder "
            f"{project_path.resolve().parent}"
        ) from None
    entry = {
        "instrument": record.instrument,
        "serial_number": record.serial_number,
        "kind": record.kind,
        "date": record.date,
        "file": relative,
    }
    others = [
        c
        for c in raw.get("calibrations", [])
        if (c.get("instrument"), c.get("serial_number"))
        != (record.instrument, record.serial_number)
    ]
    raw["calibrations"] = others + [entry]
    atomic_write_json(project_path, raw)


def restore(handle, record: CalibrationRecord) -> None:
    """Restore a saved software calibration on the instrument (same sweep as when it was made).

    An instrument that kept the calibration itself has nothing to restore: raises ``CALL-001``.
    """
    if not record.data or not handle.supports("calibration_import"):
        raise CallNotSupportedError(
            "this calibration cannot be restored: the instrument keeps its own calibration "
            "(it is lost when the instrument is switched off): calibrate again",
            call="calibration_import",
        )
    if record.sweep:
        handle.call(
            "set_frequency_sweep",
            start_frequency=record.sweep["start"],
            stop_frequency=record.sweep["stop"],
            points=int(record.sweep["points"]),
        )
    handle.call("calibration_import", data=record.data)


def network_analyzers(library, entries: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """The VNAs among the instruments of an ``.inst`` file: ``{instance_name: model_id}``.

    ``entries`` is what ``ola.connection.read_inst_entries`` returns. Manual instruments and
    models that are not network analyzers are left out."""
    found = {}
    for name, entry in entries.items():
        if entry.get("is_manual"):
            continue
        model_id = library.resolve_model_id(entry.get("model_id") or entry.get("model") or "")
        ref = library.find_model(model_id) if model_id else None
        if ref is not None and ref.category == "network_analyzers_series":
            found[name] = model_id
    return found


def save_and_attach(record: CalibrationRecord, project_path) -> Path:
    """Save the record in the ``calibrations`` folder next to the project file and list it in
    the project. Returns the path of the record."""
    project_path = Path(project_path)
    path = save_record(record, project_path.parent / "calibrations")
    attach_to_project(project_path, path, record)
    return path


def calibration_info(record: CalibrationRecord, path, project_path=None) -> Dict[str, Any]:
    """What the snapshot of a run keeps about the calibration that was applied: the record file
    (relative to the project if it is inside it), kind, date, sweep and the serial number it was
    made for."""
    file = str(path)
    if project_path is not None:
        try:
            file = str(Path(path).resolve().relative_to(Path(project_path).resolve().parent))
        except ValueError:
            pass
    return {
        "file": file,
        "kind": record.kind,
        "date": record.date,
        "sweep": record.sweep,
        "serial_number": record.serial_number,
    }


def _same_sweep(saved: Optional[Dict[str, float]], asked: Optional[Dict[str, float]]) -> bool:
    """True if a calibration made for sweep ``saved`` (start / stop / points) is valid for the
    sweep ``asked`` (start_hz / stop_hz / points) of a measurement."""
    if not saved or not asked:
        return False
    try:
        return (
            abs(float(saved["start"]) - float(asked["start_hz"])) < 0.5
            and abs(float(saved["stop"]) - float(asked["stop_hz"])) < 0.5
            and int(saved["points"]) == int(asked["points"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def find_record(project_path, serial_number: Optional[str], instrument: str = ""):
    """The newest calibration of the project made **for this apparatus**: ``(record, path)`` or
    None. A calibration belongs to one apparatus, found by its serial number: without a serial
    number (the instrument gives none) nothing is found, so a calibration is never taken for
    another instrument that happens to have the same name."""
    if not serial_number:
        return None
    project_path = Path(project_path)
    try:
        raw = json.loads(project_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entries = [
        c
        for c in raw.get("calibrations", [])
        if isinstance(c, dict) and c.get("serial_number") == serial_number
    ]
    for entry in sorted(entries, key=lambda c: str(c.get("date", "")), reverse=True):
        path = project_path.parent / str(entry.get("file", ""))
        try:
            record = load_record(path)
        except CallError:
            continue
        if record.serial_number == serial_number:  # the file says so too
            return record, path
    return None


def auto_restore(
    handle, project_path, sweep: Optional[Dict[str, float]]
) -> Optional[Dict[str, Any]]:
    """Put back, before a measurement, the saved software calibration of **this apparatus** when it
    was made for the sweep of the measurement. Returns what the snapshot of the run keeps about it
    (see ``calibration_info``), or None when nothing was restored: the instrument keeps its own
    calibration, gives no serial number, has none saved for it, a calibration is already applied, or
    the sweep is another one. Never raises for those reasons."""
    if getattr(handle, "calibration", None) or not handle.supports("calibration_import"):
        return None
    identity = getattr(handle, "identity", None)
    found = find_record(project_path, getattr(identity, "serial_number", None))
    if found is None:
        return None
    record, path = found
    if not record.data or not _same_sweep(record.sweep, sweep):
        return None
    restore(handle, record)
    info = calibration_info(record, path, project_path)
    info["restored"] = True
    handle.set_calibration(info)
    return info
