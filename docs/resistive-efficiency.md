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
       "switching": {"mode": "manual", "settle_s": 0.5},
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
* `switching`: `manual` (the program asks you to connect each load, showing its schematic). `settle_s` is the wait after connecting.
  A **switch matrix** (relays that connect the resistors in series or in parallel by themselves) is planned for a future version:
  the editor shows it as not yet usable. The engine still has a first, simple `mux` mode (the relays of an `instrument` close the
  `channel` of every resistor of the load, so they end up in parallel), which is not offered by the editor and not supported.
* `vout`: the reading of the output voltage (`vout@daq`) that checks the power in the resistors on **every** reading.
* `max_vout_v`: the largest output voltage you expect; checked **before** the run against the rating of every resistor.
* In the formulas, a load parameter called `rload` gives `rload` (nominal ohms), `rload_min` and `rload_max` (the resistance with
  the tolerances of all the resistors at their worst), so the efficiency can be given with the range the tolerances allow.

A converter with **several outputs** has one load parameter for each (in the editor: **Add load**), each with its own resistors and
its own `vout` reading; whenever any of them changes the outputs are switched off once, and you are asked to connect only the loads
that changed.

Where the load sits in the list of parameters is the nesting of the sweep, like any other parameter: put it **after** the input
voltage to try every input voltage on each load (the load changes rarely), before it to change the load at every point.

## Resistors from a kit

A resistor can be `{"kit": "PWR", "ref": "R22"}` instead of its values: the program takes the values from the
[kit](resistor-kits.md) when the measurement starts and writes them in the header of the run, so it is known later which values
were used. In the editor, **Add from a kit...** picks the resistors of a kit (one load each, or all in series or in parallel as
one load), **New load...** types one in, and **Save as a kit...** saves the resistors typed in as a **new** kit: a kit that
exists is never changed.

## Loads for a range of output current

In the editor, **Plan from a current range...** calculates the loads for you. You give the kit, the output voltage and the currents
you want, for example 0 to 10 A in 11 points at 12 V, and the program combines **all** the resistors of the kit, in series and in
parallel, nested as far as needed, each physical resistor at most once per load, so that the current at that voltage is as near as
possible to equally spaced targets. It then shows the table (target, combination, resistance, real current, how far it is in
percent of a step, the share of its rating the most loaded resistor carries, and how many resistors must be moved from the previous
point) and, if you accept, **replaces the list of loads** (the resistors stay references to the kit).

* **Output voltage**: *regulated* (a fixed value) or *not regulated*: the conversion ratio times a reference input voltage.
  The plan is only a guide for choosing resistors: in the measurement the current of each point is always the output voltage read
  divided by the resistance, so for a converter that is not regulated the points are equidistant only at the reference voltage.
* **Largest share of the rating** (default 80 %): no resistor of the network carries more than this share of its rating at the
  output voltage, so a resistor of 1 ohm alone is never offered at 12 V with a rating of 100 W (144 W).
* **Fewest moves**: among the combinations near each target the plan prefers the path that moves the fewest resistors from one
  point to the next. The cost of a point is 10 times its distance from the target (in steps) plus the resistors moved.
* **0 A** (no load) is not a load: if the range starts at 0 the plan leaves that point out; make it with the output open.
* **Speed**: the search is in Rust (`native/src/combos.rs`): 15 resistors take about 2 s, 20 about 8 s. Without the native module the
  same steps run in Python, with the same result, about 15 times slower. The method is described in
  [`ola/combinations.py`](../ola/combinations.py).
* The inputs are saved in `load.plan` (only to show them again next time; the measurement uses `loads`).

## What happens at every load change

1. The outputs that the program manages (the supply) are **switched off**.
2. The load is connected: by hand (the operator is asked, with the schematic, and confirms) or by the relays (the previous
   channels are opened, those of the new load closed); then `settle_s`.
3. The parameters are set again and the outputs switched on; the measurement goes on.

On every reading the power in each resistor is computed from the output voltage; if one is above its rating the measurement
stops with a message that names it. At the end, after an error or a stop, the outputs go off first and the relays open after.

## What the instruments must provide

The calls of the efficiency (`set_voltage`, `output_on` / `output_off`, readings) (and, for the not yet supported `mux` mode, `close_channel` and
`open_channels`).

## Not done yet

* The learning sweep (a quick first pass to measure the output voltage of a converter that is not regulated, and re-plan from it) is not done yet.
* The 0 A point (output open) is not a load of the sweep yet.
* Not tested on real hardware (see the test status list in the README).
* The old `.rfe` files of the previous format (`vin_v`, `loads` at the top, `switching`...) are not read: rewrite them as above.
  The `summary` table and the verdict of the previous module are gone; use the `derived` formulas and the golden sample.
