# Open Lab Automation

Open Lab Automation is an open-source suite for automated electrical measurements, designed for hobbyists, makers, and lab enthusiasts. The frontend is a modern Python (PyQt6) graphical interface for instrument configuration and control, while the C backend ensures fast, direct communication with instruments via USB, LAN, GPIB, or serial.

> [!IMPORTANT]  
> This software is under active development. Features and stability may change, and some parts may be incomplete or experimental.

## Main Features

- **Instrument Management**
  - Add, configure, and manage instruments using a flexible JSON library (`Instruments_LIB/instruments_lib.json`).
  - Three-level selection: type → series → model, with dynamic options.
  - Support for power supplies, dataloggers, oscilloscopes, and electronic loads.
  - **Advanced Datalogger Configuration**: 
    - Slot-based module system for modular instruments (e.g., Keysight 34972A).
    - Visual slot configuration with compatible module selection.
    - Per-channel configuration with attenuation, measurement type, and enable/disable.
    - Real-time validation with detailed error codes (DL-XXX series).
  - Detailed configuration of channels/slots, variables, attenuation, measurement type, per-channel enable/disable.
  - Guided VISA address composition for each interface (LXI, GPIB, USB, RS232, ...).
  - Edit already-inserted instruments and manage channel selection.
  - Fully translatable interface (Italian, English, French, Spanish, German).

- **Project Management**
  - Create and manage measurement projects with associated configuration files (.json, .inst, .eff, .was).
  - Advanced naming options for files and instances.
  - Dedicated editors for instruments, efficiency, and oscilloscope settings.
  - **Oscilloscope Trigger Configuration**: `.was` editor supports trigger setup (source channel, slope rise/fall, level, mode) with vendor-agnostic values mapped to instrument-specific SCPI via the instrument library.
  - **Advanced Efficiency Sweeps**: Multi-variable nested sweep system with configurable order, list/range modes, and timing parameters.
  - **Automatic Measurement**: All project variables (control and measure) are automatically measured during sweeps.

- **Backend Communication**
  - C backend for efficient, direct communication with instruments.
  - Designed to be easily extendable to new instruments and protocols.

- **Error Handling & Validation**
  - Standardized error code system with resource-specific prefixes ([RESOURCE-XXX] format).
  - Comprehensive validation for all user inputs.
  - Detailed error logging with stack traces for debugging.
  - User-friendly error messages with technical error codes for support.

- **Tools**
  - **Pulse Generator Tool**: Generate current/voltage pulses on electronic loads with real-time waveform preview.
    - Visual configuration with amplitude, frequency, rise/fall time parameters.
    - Automatic validation against instrument capabilities (max_current_a, max_voltage_v, max_power_w).
    - Real-time trapezoidal waveform visualization with matplotlib.
    - Uses ONLY library-defined SCPI commands for safety (no command guessing).
    - Automatic correction to maximum safe values when limits exceeded.
    - Supports dynamic mode (Chroma 6330A) and future extensibility for other electronic loads.

## Project Structure

