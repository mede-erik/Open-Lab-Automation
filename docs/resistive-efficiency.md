# Efficiency with a resistive load (`.rfe`)

It is the [efficiency measurement](efficiency.md) (`.eff`) with **one difference**: the load of the converter is not an
instrument but **real resistors**, so the output current is not set, it follows from the resistance. The file has the same
format, the same editor, the same `points` and `samples` tables, the same formulas, outputs, cooldown, golden sample and device
card. Everything in [`efficiency.md`](efficiency.md) applies; this page is only about the resistors.

Two types of measurement exist (`.eff` and `.rfe`) so that a file says what it is, but both are opened with the same editor.

## The load parameter

A parameter has a `load` instead of `set` / `value` / `sweep`. Its **values are the loads**: the sweep goes through the list,
and the value of the parameter (its name in the formulas) is the nominal resistance of each load.

```json resistive_efficiency.rfe
{
  "variables": [
    {"name": "vin", "set": {"instrument": "psu", "call": "set_voltage"}, "sweep": {"values": [9, 12, 15]},
     "reads": {"daq": {"instrument": "psu", "call": "read_voltage"}},
     "output": {"on": {"instrument": "psu", "call": "output_on"}, "off": {"instrument": "psu", "call": "output_off"}}},
    {"name": "rload",
     "load": {
       "loads": [
         {"name": "10R", "r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"},
         {"name": "22||47", "parallel": [
            {"r_ohm": 22, "tol_pct": 1, "power_w": 2, "channel": "202"},
            {"kit": "PWR", "ref": "R47"}]}
       ],
       "switching": {"mode": "mux", "instrument": "daq", "settle_s": 0.5},
       "vout": "vout@daq",
       "max_vout_v": 6}},
    {"name": "iin", "reads": {"daq": {"instrument": "psu", "call": "read_current"}}},
    {"name": "vout", "reads": {"daq": {"instrument": "dmm", "call": "measure_voltage"}}}
  ],
  "derived": {
    "pin": "vin * iin@daq",
    "pout": "vout@daq * vout@daq / rload",
    "efficiency": "100 * pout / pin",
    "efficiency_min": "100 * vout@daq * vout@daq / rload_max / pin"
  }
}
```

* `loads`: each load is one resistor (`r_ohm`, `tol_pct`, `power_w`, `channel`) or a `series` / `parallel` group of resistors,
  nested as needed (see [`ola/resistors.py`](../ola/resistors.py)). Two loads must not have the same resistance.
* `switching`: `manual` (the program asks you to connect each load, showing its schematic) or `mux` (the relays of the
  `instrument`, a datalogger module or a switch unit, close the `channel` of every resistor of the load: every resistor needs one).
  `settle_s` is the wait after connecting.
* `vout`: the reading of the output voltage (`vout@daq`) that checks the power in the resistors on **every** reading.
* `max_vout_v`: the largest output voltage you expect; checked **before** the run against the rating of every resistor.
* In the formulas, a load parameter called `rload` gives `rload` (nominal ohms), `rload_min` and `rload_max` (the resistance with
  the tolerances of all the resistors at their worst), so the efficiency can be given with the range the tolerances allow.

Where the load sits in the list of parameters is the nesting of the sweep, like any other parameter: put it **after** the input
voltage to try every input voltage on each load (the load changes rarely), before it to change the load at every point.

## Resistors from a kit

A resistor can be `{"kit": "PWR", "ref": "R22"}` instead of its values: the program takes the values from the
[kit](resistor-kits.md) when the measurement starts and writes them in the header of the run, so it is known later which values
were used. In the editor, **Add from a kit...** picks the resistors of a kit (one load each, or all in series or in parallel as
one load), **New load...** types one in, and **Save as a kit...** saves the resistors typed in as a **new** kit: a kit that
exists is never changed.

## What happens at every load change

1. The outputs that the program manages (the supply) are **switched off**.
2. The load is connected: by hand (the operator is asked, with the schematic, and confirms) or by the relays (the previous
   channels are opened, those of the new load closed); then `settle_s`.
3. The parameters are set again and the outputs switched on; the measurement goes on.

On every reading the power in each resistor is computed from the output voltage; if one is above its rating the measurement
stops with a message that names it. At the end, after an error or a stop, the outputs go off first and the relays open after.

## What the instruments must provide

The calls of the efficiency (`set_voltage`, `output_on` / `output_off`, readings) and, for the relays, `close_channel` and
`open_channels` on the multiplexer instrument.

## Not done yet

* The program does not yet compute **combinations of resistors** (series / parallel of a kit) to reach a range of output
  current with equidistant points: for now you write the loads you want.
* Not tested on real hardware (see the test status list in the README).
* The old `.rfe` files of the previous format (`vin_v`, `loads` at the top, `switching`...) are not read: rewrite them as above.
  The `summary` table and the verdict of the previous module are gone; use the `derived` formulas and the golden sample.
