# Efficiency with a resistive load (`.rfe`)

The efficiency of a converter whose load is made of **real resistors** that you write down: one resistor, or resistors in series and in
parallel, each with its tolerance and its power rating. For every load the measurement connects it, sweeps the input voltage, and works out
the efficiency **with the range that the tolerances of the resistors allow**. It is the measurement for a supply that is tried on a few
resistors (a bench of 10 ohm, 22 ohm, 22 || 47 ohm...) where an electronic load is not needed, or not wanted.

For a load that is a **current** (an electronic load in constant-current mode) use the [efficiency measurement](efficiency.md), which is a
sweep of any parameters. The two give the same efficiency: this one knows resistors, how to connect them, and how far they can be off.

## How it works

```
for every load:
    supply off (unless told not to), connect the load: by hand (the program asks) or by the relays of a multiplexer
    for every input voltage:
        set the voltage, switch the supply on, wait, read   Vout, Iin (and Vin)  a few times and average
        Pin = Vin * Iin          Pout = Vout^2 / R          efficiency = Pout / Pin
end: supply off, relays open
```

* **The load** is a **resistor** (`r_ohm`) or a **group** (`series` or `parallel`, nested as far as needed): the program works out the
  equivalent resistance. With the tolerances it is a **range**: the series add, and in parallel the lowest equivalent comes from
  every resistor at its lowest value.
* **The power in each resistor** is worked out from the output voltage and checked against its rating (`power_w`), as an **upper bound**
  that takes the tolerances in the worst direction. A resistor above its rating **stops the measurement** (the supply goes off, the relays
  open). With `safety.max_vout_v` the ratings are checked at that voltage **before anything is switched on**: a load that would overheat at
  the highest output the converter can give is an error at the field.
* **The efficiency** comes as `efficiency_pct` (nominal) and `efficiency_min_pct` / `efficiency_max_pct`: the resistance at its highest
  gives the lowest power and the lowest efficiency. The verdict uses the **lowest**, the one the tolerances guarantee.

## The file

```json resistive_efficiency.rfe
{
  "device": {"label": "5 V buck"},
  "vin_v": {"values": [9, 12, 15]},
  "loads": [
    {"name": "10R", "r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"},
    {"name": "22||47", "parallel": [
      {"r_ohm": 22, "tol_pct": 1, "power_w": 2, "channel": "202"},
      {"r_ohm": 47, "tol_pct": 5, "power_w": 2, "channel": "203"}]},
    {"name": "10+(22||47)", "series": [
      {"r_ohm": 10, "tol_pct": 1, "power_w": 5, "channel": "201"},
      {"parallel": [{"r_ohm": 22, "tol_pct": 1, "power_w": 2, "channel": "202"},
                    {"r_ohm": 47, "tol_pct": 5, "power_w": 2, "channel": "203"}]}]}
  ],
  "switching": {"mode": "mux", "settle_s": 0.5, "supply_off": true},
  "vout_reading": {"call": "measure_dc_voltage", "args": {"range": "AUTO", "resolution": "DEF", "channels": "103"}},
  "iin_reading": {"role": "supply", "call": "read_current"},
  "timing": {"settle_s": 1, "samples": 3, "interval_s": 0.1},
  "safety": {"max_vin_v": 20, "max_vout_v": 6, "max_iin_a": 3},
  "limits": {"min_efficiency_pct": 85},
  "confirm_setup": false
}
```

