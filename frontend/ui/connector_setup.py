"""Builds the ``connect`` of a project for the application: library + manual-action pop-up.

``make_connector(session, library_path, translator, parent)`` returns the callable the project
window gives to ``ProjectSession``: an ``ola.connection.ProjectConnector`` that reads the project's
``.inst`` file and opens the instruments from the instrument library. If the library or the engine
cannot be loaded it returns ``not_connected`` (a function that says why), so the window still works
and *Start measurement* explains the problem instead of crashing.
"""

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from PyQt6.QtWidgets import QWidget

from frontend.ui.ProjectWindow import not_connected

log = logging.getLogger(__name__)
_libraries: dict = (
    {}
)  # library path -> Library (loading it is slow; it never changes while running)


def default_library_path() -> str:
    """``Instruments_LIB/instruments_lib.json`` at the root of the application."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "Instruments_LIB", "instruments_lib.json")


def load_library(path: str) -> Any:
    """The instrument library at ``path`` (kept for next time). Raises if it cannot be loaded."""
    if path not in _libraries:
        from ola.library import Library  # not imported at the top: the engine part is optional

        _libraries[path] = Library.load(path)
    return _libraries[path]


def make_connector(
    session: Any,
    library_path: Optional[str],
    translator: Any = None,
    parent: Optional[QWidget] = None,
) -> Callable[..., Any]:
    """The ``connect`` for the project of ``session`` (see the module docstring)."""
    try:
        if not library_path:
            raise FileNotFoundError("the path of the instrument library is not known")
        library = load_library(library_path)
        from frontend.ui.manual_prompt import ManualPrompter
        from ola.connection import ProjectConnector
    except Exception as exc:  # engine not installed, library missing or damaged
        reason = f"the instrument library cannot be used: {exc}"
        log.warning("instruments cannot be connected: %s", exc)

        def unavailable(name: str, cancel=None):
            raise RuntimeError(reason)

        return unavailable

    def inst_path() -> Optional[Path]:
        project = session.project
        return project.directory / project.inst_file if project.inst_file else None

    return ProjectConnector(library, inst_path, prompt=ManualPrompter(translator, parent))


__all__ = ["make_connector", "load_library", "default_library_path", "not_connected"]
