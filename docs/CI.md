# Continuous integration and automatic tests

The workflow `.github/workflows/ci.yml` runs on **every push (any branch)**, on **every pull
request** and by hand (*Actions → CI → Run workflow*). It needs no instrument: the hardware is
replaced by simulated transports, fake TCP instruments on `localhost` and pseudo-terminals.

## Jobs

| Job | What it checks | Fails the build |
|---|---|---|
| **Lint and translations** | `scripts/check_translations.py`; `flake8` on `ola/ tests/ scripts/`; syntax errors and undefined names everywhere; style report of the legacy code | yes (the legacy report does not) |
| **Tests (Python 3.12 / 3.13)** | builds the C backend, then `pytest` on the whole suite with coverage; JUnit and coverage XML are uploaded as artifacts | yes |
| **Native transport (Rust)** | `cargo test`; builds the `ola_native` wheel with maturin and runs `pytest tests` with the native transport (serial/pty tests included); `rustfmt`/`clippy` are reported only | yes (fmt/clippy no) |
| **Project database (PostgreSQL)** | `tests/test_project_database.py` against a PostgreSQL 16 service container | yes |
| **Against Instruments_LIB main** | the suite with the library moved from the pinned submodule commit to `Instruments_LIB` `main`: shows what the next submodule update will break | no (informational) |

The library repository (`Instruments_LIB`) has its own workflow: library data checks,
conformance, generated docs, and this application's test suite run against the library change.

## What the test suite covers

| Area | Files |
|---|---|
| Engine (`ola/`): transport, steps, planner, parsers, measurement runner, projects, registry | `tests/test_*.py` (pre-existing) |
| **Whole instrument library against the engine**: every call of every model plans, every logical value plans or is refused with CALL-002, maps use logical values, parsers and result steps exist, serial settings are valid, example `.was` files plan on every oscilloscope | `tests/test_library_integrity.py` |
| Example projects: valid files, referenced files exist, models are in the library | `tests/test_examples.py`, `tests/test_example_project.py` |
| `frontend/core`: validator, tools (incl. network diagnostics), translator, logger, error handler, `LoadInstruments` against the engine | `tests/test_core_*.py` |
| Error codes: every code used in the source is documented in `ERROR_CODES.md` | `tests/test_core_errorhandler.py` |
| Translation keys used by the code exist in every locale | `tests/test_core_i18n_logging.py` |
| Command-line tools (`check_translations`, `dry_run_call`, `instrument_shell --sim`) run as subprocesses | `tests/test_scripts_cli.py` |
| Legacy C backend through ctypes against a fake LXI instrument (query, timeout, sweep) | `tests/test_c_backend.py` |
| GUI smoke tests: every window/dialog is built and shown offscreen with the example project, without error boxes; the main window opens a project | `tests/test_gui_smoke.py` |
| PostgreSQL measurement storage | `tests/test_project_database.py` |

Some checks keep an explicit list of **known gaps** (for example a model used by an example
project that is not in the library yet). The test fails both when a new gap appears and when a
listed gap is fixed, so the list is kept up to date.

## Running the tests locally

```bash
git submodule update --init
pip install -r requirements.txt
bash backend/build.sh                       # optional: enables tests/test_c_backend.py
QT_QPA_PLATFORM=offscreen pytest            # whole suite
pytest tests/test_library_integrity.py     # only the library checks
pytest -m "not gui"                         # without the Qt widgets
OLA_TEST_POSTGRES="host=127.0.0.1 port=5432 user=postgres password=postgres" \
    pytest tests/test_project_database.py   # with a PostgreSQL server
OLA_LIBRARY=/path/to/instruments_lib.json pytest tests/test_library_integrity.py  # another library file
```

On Linux the Qt tests need the system libraries `libegl1 libgl1 libxkbcommon0 libdbus-1-3
libfontconfig1 libxcb-cursor0` (installed by the CI).

## Moving the jobs to a self-hosted runner

1. Register the runner (*Settings → Actions → Runners → New self-hosted runner*), Linux x64,
   with a label of your choice.
2. Create the repository variable **`CI_RUNS_ON`** (*Settings → Secrets and variables → Actions →
   Variables*) with a JSON value: `["self-hosted", "linux", "x64"]` or `"my-label"`. Without the
   variable the jobs use `ubuntu-latest`. Do the same in `Instruments_LIB`.
3. The runner must provide:
   * `sudo` without a password **or** the packages above plus `gcc` and `make` already installed
     (the setup step installs them when it can, otherwise it prints a warning);
   * internet access for `actions/setup-python` (downloads Python 3.12/3.13), pip, crates.io and
     the Rust toolchain;
   * **Docker** for the PostgreSQL job. Without Docker set the variable `CI_SKIP_POSTGRES` to
     `true` and the job is skipped.
4. For a public repository GitHub recommends not running pull requests from forks on
   self-hosted runners (*Settings → Actions → General → Fork pull request workflows*).

The shared setup (Python, system packages, Python dependencies) is in
`.github/actions/setup-ola/action.yml`.
