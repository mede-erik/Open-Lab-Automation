# Tools

The *Tools* menu of the main window, and the command-line tools of the repository.

## In the GUI

| Tool | What it is for |
|---|---|
| **Pulse Generator** | Current pulses on an electronic load with a live trapezoidal preview. The peak and average power are checked against the load's limits while editing and again at the start. Only library commands are used. |
| **Hex / Dec / Bin converter** | Number base conversion. |
| **Instrument library manager** | Browse the library and add instruments. |
| **GPIB adapters** | Set up adapters, check their driver, scan the bus, IFC / REN, a console. See [docs/gpib-adapters.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/gpib-adapters.md). |
| **Cables and devices** | The registry: a code (`CBL-0042`) and a card for each measured object, its history, and printable **labels** with a QR code. See [docs/assets.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/assets.md). |
| **Compare results** | Overlay saved runs, or show the difference from a reference run. See [docs/compare.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/compare.md). |
| **Trend** (in a cable's history) | Cable loss against the date, with a verdict before the cable is out of use. See [docs/trend.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/trend.md). |
| **Calibrate VNA** (project window) | Guided calibration of a network analyzer, with a calibration kit. See [docs/engine.md](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/engine.md). |

## From the terminal

| Command | Purpose |
|---|---|
| `python scripts/instrument_shell.py [--sim]` | Interactive shell: run any logical call, read back values, transfer waveforms, check the RS-232 settings. |
| `python scripts/dry_run_call.py --model MODEL --call NAME --arg k=v` | Print the commands a call would send. Works without hardware. |
| `python scripts/dry_run_call.py --model MODEL --was project.was` | Print the commands of an oscilloscope settings file. |
| `python scripts/golden_check.py` | Check a run against a golden sample; exit code gives the verdict. |
| `python scripts/cable_trend.py` | Cable ageing from the saved runs. |
| `python scripts/check_translations.py` | Check that all five languages have the same keys. |
| `python -m frontend.ui.CompareDialog run1.jsonl run2.jsonl` | Compare two runs in the window. |
| `python -m frontend.ui.AssetsDialog [runs folder]` | Open the cables and devices registry. |
