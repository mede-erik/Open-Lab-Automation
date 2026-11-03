# Efficiency measurement (`.eff`)

The efficiency measurement works for a converter or for anything that needs an efficiency. It does not
know about topologies: you describe **parameters** (what you set, what you read), the **sweeps** over
them, what to do at **every point**, and the **formulas** that give input power, output power and
efficiency. The engine runs it ([engine.md](engine.md)); the file is the `params` of a measurement file
with the extension `.eff` (the old `.eff` format is not read).

## How a measurement runs

```
for every point of the sweep:
    set the parameters that changed          (in the order of your list)
    wait  settle_s
    take  samples  readings, interval_s apart   -> each one is stored (table "samples")
    average every reading, compute the formulas -> the point (table "points")
```

At the very first point everything is set, then the `startup` calls are made (outputs on). At the end,
and after any error or stop, the `shutdown` calls are made (outputs off).

## The file

```json efficiency.eff
{
  "variables": [
    {"name": "iout",
     "set": {"instrument": "load1", "call": "set_current_level"},
     "sweep": {"start": 0.5, "stop": 2.5, "points": 3},
     "reads": {"load": {"instrument": "load1", "call": "read_current"}}},
    {"name": "vin",
     "set": {"instrument": "psu1", "call": "set_voltage", "args": {"channel_number": 1}},
     "sweep": {"values": [9, 12, 15]},
     "reads": {"psu": {"instrument": "psu1", "call": "read_voltage", "args": {"channel_number": 1}},
               "daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "101"}}},
     "verify": {"read": "daq", "tol_rel": 0.01, "tol_abs": 0.02},
     "limits": {"min": 5, "max": 20}},
    {"name": "vaux",
     "set": {"instrument": "psu2", "call": "set_voltage"}, "value": 12},
    {"name": "iin",
     "reads": {"daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "102"}, "scale": 10}}},
    {"name": "vout",
     "reads": {"daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "103"}}}}
  ],
  "timing": {"settle_s": 8, "samples": 5, "interval_s": 10},
  "derived": {
    "pin": "vin@daq * iin@daq",
    "pout": "vout@daq * iout@load",
    "efficiency": "100 * pout / pin"
  },
  "startup": [{"instrument": "psu1", "call": "output_on"}],
  "shutdown": [{"instrument": "psu1", "call": "output_off"}]
}
```

The names (`vin`, `vout`, `vaux`...) are yours. The `call` names are those of the instrument library, so the
same file works with any supply, load or data logger the library knows. The instruments (`psu1`, `daq1`...)
are the names of the instruments of the project.

### A parameter

| Field | Meaning |
|---|---|
| `name` | your name for it: letters, digits and `_`, no two underscores in a row, not a function name |
| `set` | how the program sets it: `instrument`, `call`, `args` (extra arguments, for example the channel), `value_arg` (name of the value argument, default `value`) |
| `value` | a fixed value, set once (for example an auxiliary supply) |
| `sweep` | the values it takes: `{"values": [...]}`, `{"start", "stop", "points"}`, `{"start", "stop", "step"}`; add `"scale": "log"` for a logarithmic axis |
| `reads` | zero or more readings: `{label: {instrument, call, args, scale, offset}}`; the result is `reading * scale + offset` (for a shunt, `scale` is 1 / resistance) |
| `verify` | compare the setpoint with one of its readings (below) |
| `limits` | `{"min", "max"}`: allowed setpoints, checked against every value of the sweep |

A parameter that has `set` needs `value` **or** `sweep`. A parameter without `set` is only read (for
example the input current taken from a shunt).

### The order of the list matters

The list is **ordered** and you can move parameters up and down. The order is two things at once:

* the order in which parameters are set at every point (the first one is set first);
* the nesting of the sweeps: the **first** swept parameter is the fastest (innermost). The second advances
  one step only when the first has done its whole sweep, the third when the second has done its whole sweep.

With `iout` first and `vin` second in the example above, the points are
`(vin 9, iout 0.5)`, `(9, 1.5)`, `(9, 2.5)`, `(12, 0.5)`, `(12, 1.5)`... Move `vin` to the top and the
supply voltage becomes the fast sweep.

