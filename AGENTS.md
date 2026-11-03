# AGENTS.md — Open Lab Automation

> Compact guidance for OpenCode/Claude Code sessions. If the repo says one thing and
> this file says another, trust the executable source (code + config + CI scripts).

---

## Quick reference

| Action | Command | Note |
|--------|---------|------|
| Install deps | `pip install -r requirements.txt` | |
| Run app | `python frontend/launcher.py` | Preferred — sets `PYTHONPATH`. |
| Run directly | `python -m frontend.main` | Works from repo root. |
| Compile C backend | `backend/build.sh` | Produces shared library (`.so`/`.dll`). |
| Compile C (manual) | `gcc -shared -fPIC backend/*.c -Ibackend -o backend/libbackend.so -lm` | Linux. Add `-lws2_32` on Windows/MinGW. |
| Lint | `flake8 .` | |
| Format | `black .` | |
| Test | `pytest` | See **Testing** section. |

Order when it matters: `black . && flake8 . && python scripts/check_translations.py && pytest`

---

## Gotchas

- **`.gitignore` used to exclude `*test*.py`.** Fixed — test files are now tracked. Only `*_old.py`, `*_debug.py`, `*.backup`, `*.bak` and `check_*.py` remain excluded.
- **CI exists:** `.github/workflows/ci.yml` (lint → i18n check → build C → test import → test backend load).
- **I18n validation:** `python scripts/check_translations.py` — run before committing new translation keys.
- **`models.py` is deprecated.** Use `ProjectDatabaseManager` instead.
- **`DatabaseManager.py` (capital) is deprecated.** Use `ProjectDatabaseManager` instead.

---

## Architecture

```
Remote panel (PyQt6 UI + pyvisa) ──→ LXI/USB/GPIB instruments
                                          |
Automatic sweep (Python core) ──→ C backend (TCP raw) ──→ LXI instruments (port 5025)
```

| Layer | Location | Role |
|-------|----------|------|
| Entry points | `frontend/launcher.py`, `frontend/main.py` | App bootstrap |
| UI dialogs | `frontend/ui/*.py` | One file per window/dialog. Layout & signal wiring only — **no business logic**. |
| Core library | `frontend/core/*.py` | Validation, error handling, DB/project I/O, i18n, logging |
| Engine | `ola/`, `native/` | Qt-free transport, steps, call planner, measurement runner. See the section *Engine (`ola/` and `native/`)* of `README.md`. |
| C backend (legacy) | `backend/*.c`, `backend/*.h` | Shared library via ctypes, raw TCP for LXI instruments. Not used by the GUI; to be retired, do not extend. |
| C Python wrapper | `frontend/core/c_backend.py` | ctypes wrapper: load, connect, send/receive SCPI, sweep_run |
| Instrument lib | `Instruments_LIB/instruments_lib.json` | JSON-driven 3-level selector (type → series → model) |
| Translations | `frontend/lang/*.json` | One file per locale. Accessed via `Translator.translate(key)`. |

### Instrument I/O split

| Context | Stack |
|---------|-------|
| Remote control panel | Python → pyvisa → VISA backend → instrument |
| Automatic sweep | Python worker thread → `CBackend` (ctypes) → C raw TCP → LXI instrument (port 5025) |

The C backend handles TCP directly for **LXI instruments only**. USB-TMC/GPIB instruments still use pyvisa via the remote panel.

### Rules

- **Error handling**: Never raw `try/except` + `QMessageBox`. Call `errorhandler.handle_error(exc, user_message)` or raise a custom error with an `[RESOURCE-XXX]` code. See `ERROR_CODES.md`.
- **I18n**: Every new string used in the UI must have a key in **all** locale files (`it.json`, `en.json`, `fr.json`, `es.json`, `de.json`).
- **No SCPI guessing**: `PulseGeneratorDialog.py` (and similar) must only use instrument library-defined commands, not string-concatenated SCPI.
- **One file per dialog**: Each `QDialog`/`QMainWindow` in its own file under `frontend/ui/`.
- **No `time.sleep()` in GUI thread**: Use `QTimer.singleShot()` for delayed operations.
- **No bare `except:`**: Always specify the exception type. Log the error.

---

## C Backend API

```
be_init()           → init sockets (WSAStartup on Windows)
be_connect(host,port,timeout_ms) → connect TCP → return handle
be_send(handle, "SCPI command")
be_receive(handle)  → read response
be_receive_float()  → read response as double
be_receive_int()    → read response as int
be_sweep_run(cfg, voltages, currents, progress_cb) → blocking sweep loop
be_cleanup()        → close all connections
```

See `backend/backend.h` for the full API and `frontend/core/c_backend.py` for the Python wrapper.

---

## Testing

Unit tests live in `tests/` (Qt-free code under `ola/`); `test_basic_import.py` and
`test_instrument_library.py` at the repo root cover the core imports and the instrument library
(`git submodule update --init` is needed for the latter).

```bash
pytest                          # everything (tests/ + test_*.py at root)
pytest tests -q                 # Qt-free unit tests only
pytest test_basic_import.py     # focused
```

---

## Extending instruments

1. Add entry to `Instruments_LIB/instruments_lib.json`.
2. If new SCPI commands are needed, add them to the instrument's `common_scpi_commands` or model-specific `scpi_commands`.
3. If a new protocol is needed (e.g., serial), implement C-level interface in `backend/`.
4. Rebuild: `cd backend && ./build.sh`.

---

## Recent fixes (July 2026)

- `requirements.txt`: PyQt5 → PyQt6
- `.gitignore`: fixed to allow tracking test files
- Matplotlib backend: `backend_qt5agg` → `backend_qtagg`
- Import style: relative → absolute in `InstFileDialog.py`
- Bare `except:` → specific exception types (RemoteControlTab, DataloggerSlotConfigDialog)
- `time.sleep()` in GUI thread → `QTimer.singleShot()` (toggle_output)
- `print()` → `logging.getLogger()` in core modules (errorhandler, LoadInstruments, ProjectDatabaseManager)
- C backend: rewritten from stub (8-line `main()`) to shared library with TCP socket I/O
- New: `frontend/core/c_backend.py` — ctypes wrapper for the C backend
- New: `scripts/check_translations.py` — validates all locale files against `en.json`
- New: `.github/workflows/ci.yml` — lint → i18n → build C → test import → backend load
- New: `pyproject.toml` — project metadata, tool config
- Deprecated: `models.py` — use `ProjectDatabaseManager` instead
- Deprecated: `DatabaseManager.py` (capital) — use `ProjectDatabaseManager` instead
- Fixed: `database.py` no longer falsely deprecated (still used by config dialog)
- Fixed: `database_config.py` hardcoded test password replaced with `os.urandom`
- Fixed: `frontend/core/__init__.py` — re-enabled `DatabaseManager` export, removed stale comments
