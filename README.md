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
5. Configure oscilloscope acquisition in the `.was` file editor
6. Start measurements and monitor results

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
- Enhancing the C backend with new protocols
- Adding new measurement capabilities
- Documentation improvements

## License

See the LICENSE file for details.

## Support

For bug reports and feature requests, please use the [GitHub Issues](https://github.com/mede-erik/Open-Lab-Automation/issues) page.

When reporting errors, please include the error code (e.g., [DL-001]) shown in the error message for faster troubleshooting.

