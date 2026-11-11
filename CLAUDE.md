# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Common Development Commands

| Task | Command | Notes |
|------|---------|-------|
| **Get the instrument library** | `git submodule update --init` | `Instruments_LIB` is a git submodule (a separate repository); without it no instrument is available and the library tests fail. |
| **Install Python dependencies** | `pip install -r requirements.txt` | Runtime packages plus `pytest`, `pytest-qt`, `black` and `flake8`. |
| **Run the application** | `python frontend/launcher.py` | Launches the PyQt6 GUI with the correct `PYTHONPATH`. |
| **Run the GUI module directly** | `python -m frontend.main` | Useful for debugging import paths. |
| **Run the full test suite** | `QT_QPA_PLATFORM=offscreen pytest` | Discovers `tests/` and the top-level `test_*.py` files. The Qt windows are built offscreen. |
| **Run the tests without Qt** | `pytest -m "not gui"` | Skips the tests that build widgets. |
| **Run a single test** | `pytest path/to/test_file.py::test_name` | |
| **Check the translations** | `python scripts/check_translations.py` | The five locale files must have the same keys, and every key used in the code must exist. |
| **Lint the new code** | `flake8 ola tests scripts` | Must be clean. |
| **Lint for real errors** | `flake8 --select=E9,F63,F7,F82 .` | Syntax errors and undefined names, whole repository. |
| **Check the copyright headers** | `python scripts/add_copyright_headers.py --check` | Without `--check` it adds the header to the files that lack it. |
| **Native transport (optional)** | `cd native && maturin build --release` | Rust transport; without it `ola` falls back to an equivalent pure-Python one. |
| **Try an instrument without the GUI** | `python scripts/instrument_shell.py --sim` | `scripts/dry_run_call.py` shows the commands of a call without hardware. |

> **Tip** – The CI runs, in this order: translations → lint → tests (see `docs/CI.md`). Run the same before pushing.

---

## High-Level Architecture

```
GUI (frontend/ui, PyQt6)
        |
        v
Core (frontend/core) ──────────────►  Engine (ola/, native/) ──►  Instruments
  validation, errors, i18n, DB         Qt-free: planner, steps, runner,      (VISA, TCP, serial,
                                       transport, measurement modules         GPIB adapters, drivers)
                                                  ▲
                                       Instruments_LIB (submodule): models, call schemas
```

* **Frontend** (`frontend/`) – PyQt6 GUI. Entry points are `frontend/launcher.py` and `frontend/main.py`. UI code lives under `frontend/ui/`; each dialog/window occupies its own file and contains only layout and signal wiring. The main window has the *Remote control* tab and the *Measurements* tab (`ProjectWindow`).
* **Core Library** (`frontend/core/`) – Validation, error handling, translations, logging, PostgreSQL storage. Key modules:
  * `LoadInstruments.py` – Reads `Instruments_LIB/instruments_lib.json` for the GUI (`get_library_path()` gives its location).
  * `validator.py` – Central validation functions; raises `ValidationError` on failure.
  * `errorhandler.py` – Standardised `[RESOURCE-XXX]` error-code system and UI presentation.
  * `tools.py` – Stateless helpers (file I/O, CSV export, network diagnostics).
  * `Translator.py` – Internationalisation: `translator.t(key)`; translation files live in `frontend/lang/`.
  * `ProjectDatabaseManager.py`, `database_config.py` – PostgreSQL storage of the results; the connection settings are saved with an encrypted password.
  * `logger.py` – Structured logging used throughout the app.
* **Engine** (`ola/`, `native/`) – Qt-free: instrument library and call planner, step executor, transport (Rust or pure Python, pyvisa for USB-TMC/GPIB/VXI-11, serial, Prologix GPIB adapters), drivers (Analog Discovery, LiteVNA), measurement runner and the measurement modules in `ola/modules/`. Tests are in `tests/`. The description is in the section *Engine (`ola/` and `native/`)* of `README.md` and in `docs/engine.md`; do not duplicate it here.
* **Instrument library** (`Instruments_LIB/`) – A separate repository used as a git submodule: models, call schemas (`schema/`), test guide (`TESTING.md`). Changes to it are made in that repository, then a pull request here moves the submodule pointer.

### Data Flow (simplified)

