# Line and load regulation (`.reg`)

How much the output voltage of a converter or a regulator changes when the **input voltage** changes (line regulation)
and when the **load current** changes (load regulation). A supply feeds the input, an electronic load draws the current,
and the output voltage is read by a **multimeter or a channel of a datalogger**.

## What it measures

* **Line regulation** (`line_test`): the input voltage is swept at a fixed load current and the output is read at every
  step. Reported as the **spread** of the output over the sweep (mV), in **percent** of the nominal output
  (`device.nominal_v`, otherwise the mean output) and as the **slope** in **mV per volt** (a straight-line fit).
* **Load regulation** (`load_test`): the load current is swept at a fixed input voltage. It is
  `(V at the lowest current - V at the highest current) / reference * 100`, where the reference is `device.nominal_v` or,
  without it, the output at the highest current (the usual "no load to full load"). Also the **output resistance** in
  milliohms: the drop of the output per ampere (a straight-line fit of the voltage against the current).
* The **input at the converter**, if you ask (`input_reading`): the supply setpoint is not the voltage the converter sees
  when the cables drop some. With it the line test uses the measured input, and the drop in the cables is reported for
  every point (`vin_drop_v`) and as `max_vin_drop_v`.
* A **verdict** against `limits`. A regulation beyond the limit is a **result**: the run still ends as *finished*, with
  `FAIL` and a warning in the log.

At least one of the two tests is needed; both can be in one run (the line test first).

## The file

```json regulation.reg
{
  "device": {"label": "5 V buck", "nominal_v": 5.0},
  "supply_channel": 1,
  "output_reading": {"call": "measure_dc_voltage",
                     "args": {"range": "AUTO", "resolution": "DEF", "channels": "103"}},
  "input_reading": {"call": "measure_dc_voltage",
                    "args": {"range": "AUTO", "resolution": "DEF", "channels": "101"}},
  "line_test": {"vin_v": {"start": 9, "stop": 15, "points": 7}, "load_a": 1.0},
  "load_test": {"i_a": {"start": 0, "stop": 2, "points": 5}, "vin_v": 12},
  "timing": {"settle_s": 0, "samples": 2, "interval_s": 0},
  "safety": {"max_vin_v": 20, "max_load_a": 3},
  "limits": {"max_line_pct": 1, "max_load_pct": 2, "vout_min_v": 4.75, "vout_max_v": 5.25},
  "confirm_setup": false
}
```

| Field | Meaning |
|---|---|
| `device.label`, `device.asset_id`, `device.nominal_v` | the converter, its code in the registry ([`assets.md`](assets.md)) and its output voltage (the regulation in % refers to it) |
| `supply_channel` | the output channel of the supply (for a supply with several outputs) |
| `output_reading` | how the output voltage is read: `call` (`measure_dc_voltage`), `args`, and `scale` / `offset` (the voltage is `reading * scale + offset`: a 1/2 divider has `scale` 2) |
| `input_reading` | the same for the input voltage **at the converter**; `role` can be `supply` to take the supply's own reading. Without it the setpoint is the input voltage |
| `line_test.vin_v` | the input voltages to try: `{"start", "stop", "points"}` (or `"step"`) or `{"values": [...]}` |
| `line_test.load_a` | the fixed load current during the line test (0 by default: no load needed) |
| `load_test.i_a` | the load currents to try, as above |
| `load_test.vin_v` | the fixed input voltage during the load test |
| `timing` | `settle_s` (wait after a change, 1 s by default), `samples` (readings averaged, 3) and `interval_s` (between them, 0.1 s) |
| `safety` | `max_vin_v` and `max_load_a`: a test that goes above them is an error and **nothing is switched on** |
| `limits` | `max_line_pct`, `max_load_pct` (the regulation, in absolute value), `vout_min_v`, `vout_max_v` (the output must stay inside) |

### The voltmeter: multimeter or datalogger

The role `meter` is any instrument that answers `measure_dc_voltage`, so **a datalogger works in place of a multimeter**.
The arguments of that call are the instrument's own, and are written in `args`:

| Instrument | `args` |
|---|---|
| a **datalogger** (Keysight 34970A / 34972A, DAQ970A / DAQ973A) | `{"range": "AUTO", "resolution": "DEF", "channels": "103"}`: the channel is the one wired to the output |
| a **multimeter** (Agilent 34401A) | `{"range": 10, "resolution": 0.001}`: no channels, and **numbers**, not `AUTO` / `DEF` |

The call needs `range` and `resolution`: without them the instrument's library says so (*"needs argument 'range'"*). The
HP 3478A does not have this call yet. One datalogger can read the output and the input at the converter on two channels
(`output_reading` and `input_reading` with different `channels`).

## Safety

* The load is set to constant current and to **0 A before the supply is switched on**.
* `safety` refuses a test above `max_vin_v` or `max_load_a` **before** anything is switched on.
* A test that draws current without an electronic load bound to the role `load` is refused before anything is switched on.
* At the end, **also after an error or a stop**, the load goes back to 0 A and is switched off, then the supply is
  switched off. If one of them cannot be switched off the log says so and the other is still switched off.

The measurement asks once to connect the instruments (and it is shown, with the connection list, in the window of the
connections: [`wiring.md`](wiring.md)).

## Results

* **Table `points`**: a row per step: `test` (`line` or `load`), `vin_set_v`, `vin_v` (measured at the converter if asked),
  `load_a`, `vout_v` (the mean), `vout_spread_mv` (max minus min of the readings) and `samples`.
* **Table `summary`**: a row per test. Line: the input range, `span_mv`, `line_regulation_pct`,
  `line_regulation_mv_per_v`, the reference and the output range. Load: the current range, the output at the lowest and at
  the highest current, `load_regulation_pct`, `output_resistance_mohm`. And the `verdict`, and `max_vin_drop_v` with an
  input reading.
* **Curves**: `vout_vs_vin` and `vout_vs_load`, drawn as the points come in.

## What the instruments must provide

The logical calls `set_voltage` and `output_on` / `output_off` of the supply, `set_mode`, `set_current_level` and
`load_on` / `load_off` of the load, and `measure_dc_voltage` of the meter. A test plans every one of them for models of
the library (two supplies, three loads, two dataloggers and a multimeter). `ola/sim_bench.py` (`SimBench`) is a
simulated converter with its supply, load and meter, used by the tests; the figures the module finds are checked against
the line sensitivity and the output resistance of the simulation.

## Not done yet

Tried only with the simulated bench. Not measured yet: regulation against temperature, the settling of the output after
a step (a different measurement: the load transient), and the regulation of a converter with several outputs (cross
regulation).
