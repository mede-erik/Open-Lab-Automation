# Datalogger channels: range, integration time, zero, input impedance

A channel of a datalogger (an entry of the `.inst` file, edited in the datalogger configuration
dialog) can carry four settings besides its function. Each is left out of the file when it is the
default, so a file that does not use them is unchanged.

| Setting | `.inst` key | Values | What it does |
|---|---|---|---|
| Range | `range` | `"AUTO"` (default) or a number in the units of the function | Fixed range per channel, or auto range. |
| Integration time | `nplc` | power line cycles, e.g. `20`, `100` | More cycles: less noise, slower reading. Left out: the instrument default. |
| Zero | `zero` | `true` | Offset zero with the inputs shorted (see below). |
| Input impedance | `impedance` | `"auto"` or `"10M"` | Automatic (above 10 GOhm on the low DC ranges) or fixed 10 MOhm. DC voltage only. |

The editor offers only what the model of the instrument lists in the library: a model without the
calls has that cell disabled. A model that lacks the calls a saved setting needs is **refused with a
sentence when the measurement starts**; it is never read silently without the setting.

## Reading

`ola/channel_setup.py` turns the settings into the logical calls (`configure_*`, `set_*_nplc`,
`input_impedance_auto`) and wraps the datalogger handle. The wrapped handle reads a configured
channel from the scan list (`select_channels` + `read_scan`) instead of `measure_*`: on the Keysight
34970A/34972A `CONFigure` and `MEASure?` put the integration time, the impedance and the offset
back to their defaults, so a measurement module that calls `measure_dc_voltage` would lose the
settings. Modules do not need to know.

## Zero with shorted inputs

Before the measurement starts (`Runner`, before `setup`), for every channel with `zero` set, one by
one:

1. the program asks to connect the two terminals of the channel together (choices *continue*,
   *skip the zero*, *abort*);
2. it stores the reading as the offset (`null_offset`), waits for it to settle and enables the
   scaling (`set_scale_state`);
3. it asks to connect the terminals back in place.

This is useful for a shunt of a few milliohms, where the offset of the wiring and the thermal
voltages are a large part of the reading. The zero is not available in the *Remote control* tab,
only in measurements.

## Limits

* Only dataloggers whose library entry has the calls (Keysight 34970A / 34972A, DAQ970A / DAQ973A).
* Multimeters (no scan list) and the old datalogger dialog are not covered.
* Tested on a simulated 34970A (`ola/sim_datalogger.py`), not on hardware.
