# Developer guide

## Layers

| Layer | Location | Depends on Qt? | Role |
|---|---|---|---|
| GUI | `frontend/ui/`, `frontend/launcher.py`, `frontend/main.py` | yes | One file per window or dialog. Layout and signal wiring only. |
| Core helpers | `frontend/core/` | partly | Project database (`ProjectDatabaseManager.py`), settings, error handling, i18n, logging. |
| **Engine** | `ola/` | **no** | Transport, steps, call planner, instrument handles, measurement runner, measurement modules, RF maths. |
| Native transport | `native/` (Rust, PyO3) | no | TCP and serial with the GIL released. Optional. |
| Instrument library | `Instruments_LIB/` (submodule) | no | Data only: models, call names and how they are translated. |
| Legacy backend | `backend/` (C) | no | Raw TCP through ctypes. Not used any more, do not extend. |

`import ola` works without PyQt6, so the engine runs from the GUI, scripts and tests alike.

## How a measurement runs

1. A **measurement module** (a folder in `ola/modules/` with a `module.json`) describes what to measure.
2. Its `setup`, `run` and `teardown` call instruments only through logical calls: `ctx.instrument(role).call("set_voltage", value=5)`.
3. The **call planner** turns the call and its arguments into a plan of steps using the library entry of the model.
4. The **instrument layer** runs the steps (`write`, `query`, `read`, `delay`) under one lock per instrument.
5. The **runner** always runs `teardown`, even after a stop or an error.

Full description: [`docs/engine.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/engine.md). Calls and steps: [`docs/instrument-calls.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/instrument-calls.md).

## Rules for contributors

- No SCPI strings in the GUI or in modules: use the library's logical calls.
- Every error has a code (`TRN-`, `CALL-`, ... see [Error codes](Error-Codes)). No bare `except:`.
- Every user-visible string has a key in all five locale files (`it`, `en`, `fr`, `es`, `de`); `scripts/check_translations.py` checks it.
- No `time.sleep()` in the GUI thread: use `QTimer.singleShot()`.
- Business logic goes to `ola/` (or `frontend/core/`), not to the dialogs.
- Documentation travels with code: a new module needs a guide in `docs/` and a row in the README engine table. `tests/test_docs.py` enforces this.
- Deprecated, do not use: `frontend/core/models.py`, `frontend/core/DatabaseManager.py`.

## Transport

- `ola/transport.py` uses the Rust module when installed, otherwise the pure-Python one (same behaviour; `OLA_TRANSPORT=python` forces the latter).
- `ola/_visa.py` wraps pyvisa for USB-TMC, GPIB and VXI-11.
- `ola/prologix.py` drives Prologix-compatible GPIB adapters.
- `ola/drivers/` holds drivers for instruments without text commands (LiteVNA, Analog Discovery).

Benchmark: `python benchmarks/bench_transport.py`. On loopback a query costs about 35 µs (Rust) or 55 µs (Python), against about 44 ms with the legacy C backend.

## Repository layout to know

- `ola/modules/` built-in measurements; `ola/registry.py` finds them.
- `ola/project*.py`, `ola/runs.py` project and run files (JSON Lines).
- `ola/identity.py`, `ola/compat.py`, `ola/role_mapping.py` instrument identity, compatibility and role mapping between projects.
- `ola/golden.py`, `ola/trend.py`, `ola/compare.py`, `ola/assets.py`, `ola/labels.py` the tools of the Tools menu, without Qt.
- `scripts/` command-line tools, `examples/` example projects, `tests/` the test suite.

Next: [Writing a measurement module](Writing-a-Measurement-Module), [Testing and CI](Testing-and-CI).
