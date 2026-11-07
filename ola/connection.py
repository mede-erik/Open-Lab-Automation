# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""How a project reaches its instruments: the ``connect`` that the project window needs.

``ProjectConnector`` reads the project's ``.inst`` file and, for the instrument called ``name``,
returns the *handle* a measurement uses (``handle.call("set_voltage", value=5)``):

* a **manual instrument** (``is_manual`` in the file: a bench supply or load without remote control)
  gives a handle that asks the operator, through ``prompt``, to do the action by hand;
* any other instrument is looked up in the library by its ``model_id``, opened at its
  ``visa_address`` (USB-TMC, LAN, GPIB, serial...) and wrapped in an ``InstrumentHandle``.

Connections are kept open between runs (opening is slow and some instruments dislike it); the
handle is new for every run, because it carries that run's ``cancel`` event (set by *Stop*).
``close()`` closes them all. No Qt here: the application supplies ``prompt`` (a pop-up) and
``library``; a test supplies ``opener`` (a simulated instrument instead of a real one)::

    connector = ProjectConnector(library, lambda: project_dir / "x.inst", prompt=my_prompt)
    handle = connector("PSU1", cancel_event)          # the 'connect' of ProjectSession
    connector.close()

Every problem is raised as ``ConnectionProblem`` with a sentence that says what to fix.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

log = logging.getLogger(__name__)

Opener = Callable[
    [str, Any, str, int], Any
]  # (address, library, model_id, timeout_ms) -> transport
Prompt = Callable[[Any, Optional[threading.Event]], bool]  # (ManualRequest, cancel) -> confirmed


class ConnectionProblem(Exception):
    """An instrument cannot be reached; the message says why and what to check."""


