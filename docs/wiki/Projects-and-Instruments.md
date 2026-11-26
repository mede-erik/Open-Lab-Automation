# Projects and instruments

## Project format (version 2)

`<project>.json` has `"format_version": 2` and a `measurements` list. Each entry has an `id`, a `type`, a `name` and a `file`. Every measurement lives in **its own file**, and the extension identifies its type:

| Extension | Measurement |
|---|---|
| `.eff` | efficiency sweep |
| `.rfe` | efficiency with a resistive load |
| `.reg` | line and load regulation |
| `.rpl` | ripple and noise |
| `.tlg` | time log |
| `.spm` | S-parameters |
| `.rtl` | return loss / VSWR |
| `.flt` | filter |
| `.amp` | RF amplifier |
| `.att` | attenuator |
| `.ant` | antenna impedance |
| `.cbl` | cable characterization |
| `.tdr` | time domain (fault location) |
| `.bod` | Bode plot |

The results of each run are written in the `runs/` folder of the project, as JSON Lines, while the measurement runs. The calibrations of a network analyzer are kept in `calibrations/`.

## Definition files

| File | What it holds |
|---|---|
| `.inst` | the instruments of the project: name, library model, VISA address (or *manual*), channels, limits, timeout and, when they differ from the library, serial settings |
| `.was` | the oscilloscope settings (channels, time base, trigger), applied by the *Remote control* tab |

The instrument file editor checks every entry and shows a warning on the instrument that has a problem: a name used twice, a model that is not in the library, a limit above what the model can do, a sweep outside the model's range. A file that cannot be read is never overwritten.

## Renaming and using someone else's project

- Renaming an instrument updates every measurement that uses it, and nothing else (`role_bindings`). Old run files keep the name they had that day.
- Opening a project made by someone else, with instruments you do not have, offers the **role mapping** window: each role is bound to one of your instruments, and a warning says what your instrument can do less than the one used.
- A calibration belongs to one apparatus (its serial number). It is never used with another VNA.

## Instrument identity

Each run keeps, for every instrument, its name, model, **serial number** and firmware (read with `*IDN?`, never typed), and the calibration applied. A saved measurement therefore stays linked to the apparatus that made it.

## Manual instruments

A manual instrument has no remote control. When a value must be set, a pop-up asks the operator to do it by hand; *Cancel* stops the measurement. A manual instrument is always one channel.

## Devices under test and the registry

A **DUT** (the thing being tested: an antenna, a filter, a converter) is kept apart from the **components** in the signal path (cables, attenuators, adapters). Both have a code and a card; see [Tools](Tools) and the guides [`docs/duts.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/duts.md) and [`docs/assets.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/assets.md). A DUT is optional: a measurement can be made without naming one.

## Connection

Connections stay open between runs. The address can be:

- LAN / LXI: `TCPIP0::<ip>::inst0::INSTR` (raw socket or VXI-11)
- USB-TMC: `USB0::...::INSTR` through pyvisa
- GPIB: `GPIB0::<address>::INSTR`, or a Prologix-compatible adapter (`PROLOGIX::<port>::<address>::INSTR`)
- Serial (RS-232): `ASRL<port>::INSTR`, with the settings of the library
- Analog Discovery: `DWF` (the first device) or `DWF::<serial number>`

Errors at connection time carry a `TRN-` or `VISA-` code; see [Error codes](Error-Codes). Repository guide: [`docs/engine.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/engine.md#connecting-the-instruments).
