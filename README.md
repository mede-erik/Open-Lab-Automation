# Open Lab Automation

Open Lab Automation is an open-source suite for automated electrical measurements, designed for hobbyists, makers, and lab enthusiasts. A PyQt6 graphical interface configures the instruments and the project files; the instruments are driven through **logical calls** (`set_voltage`, `read_scan`, ...) that the instrument library (`Instruments_LIB`) translates into the commands of each model, so the software does not depend on the brand of the instrument. Instruments are reached over LAN, USB-TMC, GPIB or serial (RS-232) through VISA.

> [!IMPORTANT]  
> This software is under active development. Features and stability may change, and some parts may be incomplete or experimental. Most instrument models in the library are marked **experimental**: they are written from the manuals and have not been tried on a real instrument (see [Supported instruments](#supported-instruments)).

## Main Features

- **Instrument library and logical calls**
  - The JSON library (`Instruments_LIB/instruments_lib.json`) describes every model: interfaces, channels, limits and how each logical call is implemented. The call names and their arguments are fixed per category by the schemas in `Instruments_LIB/schema/`.
  - Three-level selection: type → series → model, with dynamic options; experimental models are shown only when enabled in *Settings*.
  - Serial instruments get their settings (baud rate, parity, stop bits, flow control, terminators) from the library, overridable per instrument.
  - Guided VISA address composition for each interface (LXI, USB-TMC, GPIB, serial). A serial port can be given as a number, as `COM3` or as a device (`/dev/ttyUSB0`).

- **Remote control panel**
  - Power supplies, electronic loads, oscilloscopes and dataloggers are controlled with the same logical calls, whatever the brand.
  - **Dataloggers** are configured from the `.inst` file: function of each channel and scan list. Channels are given by `channel_id` (e.g. `101`) or as `CH1..CHn` with the slot number; temperature channels use the probe and sensor types of the library (e.g. thermocouple type K).
  - **Oscilloscope settings** from a `.was` file: enabled channels are switched on (the others off), probe attenuation is set before the vertical scale, then timebase and trigger (source, slope, level, mode).

- **Manual instruments**
  - A bench supply or load without remote control can be added to a project (*Add manual instrument* in the instrument editor: type, name, maximum voltage and current). A manual instrument is **one channel** (a supply with two outputs is two manual instruments) and is not part of the library.
  - When a value must be set, the software asks the operator with a pop-up ("set X to 10 V, then press OK"); *Cancel* stops the measurement. Manual instruments are not read: readings come from other instruments.

- **Project management**
  - Measurement projects with their configuration files: `.json` (project and variables), `.inst` (instruments), `.eff` (efficiency sweep), `.was` (oscilloscope settings).
  - Dedicated editors for instruments, efficiency sweeps and oscilloscope settings, with advanced naming options for files and instances.
  - Optional PostgreSQL storage of the measurement data; the connection settings are saved with an encrypted password.
  - The automatic execution of the measurements (efficiency sweeps and the other measurement types) is **under development** and not yet available in this version: the *Avvia Efficienza* tab is a placeholder.

- **Tools** (*Tools* menu)
  - **Pulse Generator**: current pulses on an electronic load with a live preview of the trapezoidal waveform (amplitude, base level, width, frequency, rise/fall time). The current and, when the library gives the load's maximum power, the **peak and average power** (P = I × V, with a *working voltage* field) are checked while editing and again at start, when the voltage is read from the load; the parameter changed last is corrected to the largest safe value. Only the commands defined in the library are used.
  - **Hex/Dec/Bin converter**.
  - **Instrument library manager**: browse the library and add instruments to it.

- **Testing instruments from the terminal** (no GUI needed): an interactive instrument shell and a dry run that shows the exact commands a logical call would send; see [Trying an instrument from the terminal](#trying-an-instrument-from-the-terminal).

- **Error handling & validation**
  - Standardized error codes with resource prefixes (`[RESOURCE-XXX]`, e.g. `CALL-xxx` for the instrument calls, `PJDB-xxx` for the project database), shown to the user and logged with the stack trace; see `ERROR_CODES.md`.
  - Validation of user inputs; fully translatable interface (Italian, English, French, Spanish, German).

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
| `ola/library.py`, `ola/call_planner.py`, `ola/parsers.py`, `ola/instrument_handle.py` | The instrument library and the translation of a *logical call* into what an instrument understands: `Library` loads `instruments_lib.json` and the call schemas; the planner turns a call, its arguments and a model into a validated plan of steps; `parsers` turn several raw answers into one logical value; `InstrumentHandle` is what a measurement uses (`handle.call("set_voltage", value=5)`). Guide: [`docs/instrument-calls.md`](docs/instrument-calls.md). |
| `ola/manual_instrument.py` | Manual instruments (a bench supply or load without remote control): the handle asks the operator, through a prompt, to do each action by hand, and checks the values against the instrument's limits. |
| `ola/datalogger_setup.py`, `ola/was_calls.py`, `ola/waveform.py`, `ola/pulse_power.py` | From project files and instruments to logical calls: the datalogger channels of an `.inst` file, the oscilloscope settings of a `.was` file, the transfer of a whole waveform memory, and the power of a current pulse on an electronic load. |
| `ola/serial_config.py`, `ola/tester.py` | Serial (RS-232) settings applied to a VISA resource, and the helpers of the interactive instrument tester (`scripts/instrument_shell.py`): choose a model, connect, run logical calls, self-test a library entry. |
| `ola/form_model.py`, `frontend/ui/FormEditorDialog.py` | An editor window for a measurement file with **no code of its own**: a module puts a `form.json` (sections and fields: text, number with SI prefixes, choice, list, JSON, instrument; some shown only for some values of another field) next to its `module.json`. Every problem the module reports (`check()`) is shown at its field; a required instrument that is not chosen is an error. Strings in five languages. Guide: [`docs/measurement-modules.md`](docs/measurement-modules.md#an-editor-with-no-code-formjson). |
| `ola/modules/sparameters/` | **S-parameters** (`.spm`), a built-in measurement module: one sweep of a network analyzer and its S-parameters as complex curves. It uses only the logical calls `set_frequency_sweep`, `run_sweep` and `read_sparameters` of the library; role `vna` of category `network_analyzer`. Comes with the library session's PR #8 (a row here so that the table is complete once both are merged); not tried on a real VNA. |
| `ola/modules/regulation/`, `ola/sim_bench.py` | **Line and load regulation** (`.reg`) of a converter: the output against the input voltage (line regulation in % and mV/V) and against the load current (load regulation in % and the **output resistance** in milliohms). A supply feeds the input, an electronic load draws the current and a **multimeter or a datalogger channel** reads the output (and, if asked, the real input at the converter, which shows the drop in the cables). Safe: the load is at 0 A before the supply is on, a test above the limits is refused before anything is switched on, and load and supply are switched off at the end also after an error. A regulation out of limits is a result. Guide: [`docs/regulation.md`](docs/regulation.md). `sim_bench.py` is the simulated converter, supply, load and meter used by the tests. |
| `ola/modules/ripple/` | **Ripple and noise** (`.rpl`) of a supply output with an oscilloscope: peak-to-peak and rms of the AC part (AC coupling and 20 MHz limit by default), the frequency of the ripple and its harmonics from the spectrum, the noise left once the ripple is taken away, the worst of several captures, a pass / fail check, and optionally the ripple **against load current** with an electronic load (switched off at the end, also after an error). Warns when the signal clips the screen, the converter resolution limits the result or the record is too short. Guide: [`docs/ripple.md`](docs/ripple.md). |
| `ola/modules/attenuator/` | **Attenuator** (`.att`): how much an attenuator attenuates against frequency with a VNA - mean, lowest and highest attenuation, flatness, slope, deviation from the nominal value, the return loss of both ports, the attenuation at chosen frequencies, and a pass / fail check against the nominal value with a tolerance or a mask. For fixed and step attenuators (one setting per run). A value out of tolerance is a result, not an error. Guide: [`docs/attenuator.md`](docs/attenuator.md). |
| `ola/modules/amplifier/` | **RF amplifier** (`.amp`) with a two-port VNA: gain (peak, flatness, 3 dB band), input and output return loss, reverse isolation, the **stability** factors K and mu (can it oscillate? and in which bands), and optionally the **1 dB compression point** from a power sweep. Protects the amplifier and the VNA: a power above the amplifier's maximum input is refused before anything is sent, and the source power is put back after the compression test, also if it fails. Guide: [`docs/amplifier.md`](docs/amplifier.md). |
| `ola/modules/antenna/` | **Antenna impedance** (`.ant`): S11 of an antenna read as an impedance - `R + jX` against frequency, the **Smith chart** (the view the window opens with), the resonances (series and anti-resonances), the best match, the usable band and its fractional bandwidth, and at chosen frequencies the impedance and the series component that would cancel the reactance. Guide: [`docs/antenna.md`](docs/antenna.md). |
| `ola/modules/filter/` | **Filter** (`.flt`): the response of a low-pass, high-pass, band-pass or band-stop filter with a VNA - insertion loss, cut-off or band edges at -3 dB below the peak, bandwidth, centre and Q, notch depth, passband ripple, gain at chosen frequencies, group delay, return loss, and a pass / fail **mask** on the gain. An edge outside the sweep is reported, not invented. Guide: [`docs/filter.md`](docs/filter.md). |
| `ola/vna_common.py`, `ola/modules/return_loss/` | What the VNA measurements share (sweep and common parameter checks, the question about calibration and connection, setting the sweep, reading and averaging S-parameters, normalising the data) and **Return loss / VSWR** (`.rtl`): S11 against frequency - return loss, VSWR, impedance, the best and worst match, the bands where the VSWR stays under a limit (the bandwidth of an antenna), pass / fail on the return loss. Guides: [`docs/return-loss.md`](docs/return-loss.md) and, for the library, [`docs/vna-calls.md`](docs/vna-calls.md) (the calls of the network analyzer category). |
| `ola/modules/cable/`, `ola/sim_vna.py` | **Cable characterization** (`.cbl`): the loss of an RF cable against frequency with a VNA (calibrated beforehand by the user) - insertion loss in dB and per metre, loss at chosen frequencies, group delay and velocity factor, return loss, and a pass / fail check against a limit; transmission (S21) or reflection (S11 with an open or short). Its editor comes from its `form.json` and warns when the sweep is too coarse for the cable. `SimVna` is a simulated VNA with a cable to try it without hardware. Guide: [`docs/cable.md`](docs/cable.md). |
| `ola/assets.py`, `ola/labels.py`, `frontend/ui/label_paint.py`, `frontend/ui/AssetsDialog.py`, `frontend/ui/AssetEditDialog.py`, `frontend/ui/LabelDialog.py` | The **registry of cables and devices** and their **labels**. Every physical object measured (cable, antenna, filter, amplifier, attenuator, adapter...) has a code (`CBL-0042`, never reused) and a card, in one JSON file shared by all projects; the runs that used it are found by the code they saved. A label shows the code, a **QR code** (`OLA:CBL-0042`, a normal QR, not a Micro QR) and a few lines of text, drawn in millimetres: a single label, a **flag** for a thin cable (the same text either side of a fold) or a sheet of labels on a normal printer (skipping the labels already used); written as SVG, PDF at the real size, or PNG. Lines that do not fit are reported, not hidden. Needs `segno`. Windows: *Tools > Cables and devices* (cards, scan a code, history with *Compare*, labels); the measurement editors pick the code from the registry and every run keeps the card of that day. Guide: [`docs/assets.md`](docs/assets.md). |
| `ola/compare.py`, `frontend/ui/CompareDialog.py` | The **Compare results** tool (*Tools* menu, and *Compare...* in the project window): pick two or more saved runs and see them together - the curves they have in common overlaid, in dB / loss / phase / on the Smith chart, or the **difference** from a reference run with its largest value, mean and RMS; the summary figures side by side with the change from the reference; and, for runs with many points, any column against another. Export to CSV and PNG. Guide: [`docs/compare.md`](docs/compare.md). |
| `ola/wiring.py`, `frontend/ui/WiringDialog.py`, `ola/modules/*/wiring.json` | The **connection diagram** of a measurement: which instrument goes where, from a `wiring.json` that each module brings (so it is updated with the module) and from the parameters of the file (the amplifier shows its attenuator only if it has one, the cable its open or short end...). It is a picture (**your own drawings** dropped next to the module, or a diagram drawn by the program) and a **numbered list of what to connect to what**, written from the file (*connect channel 101 of daq1 to «vin»*). Shown before a measurement starts (*Start* / *Cancel*, with a tick to turn it off) and by the *Connections...* button of the project window; written as SVG. Every picture has a **placeholder** in its module folder (`scripts/make_picture_placeholders.py` writes them from the work list `docs/wiring-images.md`): the program ignores it until it is replaced by a real drawing. Guide: [`docs/wiring.md`](docs/wiring.md). |
| `ola/fixtures.py` | **Taking cables, adapters and pads out of a transmission measurement** (no Qt): a device measured through a cable, an adapter or a pad on port 1, port 2 or both. The fixture (named by its **registry code**, a cable or attenuator run, or a `.s2p` file written as seen from the VNA) is taken out, so the result is of the device alone. **Matched** model (the fixtures only attenuate: `S21 / (T1 T2)`) or **full** (the fixtures have reflections: transfer matrices, exact for any fixture; reads all four S-parameters), **complex** or **magnitude** mode. Used by the filter and attenuator measurements through `correction`, which keep the raw curves. Guide: [`docs/deembedding.md`](docs/deembedding.md). |
| `ola/deembed.py` | **Taking a cable out of a reflection measurement** (no Qt): an antenna or a device measured at the end of a cable looks better matched than it is, because the cable's loss weakens the reflection twice. With the cable already measured (by its **code in the registry**, a cable run file or a Touchstone file) the reflection of the device alone is `S11 measured / T^2`, with the phase (complete, so the impedance and the Smith chart are corrected too) or with the loss alone (VSWR and return loss). The return loss and antenna measurements use it through their `correction` parameter and keep the raw curves beside the corrected ones. Guide: the section *Through a cable* of [`docs/return-loss.md`](docs/return-loss.md). |
| `ola/spectrum.py`, `ola/sim_scope.py` | `spectrum.py` (no Qt): the amplitude spectrum of a sampled signal (Hann window, `numpy` when installed, plain Python otherwise), the peaks in it and the noise outside the peaks; used by ripple and noise and by the measurements to come that look at a signal in frequency. `sim_scope.py`: a simulated oscilloscope on a switching supply (ripple, spikes, noise, AC coupling, bandwidth limit, converter resolution, screen clipping) and a simulated load, to try the oscilloscope measurements without hardware. |
| `ola/rf.py`, `ola/limits.py` | Shared by the RF measurements (no Qt): dB, insertion / return loss, VSWR, impedance from the reflection coefficient, group delay and velocity factor, a curve at one frequency, level crossings (the -3 dB points), **Touchstone** `.s1p`/`.s2p` reading and writing; and **pass / fail limits** on a curve (a constant, a line, or one limit per band) that turn a result into a verdict. `ola.runs` exports the traces of a run to CSV and Touchstone. |
| `ola/vna_calibration_flow.py` | **Guided calibration of a network analyzer**, the same for every VNA (no Qt, no terminal): a list of steps (connect a standard, measure it) walked by `CalibrationSession` with the logical calls `calibration_begin`, `calibration_measure` and `calibration_apply`, for an instrument that calibrates itself and for one whose driver calibrates in software. A finished calibration is saved as a `.cal.json` record next to the project and listed in the project file; a software calibration can be restored for the same sweep. |
| `ola/vna_calibration.py` | **Software calibration of a network analyzer** that returns raw data (the LiteVNA), no Qt: the raw sweeps of the calibration standards (open, short, load, thru) give the error terms per frequency (three for a reflection, the thru for a transmission response) and the correction is applied to every following sweep. The standards are ideal: the offsets and the fringing capacitance of a real kit are ignored. |
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

- Python 3.10+
- PyQt6
- GCC (for backend compilation)
- Git (the instrument library `Instruments_LIB` is a submodule)
- Additional Python packages listed in `requirements.txt`

## File List and Description

### Core Application
- `frontend/launcher.py` — Application launcher with environment setup
- `frontend/main.py` — Application entry point (PyQt6)
- `frontend/ui/main_window.py` — Main window, menus and project file list
- `ola/` — Qt-free code shared by the GUI and the terminal tools: instrument library loader and call planner, instrument handles, manual instruments, transport, measurement core
- `backend/` — Legacy C backend (raw TCP for LXI instruments): not used by the GUI any more and to be retired

### Instrument Library & Configuration
- `Instruments_LIB/` — The instrument library (git submodule, [mede-erik/Instruments_LIB](https://github.com/mede-erik/Instruments_LIB))
  - `instruments_lib.json` — All supported models
  - `schema/` — The logical calls of each category (the contract between the software and the library) and `schema/README.md` (format of a library entry)
  - `COMMAND_NAMES.md` — Mandatory and optional calls of each category
  - `TESTING.md` — How to test an instrument of the library and report the result
- `frontend/ui/` — Dialog boxes and UI components (one file per window)
  - `RemoteControlTab.py` — Remote control panel
  - `InstFileDialog.py`, `InstrumentConfigDialog.py` — Instrument configuration editor (library and manual instruments)
  - `EffFileDialog.py` — Efficiency sweep editor
  - `WasFileDialog.py` — Oscilloscope settings editor (channels, timebase, trigger)
  - `AddInstrumentDialog.py` — Three-level instrument selection (type → series → model)
  - `AddressEditorDialog.py` — Guided VISA address composition
  - `DataloggerSlotConfigDialog.py` — Slot-based module configuration for modular dataloggers
  - `PulseGeneratorDialog.py` — Electronic load pulse generator with waveform preview
  - `HexDecConverterDialog.py` — Hex/Dec/Bin converter

### Scripts
- `scripts/instrument_shell.py` — Interactive instrument tester (see below)
- `scripts/dry_run_call.py` — Shows the commands a logical call or a `.was` file would send to a model, without hardware
- `scripts/check_translations.py` — Checks that the five language files have the same keys and that every key used in the code exists

### Translation & Localization
- `frontend/lang/it.json`, `en.json`, `fr.json`, `es.json`, `de.json` — Translations for the GUI
- `frontend/core/Translator.py` — Translation management system

### Core Functionality
- `frontend/core/` — Core modules for database, error handling, validation, and utilities
  - `ProjectDatabaseManager.py` — PostgreSQL project database (one database per project, one table per run)
  - `database_config.py` — Database connection settings, stored with an encrypted password
  - `LoadInstruments.py` — Instrument library interface used by the GUI
  - `errorhandler.py` — Centralized error handling with standardized error codes ([RESOURCE-XXX] format)
  - `validator.py` — Input validation functions
  - `tools.py` — Reusable utility functions
  - `Translator.py` — Multi-language translation system

### Documentation
- `README.md` — This documentation file
- `LICENSE` — License information (GPL v3)
- `ERROR_CODES.md` — Complete reference of standardized error codes
- `PLAN.md` — Design decisions and development status
- `CLAUDE.md`, `AGENTS.md` — Guidance for code assistants (commands, architecture, rules)
- `Open-Lab-Automation.code-workspace` — VS Code workspace settings
- `Instruments_LIB/docs/` — Instrument manuals and documentation
- `examples/` — Example projects and configuration files


## Getting Started

### Installation
1. Clone the repository:
   ```bash
   git clone --recurse-submodules https://github.com/mede-erik/Open-Lab-Automation.git
   cd Open-Lab-Automation
   ```
   If you already cloned without `--recurse-submodules`, download the instrument library with:
   ```bash
   git submodule update --init
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Compile the C backend (optional, for direct instrument communication):
   ```bash
   bash backend/build.sh
   ```
   This builds the shared library `backend/libbackend.so` (Linux/macOS) or `backend/backend.dll`
   (Windows, MinGW/MSYS). Manual build on Linux:
   ```bash
   gcc -shared -fPIC backend/*.c -Ibackend -o backend/libbackend.so -lm
   ```

4. Launch the application:
   ```bash
   python frontend/launcher.py
   ```

### Trying an instrument from the terminal
The instrument shell connects to one instrument of the library and runs its logical calls, showing exactly which commands are sent and what comes back. It is the quickest way to check a library entry against a real instrument (see `Instruments_LIB/TESTING.md`).

```bash
python scripts/instrument_shell.py          # choose category, model and interface, then connect
python scripts/instrument_shell.py --sim    # no hardware: a simulated instrument answers
```

Once connected, `help` lists the commands. The main ones:

| Command | What it does |
|---|---|
| `calls` / `missing` | list the calls the model defines / the mandatory calls it lacks |
| `call NAME a=v ...` | run a call (missing arguments are asked) |
| `plan NAME a=v ...` | show the commands without sending them |
| `readback NAME` | read back the value of a set call |
| `test [writes] [all]` | run every call that needs no argument (`writes` also runs the actions) |
| `was FILE.was [plan]` | apply the settings of an oscilloscope `.was` file |
| `fullwave CH`, `save FILE.csv`, `stats` | read the whole memory of a channel, save the last waveform, show its statistics |
| `serial`, `probe`, `loopback`, `raw TEXT` | RS-232 settings, find the settings an instrument answers to, adapter test, send a raw string |

The arrow keys recall previous commands (kept between sessions) and Tab completes them; on Windows this needs `pyreadline3` (in `requirements.txt`).

To see the commands a call would send to a model, without any instrument:

```bash
python scripts/dry_run_call.py --model OSC_Siglent_SDS824X_HD --call set_channel_scale --arg channel_number=1 --arg value=0.5
python scripts/dry_run_call.py --model OSC_Rigol_DS1054Z --was project.was
```

### Running the tests
```bash
pytest                                  # all tests (tests/ and the test_*.py files at the root)
python scripts/check_translations.py    # language files
```

### Supported instruments
The library currently describes:

| Category | Series |
|---|---|
| Power supplies | OWON ODP, Keysight E36300, TDK-Lambda GEN, Rohde & Schwarz HMP, HP E3631A |
| Electronic loads | Chroma 6330A, Keysight EL4900, Siglent SDL1000X-E |
| Oscilloscopes | Tektronix 5 Series MSO, Rigol DS1000Z, Siglent SDS HD |
| Dataloggers | Agilent 34970A, Keysight 34972A, Keysight DAQ970A/DAQ973A |
| Switch units | Agilent 3499A |
| Multimeters | HP 3478A, Agilent 34401A (no call schema yet, never tried) |
| Network analyzers | Zenko LiteVNA (driver-based, experimental, never tried on a real instrument) |

Tried on a real instrument so far: **Agilent 34970A** over RS-232 and **Siglent SDS824X HD** over LAN (readings, settings, 8/16-bit waveforms and whole-memory transfers, `.was` files). All the other models are written from the manuals; many are marked experimental in the library. Reports of tests on other instruments are welcome: `Instruments_LIB/TESTING.md` explains how to test and what to report.


### Quick Start
1. Create a new project or open an existing one
2. Add instruments using the three-level selection (Type → Series → Model), or add a manual instrument for a bench supply or load without remote control
3. Configure instruments:
   - For dataloggers with slots: use the "Configure Datalogger Slots" button to select modules
   - For other instruments: configure channels, variables, and measurement settings
4. Set up efficiency sweeps with nested variables in the `.eff` file editor
5. Configure oscilloscope acquisition and trigger in the `.was` file editor
6. Use the remote control panel to drive the instruments; the automatic run of the measurements is under development

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
- Testing instruments of the library on real hardware and reporting the results (`Instruments_LIB/TESTING.md`)
- Adding the call schema of new instrument categories in `Instruments_LIB/schema/`
- Adding new measurement capabilities
- Documentation improvements

## License

See the LICENSE file for details.

## Support

For bug reports and feature requests, please use the [GitHub Issues](https://github.com/mede-erik/Open-Lab-Automation/issues) page.

When reporting errors, please include the error code (e.g., [DL-001]) shown in the error message for faster troubleshooting.