1. **User interacts** with a dialog → emits a Qt signal.
2. **UI layer** validates the input with `core/validator.py`.
3. **Remote control panel / measurements** call an instrument by a *logical call* (`handle.call("set_voltage", value=5)`): `ola/call_planner.py` turns it into a plan of steps using the model's entry in the library, `ola/instrument.py` runs the steps under one lock per instrument through the transport, or hands the call to a driver. The software never builds SCPI strings itself.
4. **Measurements** (*Measurements* tab): `ProjectWindow` → `ProjectSession` → `Runner` (a thread: setup, run, always teardown) → the measurement module; instruments come from `ola/connection.py`; results are written while the run is going (`runs/` in the project folder, JSON Lines).
5. Errors carry a `[RESOURCE-XXX]` code, are logged with the stack trace and shown through `core/errorhandler.py`.

### Error-Handling Strategy

Exceptions carry a standardized code (`[RESOURCE-XXX]`) that is displayed to the user and recorded in the log with the stack trace. UI modules call `errorhandler.handle_error(exc, user_message)` instead of ad-hoc try/except plus a message box. Engine errors have their own codes: `TRN-xxx` (transport) and `CALL-xxx` (calls).

### Internationalisation

Strings are stored in `frontend/lang/<locale>.json` (`it`, `en`, `fr`, `es`, `de`) and, for the windows of the measurement modules, in `frontend/lang/modules/<area>/<locale>.json`. UI code retrieves them via `Translator.t(key)`. When adding a key, add it to **every** locale file and run `python scripts/check_translations.py`.

---

## Project-Specific Guidance

* **Instrument library** – `Instruments_LIB/instruments_lib.json` drives the selector (type → series → model); `Instruments_LIB/schema/*.json` define the logical calls of each category. Adding an instrument means adding its entry to the library (see `Instruments_LIB/TESTING.md`), not writing code here, unless it needs a driver (`ola/drivers/`).
* **Project files** – A project (`ola/project.py`, `"format_version": 2`) lists its measurements; each measurement is a file whose extension identifies its type (`.eff` efficiency, `.cbl` cable, `.flt` filter, ...). `.inst` holds the instruments and `.was` the oscilloscope settings. Keep their schemas in sync with the editors and with `docs/`.
* **Measurement modules** – Each is a folder in `ola/modules/` (`module.json`, `measurement.py`, `form.json`, `wiring.json`) with a guide in `docs/`; see `docs/measurement-modules.md`.
* **Pulse Generator Tool** – `frontend/ui/PulseGeneratorDialog.py`. It validates the parameters against the instrument's limits and uses only the commands defined in the library: no SCPI is built by hand.
* **Error-Code Reference** – See `ERROR_CODES.md` for the complete list of `[RESOURCE-XXX]` codes. When adding a new error type, follow the same prefix convention (a test checks that every code used in the source is documented).
* **Copilot / Claude Code Style Rules** – `.github/copilot-instructions.md` encodes the same separation-of-concerns rules as this file; respect them when generating new code.

### Rules for new code

* **English only** for documentation and code comments. The UI languages are the locale files.
* **Copyright header** on every new source file (`.py`, `.c`, `.h`, `.rs`, `.sh`, `.bat`, `.qss`): run `python scripts/add_copyright_headers.py FILE...`. `tests/test_copyright_headers.py` fails otherwise.
* **Tests** for new code; the docs are kept in sync by tests (`tests/test_docs.py`): public items of `ola/` need a docstring, every `ola/` file and module must be in the README engine table, relative links must work.
* **Pull requests** go to `main`. Do not stack a pull request on the branch of another one: when the first is merged the second ends up in the old branch and not in `main`.

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
* Repository URL is `mede-erik/Open-Lab-Automation` for now (it may move to the Open Lab Instruments
  organization). The Windows installer is English only and not signed yet.

---

## Frequently Used Shortcuts for Claude Code

* **Run tests** – `! QT_QPA_PLATFORM=offscreen pytest` or `! pytest path/to/test_file.py`.
* **Lint** – `! flake8 ola tests scripts`.
* **Translations** – `! python scripts/check_translations.py`.
* **Launch app** – `! python frontend/launcher.py`.

---

*This CLAUDE.md is intended for Claude Code agents to quickly understand how to build, test, and run the Open Lab Automation suite, and to follow the project's architectural conventions.*
