# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Common Development Commands

| Task | Command | Notes |
|------|---------|-------|
| **Install Python dependencies** | `pip install -r requirements.txt` | Installs runtime and optional dev packages (pytest, black, flake8, sphinx). |
| **Get the instrument library** | `git submodule update --init` | `Instruments_LIB` is a git submodule; without it no instrument is available. |
| **Run the application** | `python frontend/launcher.py` | Launches the PyQt6 GUI with the correct `PYTHONPATH`. |
| **Run the GUI module directly** | `python -m frontend.main` | Useful for debugging import paths. |
| **Run the full test suite** | `pytest` | Discovers the tests under `tests/` and the top‑level `test_*.py` files. |
| **Run a single test file** | `pytest path/to/test_file.py` | Replace `path/to/test_file.py` with the file you need. |
| **Run a single test function** | `pytest path/to/test_file.py::test_name` | Use the `::` syntax to target a specific test. |
| **Lint the code** | `flake8 .` | Checks PEP‑8 compliance across the repository. |
| **Auto‑format the code** | `black .` | Reformats all Python files in place. |
| **Generate documentation** | `sphinx-build -b html docs docs/_build/html` | Assumes a `docs/` directory with a `conf.py`. |
| **Clean build artefacts** | `git clean -fdx` | Removes compiled Python files, `__pycache__` and the build output of `native/`. |
| **Quick launch (dev shortcut)** | `! python frontend/launcher.py` | Use the `!` prefix in Claude Code to run the command directly from the chat. |

> **Tip** – Most CI pipelines run the commands above in this order: install → lint → test (the Rust module in `native/` has its own job).

---

## High‑Level Architecture

```
+-------------------+        +-------------------+        +----------------------------+
|   Frontend (Python)  | <---> |   Core Library (Python) | <---> |   Engine (ola/, native/)   |
+-------------------+        +-------------------+        +----------------------------+
```

* **Frontend** (`frontend/`) – PyQt6 GUI. Entry points are `frontend/launcher.py` and `frontend/main.py`. UI code lives under `frontend/ui/`; each dialog/window occupies its own file and contains only layout and signal wiring.
* **Core Library** (`frontend/core/`) – Business logic, validation, error handling, and utilities. Key modules:
  * `DatabaseManager.py / ProjectDatabaseManager.py` – Handles project JSON, `.inst`, `.eff`, `.was` files.
  * `LoadInstruments.py` – Reads `Instruments_LIB/instruments_lib.json` and provides lookup helpers.
  * `validator.py` – Central validation functions; raises `ValidationError` on failure.
  * `errorhandler.py` – Standardised `[RESOURCE‑XXX]` error‑code system and UI presentation.
  * `tools.py` – Stateless helpers (file I/O, CSV export, date formatting, etc.).
  * `Translator.py` – Internationalisation; translation files live in `frontend/lang/`.
  * `logger.py` – Structured JSON logging used throughout the app.
* **Engine** (`ola/`, `native/`) – Qt-free transport, step executor, call planner, measurement runner and instrument library loader, with tests in `tests/`. See the section *Engine (`ola/` and `native/`)* of `README.md`; do not duplicate that description here.

### Data Flow (simplified)

1. **User interacts** with a dialog → emits a Qt signal.
2. **UI layer** calls a validation routine from `core/validator.py`.
3. On success, **core/tools.py** writes configuration files or triggers a measurement.
4. For real‑time actions the code calls the **engine** (`ola/`: `ola.transport`, the step executor and the call planner), which sends the instrument's commands.
5. Responses are logged via **core/logger.py** and shown in the UI.

### Error‑Handling Strategy

All exceptions are wrapped in custom types defined in `core/errorhandler.py`. Each error includes a standardized code (`[RESOURCE‑XXX]`) that is displayed to the user and recorded in the log with a full stack trace. UI modules should call `errorhandler.handle_error(exc, user_message)` instead of ad‑hoc try/except blocks.

### Internationalisation

Strings are stored in `frontend/lang/<locale>.json`. UI code retrieves them via `Translator.translate(key)`. When adding a new key, ensure it exists in every locale file.

---

## Project‑Specific Guidance

* **Instrument library** – The JSON file `Instruments_LIB/instruments_lib.json` drives the three‑level selector (type → series → model). Adding support for a new instrument means extending this JSON; an instrument without text commands needs a driver in `ola/drivers/` (see `docs/instrument-calls.md`).
* **Project files** – `.inst` (instrument config), `.eff` (efficiency sweep), `.was` (oscilloscope settings), and generic `.json` metadata are all managed by the `ProjectDatabaseManager`. Keep their schemas in sync with the UI editors.
* **Pulse Generator Tool** – Located in `frontend/ui/PulseGeneratorDialog.py`. It validates user parameters against the instrument’s capabilities and visualises the waveform with matplotlib. No manual SCPI commands should be constructed here; rely on the library‑defined commands.
* **Error‑Code Reference** – See `ERROR_CODES.md` for the complete list of `[RESOURCE‑XXX]` codes. When adding new error types, follow the same prefix convention.
* **Copilot / Claude Code Style Rules** – The file `.github/copilot-instructions.md` encodes the same separation‑of‑concerns rules already reflected in this CLAUDE.md. Claude Code should respect those guidelines when generating new code.

---

## Packaging and releases

Installable packages (Windows installer + zip; Linux `.deb`, `.rpm`, tar.gz; Arch `PKGBUILD`) are
built by `.github/workflows/package.yml`: the pre-release `nightly` at every commit on `main`, a
fixed release for every tag `vX.Y.Z`. Recipes in `packaging/` (start from `packaging/README.md`),
steps in `scripts/build_package.py`.

* **Placeholder icon** – `frontend/assets/icons/icona.png` is a copy of `oscilloscope.png`; it is the
  single place for the real icon, used by the Windows exe and the Linux menu entry.
* **After a release, bump the version** in `pyproject.toml`, `frontend/appinfo.json` and `pkgver` in
  `packaging/arch/PKGBUILD` (all three must agree); otherwise nightly builds sort older than the release.
* A new data folder read at run time must also be added to `packaging/pyinstaller/ola.spec`, at the same
  relative path it has in the repository.
* Instrument library in the packages: nightly takes the newest commit of `Instruments_LIB` main; alpha, beta, rc and final
  take its latest published release (see `packaging/README.md`). Publish the library release before tagging the program.
* Repository URL is `mede-erik/Open-Lab-Automation` for now (it may move to the Open Lab Instruments
  organization). The Windows installer is English only and not signed yet.

---

## Frequently Used Shortcuts for Claude Code

* **Run tests** – `! pytest` or `! pytest path/to/test_file.py`.
* **Lint** – `! flake8 .`.
* **Launch app** – `! python frontend/launcher.py`.
* **Open a file in VS Code** – `! code path/to/file.py` (if VS Code is installed).

---

*This CLAUDE.md is intended for Claude Code agents to quickly understand how to build, test, and run the Open Lab Automation suite, and to follow the project's architectural conventions.*