# Quick start

1. **Create or open a project** (*Project* menu). A project is a folder with a `<project>.json` file and the files of its measurements.
2. **Add the instruments**. Use the three-level selector *type → series → model*. A bench supply or load without remote control is added as a **manual instrument** (one channel per instrument).
3. **Configure the instruments**: channels, limits, timeout, serial settings, and for network analyzers the ports and the usual sweep. Dataloggers take their modules from the *Configure datalogger slots* button.
4. **Create a measurement** in the *Measurements* tab (*New*). The type is chosen among the measurement modules; each one has its own editor.
5. **Start it**. Before the run, the connection diagram is shown (*Start* / *Cancel*). The run window shows progress, a live table, plots, the log and the questions the measurement may ask you (for instance "set the supply to 10 V, then press OK").
6. **Read the results**. Each run is saved in `runs/` of the project as it happens. Export to CSV, or to Touchstone for RF data. *Tools > Compare results* puts runs side by side.

The *Remote control* tab drives a single instrument by hand with the same logical calls, and applies the project's oscilloscope settings (`.was` file).

## Try it without hardware

```bash
python scripts/make_demo_project.py /tmp/demo     # a project with a finished simulated run
python frontend/launcher.py                       # Project > Open > /tmp/demo/demo.json
```

Or open the window of a project alone, with simulated instruments:

```bash
python -m frontend.ui.ProjectWindow
python -m frontend.ui.RunWindow --fault           # a run that asks a question
```

## Try an instrument from the terminal

Before using an instrument in the GUI, check it with the shell:

```bash
python scripts/instrument_shell.py          # pick category, model and interface, then connect
python scripts/instrument_shell.py --sim    # no hardware
```

Inside the shell, `calls` lists the logical calls, `call NAME a=v` runs one, `plan NAME a=v` shows the commands without sending them. To see what a call would send to a model, without any instrument:

```bash
python scripts/dry_run_call.py --model OSC_Siglent_SDS824X_HD --call set_channel_scale --arg channel_number=1 --arg value=0.5
```

The library's `TESTING.md` explains how to test a real instrument and what to report. Next: [Projects and instruments](Projects-and-Instruments).
