# Open Lab Automation — Wiki

**Open Lab Automation (OLA)** is an open-source suite for automated electrical measurements, made for hobbyists, makers and lab enthusiasts. A PyQt6 window configures the instruments and the projects; the instruments are driven with **logical calls** (`set_voltage`, `read_scan`, ...) that the [instrument library](https://github.com/mede-erik/Instruments_LIB) translates into the commands of each model, so the software does not depend on one brand.

> **Status: under active development, heading for the First Alpha.** Most instrument models are marked *experimental*: they were written from the manuals and have not been tried on a real instrument. The measurements have been tried with simulated instruments; the list of what still has to be run on real hardware is [Software test status](Software-Test-Status).

## Start here

| If you want to... | Read |
|---|---|
| install it | [Installation](Installation) |
| make your first project | [Quick start](Quick-Start) |
| know what each measurement does | [Measurements](Measurements) |
| use the tools (cables and labels, DUTs, GPIB, golden samples...) | [Tools](Tools) |
| fix a connection problem | [Troubleshooting](Troubleshooting) |
| add an instrument or a measurement | [Developer guide](Developer-Guide), [Writing a measurement module](Writing-a-Measurement-Module) |
| understand an error code | [Error codes](Error-Codes) |
| run the tests | [Testing and CI](Testing-and-CI) |

## Pages

- **Users**: [Installation](Installation) · [Quick start](Quick-Start) · [Projects and instruments](Projects-and-Instruments) · [Measurements](Measurements) · [Tools](Tools) · [Supported instruments](Supported-Instruments) · [Troubleshooting](Troubleshooting) · [Glossary](Glossary)
- **Developers**: [Developer guide](Developer-Guide) · [Writing a measurement module](Writing-a-Measurement-Module) · [Instrument library](Instrument-Library) · [Testing and CI](Testing-and-CI) · [Error codes](Error-Codes) · [Contributing](Contributing)
- **Project**: [Software test status](Software-Test-Status) · [Roadmap](Roadmap)

The authoritative documentation is in the repository, in `README.md` and `docs/`. These wiki pages are the entry point and link to it; when they disagree, the repository wins.

## Disclaimer

OLA is for hobbyist and non-professional use only. It is provided "as is", without warranty. It is not intended for professional, industrial or safety-critical use.

License: GPL v3.