| Field | Meaning |
|---|---|
| `device.label`, `device.asset_id` | the converter, and its code in the registry ([`assets.md`](assets.md)) |
| `supply_channel` | the output of a multi-output supply |
| `vin_v` | the input voltages: `{"values": [...]}` or `{"start", "stop", "points"}`. Each is tried with every load |
| `loads` | the list of loads (below). The names must be different |
| `switching.mode` | `manual` (the program asks you to connect each load) or `mux` (the relays do it) |
| `switching.settle_s` | `mux`: the wait after the relays (0.5 s by default) |
| `switching.supply_off` | `true` (the default): the supply is **off while the load is changed**. `false` switches the relays with the converter running (hot switching): a warning at the field |
| `vout_reading` | how the output voltage is read: `call` (`measure_dc_voltage`), `args` (a datalogger wants `range`, `resolution` and the `channels`; a multimeter wants numbers), `scale`, `offset` |
| `iin_reading` | how the input current is read (below) |
| `vin_reading` | optional: the input voltage **at the converter** (it shows the drop in the cables); without it the supply setpoint is used |
| `timing` | `settle_s` after a change (1 s), `samples` averaged (3), `interval_s` between them (0.1 s) |
| `safety` | `max_vin_v` (a sweep above it is refused), `max_vout_v` (the ratings of the resistors are checked at this output before anything is switched on), `max_iin_a` (checked on every reading) |
| `limits` | `min_efficiency_pct` (on the **lowest** efficiency), `vout_min_v`, `vout_max_v` |
| `golden` | optional: check the rows against a golden sample of the project ([`golden.md`](golden.md#as-a-step-of-a-measurement)) |
| `confirm_setup` | `false` skips the first question |

### A load

A resistor is `{"name", "r_ohm", "tol_pct", "power_w", "channel"}`:

| Field | Meaning |
|---|---|
| `r_ohm` | the resistance in ohms (above 0) |
| `tol_pct` | the tolerance in percent, from 0 (the default) to below 100 |
| `power_w` | the rating in watts; without it the power in that resistor is not checked |
| `channel` | the relay of the multiplexer that connects it (`"201"`); needed for every resistor in `mux` mode |
| `name` | the name of the load (a resistor of a group needs none: the program names it from the load) |

A **group** is `{"name": "...", "series": [...]}` or `{"name": "...", "parallel": [...]}`, with at least two members, each a resistor or a
group. In `mux` mode the load is connected by closing the channel of **every** resistor it contains, so the relays only connect each
resistor, and the series / parallel structure is the one you wire (or that the program works out for the power). A resistor used in several
loads (`"channel": "201"` above) is one physical resistor with one relay.

### The input current

* **The supply's own readback**: `{"role": "supply", "call": "read_current"}` (the call is `read_current` by default for the supply).
  Simple, but only as good as the supply's meter.
* **A shunt read by a datalogger**: `{"call": "measure_dc_voltage", "args": {"channels": "102"}, "scale": 10}`. `scale` is 1 / the shunt in
  ohms: a 0.1 ohm shunt is `10`, so the voltage in volts becomes the current in amps.

## How to measure

1. Wire the supply to the converter, the voltmeter (or the datalogger channel) to its output, and the current reading.
2. **By hand**: the program asks for each load by its name and goes on when you say *continue* (*abort* stops with nothing left on).
   **With a multiplexer**: wire each resistor between the output and ground through its relay (a datalogger module or a switch unit,
   bound to the role `switch`).
3. Start the run. The supply is switched on at the first input voltage and **off while the load changes** and at the end.

## What you get

* **Table `points`**: a row for each load and input voltage: `load`, `r_nom_ohm`, `r_min_ohm`, `r_max_ohm`, `vin_set_v`, `vin_v`, `iin_a`,
  `vout_v`, `iout_a`, `pin_w`, `pout_w`, `pout_min_w`, `pout_max_w`, `efficiency_pct`, `efficiency_min_pct`, `efficiency_max_pct`,
  `loading_pct` (the fullest resistor, in percent of its rating) and `loading_resistor`; with `limits` also `verdict`.
* **Table `summary`**: a row for each load with the mean, lowest and highest efficiency, the input voltage of the best one and the verdict.
* **Curves** `eff_vs_vin_<load>` (efficiency against the input voltage, one for each load) and `eff_vs_r_<vin>V` (against the resistance of
  the load, hidden at first).

When there is no input power (a converter that does not start: below its minimum input voltage) the efficiency is empty and the log says so;
with `min_efficiency_pct` such a point fails.

## What the instruments must provide

The supply: `set_voltage`, `output_on`, `output_off` and, for its own readback, `read_current`. The voltmeter: `measure_dc_voltage` (a multimeter
or a datalogger channel). The multiplexer (only for `mux`): `close_channel` and `open_channels`, which both the datalogger and the switch unit
categories of the library have. `ola/sim_bench.py` has `SimResistiveBench`, a simulated converter with resistors on relays, used by the tests.

## Not done yet

Tried only with the simulated bench. The power in each resistor is the **nominal power** of its rating, with no derating for temperature or
for the mounting; a measurement of the real resistance of each load (an ohmmeter reading before the run) is not done: the nominal value and
its tolerance are used. The relays are not read back (`query_channel_closed_state`) to check that they closed.
