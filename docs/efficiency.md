# Efficiency measurement (`.eff`)

The efficiency measurement works for a converter or for anything that needs an efficiency. It does not
know about topologies: you describe **parameters** (what you set, what you read), the **sweeps** over
them, what to do at **every point**, and the **formulas** that give input power, output power and
efficiency. The engine runs it ([engine.md](engine.md)); the file is the `params` of a measurement file
with the extension `.eff` (the old `.eff` format is not read).

## How a measurement runs

```
start:    set every parameter; switch the outputs on (always-on ones first, then the power order)
for every point of the sweep:
    set the parameters that changed          (in the order of your list)
    wait  settle_s
    take  samples  readings, interval_s apart   -> each one is stored (table "samples")
    average every reading, compute the formulas -> the point (table "points")
    when the innermost sweep has finished its run and an outer parameter advances:
        cooldown: switch some outputs off, wait cooldown_s, switch them on again
end:      switch the outputs off (except the always-on ones)
```

What happens to the outputs is **your choice, parameter by parameter** (see "Outputs" below).

## The file

```json efficiency.eff
{
  "variables": [
    {"name": "iout",
     "set": {"instrument": "load1", "call": "set_current_level"},
     "sweep": {"start": 0.5, "stop": 2.5, "points": 3},
     "reads": {"load": {"instrument": "load1", "call": "read_current"}},
     "output": {"on": {"instrument": "load1", "call": "load_on"},
                "off": {"instrument": "load1", "call": "load_off"},
                "state": {"instrument": "load1", "call": "query_input_state"},
                "mode": "off_during_cooldown"}},
    {"name": "vin",
     "set": {"instrument": "psu1", "call": "set_voltage", "args": {"channel_number": 1}},
     "sweep": {"values": [9, 12, 15]},
     "reads": {"psu": {"instrument": "psu1", "call": "read_voltage", "args": {"channel_number": 1}},
               "daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "101"}}},
     "verify": {"read": "daq", "tol_rel": 0.01, "tol_abs": 0.02},
     "limits": {"min": 5, "max": 20},
     "output": {"on": {"instrument": "psu1", "call": "output_on"},
                "off": {"instrument": "psu1", "call": "output_off"},
                "state": {"instrument": "psu1", "call": "output_state_query"},
                "mode": "off_during_cooldown"}},
    {"name": "vaux",
     "set": {"instrument": "psu2", "call": "set_voltage"}, "value": 12,
     "output": {"on": {"instrument": "psu2", "call": "output_on"},
                "state": {"instrument": "psu2", "call": "output_state_query"},
                "mode": "always_on"}},
    {"name": "iin",
     "reads": {"daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "102"}, "scale": 10}}},
    {"name": "vout",
     "reads": {"daq": {"instrument": "daq1", "call": "read_ch", "args": {"channels": "103"}}}}
  ],
  "timing": {"settle_s": 8, "samples": 5, "interval_s": 10, "cooldown_s": 600},
  "power_order": ["vin", "iout"],
  "derived": {
    "pin": "vin@daq * iin@daq",
    "pout": "vout@daq * iout@load",
    "efficiency": "100 * pout / pin"
  },
  "startup": [],
  "shutdown": []
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
| `output` | how the output of its instrument is switched on and off: `on`, `off` and `mode` (below) |

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

## Outputs, cooldown and power order

Some converters hold state that must not be lost: a microcontroller without non-volatile memory loses its
program when its supply is cut. And a converter that has just been measured needs to cool down. So the
program never decides alone: every parameter that is set can have an `output` block with the calls that
switch its output (`on`, `off`, and optionally `state`) and a `mode`:

| `mode` | At the start | During the cooldown | At the end, after an error or a stop |
|---|---|---|---|
| `keep_on` (default) | switched on | stays on | switched off |
| `off_during_cooldown` | switched on | **switched off**, then on again | switched off |
| `always_on` | switched on **only if it is off** | stays on | **never switched off** |

### Cooldown between sweeps

`timing.cooldown_s` is a rest for the converter. It happens **between sweeps, not between points**: every
time the innermost sweep (the first swept parameter of your list) has finished its whole run and an outer
parameter advances, the outputs marked `off_during_cooldown` are switched off (in reverse power order), the
measurement waits `cooldown_s`, then those parameters are set again and the outputs are switched on again (in
power order). Between the points of the innermost sweep nothing is switched off. With three swept parameters
there is a cooldown every time the first one has finished, whichever outer parameter moves. There is no
cooldown after the last sweep: the measurement ends. A stop during the cooldown ends the measurement at once.

The validation warns when the pieces do not fit: outputs marked for the cooldown but `cooldown_s` 0, a
`cooldown_s` with no output marked (the converter keeps running while the program waits), or only one sweep
(there is no second sweep, so the cooldown is never used).

### Power order

The order in which the outputs are switched on is its own list, `power_order`, separate from the order of the
sweeps: `["vin", "iout"]` switches the supply on first and the load second. Outputs go off in the reverse
order. If you do not give it, the order of the parameter list is used. Outputs that are always on are **not**
part of this list: they are handled first, before anything in the list.

### Always on

`always_on` is the "never switch this off" tick: an auxiliary supply that keeps a microcontroller alive, or an
input that must stay up. Such instruments are usually switched on from the instruments' own interface before
the measurement, so:

* if the output has a `state` call (for example the library call `output_state_query`) the program **asks
  first**: an output that is already on is **left alone**; one that is off is switched on;
* without a `state` call the `on` call is sent anyway (the validation warns about it);
* the program **never** switches it off: not between points, not in the cooldown, not at the end, also when the
  measurement fails, is stopped or is aborted from the pop-up. Leaving it on is then your decision, and the
  editor shows a warning to remind you. An `off` call given to an always-on output is ignored, and a
  `shutdown` call that switches it off is refused as an error.

The answer of the `state` call can be a boolean, a number (0 / not 0) or the text ON/OFF/1/0.

### An output that is already on and will be switched off

If an output is defined to be switched off (it has an `off` call and is not always on) the program switches it
off at the end, **also if it was already on before the measurement**. To make that visible, the measurement
checks the outputs that have a `state` call **before it touches anything**. If some are already on, one
pop-up (a `question` event) says so: *"These outputs are already on and will be switched off when the
measurement ends: 'vin' (psu1). Continue, or stop to change the file?"*, with the choices **continue** and
**abort**. Abort ends the measurement as *stopped* with nothing changed and nothing switched off, so you can
edit the file (for example mark the output as always on). An unattended run (`unattended=...`) answers with
the question's default, which is *abort*: pass `unattended="continue"` to go on. An output without a `state`
call cannot be checked, and the validation warns about it.

### Other rules

* The setpoint of a parameter whose output was cooled is sent again before it is switched on again, in case
  the instrument forgot it.
* A parameter without an `output` block is never switched on or off by the program.
* An output that has an `off` call but no `on` call is switched off at the end, not switched on at the start.
* `startup` and `shutdown` are optional extra calls: `startup` after the outputs are on, `shutdown` before they
  are switched off. They are for anything else that is not the output of a parameter.

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

`timing`: `settle_s` (wait after setting), `samples` (how many readings), `interval_s` (time between them),
and `cooldown_s` (rest between sweeps, see below; default 0).
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

## The editor window

`python -m frontend.ui.EfficiencyEditorDialog [file.eff]` opens the editor (the application opens it with the
instruments of the project). It is split in two so that it can be tested without a screen:

* `ola/efficiency_editor.py` (`EfficiencyEditor`) owns the data: add, duplicate, remove, move and rename a
  parameter (formulas that use the name are rewritten), readings, sweeps, formulas, power order, extra calls,
  and `problems()` / `summary()` after every change;
* `frontend/ui/EfficiencyEditorDialog.py` only shows it. Every field is bound to a path of the parameters
  (`variables[1].set.call`); a mistake gives a **red border** (error) or **amber** (warning) and a tooltip on
  the field, and is listed at the bottom (double-click goes to the field). The top line says what the file
  would do: points, sweeps, cooldowns and the time spent waiting.

Tabs: *Parameters* (the ordered list, with up / down: the first is set first and is the fastest sweep; for the
selected one: the set call, the value or sweep, the readings, the check, the limits, the output switching),
*Timing*, *Formulas* (double-click a name to insert it), *Power-on order* (and the extra start / end calls) and
a preview of the file. A file with errors can be saved after a confirmation. The texts are in
`frontend/lang/modules/efficiency/<lang>.json`; a test checks that every language has the same keys.

## Results

Two tables, written while the measurement runs ([engine.md](engine.md#files)):

* `points`: one row per point: the setpoints, the averaged readings (`vin@daq`...), `n_samples`, the derived
  quantities (`pin`, `pout`, `efficiency`) and, if any, `verify_skipped`;
* `samples`: one row per reading: `point`, `attempt` (1, or 2... after a retry), `sample`, the setpoints
  and the readings.

`ola.runs.export_points_csv(run, csv)` exports `points`; add `table="samples"` for the other one.

## Not done yet

The "start measurement" action and the run window of the GUI (progress, pop-ups, plots), and opening the editor from the project window. The measurement
has been tested against simulated instruments only, not on real hardware.