## Names in formulas

| Name | Meaning |
|---|---|
| `vin` | the value that was **set** (the setpoint of that point) |
| `vin@daq` | the **reading** labelled `daq` of `vin`; `vin@psu` is the reading made by the supply |
| `pin`, `efficiency`... | another derived quantity |

You choose which reading goes into a calculation by writing it: `vin@daq * iin@daq` computes the input power
from the data logger, `vin@psu * iin@psu` from the supply's own readback. A parameter that is only read has no
setpoint, so plain `iin` is an error with the fix in the message ("use iin@daq").

A formula is plain arithmetic: numbers, `+ - * / **`, parentheses and `abs min max sqrt log log10 exp`. It
is never run as code. If a formula cannot be computed at a point (division by zero when `iout` is 0, a
missing value), that value is stored empty and the measurement goes on.

## At every point

`timing`: `settle_s` (wait after setting), `samples` (how many readings), `interval_s` (time between them).
The point is the **average of each reading**; the formulas are computed on the averages. "Five readings
every 10 s" is `samples: 5, interval_s: 10`; "one reading after 8 s" is `settle_s: 8, samples: 1`. Every
single reading is also stored, so you can see the converter warming up.

## Checking that the instrument did what was asked

With `verify` the program compares the setpoint (`vin`) with the reading you name (`vin@daq`) on every
sample. The tolerance is `tol_abs + tol_rel * |setpoint|`. If the reading is off:

| `on_fail` | What happens |
|---|---|
| `ask` (default) | the measurement **stops and asks**: *"vin read by daq (10.8) differs from the set value (9) by 20.0%"* with the buttons **Retry**, **Abort**, **Skip** |
| `warn` | a warning in the log, the measurement goes on |
| `stop` | the measurement fails without asking |

* **Retry** sets every parameter again, waits, and measures the point again.
* **Abort** ends the measurement (state *stopped*); the shutdown calls are made.
* **Skip** goes on. It is remembered while the setpoint of that parameter stays the same, and the affected
  points have a `verify_skipped` column; a new setpoint is checked and asked about again.

The question reaches the interface as a `question` event (with the numbers in `data`, so a dialog can format
and translate it); the interface answers with `runner.answer(id, choice)`. In scripts without a user,
`Runner(..., unattended="skip")` answers by itself. The question and the answer are written in the run file.

## Checking the file while it is being written

`ola.efficiency_spec.validate_params(params, bound_instruments, checker)` returns the list of problems, each
with the **path of the field** (`variables[1].set.call`, `derived.pin`, `timing.samples`...), a message that
says what to do, and a severity (`error` stops the measurement, `warning` does not). It does no I/O and is
meant to be called at every edit of the dialog, so a mistake is shown next to the field where it is made:

* names that do not exist, with a suggestion ("unknown name 'pot' (did you mean 'pout'?)");
* a reading label that does not exist, with the available ones;
* a formula that does not parse, or that depends on itself;
* a sweep that does not make sense, a setpoint outside `limits`, a missing value;
* an instrument that is not in the project (with a suggestion).

`bound_instruments` are the instruments of the project. The optional `checker` is the second level: the
application asks the instrument library whether each call exists and whether each value (the extremes of
every sweep) is acceptable for that instrument, so *"20 V is above the 15 V maximum of psu1"* appears while the
value is typed. The same check is made again before the measurement starts, for files edited by hand.

## Results

Two tables, written while the measurement runs ([engine.md](engine.md#files)):

* `points`: one row per point: the setpoints, the averaged readings (`vin@daq`...), `n_samples`, the derived
  quantities (`pin`, `pout`, `efficiency`) and, if any, `verify_skipped`;
* `samples`: one row per reading: `point`, `attempt` (1, or 2... after a retry), `sample`, the setpoints
  and the readings.

`ola.runs.export_points_csv(run, csv)` exports `points`; add `table="samples"` for the other one.

## Not done yet

The editor dialog (`frontend/ui/`), the "start measurement" action of the GUI, and the plots. The measurement
has been tested against simulated instruments only, not on real hardware.
