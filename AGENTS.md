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
| Lint | `flake8 .` | |
| Format | `black .` | |
| Test | `pytest` | See **Testing** section. |

Order when it matters: `black . && flake8 . && python scripts/check_translations.py && pytest`

---

## Gotchas

- **`.gitignore` used to exclude `*test*.py`.** Fixed — test files are now tracked. Only `*_old.py`, `*_debug.py`, `*.backup`, `*.bak` and `check_*.py` remain excluded.
- **CI exists:** `.github/workflows/ci.yml` runs on every push and pull request (lint → i18n check → build C → full `pytest` suite incl. library integrity and GUI smoke tests → native Rust transport → PostgreSQL). See `docs/CI.md`.
- **I18n validation:** `python scripts/check_translations.py` — run before committing new translation keys.
- **`models.py` is deprecated.** Use `ProjectDatabaseManager` instead.
- **`DatabaseManager.py` (capital) is deprecated.** Use `ProjectDatabaseManager` instead.

---

## Architecture

```
Remote panel (PyQt6 UI + pyvisa) ──→ LXI/USB/GPIB instruments
                                          |
Measurements (engine `ola/`) ──→ ola.transport (Rust or Python) / pyvisa ──→ LXI instruments (port 5025), serial, VISA
```

| Layer | Location | Role |
|-------|----------|------|
| Entry points | `frontend/launcher.py`, `frontend/main.py` | App bootstrap |
| UI dialogs | `frontend/ui/*.py` | One file per window/dialog. Layout & signal wiring only — **no business logic**. |
| Core library | `frontend/core/*.py` | Validation, error handling, DB/project I/O, i18n, logging |
| Engine | `ola/`, `native/` | Qt-free transport, steps, call planner, measurement runner. See the section *Engine (`ola/` and `native/`)* of `README.md`. |
| Instrument lib | `Instruments_LIB/instruments_lib.json` | JSON-driven 3-level selector (type → series → model) |
| Translations | `frontend/lang/*.json` | One file per locale. Accessed via `Translator.translate(key)`. |

### Instrument I/O split

| Context | Stack |
|---------|-------|
| Remote control panel | Python → pyvisa → VISA backend → instrument |
| Measurements | Engine (`ola/`) in a worker thread → `ola.transport` (native Rust `ola_native`, or pure Python) for raw sockets and serial, pyvisa for VISA addresses → instrument |

The former C backend (raw TCP, LXI only) was removed in November 2026: the transport of `ola/` replaces it and also covers serial and VISA.

### Rules

- **Error handling**: Never raw `try/except` + `QMessageBox`. Call `errorhandler.handle_error(exc, user_message)` or raise a custom error with an `[RESOURCE-XXX]` code. See `ERROR_CODES.md`.
- **I18n**: Every new string used in the UI must have a key in **all** locale files (`it.json`, `en.json`, `fr.json`, `es.json`, `de.json`).
- **No SCPI guessing**: `PulseGeneratorDialog.py` (and similar) must only use instrument library-defined commands, not string-concatenated SCPI.
- **One file per dialog**: Each `QDialog`/`QMainWindow` in its own file under `frontend/ui/`.
- **No `time.sleep()` in GUI thread**: Use `QTimer.singleShot()` for delayed operations.
- **No bare `except:`**: Always specify the exception type. Log the error.

---

## Testing

Tests live in `tests/` (engine, whole-library integrity, `frontend/core`, scripts,
GUI smoke tests); `test_basic_import.py` and `test_instrument_library.py` at the repo root cover
the core imports and the instrument library (`git submodule update --init` is needed for the
library tests). What each file covers and how CI runs them: `docs/CI.md`.

```bash
QT_QPA_PLATFORM=offscreen pytest   # everything (tests/ + test_*.py at root)
pytest -m "not gui"                # without the Qt widgets
pytest tests/test_library_integrity.py   # every call of every library model
```

When you change the library usage, a dialog or an error code, run the suite: the integrity,
GUI smoke and error-code tests are meant to catch exactly those changes.

---

## Extending instruments

1. Add entry to `Instruments_LIB/instruments_lib.json`.
2. If new SCPI commands are needed, add them to the instrument's `common_scpi_commands` or model-specific `scpi_commands`.
3. If a new protocol is needed, add a transport or a driver in `ola/` (see `docs/instrument-calls.md` and `docs/engine.md`).

---

## Packaging and releases

Packages are built by `.github/workflows/package.yml` and published as GitHub releases: the
pre-release `nightly` at every commit on `main`, a fixed release for every tag `vX.Y.Z`. The
recipes are in `packaging/` (read `packaging/README.md` first), the steps in
`scripts/build_package.py`. Windows: installer + zip; Linux: `.deb`, `.rpm`, tar.gz; Arch:
`packaging/arch/PKGBUILD`.

- **Placeholder icon.** `frontend/assets/icons/icona.png` is a copy of `oscilloscope.png` and is the
  single place for the program icon (Windows exe, Linux menu entry). Replace that file when the
  real icon exists; see `packaging/README.md` for the sizes.
- **Version in three places:** `pyproject.toml`, `frontend/appinfo.json` and `pkgver` in
  `packaging/arch/PKGBUILD` (`tests/test_packaging.py` checks they agree).
- **After a release, bump the version** in those three places to the next one: otherwise the nightly
  builds (`X.Y.Z-nightly...`) sort older than the release `X.Y.Z`.
- A data folder the program reads at run time (next to `frontend/`, `ola/`, `Instruments_LIB/`) must
  also be listed in `packaging/pyinstaller/ola.spec`, at the same relative path.
- The repository URL (`frontend/appinfo.json`, `packaging/`) is `mede-erik/Open-Lab-Automation`;
  update it if the repository moves to the Open Lab Instruments organization.
- Instrument library in the packages: nightly takes the newest commit of the library's `main`; alpha, beta, rc and final
  take the latest published release of `Instruments_LIB` (see `packaging/README.md`, "Which instrument library goes in a package").
  Publish the library release before tagging the program.
- Open points: the Windows installer is not signed and is English only.

---

## Recent fixes (July 2026)

- `requirements.txt`: PyQt5 → PyQt6
- `.gitignore`: fixed to allow tracking test files
- Matplotlib backend: `backend_qt5agg` → `backend_qtagg`
- Import style: relative → absolute in `InstFileDialog.py`
- Bare `except:` → specific exception types (RemoteControlTab, DataloggerSlotConfigDialog)
- `time.sleep()` in GUI thread → `QTimer.singleShot()` (toggle_output)
- `print()` → `logging.getLogger()` in core modules (errorhandler, LoadInstruments, ProjectDatabaseManager)
- C backend (`backend/`, `frontend/core/c_backend.py`): added in July 2026, removed in November 2026 (replaced by `ola/transport.py` and `native/`)
- New: `scripts/check_translations.py` — validates all locale files against `en.json`
- New: `.github/workflows/ci.yml` — lint → i18n → tests
- New: `pyproject.toml` — project metadata, tool config
- Deprecated: `models.py` — use `ProjectDatabaseManager` instead
- Deprecated: `DatabaseManager.py` (capital) — use `ProjectDatabaseManager` instead
- Fixed: `database.py` no longer falsely deprecated (still used by config dialog)
- Fixed: `database_config.py` hardcoded test password replaced with `os.urandom`
- Fixed: `frontend/core/__init__.py` — re-enabled `DatabaseManager` export, removed stale comments