def read_inst_entries(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """The entries of an ``.inst`` file by ``instance_name``. ``ConnectionProblem`` if there is no
    file or it cannot be read."""
    if path is None:
        raise ConnectionProblem("the project has no instrument file (.inst)")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConnectionProblem(f"cannot read the instrument file {path}: {exc}") from exc
    items = data.get("instruments", []) if isinstance(data, dict) else []
    return {i["instance_name"]: i for i in items if isinstance(i, dict) and i.get("instance_name")}


def _default_opener(
    address: str, library: Any, model_id: str, timeout_ms: int, serial_override: Any = None
) -> Any:
    from .tester import open_visa

    return open_visa(
        address, library, model_id, timeout_ms=timeout_ms, serial_override=serial_override
    )


class ProjectConnector:
    """Gives the handle of an instrument of the project (see the module docstring)."""

    def __init__(
        self,
        library: Any,
        inst_path: Callable[[], Optional[Path]],
        prompt: Optional[Prompt] = None,
        opener: Optional[Opener] = None,
        timeout_ms: int = 5000,
    ):
        """``library``: an ``ola.library.Library``. ``inst_path()``: the ``.inst`` file of the
        project *now* (it is read at every connection, so a change of file is taken into
        account). ``prompt(request, cancel)``: shows a manual action to the operator, True if
        done."""
        self.library, self._inst_path, self.prompt = library, inst_path, prompt
        self._opener = opener or _default_opener
        self.timeout_ms = timeout_ms
        self._open: Dict[str, Tuple[tuple, Any, Any]] = {}  # name -> (key, instrument, link)
        self._lock = threading.Lock()

    def __call__(self, name: str, cancel: Optional[threading.Event] = None) -> Any:
        return self.connect(name, cancel)

    def names(self) -> list:
        """The instruments of the instrument file."""
        return list(read_inst_entries(self._inst_path()))

    def connect(self, name: str, cancel: Optional[threading.Event] = None) -> Any:
        """The handle of instrument ``name`` for one run (``cancel``: the run's stop event)."""
        entries = read_inst_entries(self._inst_path())
        entry = entries.get(name)
        if entry is None:
            known = ", ".join(sorted(entries)) or "none"
            raise ConnectionProblem(
                f"'{name}' is not in the instrument file (instruments there: {known})"
            )
        if entry.get("is_manual"):
            return self._manual(entry, cancel)
        return self._remote(name, entry, cancel)

    # ----- the two kinds of instrument -------------------------------------------------------
    def characteristics(self, name: str) -> Dict[str, float]:
        """What the instrument ``name`` of the instrument file can do, without connecting to it:
        the limits of a manual instrument, the numbers the library gives for any other. Empty if
        the instrument or its model is not known."""
        from .compat import characteristics

        entry = read_inst_entries(self._inst_path()).get(name)
        if entry is None:
            return {}
        if entry.get("is_manual"):
            channel = (entry.get("channels") or [{}])[0]
            return {
                k: float(channel[k])
                for k in ("max_voltage", "max_current", "max_power")
                if isinstance(channel.get(k), (int, float)) and channel[k]
            }
        model_id = self.library.resolve_model_id(entry.get("model_id") or entry.get("model") or "")
        return characteristics(self.library, model_id) if model_id else {}

    def abilities(self, name: str) -> Dict[str, Any]:
        """What a network analyzer of the project can measure, without connecting to it:
        ``sparameters`` (the list the library gives for the model, None if it gives none) and
        ``source_power`` (whether the model has the call). Empty for any other instrument."""
        entry = read_inst_entries(self._inst_path()).get(name)
        if entry is None or entry.get("is_manual"):
            return {}
        model_id = self.library.resolve_model_id(entry.get("model_id") or entry.get("model") or "")
        ref = self.library.find_model(model_id) if model_id else None
        if ref is None or ref.category != "network_analyzers_series":
            return {}
        measurable = (ref.model.get("capabilities") or {}).get("measurable_sparameters")
        commands = self.library.commands(model_id) or {}
        return {
            "sparameters": list(measurable) if isinstance(measurable, list) else None,
            "source_power": "set_source_power" in commands,
        }

    def _manual(self, entry: Dict[str, Any], cancel: Optional[threading.Event]) -> Any:
        from .manual_instrument import manual_handle_from_inst

        prompt = (lambda request: self.prompt(request, cancel)) if self.prompt else None
        try:
            return manual_handle_from_inst(entry, self.library, prompt, cancel)
        except Exception as exc:  # e.g. a type of manual instrument that does not exist
            raise ConnectionProblem(f"manual instrument '{entry['instance_name']}': {exc}") from exc

    def _remote(self, name: str, entry: Dict[str, Any], cancel: Optional[threading.Event]) -> Any:
        from .drivers import driver_for
        from .instrument import Instrument
        from .identity import read_identity
        from .instrument_handle import InstrumentHandle

        identifier = entry.get("model_id") or entry.get("model")
        if not identifier:
            raise ConnectionProblem(f"'{name}' has no model in the instrument file")
        model_id = self.library.resolve_model_id(identifier)
        if model_id is None:
            raise ConnectionProblem(
                f"the model of '{name}' ({identifier}) is not in the instrument library"
            )
        address = entry.get("visa_address")
        if not address:
            raise ConnectionProblem(
                f"'{name}' has no address (visa_address) in the instrument file"
            )
        serial = dict(entry.get("serial") or {})  # RS-232 settings that differ from the library
        timeout_ms = int(entry.get("timeout_ms") or self.timeout_ms)
        key = (model_id, address, json.dumps(serial, sort_keys=True), timeout_ms)
        with self._lock:
            known = self._open.get(name)
            if known is not None and known[0] == key:
                instrument, fresh = known[1], False
            else:
                if known is not None:
                    self._close_link(known[2])
                link = self._open_link(name, address, model_id, timeout_ms, serial)
                instrument = Instrument(name, link, driver_for(self.library, model_id, link))
                self._open[name] = (key, instrument, link)
                fresh = True
        handle = InstrumentHandle(name, self.library, model_id, instrument, cancel)
        if fresh and address.upper().startswith("ASRL") and handle.supports("set_remote"):
            try:  # serial instruments are usually put in remote mode by hand otherwise
                handle.call("set_remote")
            except Exception as exc:
                log.warning("set_remote not accepted by %s: %s", name, exc)
        if fresh:  # who the apparatus is, read once per connection and kept for the saved runs
            instrument.identity = read_identity(handle, address)
        return handle

    def _open_link(
        self, name: str, address: str, model_id: str, timeout_ms: int, serial: Dict[str, Any]
    ) -> Any:
        try:
            if serial:  # an opener that does not know serial settings is only called without them
                return self._opener(
                    address, self.library, model_id, timeout_ms, serial_override=serial
                )
            return self._opener(address, self.library, model_id, timeout_ms)
        except Exception as exc:
            raise ConnectionProblem(
                f"cannot open '{name}' at {address}: {type(exc).__name__}: {exc}. Check that it is "
                f"switched on, connected, and that the address is right"
            ) from exc

    @staticmethod
    def _close_link(link: Any) -> None:
        try:
            link.close()
        except Exception as exc:  # already closed, or gone
            log.debug("closing a connection failed: %s", exc)

    def close(self) -> None:
        """Close every open connection (the instruments are left as they are)."""
        with self._lock:
            for _key, _instrument, link in self._open.values():
                self._close_link(link)
            self._open.clear()
