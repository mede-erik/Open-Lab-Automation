# AGENTS.md — Open Lab Automation

> Compact guidance for OpenCode/Claude Code sessions. If the repo says one thing and
> this file says another, trust the executable source (code + config + CI scripts).

---

## Quick reference

| Action | Command | Note |
|--------|---------|------|
| Get the library | `git submodule update --init` | `Instruments_LIB` is a separate repository. |
| Install deps | `pip install -r requirements.txt` | |
| Run app | `python frontend/launcher.py` | Preferred — sets `PYTHONPATH`. |
| Run directly | `python -m frontend.main` | Works from repo root. |
| Test | `QT_QPA_PLATFORM=offscreen pytest` | See **Testing** section. |
| Translations | `python scripts/check_translations.py` | Run before committing new translation keys. |
| Lint (new code) | `flake8 ola tests scripts` | Must be clean. |
| Lint (real errors) | `flake8 --select=E9,F63,F7,F82 .` | Whole repository. |
| Copyright header | `python scripts/add_copyright_headers.py [FILE...]` | `--check` only lists the files without it. |
| Try an instrument | `python scripts/instrument_shell.py [--sim]` | `scripts/dry_run_call.py` shows the commands of a call without hardware. |

Order when it matters: `python scripts/check_translations.py && flake8 ola tests scripts && pytest`

---

## Gotchas

- **CI** is `.github/workflows/ci.yml` (translations → lint → tests on Python 3.12 / 3.13 → Rust transport → PostgreSQL → tests against the library `main`). It runs on every push and pull request; the runner is set by the repository variable `CI_RUNS_ON`. Details: `docs/CI.md`.
- **`.gitignore` excludes** `*_old.py`, `*_debug.py`, `debug_*.py`, `check_*.py` (except `scripts/check_*.py`), `*.backup`, `*.bak`, `.vscode/` and `*.code-workspace`. Test files are tracked.
- **`Instruments_LIB` is a git submodule.** Change the library in its own repository; here only the pointer moves, in a separate pull request.
- **Stacked pull requests are a trap.** If a pull request is based on the branch of another one, merging it after the first lands it in that branch, not in `main`. Base every pull request on `main`.
- **`models.py` and `DatabaseManager.py` (capital) are deprecated.** Use `ProjectDatabaseManager`.
- **The former C backend was removed in November 2026**: `ola/transport.py` and `native/` replace it.
- **Documentation and code comments are in English.** The UI strings are in the locale files.

---

## Architecture

```
GUI (frontend/ui) ──► Core (frontend/core) ──► Engine (ola/, native/) ──► Instruments
 Remote control tab     validation, errors,      planner, steps, runner,    VISA, TCP, serial,
 Measurements tab       i18n, PostgreSQL         transport, drivers,        GPIB adapters,
                                                 measurement modules        drivers (SDK)
                                    Instruments_LIB (submodule): models and call schemas
```

| Layer | Location | Role |
|-------|----------|------|
| Entry points | `frontend/launcher.py`, `frontend/main.py` | App bootstrap |
| UI dialogs | `frontend/ui/*.py` | One file per window/dialog. Layout & signal wiring only — **no business logic**. |
| Core library | `frontend/core/*.py` | Validation, error handling, PostgreSQL storage, i18n, logging |
| Engine | `ola/`, `native/` | Qt-free transport, steps, call planner, drivers, measurement runner and modules. See the section *Engine (`ola/` and `native/`)* of `README.md` and `docs/engine.md`. |
| Measurement modules | `ola/modules/<id>/` | `module.json`, `measurement.py`, `form.json`, `wiring.json`; guide in `docs/`. |
| Instrument library | `Instruments_LIB/instruments_lib.json`, `Instruments_LIB/schema/` | Models, interfaces, limits, and the logical calls of each category. |
| Translations | `frontend/lang/*.json`, `frontend/lang/modules/*/` | One file per locale. Accessed via `Translator.t(key)`. |

### Instrument I/O

Everything the GUI and the measurements ask of an instrument is a **logical call** (`handle.call("set_voltage", value=5)`). The planner builds the steps from the model's entry in the library, the executor runs them under one lock per instrument, and the transport carries them: Rust or pure-Python TCP and serial, pyvisa (USB-TMC, GPIB, VXI-11), Prologix GPIB adapters. Instruments with `access: driver` (Analog Discovery, LiteVNA) are handed to a driver in `ola/drivers/`. Manual instruments (no remote control) ask the operator through a pop-up.

### Rules

- **Error handling**: Never raw `try/except` + `QMessageBox`. Call `errorhandler.handle_error(exc, user_message)` or raise a custom error with an `[RESOURCE-XXX]` code. See `ERROR_CODES.md`.
- **I18n**: Every new string used in the UI must have a key in **all** locale files (`it.json`, `en.json`, `fr.json`, `es.json`, `de.json`).
- **No SCPI guessing**: the software never builds SCPI strings; a call missing from the library means "not supported by this instrument" (`CALL-001`), never a guessed command. This applies to `PulseGeneratorDialog.py` and to every measurement.
- **One file per dialog**: Each `QDialog`/`QMainWindow` in its own file under `frontend/ui/`.
- **No `time.sleep()` in GUI thread**: Use `QTimer.singleShot()` for delayed operations, and stop the timer when the window closes.
- **No bare `except:`**: Always specify the exception type. Log the error.
- **Copyright header** on every new source file (`python scripts/add_copyright_headers.py FILE...`).
- **Safety in measurements**: `teardown` always runs and puts the instruments in a safe state; limits come from the library and are checked before anything is sent.

---

## Testing

Tests live in `tests/` (engine, measurement modules, whole-library integrity, `frontend/core`, scripts, GUI windows built offscreen); `test_basic_import.py` and `test_instrument_library.py` at the repo root cover the core imports and the instrument library (`git submodule update --init` is needed for the library tests). What each file covers and how CI runs them: `docs/CI.md`.

```bash
QT_QPA_PLATFORM=offscreen pytest   # everything (tests/ + test_*.py at root)
pytest -m "not gui"                # without the Qt widgets
pytest tests/test_library_integrity.py   # every call of every library model
OLA_TEST_POSTGRES="host=127.0.0.1 port=5432 user=postgres password=postgres" \
    pytest tests/test_project_database.py   # with a PostgreSQL server
```

Some tests keep the documentation in sync: public items of `ola/` need a docstring, every `ola/` file and module must be in the README engine table, every `TRN-xxx` / `CALL-xxx` code must be in `ERROR_CODES.md`, relative links must not be broken. When you change the library usage, a dialog or an error code, run the suite: the integrity, window and error-code tests are meant to catch exactly those changes.

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

---

## Extending instruments

1. Add the model to `Instruments_LIB/instruments_lib.json` (in the library repository) following `Instruments_LIB/TESTING.md`; the call names and arguments are fixed per category by `Instruments_LIB/schema/*.json`.
2. A model overrides, removes (`null`) or patches (`{"patch": …}`) the commands of its series; the resolution is in `ola/library.py`.
3. If the instrument has no text protocol (a vendor SDK), add a driver in `ola/drivers/` and set `access: driver` in the library.
4. If a new category is needed, add its schema in `Instruments_LIB/schema/` and the type in `LoadInstruments.py`.
5. Test it with `python scripts/dry_run_call.py` and `python scripts/instrument_shell.py`, then run `pytest tests/test_library_integrity.py`.
