# AGENTS.md — Open Lab Automation

> Compact guidance for code assistants working in this repository. The executable source
> (code, `pyproject.toml`, `.github/workflows/ci.yml`) is the authority: if this file and the
> code disagree, trust the code and fix this file.

---

## Quick reference

| Action | Command | Note |
|--------|---------|------|
| Get the instrument library | `git submodule update --init` | `Instruments_LIB/` is a submodule; library tests need it. |
| Install dependencies | `pip install -r requirements.txt` | Runtime and dev packages. |
| Run the app | `python frontend/launcher.py` | Sets `PYTHONPATH`. |
| Run the app directly | `python -m frontend.main` | Useful to debug import paths. |
| Run a module window alone | `python -m frontend.ui.ProjectWindow [project.json]` | Also `RunWindow`, `EfficiencyEditorDialog`, `CompareDialog`. |
| Terminal instrument shell | `python scripts/instrument_shell.py [--sim]` | `--sim` needs no hardware. |
| Dry run of a call | `python scripts/dry_run_call.py --model MODEL --call NAME` | Shows the commands; sends nothing. |
| Optional Rust transport | `cd native && maturin build --release` | Without it the pure-Python transport is used. |
| Rust tests | `cd native && cargo test` | |
| Lint (new code) | `flake8 ola tests scripts` | Settings in `.flake8`. |
| Translations | `python scripts/check_translations.py` | Run before committing new keys. |
| Tests | `QT_QPA_PLATFORM=offscreen pytest` | See **Testing**. |

CI order (`.github/workflows/ci.yml`): lint and translations → build the legacy C backend → `pytest` → native Rust transport → PostgreSQL tests. Details: `docs/CI.md`.

---

## Architecture

| Layer | Location | Role |
|-------|----------|------|
| GUI | `frontend/` (`launcher.py`, `main.py`, `ui/`, `lang/`) | PyQt6. One file per window or dialog. |
| Core (Qt-side helpers) | `frontend/core/` | Validation, error handling, project database I/O, i18n, logging. |
| **Engine** | `ola/`, `native/` | Qt-free: transport, steps, call planner, instrument handles, measurement runner, measurement modules. **This is where new behaviour goes.** |
| Instrument library | `Instruments_LIB/` (submodule) | `instruments_lib.json` + `schema/`: the logical calls and how each model implements them. Data only. |
| Legacy C backend | `backend/` | Raw TCP via ctypes. Not used by the GUI or `ola/`. Scheduled for removal: do not extend. |
| Tests | `tests/`, `test_*.py` at the root | See **Testing**. |

The engine's own description (layers, transports, the measurement runner, the project format) is in
the **Engine** section of `README.md` and in `docs/engine.md`. Do not duplicate it here.

### How an instrument is driven

```
measurement module (ola/modules/<name>/)   what to measure: setup / run / teardown
    handle.call("set_voltage", value=5)    logical calls, never raw SCPI in the module
        -> ola/call_planner.py + Instruments_LIB   plan of steps for this model
        -> ola/instrument.py                       write / query / read / delay, one lock per instrument
        -> ola/transport.py | _visa.py | prologix.py | serial (native/)
```

- Measurement modules are found from `module.json` (`ola/registry.py`). Finding a module never runs its code; a non-built-in module needs explicit permission (`allow_user_code`).
- Modules reach instruments only through `ctx.instrument(role).call(name, **args)`.
- Simulated instruments (`ola/sim*.py`, `ola/demo_lab.py`) let every measurement run without hardware.

---

## Rules

- **Logical calls only.** Do not build SCPI strings in the GUI or in modules. Use the library's calls (`PulseGeneratorDialog.py` included).
- **Error codes.** Every error is an exception with a stable code (`TRN-xxx`, `CALL-xxx`, or the code of its resource; see `ERROR_CODES.md`). Engine code raises `ola/errors.py` / `ola/call_errors.py` types. In the GUI, show errors through `frontend/core/errorhandler.py` (`handle_error(exc, user_message)`) rather than ad-hoc `try/except` with message boxes.
- **i18n.** Every new user-visible string needs a key in all five locale files (`it`, `en`, `fr`, `es`, `de`) under `frontend/lang/`; the strings of the project and run windows are in `frontend/lang/modules/<area>/<lang>.json`. `check_translations.py` enforces it.
- **No bare `except:`.** Name the exception type and log it (`frontend/core/logger.py`).
- **No `time.sleep()` in the GUI thread.** Use `QTimer.singleShot()`.
- **One file per dialog** under `frontend/ui/`, layout and signal wiring only. Business logic goes to `ola/` (or `frontend/core/` for database and project I/O).
- **Documentation travels with code.** A new module needs a guide in `docs/` and a row in the README Engine table: `tests/test_docs.py` fails otherwise.
- **Do not extend `backend/`.** Legacy; it will be removed once nothing needs it.
- **Deprecated, do not use:** `frontend/core/models.py`, `frontend/core/DatabaseManager.py`. Use `ProjectDatabaseManager`.

---

## Instrument library

- Adding an instrument: add the model to `Instruments_LIB/instruments_lib.json` (new models are `"experimental": true` until tried on hardware), using the call names of `Instruments_LIB/schema/` and `docs/COMMANDS.md`.
- New logical calls for a category belong in `Instruments_LIB/schema/`, not in code.
- The library is its own repository (`mede-erik/Instruments_LIB`). Changes there are committed and merged there first, then the submodule pointer is updated here.
- Check the library with `python -m pytest tests/test_library_integrity.py` and, in the library repo, `Tests/check_conformance.py`.

---

## Testing

Tests live in `tests/` (engine, whole-library integrity, `frontend/core`, scripts, GUI smoke tests) and in `test_basic_import.py` / `test_instrument_library.py` at the root.

```bash
QT_QPA_PLATFORM=offscreen pytest      # everything
pytest -m "not gui"                    # without Qt widgets
pytest tests/test_library_integrity.py # every call of every library model (needs the submodule)
pytest tests/test_docs.py              # docs stay in sync with the code
```

What to run after a change:

- a library usage, a dialog or an error code: the full suite (integrity, GUI smoke and error-code tests catch exactly these);
- documentation: `tests/test_docs.py` (docstrings, README engine table, error codes, relative links, the example in `docs/measurement-modules.md`).

---

## Gotchas

- `Instruments_LIB/` is empty until `git submodule update --init`. Tests that read the library and the link from `docs/ripple.md` into it fail without it.
- `.gitignore` excludes only `*_old.py`, `*_debug.py`, `*.backup`, `*.bak`, `check_*.py`; test files are tracked.
- The GPIB adapter stack (`ola/gpib_*.py`, `ola/prologix.py`) needs the driver of the adapter; `gpib_linux.py` runs its set-up through `pkexec`. Tests use stand-ins.
- Use `QT_QPA_PLATFORM=offscreen` for any test that creates a window.
