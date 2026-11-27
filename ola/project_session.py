# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

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
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import bench as ola_bench
from .assets import normalize_code, snapshots_for
from .duts import dut_snapshots_for
from .compat import Finding, check_network_analyzer, check_role, observed_of
from .deembed import latest_cable_run
from .inst_file import fits_role, load_inst
from .measurement import MeasurementError
from .project import MeasurementFile, MeasurementRef, Project, check_plain_filename
from .registry import ModuleInfo, ModuleRegistry
from .runner import Runner
from .efficiency_spec import SpecError, parse_params
from .runs import RunWriter, read_run
from .scope_capture import DEFAULT_POINTS
from .scope_capture import estimate as scope_estimate
from .was_calls import check_was
from .variants import (
    ASK_FOR_VARIANT,
    dut_group,
    previous_variants,
    variant_names,
    variant_of,
    with_variant,
)
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
        duts: Optional[Any] = None,
    ):
        """``instruments``: the names of the project's instruments; by default those of the
        ``.inst`` file of the project. ``run_dir``: where the run files go (default: the
        ``runs`` folder of the project). ``assets``: the registry of cables and devices
        (``ola.assets.AssetRegistry``): the card of every object a measurement names is saved in
        the header of its runs. ``duts``: the archive of the devices under test
        (``ola.duts.DutRegistry``): the card of the DUT a measurement names, with its versions, is
        saved there too."""
        self.project, self.registry, self.connect = project, registry, connect
        self._instruments = list(instruments) if instruments is not None else None
        self.assets = assets
        self.duts = duts
        self.resistor_kits: Optional[Any] = None  # ``ola.resistor_kits.KitRegistry`` (default file)
        self.run_dir = Path(run_dir) if run_dir else project.directory / RUNS_FOLDER
        self.extra_run_dirs: List[Path] = []  # more folders where cable measurements are looked for
        # VNAs that keep their own calibration and lost it (``ola.vna_power_state``), as found by
        # the last ``bind``: ``{"instrument": name, "text": warning}``
        self.calibration_warnings: List[Dict[str, str]] = []

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

    def instruments_by_role(self, info: ModuleInfo) -> Dict[str, List[str]]:
        """For each role of a measurement type, the names of the project's instruments that can
        take it (``ola.inst_file.fits_role``): a supply role does not list a datalogger. When the
        types of the instruments are not known (no instrument file), every role gets all names."""
        names = self.instruments
        entries: Dict[str, Dict[str, Any]] = {}
        if self._instruments is None and self.project.inst_file:
            try:
                path = self.project.directory / check_plain_filename(self.project.inst_file)
                entries = {
                    str(e.get("instance_name")): e
                    for e in load_inst(path)[0]
                    if e.get("instance_name")
                }
            except (ValueError, MeasurementError):
                entries = {}
        return {
            role.name: [n for n in names if n not in entries or fits_role(entries[n], role)]
            for role in info.roles
        }

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
        if type in ("efficiency", "resistive_efficiency"):
            from .efficiency_editor import EfficiencyEditor

            load = type == "resistive_efficiency"
            params = EfficiencyEditor.template(self.instruments, load=load)
        elif self.registry.get(type).builtin:  # a built-in module may give its own starting point
            import sys

            module = sys.modules.get(self.registry.load_class(type).__module__)
            starting = getattr(module, "default_params", None)
            params = dict(starting()) if callable(starting) else {}
        ref = self.project.add_measurement(type, name, self.registry, params)
        self.project.save()
        return ref

    def adopt(self, file_name: str, name: str = "") -> MeasurementRef:
        """Add an existing measurement file of the project folder to the project and save it.
        The type is read from the file; ``MeasurementError`` if it is not a measurement file of
        a known type or is already in the project."""
        check_plain_filename(file_name)
        if any(m.file.lower() == file_name.lower() for m in self.project.measurements):
            raise MeasurementError(f"{file_name} is already in the project")
        content = MeasurementFile.load(self.project.directory / file_name)
        info = self.registry.get(content.type)  # unknown type -> MeasurementError
        taken = {m.id for m in self.project.measurements}
        n = 1
        while f"m{n}" in taken:
            n += 1
        ref = MeasurementRef(f"m{n}", info.id, name.strip() or Path(file_name).stem, file_name)
        self.project.measurements.append(ref)
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
        all the project's instruments, except an **optional role of a kind** (an oscilloscope for
        the waveforms, an electronic load for the ripple conditions): that one gets none until a
        name is written, so that a measurement that does not use it does not connect everything.
        ``MeasurementError`` (readable) if an instrument is not in the project or cannot be
        reached."""
        if self.connect is None:
            raise MeasurementError("the instruments are not connected: no way to reach them yet")
        self.calibration_warnings = []  # VNAs whose own calibration is missing or lost
        known = set(self.instruments)
        handles: Dict[str, Any] = {}
        cache: Dict[str, Any] = {}
        for role in info.roles:
            wanted = measurement_file.role_bindings.get(role.name)
            if not wanted:
                optional_kind = not role.required and role.category != "any"
                wanted = [] if optional_kind else list(self.instruments)
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
        logged: the measurement then runs as before (it can require a calibration itself).

        A software calibration that is already applied to the connection but was made for another
        sweep stops the run here (``MeasurementError`` with the two sweeps): the driver would refuse
        to read, after the questions of the measurement."""
        from .compat import sweep_of
        from .vna_calibration_flow import auto_restore, note_kept_calibration, sweep_problem
        from .vna_power_state import POWER_STATE

        sweep = sweep_of(params)
        for handle in handles:
            # a VNA that keeps its own calibration: is it still valid (not switched off since)?
            try:
                warning = POWER_STATE.check(handle)
            except Exception as exc:  # never stops the run: the operator decides
                log.warning("the calibration state of %s is not known: %s", handle.name, exc)
                warning = None
            if warning:
                self.calibration_warnings.append({"instrument": handle.name, "text": warning})
            if not POWER_STATE.allows_restore(handle):
                continue  # a calibration of an earlier run, or lost: not put back
            problem = sweep_problem(handle, sweep)
            if problem:
                raise MeasurementError(f"{handle.name}: {problem}")
            try:
                auto_restore(handle, self.project.path, sweep)
                note_kept_calibration(handle, self.project.path)  # which kind the VNA holds
            except Exception as exc:
                log.warning("the calibration of %s was not restored: %s", handle.name, exc)

    def compatibility(
        self,
        ref: MeasurementRef,
        characteristics_of: Callable[[str], Dict[str, float]],
        abilities_of: Optional[Callable[[str], Dict[str, Any]]] = None,
        bindings: Optional[Dict[str, Any]] = None,
    ) -> List[Finding]:
        """What the instruments now bound to the roles of a measurement have less of than the ones
        of its previous runs (see ``ola.compat.check_role``). ``characteristics_of(name)`` gives
        what an instrument of the project can do (``ProjectConnector.characteristics``). Nothing
        is connected. ``abilities_of(name)``: what a network analyzer can measure (see
        ``ProjectConnector.abilities``). For the previous instrument of a role there have to be
        previous runs, except for a VNA, whose sweep is checked against the parameters of the
        measurement whether or not it was run before. ``bindings`` (``{role: name or [names]}``)
        is used instead of the ones in the measurement file, to see what an instrument that is only
        proposed would give."""
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
            chosen = bindings if bindings is not None else measurement_file.role_bindings
            wanted = chosen.get(role.name) or list(self.instruments)
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

    def variant_question(self, ref: MeasurementRef) -> Optional[Dict[str, Any]]:
        """What to show when a run of this measurement starts and asks for its variant, or None if
        it does not (a type that does not ask, or no DUT named). ``dut_id``, ``dut`` (its label),
        ``version``, ``current`` (the variant of the file), ``last`` (the variant of the last run
        of this DUT, or of the file if there is none) and ``names`` (those used before)."""
        if ref.type not in ASK_FOR_VARIANT:
            return None
        try:
            params = self.load(ref).params
        except Exception:  # the file cannot be read: the run will say so
            return None
        group = dut_group(params)
        if group is None:
            return None
        device = params[group]
        dut_id = str(device["dut_id"])
        earlier = previous_variants(self.run_dir, dut_id)
        current = variant_of(params)
        card = self.duts.get(dut_id) if self.duts is not None else None
        return {
            "dut_id": dut_id,
            "dut": getattr(card, "label", "") or dut_id,
            "version": str(device.get("version") or ""),
            "current": current,
            "last": earlier[0] if earlier else current,
            "names": variant_names(earlier + [current]),
        }

    def build_runner(
        self,
        ref: MeasurementRef,
        unattended: Optional[str] = None,
        accepted_differences: Optional[List[Finding]] = None,
        bench: Optional[bool] = None,
        variant: Optional[Mapping[str, Any]] = None,
        keep_failed: bool = False,
    ) -> Tuple[Runner, Path]:
        """A runner for the measurement, not started, writing its results to the returned run
        file (a run that ends as failed is deleted, unless ``keep_failed``: see ``ola.runs``).
        Raises ``MeasurementError`` with a readable reason if it cannot be prepared (missing file or
        module, instrument not reachable). ``bench``: benchmark mode (``ola.bench``) from
        the opening of the connections on; None follows the ``OLA_BENCH`` environment variable.
        ``variant``: the variant of the DUT for this run (``ola.variants``), taking the place of the
        one in the file, which is not changed; None keeps the one of the file."""
        if bench is None:
            bench = ola_bench.env_enabled()
        if bench:
            ola_bench.enable(fresh=True)  # so opening the connections is measured too
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
        scopes = (measurement_file.params.get("scope_capture") or {}).get("instruments")
        if scopes and not measurement_file.role_bindings.get("scope"):
            # a file written by hand: the oscilloscopes of the waveforms are the ones it names
            measurement_file.role_bindings = {**measurement_file.role_bindings, "scope": scopes}
        handles = self.bind(measurement_file, row.info, cancel)
        params = self.resolve_scope_settings(measurement_file.params)
        if variant is not None:
            try:
                params = with_variant(params, variant)
            except ValueError as exc:
                raise MeasurementError(str(exc)) from exc
        measurement = self.registry.create(
            ref.type,
            self.resolve_kits(self.resolve_golden(self.resolve_correction(params))),
        )
        runner = Runner(measurement, handles, unattended=unattended, stop_event=cancel, bench=bench)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        # the run id is in the name: two people starting in the same second never collide
        path = self.run_dir / f"{Path(ref.file).stem}_{stamp}_{runner.run_id}.jsonl"
        attach = getattr(measurement, "set_run_path", None)
        if callable(attach):  # a measurement that writes files next to its results (waveforms)
            attach(path)
        extra: Dict[str, Any] = {}
        cards = snapshots_for(measurement_file.params, self.assets)
        if cards:  # what the cable / device was on the day, kept with its results
            extra["assets"] = cards
        dut_cards = dut_snapshots_for(measurement_file.params, self.duts)
        if dut_cards:  # the same for the device under test, with its versions
            extra["duts"] = dut_cards
        if self.calibration_warnings:  # the data of this run are not calibrated: said in the file
            extra["calibration_lost"] = [dict(w) for w in self.calibration_warnings]
        if accepted_differences:  # the user went on although an instrument has less than before
            extra["accepted_differences"] = [f.to_dict() for f in accepted_differences]
        header = RunWriter.header_for(
            runner,
            measurement_id=ref.id,
            measurement_name=ref.name,
            project=self.project.name,
            **extra,
        )
        runner.add_listener(
            RunWriter(
                path, header, observed=lambda: observed_of(runner), discard_failed=not keep_failed
            )
        )
        for warning in self.calibration_warnings:  # reported, not blocked
            runner._publish_log(warning["text"], "warning")
        return runner, path

    def resolve_scope_settings(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        """The parameters with the acquisitions of the waveforms written in: when ``scope_capture``
        is asked for, the scope settings files of the project that are on, in order, each as
        ``{"name": file name without .was, "file": ..., "settings": its content}``.
        ``MeasurementError`` if there is none, or one is missing, unreadable or wrong, so that the
        run does not start. Parameters that do not ask for waveforms are returned as they are."""
        capture = params.get("scope_capture")
        if not isinstance(capture, dict) or not (capture.get("every") or capture.get("when")):
            return dict(params)
        acquisitions = []
        for name in self.project.active_scope_files():
            path = self.project.scope_path(name)
            try:
                settings = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise MeasurementError(f"the scope settings file {name} is missing") from exc
            except (OSError, ValueError) as exc:
                raise MeasurementError(f"{name} cannot be read: {exc}") from exc
            problems = check_was(settings)
            if problems:
                raise MeasurementError(f"{name}: {problems[0]}")
            acquisition = {"name": path.stem, "file": name, "settings": settings}
            target = self.project.scope_target(name)
            if target:  # the file is for one oscilloscope only
                acquisition["scope"] = target
            acquisitions.append(acquisition)
        if not acquisitions:
            raise MeasurementError(
                "waveforms are asked for, but the project has no scope settings file that is on "
                "(add a .was file to the project, or switch one on)"
            )
        resolved = json.loads(json.dumps(params))
        resolved["scope_capture"]["acquisitions"] = acquisitions
        return resolved

    def wave_estimate(self, ref: MeasurementRef) -> Optional[Dict[str, int]]:
        """What the waveforms of a run of this measurement will take, or None if it asks for none:
        ``steps``, ``captures``, ``waveforms`` and ``bytes`` (at ``scope_capture.points`` samples
        per waveform, 1 M if it does not say). For the warning before the start."""
        try:
            params = self.load(ref).params
        except Exception:  # the file cannot be read: the run will say so
            return None
        capture = params.get("scope_capture")
        if not isinstance(capture, dict) or not (capture.get("every") or capture.get("when")):
            return None
        try:
            load = ref.type == "resistive_efficiency"
            steps = parse_params(params, allow_load=load).point_count()
            resolved = self.resolve_scope_settings(params)
        except (SpecError, MeasurementError):
            return None
        found = scope_estimate(
            steps,
            capture.get("every"),
            resolved["scope_capture"]["acquisitions"],
            capture.get("channels"),
            int(capture.get("points") or DEFAULT_POINTS),
            capture.get("instruments") or [""],
            capture.get("max"),
        )
        return {"steps": steps, **found}

    def resolve_kits(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """The parameters with the resistors of a kit written out: a resistor of a load that is
        ``{"kit": "PWR", "ref": "R22"}`` (or ``{"ref": "R22"}`` with ``resistor_kit``) becomes the
        values of that resistor in the kit, saved in the header of the run, so it is known later
        which values were used. ``MeasurementError`` for an unknown kit or resistor. Parameters
        without a reference are returned unchanged."""
        from .resistor_kits import KitError, KitRegistry
        from .resistors import has_refs

        owners = [
            var["load"]
            for var in params.get("variables") or []
            if isinstance(var, dict) and isinstance(var.get("load"), dict)
        ]
        learning = [o for o in owners if isinstance(o.get("plan"), dict) and o["plan"].get("learn")]
        if not learning and not any(has_refs(owner.get("loads")) for owner in owners):
            return params
        try:
            kits = self.resistor_kits if self.resistor_kits is not None else KitRegistry()
            resolved = json.loads(json.dumps(params))
            for var in resolved["variables"]:
                if not isinstance(var.get("load"), dict):
                    continue
                var["load"]["loads"] = kits.resolve_loads(var["load"].get("loads"))
                plan = var["load"].get("plan")
                if isinstance(plan, dict) and plan.get("learn"):
                    # a run that learns plans loads again: it needs every resistor of the kit
                    kit = kits.get(str(plan.get("kit")))
                    if kit is None:
                        raise KitError(f"there is no kit of resistors called {plan.get('kit')!r}")
                    plan["resistors"] = [
                        {**r.to_dict(), "kit": kit.name, "ref": r.name} for r in kit.resistors
                    ]
        except KitError as exc:
            raise MeasurementError(str(exc)) from exc
        return resolved

    def resolve_golden(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """The parameters with the golden sample found: ``golden.name`` becomes the file of that
        name in the ``golden/`` folder of the project (``golden.run``), saved in the header of the
        run. ``MeasurementError`` if there is no such golden sample. Parameters without one, or
        with the file already named, are returned unchanged."""
        from .golden import GoldenError, golden_path, list_golden

        spec = params.get("golden")
        if not isinstance(spec, dict) or spec.get("run") or not spec.get("name"):
            return params
        try:
            path = golden_path(self.project.directory, str(spec["name"]))
        except GoldenError as exc:
            raise MeasurementError(str(exc)) from exc
        if not path.is_file():
            known = list_golden(self.project.directory)
            raise MeasurementError(
                f"no golden sample called {spec['name']!r} in the project"
                + (f" (there are: {', '.join(known)})" if known else "")
                + ": keep one from the comparison window (Golden sample tab) first"
            )
        resolved = json.loads(json.dumps(params))
        resolved["golden"]["run"] = str(path)
        return resolved

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
            found = latest_cable_run(code, folders, kinds, self.assets)
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
    """``stem_<date>_<time>_<run id>.jsonl`` and not the run of another measurement whose file name
    merely starts with the same letters (``eff_2.eff`` and ``eff.eff``)."""
    start = len(stem) + 1
    rest = path.stem[start:]
    parts = rest.split("_")
    return (
        len(parts) == 3
        and parts[0].isdigit()
        and len(parts[0]) == 8
        and parts[1].isdigit()
        and len(parts[1]) == 6
        and bool(parts[2])
    )
