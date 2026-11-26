# Roadmap

This page lists what is planned. For what works today, see [Measurements](Measurements) and [Supported instruments](Supported-Instruments); for what is not yet tried on real hardware, [Software test status](Software-Test-Status). The detailed design, decisions and open points are in the repository's [`PLAN.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/PLAN.md).

## First Alpha

The goals of the first alpha are the issues of the milestone [First Alpha](https://github.com/mede-erik/Open-Lab-Automation/milestone/1). In short:

- **Hardware validation**: one model per category tried end to end on real hardware, and the real GPIB adapter tested on Windows and Linux.
- **Project format**: the oscilloscope settings file becomes a definition file of the project, a project made with an older version is converted after the user confirms, with a backup.
- **Waveforms**: an oscilloscope waveform acquired at some steps of the converter measurements.
- **Pulse generator**: moved from the *Tools* menu to a measurement.
- **Documentation**: this wiki, and the library's wiki.
- **Tests**: more coverage of the remote control tab and the pulse generator.

## Later

- **Measurement report**: an HTML report that can be saved as PDF, built from a template the user can edit. For now the results are exported as CSV (and Touchstone for RF traces).
- **Measurement templates**: ready-made measurement files to choose from *New measurement*, for the measurements that are a variation of an existing module.
- **More measurement modules**: load transient, battery discharge.
- **Several oscilloscope settings files** in one project.
- **A frozen module API** (`api_version` 1) before modules written by others are promised compatibility.
