# Testing and CI

The tests need no instrument: hardware is replaced by simulated transports, fake TCP instruments on `localhost` and pseudo-terminals.

## Run them

```bash
git submodule update --init                 # the library tests need it
pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen pytest            # everything
pytest -m "not gui"                         # without Qt widgets
pytest tests/test_library_integrity.py      # every call of every library model
pytest tests/test_docs.py                   # documentation in sync with the code
python scripts/check_translations.py        # five languages, same keys
flake8 ola tests scripts                    # style of new code
```

Native transport: `cd native && cargo test`, then `pytest tests` with the Rust module installed.

## What the suite covers

| Area | Test files |
|---|---|
| Engine: transport, steps, planner, parsers, runner, projects, registry | `tests/test_*.py` |
| Whole library against the engine (every call of every model) | `tests/test_library_integrity.py` |
| Example projects and the example `.was` files | `tests/test_examples.py`, `tests/test_example_project.py` |
| `frontend/core` helpers | `tests/test_core_*.py` |
| Error codes documented in `ERROR_CODES.md` | `tests/test_core_errorhandler.py` |
| Translation keys in every locale | `tests/test_core_i18n_logging.py` |
| Command-line tools | `tests/test_scripts_cli.py` |
| Documentation: docstrings, README table, links, the module example | `tests/test_docs.py` |
| GUI smoke tests: every window built offscreen | `tests/test_gui_smoke.py` |
| PostgreSQL storage | `tests/test_project_database.py` (needs a server) |

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

1. **Lint and translations**: `check_translations.py`, `flake8`.
2. **Tests (Python 3.12 and 3.13)**: builds the C backend, runs the whole suite with coverage.
3. **Native transport (Rust)**: `cargo test`, builds the wheel with maturin and runs the transport tests.
4. **Project database (PostgreSQL 16)**.
5. **Against the library's main branch**: informational, shows what the next submodule update would break.

Full description: [`docs/CI.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/CI.md).
