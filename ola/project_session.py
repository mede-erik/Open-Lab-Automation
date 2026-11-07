"""A project at work: what the project window does, without any screen.

``ProjectSession`` ties together a ``Project`` (its measurements and files), the module registry
(measurement types) and a way to reach the instruments, and answers the questions of a window:

    session = ProjectSession(project, registry, connect=my_connect)
    session.rows()                      # the measurements, with a problem text if one is not usable
    ref = session.create("efficiency", "Converter 12V")
    session.rename(ref.id, "Converter 12V rev B"); session.remove(ref.id, delete_file=False)
    runner, run_file = session.build_runner(ref)     # ready to start, results written to run_file
    session.runs(ref)                   # the run files of this measurement, newest first

``connect(name, cancel)`` must return the *handle* of the instrument called ``name`` in the
instrument file (an object with ``.name`` and ``.call(call_name, **args)``); ``cancel`` is the stop
event of the run, which the handle should honour (``ola.connection.ProjectConnector`` does). The
application provides it; without it a measurement cannot start and the reason is a readable message,
not a crash. The window of the
measurement to run is chosen by the GUI, not here.
"""

from __future__ import annotations

import json
import threading
import time
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .assets import normalize_code, snapshots_for
from .compat import Finding, check_network_analyzer, check_role, observed_of
from .deembed import latest_cable_run
from .measurement import MeasurementError
from .project import MeasurementFile, MeasurementRef, Project, check_plain_filename
from .registry import ModuleInfo, ModuleRegistry
from .runner import Runner
from .runs import RunWriter, read_run
from .wiring import Diagram, diagram_for, load_wiring

log = logging.getLogger(__name__)

Connect = Callable[[str, Optional[threading.Event]], Any]  # (name, run's stop event) -> handle
RUNS_FOLDER = "runs"
FIXTURE_KINDS = ("cable", "attenuator")  # measurements that can be taken out as a fixture


@dataclass
class Row:
    """One line of the list of measurements."""

    ref: MeasurementRef
    info: Optional[ModuleInfo]  # None if the type is unknown (module missing)
    problem: str = ""  # why this measurement cannot be used, or ""


