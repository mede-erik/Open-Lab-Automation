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

KINDS = ("ONE_PORT", "TRANSMISSION_RESPONSE", "TWO_PORT")
KIND_TEXT = {
    "ONE_PORT": "one port (reflection): OPEN, SHORT and LOAD on a port",
    "TRANSMISSION_RESPONSE": "transmission response: a THRU between two ports",
    "TWO_PORT": "two ports (full): OPEN, SHORT and LOAD on both ports and a THRU",
}
RECORD_FORMAT = 1

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
    ):
        self.handle, self.kind, self.port, self.port2, self.sweep = handle, kind, port, port2, sweep
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
        return CalibrationRecord(
            instrument=instrument_name,
            model_id=model_id,
            kind=self.kind,
            port=self.port,
            port2=self.port2,
            sweep=self.sweep,
            standards=[
                f"{s.standard}@{s.port}" + (f"-{s.port2}" if s.port2 else "") for s in self.steps
            ],
            data=data,
        )


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "vna"


def save_record(record: CalibrationRecord, directory) -> Path:
    """Write the record as ``<instrument>_<date>.cal.json`` in ``directory``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = re.sub(r"[^0-9]", "", record.date)
    path = directory / f"{_slug(record.instrument)}_{stamp}.cal.json"
    path.write_text(
        json.dumps(asdict(record), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
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
    """List the calibration in the project file (key ``calibrations``, the newest per
    instrument replaces the older one). Other keys of the project file are kept."""
    project_path = Path(project_path)
    raw = json.loads(project_path.read_text(encoding="utf-8"))
    entry = {
        "instrument": record.instrument,
        "kind": record.kind,
        "date": record.date,
        "file": (
            str(Path(record_path).resolve().relative_to(project_path.resolve().parent))
            if project_path.resolve().parent in Path(record_path).resolve().parents
            else str(record_path)
        ),
    }
    others = [c for c in raw.get("calibrations", []) if c.get("instrument") != record.instrument]
    raw["calibrations"] = others + [entry]
    project_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