- **Frontend:** Python (PyQt6) — Modern graphical interface with comprehensive instrument management and advanced sweep configuration
- **Engine (`ola/`, `native/`):** Python + Rust — Qt-free instrument transport, step executor and measurement core (see [Engine](#engine-ola-and-native) below)
- **Legacy backend (`backend/`):** C — original communication layer, not used by the GUI any more (`frontend/core/c_backend.py` is not called from `frontend/`); it will be retired once the app uses `ola/`
- **Instrument Library:** JSON (`Instruments_LIB/instruments_lib.json`) — Extensible database of supported instruments
- **Configuration Files:**
  - `.inst` — Instrument configuration and channel setup
  - `.eff` — Efficiency measurement sweeps with nested variable support
  - `.was` — Oscilloscope waveform acquisition and trigger settings
  - `.json` — Project metadata and variable definitions

## Engine (`ola/` and `native/`)

The engine is everything that talks to instruments and runs measurements. It has **no Qt dependency**, so it can be used from the GUI, from scripts and from tests (`import frontend.core` needs PyQt6, `import ola` does not). It is not wired into the GUI yet.

```
measurement module (Python)         what to measure: setup / run / teardown
        |  handle.call("set_voltage", value=5)       logical calls, no SCPI
        v
instrument layer  ola/instrument.py                  steps write / query / read / delay,
        |                                            one lock per instrument per call
        v
transport  ola/transport.py                          TCP raw socket, serial (Rust)
           ola/_visa.py                              USB-TMC, GPIB, VXI-11 (pyvisa)
```

| Path | Purpose |
|---|---|
| `native/` | Rust crate `ola_native` (PyO3): TCP (`TCP_NODELAY`, deadline-bounded buffered reads), serial, IEEE 488.2 blocks. The GIL is released during I/O. |
| `ola/transport.py`, `ola/_pyconn.py` | Entry point; uses `ola_native` if installed, otherwise a pure-Python implementation with identical behaviour (`OLA_TRANSPORT=python` forces it). |
| `ola/_visa.py` | pyvisa adapter with the same interface. It never leaves a shared pyvisa resource modified. |
| `ola/steps.py`, `ola/instrument.py` | A call is a list of steps (`write`, `query`, `read`, `delay`) run in order; the first failure stops it (`CALL-004` with the step index). `driver` plans (e.g. Analog Discovery via its SDK) are dispatched to a driver object. |
| `ola/measurement.py`, `ola/runner.py` | `Measurement` base class and the thread runner: `setup`, `run`, and **always** `teardown`; stop, pause/resume, errors with code and traceback. |
| `ola/registry.py`, `ola/modules/` | Measurement modules, found from their `module.json`. Finding a module never runs its code; a module that is not built in needs explicit permission to load. |
| `ola/project.py`, `ola/runs.py` | Project with several measurements, one file per measurement (the extension identifies the type); run results written while the measurement runs (JSON Lines). |
| `ola/sim.py` | Simulated transport for development and dry runs without hardware. |
| `ola/rf.py`, `ola/limits.py` | Shared by the RF measurements (no Qt): dB, insertion / return loss, VSWR, impedance from the reflection coefficient, group delay and velocity factor, a curve at one frequency, level crossings (the -3 dB points), **Touchstone** `.s1p`/`.s2p` reading and writing; and **pass / fail limits** on a curve (a constant, a line, or one limit per band) that turn a result into a verdict. `ola.runs` exports the traces of a run to CSV and Touchstone. |
| `ola/connection.py`, `frontend/ui/manual_prompt.py` | How a project reaches its instruments (the `connect` of the project window): `ProjectConnector` reads the `.inst` file and gives the handle of an instrument - a manual one (the operator is asked, in a pop-up, to do the action by hand) or one opened from the library at its VISA address (USB, LAN, GPIB, serial). Connections stay open between runs; every problem is a sentence that says what to check. See [`docs/engine.md`](docs/engine.md#connecting-the-instruments). |
| `ola/project_session.py`, `frontend/ui/ProjectWindow.py` | The window of a project (format 2: one file per measurement): the list of its measurements, **New** (type chosen among the measurement modules), **Edit** (the efficiency editor for `.eff`, a validated JSON editor for other types), **Start measurement** (opens the run window; results go to `runs/` in the project folder), Rename, Remove, the runs already made with CSV export. The logic is in `ProjectSession` (no Qt); the instruments come from the application through `connect(name) -> handle`. Strings: `frontend/lang/modules/project/<lang>.json`. Try it: `python -m frontend.ui.ProjectWindow [project.json]` (no argument: a demo project with simulated instruments). See [`docs/engine.md`](docs/engine.md#the-project-window). |
| `ola/run_view.py`, `ola/demo_lab.py`, `frontend/ui/RunWindow.py`, `frontend/ui/plot_widget.py`, `frontend/ui/trace_plot.py` | The window that runs a measurement: a model without Qt (`RunModel`: state, progress and time left, table, log, open questions, series for plots) and a thin PyQt6 window with Start / Pause / Stop, a live table, a plot (any column against any other, one line per value of a third), a *Curves* tab (traces with magnitude / loss / phase / **Smith chart** views, logarithmic axis, limit lines, CSV and Touchstone export), the log and **pop-ups for the questions** of the measurement. Strings: `frontend/lang/modules/run/<lang>.json`. Try it with simulated instruments: `python -m frontend.ui.RunWindow` (add `--fault` to see the pop-up). See [`docs/engine.md`](docs/engine.md#the-run-window). |
| `ola/efficiency_editor.py`, `frontend/ui/EfficiencyEditorDialog.py` | The editor of the `.eff` file: a model without Qt (`EfficiencyEditor`: add / duplicate / move / rename parameters, sweeps, formulas, power order, live problems) and a thin PyQt6 window on top of it. Strings: `frontend/lang/modules/efficiency/<lang>.json` (en, it, fr, es, de). Try it: `python -m frontend.ui.EfficiencyEditorDialog [file.eff]`. See [`docs/efficiency.md`](docs/efficiency.md#the-editor-window). |
| `ola/efficiency_spec.py`, `ola/formula.py`, `ola/sweep.py`, `ola/modules/efficiency/` | The efficiency measurement (`.eff`): ordered list of parameters (set / sweep / read), averaging, formulas such as `100 * pout / pin` (safe: never `eval`), live validation for the editor dialog, and a question to the user (retry / abort / skip) when a reading disagrees with the setpoint. Guide: [`docs/efficiency.md`](docs/efficiency.md). |
| `ola/errors.py`, `ola/call_errors.py` | Exceptions with a stable `code`: `TRN-xxx` (transport) and `CALL-xxx` (calls); see `ERROR_CODES.md`. |

**Guides** (in `docs/`): [how a run works, events, files and guarantees](docs/engine.md) · [writing a measurement module](docs/measurement-modules.md) · [instrument calls, steps, transports and RS-232 notes](docs/instrument-calls.md).

**Why a new transport.** The old C backend needed about 44 ms per SCPI query on loopback (Nagle + delayed ACK: no `TCP_NODELAY`, command and terminator sent separately). The new transport needs about 35 µs (Rust) or 55 µs (pure-Python fallback); see `benchmarks/bench_transport.py`. On real instruments a query costs 1-50 ms, so the instrument dominates; the engine's job is to add nothing on top.

**Project format (v2).** `<project>.json` has `"format_version": 2` and a `measurements` list (`id`, `type`, `name`, `file`). Each measurement lives in its own file whose extension is defined by its module (`.tlg` for the built-in time log). The old `eff_files` / `was_files` project format is not read.

**Writing a measurement module.** A folder with a `module.json` (id, name, version, `api_version`, unique `extension`, `entry`, `roles`, `params_schema`) and a Python file with a `Measurement` subclass. Instruments are only reached through `ctx.instrument(role).call(name, **args)`. See `ola/modules/time_log/` for a complete example. Modules are searched in `ola/modules/` (built in), `~/.open_lab_automation/modules/` and `<project>/modules/`.

**Build, test, benchmark**

```bash
pip install maturin
cd native && maturin build --release && pip install target/wheels/ola_native-*.whl   # optional: fast transport
cd native && cargo test        # Rust tests
pytest tests                   # Python tests (native and pure-Python transport)
python benchmarks/bench_transport.py
```

Error codes of the engine are `TRN-xxx` (transport) and `CALL-xxx` (calls); see `ERROR_CODES.md`. The design and the project status are in `PLAN.md`.

## Requirements

- Python 3.7+
- PyQt6
- GCC (for backend compilation)
- Additional Python packages listed in `requirements.txt`

## File List and Description

### Core Application
- `frontend/launcher.py` — Application launcher with environment setup
- `frontend/main.py` — Main Python GUI application (PyQt6), instrument/project management dialogs
- `backend/backend.c` — C backend for low-level instrument communication

### Instrument Library & Configuration
- `Instruments_LIB/instruments_lib.json` — Instrument library (JSON structure for all supported instruments)
- `frontend/ui/` — Dialog boxes and UI components for instrument and project configuration
  - `EffFileDialog.py` — Advanced multi-variable nested sweep editor
  - `InstFileDialog.py` — Instrument configuration editor
  - `WasFileDialog.py` — Oscilloscope waveform settings editor
  - `AddInstrumentDialog.py` — Three-level instrument selection (type → series → model)
  - `DataloggerSlotConfigDialog.py` — Slot-based module configuration for modular dataloggers
  - `PulseGeneratorDialog.py` — Electronic load pulse generator with waveform preview
  - Various instrument-specific configuration dialogs (power supplies, electronic loads, oscilloscopes)

### Translation & Localization
- `frontend/lang/it.json`, `en.json`, `fr.json`, `es.json`, `de.json` — Translations for the GUI
- `frontend/core/Translator.py` — Translation management system

### Core Functionality
- `frontend/core/` — Core modules for database, error handling, validation, and utilities
  - `ProjectDatabaseManager.py` — Project and measurement data management
  - `LoadInstruments.py` — Instrument library interface with module management
  - `errorhandler.py` — Centralized error handling with standardized error codes ([RESOURCE-XXX] format)
  - `validator.py` — Input validation functions
  - `tools.py` — Reusable utility functions
  - `Translator.py` — Multi-language translation system

### Documentation
- `README.md` — This documentation file
- `LICENSE` — License information
- `ERROR_CODES.md` — Complete reference of standardized error codes
- `Open-Lab-Automation.code-workspace` — VS Code workspace settings
- `Instruments_LIB/docs/` — Instrument manuals and documentation
- `examples/` — Example projects and configuration files

## Getting Started

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/mede-erik/Open-Lab-Automation.git
   cd Open-Lab-Automation
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Compile the C backend (optional, for direct instrument communication):
   ```bash
   gcc backend/backend.c -o backend/backend.exe
   ```

4. Launch the application:
   ```bash
   python frontend/launcher.py
   ```

### Quick Start
1. Create a new project or open an existing one
2. Add instruments using the three-level selection (Type → Series → Model)
3. Configure instruments:
   - For dataloggers with slots: use the "Configure Datalogger Slots" button to select modules
   - For other instruments: configure channels, variables, and measurement settings
4. Set up efficiency sweeps with nested variables in the `.eff` file editor
5. Configure oscilloscope acquisition and trigger in the `.was` file editor
6. Start measurements and monitor results

### Example Projects
Check the `examples/` directory for sample configurations:
- `test-dcdc-project/` — DC-DC converter efficiency measurement setup
- `Test_scpi/` — Basic SCPI communication examples

## Future features

Things that are planned but not started. They are deliberately left for later, when the measurements work
and the software reaches a beta state. The detailed plan (in Italian) is in [`PLAN.md`](PLAN.md#6b-misure-rf-e-roadmap).

- **Measurement report**: an HTML report that can be saved as PDF, built from a template the user can edit
  (project, measurement, instruments, parameters, plots, results). For now the results are exported as CSV
  (and Touchstone for RF traces).
- **Results comparison tool** (menu *Tools*, like the Hex/Dec converter): pick two or more saved results and
  overlay them - for example the loss of two cables.
- **Cable label tool** (menu *Tools*): generate a printable label template and fill in the data that identifies
  a cable, so that every measurement is tied to the cable it was made on. To be designed after the RF
  measurements (cable, return loss, filter, antenna) are done.
- **Measurement templates**: ready-made measurement files to choose from *New measurement* (line and load
  regulation, I-V curve...) for the measurements that are a variation of an existing module.
- **More measurement modules**: ripple and noise, Bode plot, load transient, spectrum analysis, battery
  discharge. See the table in `PLAN.md`.
- **Instruments without SCPI**: the LiteVNA67 (text commands on a serial port) and the Analog Discovery 2/3
  (driver system).

## Disclaimer
> [!WARNING]
> **This software is provided for hobbyist and non-professional use only.**
>
> The authors and contributors of Open Lab Automation accept no responsibility for damage to persons, property, or equipment resulting from the use of this software. Use at your own risk. The software is provided "as is", without any express or implied warranty. It is not intended for professional, industrial, or safety-critical use.

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

### Areas for Contribution
- Adding support for new instruments in `Instruments_LIB/instruments_lib.json`
- Improving translations in `frontend/lang/*.json`
- Enhancing the C backend with new protocols
- Adding new measurement capabilities
- Documentation improvements

## License

See the LICENSE file for details.

## Support

For bug reports and feature requests, please use the [GitHub Issues](https://github.com/mede-erik/Open-Lab-Automation/issues) page.

When reporting errors, please include the error code (e.g., [DL-001]) shown in the error message for faster troubleshooting.