def instrument_names(inst_path: Path) -> List[str]:
    """The names (``instance_name``) of the instruments of an ``.inst`` file; ``[]`` if the file
    is missing or not readable."""
    try:
        data = json.loads(Path(inst_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("instruments", []) if isinstance(data, dict) else []
    names = [i.get("instance_name") for i in items if isinstance(i, dict)]
    return [n for n in names if isinstance(n, str) and n]


class ProjectSession:
    """A project, its measurement types and the way to reach its instruments."""

    def __init__(
        self,
        project: Project,
        registry: ModuleRegistry,
        connect: Optional[Connect] = None,
        instruments: Optional[Sequence[str]] = None,
        run_dir: Optional[Path] = None,
        assets: Optional[Any] = None,
    ):
        """``instruments``: the names of the project's instruments; by default those of the
        ``.inst`` file of the project. ``run_dir``: where the run files go (default: the
        ``runs`` folder of the project). ``assets``: the registry of cables and devices
        (``ola.assets.AssetRegistry``): the card of every object a measurement names is saved in
        the header of its runs."""
        self.project, self.registry, self.connect = project, registry, connect
        self._instruments = list(instruments) if instruments is not None else None
        self.assets = assets
        self.run_dir = Path(run_dir) if run_dir else project.directory / RUNS_FOLDER
        self.extra_run_dirs: List[Path] = []  # more folders where cable measurements are looked for

    # ----- the project ------------------------------------------------------------------------
    @property
    def instruments(self) -> List[str]:
        """Names of the instruments the measurements of this project can use."""
        if self._instruments is not None:
            return list(self._instruments)
        if not self.project.inst_file:
            return []
        return instrument_names(
            self.project.directory / check_plain_filename(self.project.inst_file)
        )

    def module_types(self) -> List[ModuleInfo]:
        """The measurement types that can be added."""
        return self.registry.list()

    def rows(self) -> List[Row]:
        """The measurements of the project, each with the reason if it cannot be used."""
        out = []
        for ref in self.project.measurements:
            try:
                info: Optional[ModuleInfo] = self.registry.get(ref.type)
            except MeasurementError as exc:
                out.append(Row(ref, None, str(exc)))
                continue
            problem = ""
            try:
                path = self.project.file_path(ref)
                if not path.is_file():
                    problem = f"file {ref.file!r} is missing"
                elif not ref.file.lower().endswith(info.extension):
                    problem = f"file {ref.file!r} should end with {info.extension}"
            except MeasurementError as exc:
                problem = str(exc)
            out.append(Row(ref, info, problem))
        return out

    def path(self, ref: MeasurementRef) -> Path:
        """Path of the file of a measurement."""
        return self.project.file_path(ref)

    def load(self, ref: MeasurementRef) -> MeasurementFile:
        """The content of the file of a measurement."""
        return MeasurementFile.load(self.path(ref))

    # ----- changing the project ---------------------------------------------------------------
    def create(self, type: str, name: str) -> MeasurementRef:
        """Add a measurement of ``type`` with starting parameters and save the project. An
        efficiency measurement starts from the template of its editor, with the instruments of
        the project already filled in where possible."""
        name = name.strip()
        if not name:
            raise MeasurementError("the measurement needs a name")
        params: Dict[str, Any] = {}
        if type == "efficiency":
            from .efficiency_editor import EfficiencyEditor

            params = EfficiencyEditor.template(self.instruments)
        elif self.registry.get(type).builtin:  # a built-in module may give its own starting point
            import sys

            module = sys.modules.get(self.registry.load_class(type).__module__)
            starting = getattr(module, "default_params", None)
            params = dict(starting()) if callable(starting) else {}
        ref = self.project.add_measurement(type, name, self.registry, params)
        self.project.save()
        return ref

    def rename(self, measurement_id: str, name: str) -> None:
        """Change the displayed name (the file keeps its name)."""
        name = name.strip()
        if not name:
            raise MeasurementError("the measurement needs a name")
        self.project.get(measurement_id).name = name
        self.project.save()

    def remove(self, measurement_id: str, delete_file: bool = False) -> None:
        """Take a measurement out of the project (its file is deleted only if asked)."""
        self.project.remove_measurement(measurement_id, delete_file=delete_file)
        self.project.save()

    def set_instrument_file(self, file_name: str) -> None:
        """Choose the ``.inst`` file of the project (a file in the project folder)."""
        check_plain_filename(file_name)
        if not (self.project.directory / file_name).is_file():
            raise MeasurementError(f"{file_name!r} is not in the project folder")
        self._instruments = None
        self.project.inst_file = file_name
        self.project.save()

    # ----- running ----------------------------------------------------------------------------
    def bind(
        self,
        measurement_file: MeasurementFile,
        info: ModuleInfo,
        cancel: Optional[threading.Event] = None,
    ) -> Dict[str, List[Any]]:
        """The handles for every role of the measurement. A role without names in the file gets
        all the project's instruments. ``MeasurementError`` (readable) if an instrument is not in
        the project or cannot be reached."""
        if self.connect is None:
            raise MeasurementError("the instruments are not connected: no way to reach them yet")
        known = set(self.instruments)
        handles: Dict[str, Any] = {}
        cache: Dict[str, Any] = {}
        for role in info.roles:
            wanted = measurement_file.role_bindings.get(role.name) or list(self.instruments)
            if isinstance(wanted, str):
                wanted = [wanted]
            missing = [n for n in wanted if known and n not in known]
            if missing:
                raise MeasurementError(
                    f"instrument(s) not in the project: {', '.join(missing)} "
                    f"(role '{role.name}')"
                )
            role_handles = []
            for name in wanted:
                if name not in cache:
                    try:
                        cache[name] = self.connect(name, cancel)
                    except Exception as exc:  # the real reason is shown to the user
                        raise MeasurementError(f"cannot reach instrument '{name}': {exc}") from exc
                role_handles.append(cache[name])
            if role.category == "network_analyzer":
                self._restore_calibrations(role_handles, measurement_file.params)
            handles[role.name] = role_handles
        return handles

    def _restore_calibrations(self, handles: List[Any], params: Dict[str, Any]) -> None:
        """Before a run: each VNA gets back the saved software calibration made for **it** (its
        serial number) and for the sweep of the measurement, if there is one. A failure is only
        logged: the measurement then runs as before (it can require a calibration itself)."""
        from .compat import sweep_of
        from .vna_calibration_flow import auto_restore

        sweep = sweep_of(params)
        for handle in handles:
            try:
                auto_restore(handle, self.project.path, sweep)
            except Exception as exc:
                log.warning("the calibration of %s was not restored: %s", handle.name, exc)

    def compatibility(
        self,
        ref: MeasurementRef,
        characteristics_of: Callable[[str], Dict[str, float]],
        abilities_of: Optional[Callable[[str], Dict[str, Any]]] = None,
    ) -> List[Finding]:
        """What the instruments now bound to the roles of a measurement have less of than the ones
        of its previous runs (see ``ola.compat.check_role``). ``characteristics_of(name)`` gives
        what an instrument of the project can do (``ProjectConnector.characteristics``). Nothing
        is connected. ``abilities_of(name)``: what a network analyzer can measure (see
        ``ProjectConnector.abilities``). For the previous instrument of a role there have to be
        previous runs, except for a VNA, whose sweep is checked against the parameters of the
        measurement whether or not it was run before."""
        row = next((r for r in self.rows() if r.ref.id == ref.id), None)
        if row is None or row.info is None:
            return []
        measurement_file = self.load(ref)
        runs = []
        for path in self.runs(ref):
            try:
                runs.append(read_run(path))
            except (OSError, ValueError):
                continue
        findings: List[Finding] = []
        for role in row.info.roles:
            wanted = measurement_file.role_bindings.get(role.name) or list(self.instruments)
            if isinstance(wanted, str):
                wanted = [wanted]
            bound = [{"name": n, "characteristics": characteristics_of(n)} for n in wanted]
            if role.category == "network_analyzer":
                for item in bound:
                    item["abilities"] = abilities_of(item["name"]) if abilities_of else {}
                findings += check_network_analyzer(role.name, bound, measurement_file.params, runs)
            else:
                findings += check_role(role.name, bound, runs)
        return findings

    def build_runner(
        self,
        ref: MeasurementRef,
        unattended: Optional[str] = None,
        accepted_differences: Optional[List[Finding]] = None,
    ) -> Tuple[Runner, Path]:
        """A runner for the measurement, not started, writing its results to the returned run
        file. Raises ``MeasurementError`` with a readable reason if it cannot be prepared (missing
        file or module, instrument not reachable)."""
        row = next((r for r in self.rows() if r.ref.id == ref.id), None)
        if row is None or row.info is None or row.problem:
            raise MeasurementError(row.problem if row else f"no measurement {ref.id!r}")
        measurement_file = self.load(ref)
        if measurement_file.type != ref.type:
            raise MeasurementError(
                f"{ref.file}: the file is a '{measurement_file.type}' measurement, the project "
                f"says '{ref.type}'"
            )
        cancel = threading.Event()  # shared by the runner (Stop) and the instrument handles
        handles = self.bind(measurement_file, row.info, cancel)
        measurement = self.registry.create(
            ref.type, self.resolve_correction(measurement_file.params)
        )
        runner = Runner(measurement, handles, unattended=unattended, stop_event=cancel)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = self.run_dir / f"{Path(ref.file).stem}_{stamp}.jsonl"
        suffix = 2
        while path.exists():  # two runs in the same second
            path = self.run_dir / f"{Path(ref.file).stem}_{stamp}_{suffix}.jsonl"
            suffix += 1
        extra: Dict[str, Any] = {}
        cards = snapshots_for(measurement_file.params, self.assets)
        if cards:  # what the cable / device was on the day, kept with its results
            extra["assets"] = cards
        if accepted_differences:  # the user went on although an instrument has less than before
            extra["accepted_differences"] = [f.to_dict() for f in accepted_differences]
        header = RunWriter.header_for(
            runner,
            measurement_id=ref.id,
            measurement_name=ref.name,
            project=self.project.name,
            **extra,
        )
        runner.add_listener(RunWriter(path, header, observed=lambda: observed_of(runner)))
        return runner, path

    def resolve_correction(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """The parameters with the cables of a ``correction`` found: a cable (``correction.cable``
        of a reflection measurement) or a fixture (``correction.port1`` / ``port2`` of a
        transmission one) named by its registry code (``asset_id``) becomes the newest finished
        measurement of that code in the runs folder (``run``), which is then saved in the header of
        the run, so it is known later which measurement was used. A fixture may be a cable or an
        attenuator. ``MeasurementError`` if there is none. Parameters without a correction, or
        with the file already named, are returned unchanged."""
        correction = params.get("correction")
        if not isinstance(correction, dict):
            return params
        resolved = params
        for key, kinds in (
            ("cable", ("cable",)),
            ("port1", FIXTURE_KINDS),
            ("port2", FIXTURE_KINDS),
        ):
            spec = correction.get(key)
            if not isinstance(spec, dict) or spec.get("run") or spec.get("touchstone"):
                continue
            code = normalize_code(str(spec.get("asset_id", "")))
            if not code:
                continue
            folders = [self.run_dir, *self.extra_run_dirs]
            found = latest_cable_run(code, folders, kinds)
            if found is None:
                what = " or ".join(kinds)
                raise MeasurementError(
                    f"no finished {what} measurement of {code} in "
                    f"{', '.join(str(f) for f in folders)}: measure it first (with this code in "
                    "its card), or name a run file or a Touchstone file in the correction"
                )
            if resolved is params:
                resolved = json.loads(json.dumps(params))
            resolved["correction"][key]["run"] = str(found)
        return resolved

    def wiring(self, ref: MeasurementRef, lang: str = "en") -> Optional[Diagram]:
        """The connection diagram of a measurement (see ``ola.wiring``): the one of its module,
        for the parameters of its file and with the names of the instruments the file binds to
        each role; None if the module has no diagram or it has nothing to show for this file.
        ``WiringError`` if the file is wrong."""
        row = next((r for r in self.rows() if r.ref.id == ref.id), None)
        if row is None or row.info is None:
            return None
        wiring = load_wiring(row.info.path)
        if wiring is None:
            return None
        measurement_file = self.load(ref)
        names: Dict[str, List[str]] = {}
        for role, bound in measurement_file.role_bindings.items():
            names[role] = [bound] if isinstance(bound, str) else [str(n) for n in bound]
        diagram = diagram_for(wiring, measurement_file.params, names, lang, row.info.path)
        return None if diagram.empty else diagram

    def runs(self, ref: MeasurementRef) -> List[Path]:
        """The run files of this measurement (made from its file), newest first."""
        if not self.run_dir.is_dir():
            return []
        stem = Path(ref.file).stem
        files = [p for p in self.run_dir.glob(f"{stem}_*.jsonl") if _belongs(p, stem)]
        return sorted(files, key=lambda p: p.name, reverse=True)

    @staticmethod
    def describe_run(path: Path) -> Dict[str, Any]:
        """Short summary of a run file: state, number of points, start time."""
        run = read_run(path)
        header = run["header"] or {}
        end = run["end"] or {}
        return {
            "file": path.name,
            "state": end.get("state", "interrupted"),
            "points": len(run["points"]),
            "started": header.get("started_at"),
        }


def _belongs(path: Path, stem: str) -> bool:
    """``stem_<date>_<time>[_n].jsonl`` and not the run of another measurement whose file name
    merely starts with the same letters (``eff_2.eff`` and ``eff.eff``)."""
    start = len(stem) + 1
    rest = path.stem[start:]
    parts = rest.split("_")
    return len(parts) in (2, 3) and parts[0].isdigit() and len(parts[0]) == 8
