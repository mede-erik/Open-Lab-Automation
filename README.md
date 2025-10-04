# Open Lab Automation

Open Lab Automation is an open-source suite for automated electrical measurements, designed for hobbyists, makers, and lab enthusiasts. The frontend is a modern Python (PyQt5) graphical interface for instrument configuration and control, while the C backend ensures fast, direct communication with instruments via USB, LAN, GPIB, or serial.

**Note: This software is under active development. Features and stability may change, and some parts may be incomplete or experimental.**

## Main Features

- **Instrument Management**
  - Add, configure, and manage instruments using a flexible JSON library (`Instruments_LIB/instruments_lib.json`).
  - Three-level selection: type → series → model, with dynamic options.
  - Support for power supplies, dataloggers, oscilloscopes, and electronic loads.
  - Detailed configuration of channels/slots, variables, attenuation, measurement type, per-channel enable/disable.
  - Guided VISA address composition for each interface (LXI, GPIB, USB, RS232, ...).
  - Edit already-inserted instruments and manage channel selection.
  - Fully translatable interface (Italian, English, French, Spanish, German).

- **Project Management**
  - Create and manage measurement projects with associated configuration files (.json, .inst, .eff, .was).
  - Advanced naming options for files and instances.
  - Dedicated editors for instruments, efficiency, and oscilloscope settings.
  - **Advanced Efficiency Sweeps**: Multi-variable nested sweep system with configurable order, list/range modes, and timing parameters.
  - **Automatic Measurement**: All project variables (control and measure) are automatically measured during sweeps.

- **Backend Communication**
  - C backend for efficient, direct communication with instruments.
  - Designed to be easily extendable to new instruments and protocols.

## Project Structure

- **Frontend:** Python (PyQt6) — Modern graphical interface with comprehensive instrument management and advanced sweep configuration
- **Backend:** C — Fast, low-level communication layer for instrument control
- **Instrument Library:** JSON (`Instruments_LIB/instruments_lib.json`) — Extensible database of supported instruments
- **Configuration Files:**
  - `.inst` — Instrument configuration and channel setup
  - `.eff` — Efficiency measurement sweeps with nested variable support
  - `.was` — Oscilloscope waveform acquisition settings
  - `.json` — Project metadata and variable definitions

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
  - Various instrument-specific configuration dialogs

### Translation & Localization
- `frontend/lang/it.json`, `en.json`, `fr.json`, `es.json`, `de.json` — Translations for the GUI
- `frontend/core/Translator.py` — Translation management system

### Core Functionality
- `frontend/core/` — Core modules for database, error handling, validation, and utilities
  - `ProjectDatabaseManager.py` — Project and measurement data management
  - `errorhandler.py` — Centralized error handling with standardized error codes
  - `validator.py` — Input validation functions
  - `tools.py` — Reusable utility functions

### Documentation
- `README.md` — This documentation file
- `LICENSE` — License information
- `Open-Lab-Automation.code-workspace` — VS Code workspace settings
- `Instruments_LIB/docs/` — Instrument manuals and documentation

## Disclaimer

**This software is provided for hobbyist and non-professional use only.**

The authors and contributors of Open Lab Automation accept no responsibility for damage to persons, property, or equipment resulting from the use of this software. Use at your own risk. The software is provided "as is", without any express or implied warranty. It is not intended for professional, industrial, or safety-critical use.

## License

See the LICENSE file for details.
