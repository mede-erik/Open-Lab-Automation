# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Common Development Commands

| Task | Command | Notes |
|------|---------|-------|
| **Install Python dependencies** | `pip install -r requirements.txt` | Installs runtime and optional dev packages (pytest, black, flake8, sphinx). |
| **Compile the C backend** | `gcc backend/backend.c -o backend/backend.exe` | Required for direct instrument communication; skip for GUI‑only simulation. |
| **Run the application** | `python frontend/launcher.py` | Launches the PyQt6 GUI with the correct `PYTHONPATH`. |
| **Run the GUI module directly** | `python -m frontend.main` | Useful for debugging import paths. |
| **Run the full test suite** | `pytest` | Discovers tests under `frontend/tests` and top‑level test files. |
| **Run a single test file** | `pytest path/to/test_file.py` | Replace `path/to/test_file.py` with the file you need. |
| **Run a single test function** | `pytest path/to/test_file.py::test_name` | Use the `::` syntax to target a specific test. |
| **Lint the code** | `flake8 .` | Checks PEP‑8 compliance across the repository. |
| **Auto‑format the code** | `black .` | Reformats all Python files in place. |
| **Generate documentation** | `sphinx-build -b html docs docs/_build/html` | Assumes a `docs/` directory with a `conf.py`. |
| **Clean build artefacts** | `git clean -fdx` | Removes compiled Python files, `__pycache__`, and the compiled C binary. |
| **Quick launch (dev shortcut)** | `! python frontend/launcher.py` | Use the `!` prefix in Claude Code to run the command directly from the chat. |

> **Tip** – Most CI pipelines run the commands above in this order: install → compile → lint → test.

---

## High‑Level Architecture

```
+-------------------+        +-------------------+        +-------------------+
|   Frontend (Python)  | <---> |   Core Library (Python) | <---> |   Backend (C)   |
+-------------------+        +-------------------+        +-------------------+
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
* **Backend** (`backend/backend.c`) – Low‑latency C layer exposing a simple API (via `ctypes`/`cffi` wrappers in `core/tools.py`) for VISA, USB, LAN, GPIB, or serial instrument communication. Adding a new protocol means implementing the C interface and rebuilding the binary.

### Data Flow (simplified)

1. **User interacts** with a dialog → emits a Qt signal.
2. **UI layer** calls a validation routine from `core/validator.py`.
3. On success, **core/tools.py** writes configuration files or triggers a measurement.
4. For real‑time actions the core calls the **C backend**, which sends SCPI commands to the instrument.
5. Responses are logged via **core/logger.py** and shown in the UI.

### Error‑Handling Strategy

All exceptions are wrapped in custom types defined in `core/errorhandler.py`. Each error includes a standardized code (`[RESOURCE‑XXX]`) that is displayed to the user and recorded in the log with a full stack trace. UI modules should call `errorhandler.handle_error(exc, user_message)` instead of ad‑hoc try/except blocks.

### Internationalisation

Strings are stored in `frontend/lang/<locale>.json`. UI code retrieves them via `Translator.translate(key)`. When adding a new key, ensure it exists in every locale file.

---

## Project‑Specific Guidance

* **Instrument library** – The JSON file `Instruments_LIB/instruments_lib.json` drives the three‑level selector (type → series → model). Adding support for a new instrument means extending this JSON and, if necessary, providing a C‑level command implementation.
* **Project files** – `.inst` (instrument config), `.eff` (efficiency sweep), `.was` (oscilloscope settings), and generic `.json` metadata are all managed by the `ProjectDatabaseManager`. Keep their schemas in sync with the UI editors.
* **Pulse Generator Tool** – Located in `frontend/ui/PulseGeneratorDialog.py`. It validates user parameters against the instrument’s capabilities and visualises the waveform with matplotlib. No manual SCPI commands should be constructed here; rely on the library‑defined commands.
* **Error‑Code Reference** – See `ERROR_CODES.md` for the complete list of `[RESOURCE‑XXX]` codes. When adding new error types, follow the same prefix convention.
* **Copilot / Claude Code Style Rules** – The file `.github/copilot-instructions.md` encodes the same separation‑of‑concerns rules already reflected in this CLAUDE.md. Claude Code should respect those guidelines when generating new code.

---

## Frequently Used Shortcuts for Claude Code

* **Run tests** – `! pytest` or `! pytest path/to/test_file.py`.
* **Lint** – `! flake8 .`.
* **Build backend** – `! gcc backend/backend.c -o backend/backend.exe`.
* **Launch app** – `! python frontend/launcher.py`.
* **Open a file in VS Code** – `! code path/to/file.py` (if VS Code is installed).

---

*This CLAUDE.md is intended for Claude Code agents to quickly understand how to build, test, and run the Open Lab Automation suite, and to follow the project's architectural conventions.*