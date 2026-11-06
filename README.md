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
- **Backend:** C — Fast, low-level communication layer for instrument control
- **Instrument Library:** JSON (`Instruments_LIB/instruments_lib.json`) — Extensible database of supported instruments
- **Configuration Files:**
  - `.inst` — Instrument configuration and channel setup
  - `.eff` — Efficiency measurement sweeps with nested variable support
  - `.was` — Oscilloscope waveform acquisition and trigger settings
  - `.json` — Project metadata and variable definitions

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

