# -*- mode: python ; coding: utf-8 -*-
# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""PyInstaller recipe for Open Lab Automation (Windows and Linux, one-folder build).

    pyinstaller --noconfirm --distpath dist-package --workpath build-package \
        packaging/pyinstaller/ola.spec

Result: ``dist-package/OpenLabAutomation/`` with

* ``OpenLabAutomation``  the GUI (no console window);
* ``ola-selftest``       a console program that checks the frozen bundle (see ``selftest.py``).

Layout rule: the program finds its data with paths relative to the module files
(``Instruments_LIB`` at the application root, ``frontend/lang``, ``ola/modules``...). Inside a
frozen bundle the module files live under ``sys._MEIPASS`` with the same relative paths, so the
data below is copied to the SAME relative paths it has in the repository, and the code needs no
special case for the frozen state. Keep it so: do not move data to other folders here.

``Instruments_LIB/docs`` (hundreds of MB of manufacturer PDFs) is left out: nothing reads it.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821  (SPECPATH is set by PyInstaller)

SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def tree(src, dest):
    """All files under ``src`` as PyInstaller ``datas`` entries that keep the layout under ``dest``."""
    src = Path(src)
    entries = []
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        rel = Path(base).relative_to(src)
        for name in files:
            if Path(name).suffix in SKIP_SUFFIXES:
                continue
            entries.append((str(Path(base) / name), str(Path(dest) / rel)))
    return entries


library = ROOT / "Instruments_LIB"
if not (library / "instruments_lib.json").is_file():
    raise SystemExit(
        "Instruments_LIB is empty: run  git submodule update --init  before building the package"
    )

def is_package_dir(directory):
    """True if ``directory`` and every folder above it up to ROOT hold an ``__init__.py``."""
    while directory != ROOT:
        if not (directory / "__init__.py").is_file():
            return False
        directory = directory.parent
    return True


def modules_of(package):
    """Dotted names of every module of a package of the repository, read from the files.

    Not ``collect_submodules``: it imports the package in a child process that does not have the
    repository root on its path, and silently returns nothing. Folders without ``__init__.py``
    (``ola/modules/*``) are data, not packages: their files are copied by ``tree``."""
    names = {package}
    for path in (ROOT / package).rglob("*.py"):
        if SKIP_DIRS & set(path.parts) or not is_package_dir(path.parent):
            continue
        rel = path.relative_to(ROOT).with_suffix("")
        names.add(".".join(rel.parent.parts if rel.name == "__init__" else rel.parts))
    return sorted(names)


datas = []
datas += tree(ROOT / "frontend" / "lang", "frontend/lang")
datas += tree(ROOT / "frontend" / "assets", "frontend/assets")
datas.append((str(ROOT / "frontend" / "appinfo.json"), "frontend"))
# Built-in measurement modules: manifests, drawings and the measurement.py files that the
# registry loads from the file (importlib.util.spec_from_file_location)
datas += tree(ROOT / "ola" / "modules", "ola/modules")
# Instrument library: the data only, not the manufacturer documents
datas.append((str(library / "instruments_lib.json"), "Instruments_LIB"))
datas += tree(library / "schema", "Instruments_LIB/schema")
for name in ("LICENSE", "README.md", "COMMAND_NAMES.md"):
    if (library / name).is_file():
        datas.append((str(library / name), "Instruments_LIB"))
datas += tree(ROOT / "examples", "examples")
datas.append((str(ROOT / "LICENSE"), "."))

# The built-in measurement.py files import these from the engine; they are loaded from a file,
# so the analysis cannot see them: take the whole engine and the whole UI.
hiddenimports = []
hiddenimports += modules_of("ola")
hiddenimports += modules_of("frontend")
# pyvisa-py loads its session classes by name; pyserial lists ports through a platform module
hiddenimports += collect_submodules("pyvisa_py")
hiddenimports += collect_submodules("serial.tools")
hiddenimports += ["matplotlib.backends.backend_qtagg"]
# ola_native (Rust) is imported inside try/except: it is bundled when it is installed in the
# build environment, otherwise the program falls back to the Python transport.

excludes = [
    "tkinter",
    "PyQt5",
    "PySide2",
    "PySide6",
    "pytest",
    "_pytest",
    "pytestqt",
    "black",
    "flake8",
    "sphinx",
    "IPython",
]

# icona.png is the one place for the icon of the program (a copy of the oscilloscope for now);
# PyInstaller converts the PNG to the Windows icon (needs Pillow, which matplotlib brings)
icon = ROOT / "frontend" / "assets" / "icons" / "icona.png"

gui = Analysis(  # noqa: F821
    [str(ROOT / "frontend" / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
selftest = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "pyinstaller" / "selftest.py")],
    pathex=[str(ROOT)],
    datas=[],
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
# No MERGE(): it moves the modules the two programs share out of the second one, and the
# selftest then fails to import them. The duplicated pure-Python modules are a few MB.
gui_pyz = PYZ(gui.pure)  # noqa: F821
selftest_pyz = PYZ(selftest.pure)  # noqa: F821

gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui.scripts,
    [],
    exclude_binaries=True,
    name="OpenLabAutomation",
    console=False,
    icon=str(icon) if sys.platform == "win32" and icon.is_file() else None,
    upx=False,
)
selftest_exe = EXE(  # noqa: F821
    selftest_pyz,
    selftest.scripts,
    [],
    exclude_binaries=True,
    name="ola-selftest",
    console=True,
    upx=False,
)

COLLECT(  # noqa: F821
    gui_exe,
    gui.binaries,
    gui.datas,
    selftest_exe,
    selftest.binaries,
    selftest.datas,
    name="OpenLabAutomation",
    upx=False,
)
