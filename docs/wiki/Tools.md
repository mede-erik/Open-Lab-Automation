# Tools

The *Tools* menu of the main window, and the command-line tools of the repository.

## In the GUI

| Tool | What it is for |
|---|---|
| **Instrument library manager** | Browse the library and add instruments. |
| **Hex / Dec / Bin converter** | Number base conversion. |
| **Compare results** | Overlay saved runs, or show the difference from a reference run. See [docs/compare.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/compare.md). |
| **Cables and devices** | The registry of components: a code (`CBL-0042`) and a card for each cable, adapter, attenuator, and printable **labels** with a QR code. See [docs/assets.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/assets.md). |
| **Devices under test** | The archive of what is tested (antennas, filters, converters), with versions. See [docs/duts.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/duts.md). |
| **Resistor kits** | The power resistors of a bench, kept once and used by the efficiency measurement with a resistive load. See [docs/resistor-kits.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/resistor-kits.md). |
| **GPIB adapters** | Set up adapters, check their driver, scan the bus, IFC / REN, a console. See [docs/gpib-adapters.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/gpib-adapters.md). |
| **Pulse Generator** | Current pulses on an electronic load with a live trapezoidal preview. The peak and average power are checked against the load's limits while editing and again at the start. Only library commands are used. Planned to become a measurement. |

Other windows are in the project window: **Trend** (cable loss against the date, with a verdict before the cable is out of use: [docs/trend.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/trend.md)) and **Calibrate VNA** (a guided calibration of a network analyzer, with a calibration kit).

## From the terminal

| Command | Purpose |
|---|---|
| `python scripts/instrument_shell.py [--sim]` | Interactive shell: run any logical call, read back values, transfer waveforms, check the RS-232 settings. |
| `python scripts/dry_run_call.py --model MODEL --call NAME --arg k=v` | Print the commands a call would send. Works without hardware. |
| `python scripts/dry_run_call.py --model MODEL --was project.was` | Print the commands of an oscilloscope settings file. |
| `python scripts/golden_check.py` | Check a run against a golden sample; the exit code gives the verdict. |
| `python scripts/cable_trend.py` | Cable ageing from the saved runs. |
| `python scripts/make_demo_project.py DIR` | Make a demo project with a finished simulated run. |
| `python benchmarks/bench_hardware.py` | Hardware benchmark on a lab instrument ([docs/benchmark.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/benchmark.md)). |
| `python scripts/check_translations.py` | Check that all five languages have the same keys. |
| `python scripts/add_copyright_headers.py [--check] [FILE...]` | Add (or check) the copyright header of source files. |
| `python -m frontend.ui.CompareDialog run1.jsonl run2.jsonl` | Compare two runs in the window. |
| `python -m frontend.ui.AssetsDialog [runs folder]` | Open the registry of cables and devices. |
