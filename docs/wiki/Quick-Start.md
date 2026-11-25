# Quick start

1. **Create or open a project** (*File* menu). A project is a folder with a `<project>.json` file and the files of its measurements.
2. **Add the instruments**. Use the three-level selector *type → series → model*. A bench supply or load without remote control is added as a **manual instrument** (one channel per instrument).
3. **Configure the instruments**: channels, limits, timeout, serial settings, and for network analyzers the ports and the usual sweep. Dataloggers take their modules from the *Configure datalogger slots* button.
4. **Create a measurement** in the *Measurements* tab (*New*). The type is chosen among the measurement modules; each one has its own editor.
5. **Start it**. Before the run, the connection diagram is shown (*Start* / *Cancel*). The run window shows progress, a live table, plots, the log and the questions the measurement may ask you (for instance "set the supply to 10 V, then press OK").
6. **Read the results**. Each run is saved in `runs/` of the project as it happens. Export to CSV, or to Touchstone for RF data. *Tools > Compare results* puts runs side by side.

To try everything without hardware, open the demo project from the terminal:

```bash
python -m frontend.ui.ProjectWindow          # no argument: demo project with simulated instruments
python -m frontend.ui.RunWindow --fault      # a run that asks a question
```

For a first real instrument, use the terminal shell before the GUI:

```bash
python scripts/instrument_shell.py          # pick category, model and interface, then connect
python scripts/instrument_shell.py --sim    # no hardware
```

Inside the shell, `calls` lists the logical calls, `call NAME a=v` runs one, `plan NAME a=v` shows the commands without sending them. See [Testing and CI](Testing-and-CI) and the repository guide `Instruments_LIB/TESTING.md`.

Next: [Projects and instruments](Projects-and-Instruments).
