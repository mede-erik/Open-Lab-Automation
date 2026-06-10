# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

| Task | Command | Notes |
|------|---------|-------|
| **Install Python dependencies** | `pip install -r requirements.txt` | Installs all runtime and optional dev dependencies (pytest, black, flake8, sphinx). |
| **Compile the C backend** | `gcc backend/backend.c -o backend/backend.exe` | Required for direct instrument communication. Skip if you only run the GUI in a simulated environment. |
| **Run the application** | `python frontend/launcher.py` | Launches the PyQt6 GUI with the correct `PYTHONPATH` set. |
| **Run the GUI module directly** | `python -m frontend.main` | Equivalent to the launcher; useful for debugging import paths. |
| **Run the full test suite** | `pytest` | Discovers tests under `frontend/tests` and the top‑level test files. |
| **Run a single test file** | `pytest test_database_menu.py` | Replace the filename with any other test module. |
| **Run a single test function** | `pytest test_database_menu.py::test_save_project` | Use the `::` syntax to target a specific test function. |
| **Lint the code** | `flake8 .` | Checks for PEP8 violations across the repository. |
| **Auto‑format the code** | `black .` | Reformats all Python files in place. |
| **Generate documentation** | `sphinx-build -b html docs docs/_build/html` | Assumes a `docs/` directory with a Sphinx `conf.py`. |
| **Clean build artifacts** | `git clean -fdx` | Removes compiled Python files, `__pycache__`, and the compiled C binary. |

> **Tip**: Most CI pipelines in this project run the commands above in the order: install deps → compile backend → lint → test.

## High‑Level Architecture

```
+-------------------+        +-------------------+        +-------------------+
|   Frontend (Python)  | <---> |   Core Library (Python) | <---> |   Backend (C)   |
+-------------------+        +-------------------+        +-------------------+
```

* **Frontend** (`frontend/`)
  * Entry points: `frontend/launcher.py` and `frontend/main.py`.
  * Built with **PyQt6** – UI code lives under `frontend/ui/`.
  * Each window/dialog is isolated in its own module (e.g., `ui/main_window.py`, `ui/InstrumentConfigDialog.py`).
  * UI modules contain only widget layout, signal connections, and UI‑specific callbacks. No business logic is embedded here.
* **Core Library** (`frontend/core/`)
  * **`DatabaseManager.py` / `ProjectDatabaseManager.py`** – Handles project JSON, `.inst`, `.eff`, `.was` files and persists configuration.
  * **`LoadInstruments.py`** – Loads the instrument definitions from `Instruments_LIB/instruments_lib.json` and provides lookup utilities.
  * **`validator.py`** – Central validation functions; used by UI dialogs to ensure user input conforms to expected formats.
  * **`errorhandler.py`** – Standardized error‑code system (`[RESOURCE-XXX]`) and UI error presentation.
  * **`tools.py`** – General‑purpose utilities (file I/O, CSV export, date formatting) that are deliberately stateless.
  * **`Translator.py`** – Internationalisation layer; translation files live in `frontend/lang/*.json`.
  * **`logger.py`** – Structured logging (JSON) used across the app for debugging and audit trails.
* **Backend** (`backend/backend.c`)
  * Provides low‑latency, direct instrument communication via VISA, USB, LAN, GPIB, or serial.
  * Exposes a simple C API that the Python core calls through `ctypes`/`cffi` wrappers (see `frontend/core/tools.py`).
  * Designed to be extensible: add new protocol handlers by implementing the C interface and rebuilding the binary.

### Data Flow Overview
1. **User Interaction** – UI dialog emits a signal (e.g., *Save* button).
2. **UI Layer** – Calls a validation function from `core/validator.py`.
3. **Core Layer** – If valid, `core/tools.py` writes the JSON configuration or triggers a measurement.
4. **Backend Call** – For real‑time instrument actions, the core uses the C backend functions to send SCPI commands.
5. **Result Handling** – Responses are logged via `core/logger.py` and displayed in the UI.

### Error‑Handling Strategy
* All exceptions are wrapped in custom types defined in `core/errorhandler.py`.
* Each error carries a standardized code (`[FILE-001]`, `[DL-003]`, …) that is shown to the user and logged with a stack trace.
* UI modules invoke `errorhandler.handle_error(exc, user_message)` rather than raw `try/except` blocks.

### Internationalisation
* Translation strings are loaded from `frontend/lang/<locale>.json`.
* UI modules retrieve strings via `Translator.translate(key)`; new keys should be added to every locale file.

## Important Project‑Specific Files
* **`ERROR_CODES.md`** – Full reference of all `[RESOURCE‑XXX]` codes used throughout the app.
* **`Instruments_LIB/instruments_lib.json`** – Master catalog of supported instruments; the UI builds its three‑level selector (type → series → model) from this file.
* **`.github/copilot-instructions.md`** – Provides Copilot style guidelines; Claude Code should respect the same separation‑of‑concerns rules when generating new code.
* **`README.md`** – High‑level feature description and quick‑start instructions (already mirrored above).

## Development Conventions (derived from Copilot instructions)
* **One file per UI component** – All `ui/*.py` files contain a single `QMainWindow`/`QDialog` subclass.
* **No business logic in UI** – Keep calculations, DB access, and protocol handling in `frontend/core/*`.
* **Signal wiring** – Connect PyQt signals to methods of the same class or to functions imported from core modules.
* **Utility functions** – Place generic helpers in `core/tools.py`; keep them stateless.
* **Validation** – All user‑entered data passes through `core/validator.py`; raise `ValidationError` on failure.
* **Error handling** – Use `core/errorhandler.handle_error` for any UI‑visible error.
* **Translation** – Access UI strings via `Translator.translate`; add missing keys across all language files.

## Frequently Used Shortcuts for Claude Code
* **Run tests** – `! pytest` or `! pytest path/to/test_file.py`.
* **Lint** – `! flake8 .`.
* **Build backend** – `! gcc backend/backend.c -o backend/backend.exe`.
* **Launch app** – `! python frontend/launcher.py`.
* **Open a file** – `! code path/to/file.py` (if VS Code is installed).

---

*This CLAUDE.md is intended for Claude Code agents to quickly understand how to build, test, and run the Open Lab Automation suite, and to follow the project's architectural conventions.*