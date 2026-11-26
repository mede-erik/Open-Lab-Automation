# Developer guide

## Layers

| Layer | Location | Depends on Qt? | Role |
|---|---|---|---|
| GUI | `frontend/ui/`, `frontend/launcher.py`, `frontend/main.py` | yes | One file per window or dialog. Layout and signal wiring only. |
| Core helpers | `frontend/core/` | partly | Validation, error handling (`errorhandler.py`), translations, logging, network diagnostics, saved settings. |
| **Engine** | `ola/` | **no** | Transport, steps, call planner, instrument handles, measurement runner, measurement modules, RF maths, registries. |
| Native transport | `native/` (Rust, PyO3) | no | TCP and serial with the GIL released. Optional. |
| Instrument library | `Instruments_LIB/` (submodule) | no | Data only: models, call schemas and how each model implements them. A separate repository. |

`import ola` works without PyQt6, so the engine runs from the GUI, scripts and tests alike. The legacy C backend and the PostgreSQL storage were removed in November 2026: results are the run files in `runs/`.

## How a measurement runs

1. A **measurement module** (a folder in `ola/modules/` with a `module.json`) describes what to measure.
2. The *Measurements* tab goes `ProjectWindow` → `ProjectSession` → `Runner` (a thread: `setup`, `run`, and **always** `teardown`).
3. The module calls instruments only through logical calls: `ctx.instrument(role).call("set_voltage", value=5)`.
4. The **call planner** turns the call and its arguments into a plan of steps using the library entry of the model.
5. The **instrument layer** runs the steps (`write`, `query`, `read`, `delay`) under one lock per instrument, or hands the call to a driver.
6. Results are written to `runs/` while the run is going (JSON Lines).

Full description: [`docs/engine.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/engine.md). Calls and steps: [`docs/instrument-calls.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/instrument-calls.md).

## Rules for contributors

- **No SCPI strings** in the GUI or in modules: use the library's logical calls. A call missing from the library means "not supported" (`CALL-001`), never a guessed command.
- **Error codes**: every error has a code (see [Error codes](Error-Codes)). In the GUI, show errors through `errorhandler.handle_error(exc, user_message)`. No bare `except:`.
- **Translations**: every user-visible string has a key in all five locale files (`it`, `en`, `fr`, `es`, `de`); `scripts/check_translations.py` checks it.
- **No `time.sleep()` in the GUI thread**: use `QTimer.singleShot()`.
- **Business logic goes to `ola/`** (or `frontend/core/`), not to the dialogs.
- **English only** for documentation and code comments; the UI languages are the locale files.
- **Copyright header** on every new source file: `python scripts/add_copyright_headers.py FILE...`. A test fails without it.
- **Documentation travels with code**: a new module needs a guide in `docs/` and a row in the README engine table; public items of `ola/` need a docstring. `tests/test_docs.py` enforces this.
- **Test status list**: a new feature is added unchecked to *Software test status* in the README; it is checked only after a run on real hardware.
- **Pull requests go to `main`**, not stacked on another branch.
- **Safety in measurements**: `teardown` always puts the instruments in a safe state, and limits come from the library and are checked before anything is sent.

## Transport

- `ola/transport.py` uses the Rust module when installed, otherwise the pure-Python one (same behaviour; `OLA_TRANSPORT=python` forces the latter).
- `ola/_visa.py` wraps pyvisa for USB-TMC, GPIB and VXI-11.
- `ola/prologix.py` drives Prologix-compatible GPIB adapters.
- `ola/drivers/` holds drivers for instruments without text commands (LiteVNA, Analog Discovery).

Benchmark: `python benchmarks/bench_transport.py`. On loopback a query costs about 35 µs (Rust) or 55 µs (pure Python). The *benchmark mode* ([`docs/benchmark.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/benchmark.md)) tells where the time goes during a real run.

## Packaging

Packages are built by `.github/workflows/package.yml`: the `nightly` pre-release at every commit on `main`, a fixed release for every tag `vX.Y.Z`. The version lives in three places (`pyproject.toml`, `frontend/appinfo.json` and `pkgver` in `packaging/arch/PKGBUILD`) that must agree; a new data folder read at run time must also be listed in `packaging/pyinstaller/ola.spec`. Read `packaging/README.md` first.

## Repository layout to know

- `ola/modules/` built-in measurements; `ola/registry.py` finds them.
- `ola/project*.py`, `ola/runs.py` project and run files.
- `ola/identity.py`, `ola/compat.py`, `ola/role_mapping.py` instrument identity, compatibility and role mapping between projects.
- `ola/golden.py`, `ola/trend.py`, `ola/compare.py`, `ola/assets.py`, `ola/labels.py` the tools of the *Tools* menu, without Qt.
- `scripts/` command-line tools, `examples/` example projects, `tests/` the test suite, `packaging/` the package recipes.

Next: [Writing a measurement module](Writing-a-Measurement-Module), [Testing and CI](Testing-and-CI).
