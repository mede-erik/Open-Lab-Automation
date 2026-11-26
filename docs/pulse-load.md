# Pulse on an electronic load (`.pls`)

A current pulse on an electronic load, as a measurement of the project: the load makes the pulse in its **dynamic mode**
(a high and a low current, a width and a repetition frequency) while the program reads its voltage and current and
records them. It replaces the *Pulse Generator* tool of the *Tools* menu, which is gone: the pulse is created from *New
measurement*, its parameters are saved in a file, and it runs from the project window like the other measurements.

## What it does

1. **Checks before anything is switched on.** The parameters must be valid (the width must fit in the period). The peak
   and the average power of the pulse (power = current × voltage) are compared with the maximum power the library gives
   for the load. The voltage is the larger of the *working voltage* of the file and the voltage the load reads at that
   moment. A pulse above the limit, a current above the maximum of the load, or a power limit with no known voltage is
   **refused**, with the powers and the limit in the message, and nothing is switched on.
2. **Starts the pulse** with logical calls only: `set_dynamic_level_high`, `set_dynamic_level_low`,
   `set_dynamic_timing` (frequency and duty cycle), `enable_dynamic_mode`, `load_on`. A load model that lacks one of
   them (or `disable_dynamic_mode`, `load_off`) is refused, naming the calls.
3. **Reads** `read_voltage` and `read_current` every `read_interval_s` until `duration_s` has passed or you press *Stop*,
   and records the time, the voltage, the current and their product (table `points`, shown as curves in the run window).
   The run window also draws **the shape of the pulse** that was asked for (the curve `profile`).
4. **Switches the load off at the end**, also after an error or a stop: the dynamic mode first, then the load input. If
   the first call fails the second is still sent, and the failure is written in the log.

## The file

```json pulse.pls
{
  "amplitude_a": 1.0,
  "base_level_a": 0.0,
  "width_us": 100,
  "frequency_hz": 1000,
  "rise_time_us": 10,
  "fall_time_us": 10,
  "voltage_v": 12.0,
  "duration_s": 10,
  "read_interval_s": 0.5
}
```

| Field | Meaning |
|---|---|
| `amplitude_a`, `base_level_a` | the high and the low current in A, 0 or more |
| `width_us` | the time at the high level in every period, in microseconds (1 or more); it must fit in the period of `frequency_hz` |
| `frequency_hz` | the repetition frequency; with the width it gives the duty cycle sent to the load (`width × frequency / 10000` %) |
| `rise_time_us`, `fall_time_us` | the edges of the **drawing** only; the load makes its own edges |
| `voltage_v` | the voltage across the load, which the circuit under test decides. Needed when the load has a power limit and the load cannot read it |
| `duration_s` | optional: how long the pulse runs; without it, until *Stop* |
| `read_interval_s` | the time between two readings, 0.05 s or more (0.5 s by default) |

The role is `load` (category electronic load); the instrument is chosen in the editor.

## The editor

*Edit* in the project window opens the form of the module with the **preview** of the pulse (the trapezoid, two periods)
above it, redrawn at every change; with the values not valid nothing is drawn. The same limits of the old tool act while
you type, using the model of the load chosen in the file:

* a current above the **maximum current** of the load is brought back to it, with a message;
* a pulse whose peak or average power is above the **power limit** has the **parameter changed last** corrected to the
  largest value that keeps it within the limit, and the message says which one and to what (changing the working
  voltage lowers the amplitude, since the voltage comes from the circuit).

Nothing is checked until a load is chosen or when the library gives no limit. The same checks run again when the pulse
starts, with the voltage read from the load.

## What is not done

* The rise and fall times are not sent to the load: the library has current slew rate calls
  (`set_current_slew_rate_rise` / `_fall`), but the old tool never used them and they were not tried on a real load.
* The operating mode (CC, CV, CP) of the old tool was never sent to the load and is not in the file: the pulse is a
  constant-current dynamic mode.
* Not tried on a real electronic load, only with a simulated one.
