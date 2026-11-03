# Example projects

The projects in this folder are **fictitious**: they show what the software does and are used to test it. The instrument addresses are examples (`192.168.1.xxx`), so without real instruments the measurements show `NC` (not connected). The project is kept consistent with the instrument library by `tests/test_example_project.py`.

## `test-dcdc-project/`: DC-DC converter test

| File | Content |
|---|---|
| `Test DC-DC Converter.json` | project file: variables, `.inst`, `.eff` and `.was` files |
| `test_instruments.inst` | the instruments of the project |
| `osc1.was` | oscilloscope settings (timebase, vertical scales, trigger) |
| `Wav_setup.was` | a second oscilloscope setting (1 channel, 50 mV/div, 10 ms/div) |
| `eff.eff` | efficiency sweep of the `Vaux` supply from 5 V to 10 V in 5 points |

### Instruments

| Name | Type | What it is |
|---|---|---|
| `HC` | power supply | Keysight E36312A (library): `Vdrive` 6 V / 5 A, `Vcc` 25 V / 1 A |
| `VIN` | power supply | **manual instrument**: the input supply, 60 V / 10 A |
| `AUX` | power supply | **manual instrument**: the auxiliary supply `Vaux`, 15 V / 2 A |
| `LOAD` | electronic load | **manual instrument**: `Iout`, 60 V / 20 A |
| `DAQ` | datalogger | Keysight 34972A (library) with a 34901A in slot 1: `VOUT` (101), `VIN_monitor` (102, 10:1 divider), `Temp_Q1` (103, type K thermocouple) |
| `OSC` | oscilloscope | Siglent SDS824X HD (library): `Vd_Q1` on CH1 and `Vs_Q1` on CH2, 10:1 probes |

### Manual instruments

`VIN`, `AUX` and `LOAD` have no remote control and are **not** in the instrument library: each one is a generic instrument with a type, a name and the limits of its single channel (`is_manual: true`, no `model_id`). When a measurement has to change one of them, a popup asks the operator to set it, and the measurement goes on after OK. They cannot be read, so the readings come from the datalogger. Add your own with *Add manual instrument* in the instrument editor.

## `Test_scpi/`

A single OWON SPE6103 supply on the serial port `ASRL1::INSTR`, to try the remote control of a supply.

## How to use an example

1. Start the application: `python frontend/launcher.py`.
2. *File*, *Open project*, then choose `examples/test-dcdc-project/Test DC-DC Converter.json`.
3. In the *Remote Control* tab the measurements of the datalogger are at the top and the controls of the supplies and the load below.

To make your own project, copy the folder, rename the files, edit the instruments in the editor and set the real addresses.
