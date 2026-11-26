# Testing and CI

The tests need no instrument: hardware is replaced by simulated transports, fake TCP instruments on `localhost` and pseudo-terminals.

## Run them

```bash
git submodule update --init                       # the library tests need it
pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen pytest                  # everything
pytest -m "not gui"                               # without Qt widgets
pytest tests/test_library_integrity.py            # every call of every library model
pytest tests/test_docs.py                         # documentation in sync with the code
python scripts/check_translations.py              # five languages, same keys
flake8 ola tests scripts                          # style of new code
flake8 --select=E9,F63,F7,F82 .                   # real errors, whole repository
python scripts/add_copyright_headers.py --check   # files without the copyright header
```

Native transport: `cd native && cargo test`, then `pytest tests` with the Rust module installed.

## What the suite covers

| Area | Test files |
|---|---|
| Engine: transport, steps, planner, parsers, runner, projects, registry, measurement modules | `tests/test_*.py` |
| Whole library against the engine (every call of every model) | `tests/test_library_integrity.py` |
| Example projects and the example `.was` files | `tests/test_examples.py`, `tests/test_example_project.py` |
| `frontend/core` helpers | `tests/test_core_*.py` |
| Error codes used in the source are documented in `ERROR_CODES.md` | `tests/test_core_errorhandler.py` |
| Translation keys in every locale | `tests/test_core_i18n_logging.py` |
| Command-line tools | `tests/test_scripts_cli.py` |
| Documentation: docstrings, README engine table, links, the module example | `tests/test_docs.py` |
| Copyright headers on source files | `tests/test_copyright_headers.py` |
| Packaging: the version agrees in its three places | `tests/test_packaging.py` |
| GUI smoke tests: every window built offscreen | `tests/test_gui_smoke.py` |

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and on every push to a branch other than `main`:

1. **Lint and translations**: `check_translations.py`, `flake8`.
2. **Tests (Python 3.12 and 3.13)**: the whole suite with coverage.
3. **Native transport (Rust)**: `cargo test`, builds the wheel with maturin and runs the transport tests with it.
4. **Against the library's main branch**: informational; shows what the next submodule update would break.

On `main` and on the version tags, the *Package* workflow runs the same jobs first and builds the packages only if they pass. Full description: [`docs/CI.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/CI.md).

The tests prove that the software works against simulated instruments. What still has to be run on real hardware is in [Software test status](Software-Test-Status).
