# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Self-test of the packaged program (``ola-selftest``, built by ``ola.spec``).

It checks what a unit test cannot: that the FROZEN bundle holds everything the program reads at
run time (library, translations, measurement modules, drawings), that every module imports, and
that the main window opens. It needs no display and no instrument; settings go to a temporary
home folder. Exit code 0 = all good, 1 = at least one check failed.

Also runs from a source checkout:  python packaging/pyinstaller/selftest.py

``--expect-native`` fails the test if the Rust transport (``ola_native``) is not in the bundle.
"""

from __future__ import annotations

import importlib
import json
import os
import pkgutil
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Settings and config files of the test go to a throw-away home
_HOME = tempfile.mkdtemp(prefix="ola-selftest-")
for _var in ("HOME", "USERPROFILE", "APPDATA", "XDG_CONFIG_HOME"):
    os.environ[_var] = _HOME

if not getattr(sys, "frozen", False):
    # Running from a checkout: make the repository root importable
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_failures: list[str] = []


def check(name: str, func) -> None:
    """Run one check; print OK / FAIL and keep going."""
    try:
        detail = func()
    except Exception:  # noqa: BLE001 - any failure is a failed check
        _failures.append(name)
        print(f"FAIL  {name}")
        print("      " + traceback.format_exc().strip().replace("\n", "\n      "))
        return
    print(f"OK    {name}" + (f"  ({detail})" if detail else ""))


def import_all(package_name: str) -> str:
    """Import every module of a package (sub-packages included)."""
    package = importlib.import_module(package_name)
    names = [package_name]
    for info in pkgutil.walk_packages(package.__path__, package_name + "."):
        names.append(info.name)
    bad = []
    for name in names:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{name}: {type(exc).__name__}: {exc}")
    if bad:
        raise RuntimeError("cannot import:\n" + "\n".join(bad))
    return f"{len(names)} modules"


def check_appinfo() -> str:
    import frontend

    path = os.path.join(os.path.dirname(frontend.__file__), "appinfo.json")
    with open(path, encoding="utf-8") as handle:
        info = json.load(handle)
    return f"{info['app_name']} {info['version']}"


def check_translations() -> str:
    from frontend.core.Translator import Translator

    translator = Translator()
    for lang in ("en", "it", "de", "es", "fr"):
        if lang not in translator.available_langs:
            raise RuntimeError(f"language file missing: {lang}")
        translator.set_language(lang)
        if not translator.translations:
            raise RuntimeError(f"language file empty or unreadable: {lang}")
    return ", ".join(sorted(translator.available_langs))


def check_library() -> str:
    from frontend.ui.connector_setup import default_library_path, load_library

    path = default_library_path()
    if not os.path.isfile(path):
        raise RuntimeError(f"instrument library not found: {path}")
    if not os.path.isdir(os.path.join(os.path.dirname(path), "schema")):
        raise RuntimeError("Instruments_LIB/schema not found")
    library = load_library(path)
    return type(library).__name__


def check_modules() -> str:
    from ola.registry import default_registry

    registry = default_registry()
    modules = registry.list()
    if not modules:
        raise RuntimeError("no measurement module found")
    for info in modules:
        if info.builtin:
            registry.load_class(info.id)
    return f"{len(modules)} modules"


def check_transport(expect_native: bool) -> str:
    import ola.transport as transport

    if expect_native and transport.BACKEND != "native":
        raise RuntimeError(f"native transport expected, got '{transport.BACKEND}'")
    return transport.BACKEND


def check_main_window() -> str:
    from PyQt6.QtWidgets import QApplication

    from frontend.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    window.close()
    app.processEvents()
    return "built, shown, closed"


def main(argv: list[str]) -> int:
    expect_native = "--expect-native" in argv
    print(f"frozen: {bool(getattr(sys, 'frozen', False))}   python: {sys.version.split()[0]}")
    check("appinfo.json", check_appinfo)
    check("translations", check_translations)
    check("instrument library", check_library)
    check("import ola.*", lambda: import_all("ola"))
    check("import frontend.*", lambda: import_all("frontend"))
    check("built-in measurement modules", check_modules)
    check("transport", lambda: check_transport(expect_native))
    check("main window", check_main_window)
    if _failures:
        print(f"\n{len(_failures)} check(s) FAILED: {', '.join(_failures)}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
