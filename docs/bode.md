# Bode plot (`.bod`)

The **gain and the phase of a circuit against frequency**, measured with a **function generator** and an **oscilloscope**:
the generator feeds the circuit with a sine, one scope channel looks at the input and one at the output. It is the measurement
for the response of a filter or an amplifier at audio and low radio frequencies, the loop gain of a converter (with the **phase
margin** and the **gain margin**), and the transfer function of anything that has an input and an output. (For radio
frequencies the [filter](filter.md) measurement with a VNA does the same much faster.)

## How it measures

At every frequency of the sweep:

1. the generator is set to the frequency, and the program waits `settle_s` for the circuit to settle;
2. the timebase of the scope is set to show `scope.cycles` periods (5 by default);
3. the scope is started, and **both channels are read from the same capture**;
4. a **sine of the known frequency is fitted** to each channel (least squares, [`ola/spectrum.py`](../ola/spectrum.py) `fit_sine`):
   the **gain** is the ratio of the two amplitudes, the **phase** is the difference of the two phases.

The fit gives a good gain and phase even when the signal is **under the noise** (a few percent of error at five times more
noise than signal, because it uses the whole record), and what the sine does not explain (noise and distortion) is
reported at every frequency (`residual_in_pct`, `residual_out_pct`) with a warning above 10 %.

**The vertical scales adjust themselves** at every frequency, as the output of a circuit changes by decades. A trace that clips
the screen or fills less than 15 % of it is captured again with a better scale (up to six times), and the next frequency starts
from the scale the last one needed. The scale also has room for the noise, not only for the sine.

The **phase** is made continuous along the frequency (`phase_deg` has no jumps of 360 degrees: a delay shows as a phase that
keeps falling). The first point is taken between -180 and 180 degrees, or near `phase_start_deg`; `phase_offset_deg` is added to
all of it (180 for a loop measured with an inverting injection).

## The file

```json bode.bod
{
  "device": {"label": "buck converter loop"},
  "sweep": {"start_hz": 100, "stop_hz": 1000000, "points": 41, "scale": "log"},
  "source": {"channel": 1, "amplitude_vpp": 0.1, "offset_v": 0},
  "scope": {"input_channel": 1, "output_channel": 2, "probe_attenuation": 1, "coupling": "DC",
            "cycles": 5, "memory_depth": 100000, "bandwidth_limit_hz": 0},
  "settle_s": 0,
  "capture_wait_s": 0,
  "averages": 1,
  "loop": true,
  "phase_offset_deg": 0,
  "limits": {"min_phase_margin_deg": 45, "max_peaking_db": 3},
  "safety": {"max_amplitude_vpp": 1},
  "confirm_setup": false
}
```

| Field | Meaning |
|---|---|
| `device.label`, `device.asset_id` | the circuit, and its code in the registry ([`assets.md`](assets.md)) |
| `sweep` | `start_hz`, `stop_hz`, `points`, `scale` (`log` or `linear`). A few points per decade (10 to 20) are enough for a smooth circuit; more near a resonance |
| `source.channel`, `source.amplitude_vpp`, `source.offset_v` | the generator: its output, the peak-to-peak amplitude (the same at every frequency) and a DC offset. Small enough not to saturate the circuit, large enough to read |
| `scope.input_channel`, `scope.output_channel` | the scope channels on the input and on the output of the circuit (different) |
| `scope.probe_attenuation` | the same on both channels (10 = 10:1) |
| `scope.coupling` | `DC` (the default) or `AC`. A scope that has no AC coupling (the Analog Discovery) refuses `AC`: the run stops before anything is switched on, with a message that says to use `DC`. **AC coupling adds phase lead below about 20 Hz**: a sweep that starts lower is warned about and should use `DC` |
| `scope.cycles` | the periods shown at every frequency (5 by default) |
| `scope.memory_depth` | optional, in points; most oscilloscopes accept only some values (`10000`, `100000`, `1000000`...). At the highest frequency it must give at least 8 samples a cycle (a warning says when not) |
| `scope.bandwidth_limit_hz` | optional; a limit lowers the noise but also changes the phase near it |
| `scope.input_volts_per_div`, `scope.output_volts_per_div` | optional: where the scales **start** (then they follow the signal) |
| `settle_s`, `capture_wait_s` | the wait after a change of frequency (0.5 s by default; a slow loop needs more) and after starting an acquisition (0.3 s) |
| `averages` | captures averaged at every frequency (the complex ratio is averaged) |
| `loop` | the circuit is a **loop gain**: the crossover and the margins are found |
| `phase_offset_deg`, `phase_start_deg` | see above |
| `limits` | `min_phase_margin_deg`, `min_gain_margin_db`, `min_bandwidth_hz`, `max_peaking_db`. The margins need `loop` |
| `safety` | `max_amplitude_vpp`: a larger amplitude is refused before anything is switched on |
| `confirm_setup` | `false` skips the question |

## What you get

* **Curves**: `H`, the complex transfer function, opens as a **Bode plot** (gain in dB and phase); `gain_db` and `phase_deg` are
  there to pick. The curves grow with every frequency while the measurement runs.
* **Table `sweep`**: a row per frequency: `frequency_hz`, `gain_db`, `phase_deg`, the peak input and output (`vin_peak_v`,
  `vout_peak_v`), the share of each that is not a sine, the scales and the number of samples.
* **Table `points`** (one row): the gain at the lowest frequency (`dc_gain_db`), the peak and its frequency and the **peaking**
  (`peaking_db`: the peak above the low-frequency gain), the **-3 dB bandwidth** (`bandwidth_3db_hz`: where the gain first falls
  3 dB below the gain at the lowest frequency). With `loop`: the **crossover** (`crossover_hz`, where the gain falls through 0 dB),
  the phase there and the **phase margin** (`phase_margin_deg`: 180 degrees plus the phase at the crossover), the frequency where the
  phase reaches -180 degrees (`phase_crossover_hz`) and the **gain margin** there (`gain_margin_db`: minus the gain), and the
  `verdict` against `limits`. Crossings are found by interpolating in the **logarithm** of the frequency.

A figure that is not found is not invented: if the gain never falls through 0 dB in the sweep there is no crossover and no phase
margin (the log says to widen the sweep), and a limit on it **fails** with that reason. A limit that is not met is a **result**:
the run still ends as *finished*, with `FAIL` and a warning in the log.

## Connecting a loop gain

For the loop gain of a converter or a regulator, inject the signal **in series with the loop** (a small resistor of some ohms, or an
injection transformer) and measure on both sides of the injection: channel 1 on the side that goes into the loop, channel 2 on the
side that comes back. The circuit must be working in its normal state. Use the same kind of probe and the same ground lead on the two
channels: a difference in cable delay shows as phase at high frequency. The window of the connections ([`wiring.md`](wiring.md)) says
all this before the measurement starts.

## Safety

The generator output is **off** while the circuit is set up (the scope is configured and the amplitude is set before the output is
switched on), is switched on at the first frequency, and is **switched off at the end, also after an error or a stop**.
`safety.max_amplitude_vpp` refuses a larger amplitude before anything is switched on.

**A generator with no output switch** (some models, such as the Agilent 33120A, have no command to switch the output on and off;
`set_output_state` is optional in the library) cannot be kept off while the circuit is set up. The measurement then **always asks
first**, whatever `confirm_setup` says, and the question says that the output is on as soon as the amplitude is set and stays on at
the end: answer *continue*, or *abort* (nothing has been set yet). The log has a warning at the start and a reminder at the end
to switch the generator off by hand. A run can be stopped at any time as usual. How such models should be handled is still being
looked into.

## What the instruments must provide

**The oscilloscope**: the calls of the oscilloscope category that the [ripple](ripple.md) measurement uses
(`set_channel_state`, `set_probe_attenuation`, `set_channel_coupling`, `set_channel_bandwidth_limit`, `set_channel_scale`,
`set_timebase_scale`, `set_acquisition_depth`, `run_acquisition`) and the transfer of the whole memory of a channel
(`read_waveform_full`). The second channel is read with `stop=False`, from the same acquisition. A test plans these calls for the
Siglent SDS824X HD, the Rigol DS1054Z and the Tektronix MSO54.

**The function generator** is a category that the library does not have yet. The measurement asks, for the role `generator`
(category `function_generator`):

| Call | Arguments | Notes |
|---|---|---|
| `set_output_state` | `channel_number`, `state` (bool) | **mandatory**; switched off first and last |
| `set_frequency` | `channel_number`, `value` (Hz) | **mandatory** |
| `set_amplitude` | `channel_number`, `value` (Vpp) | **mandatory** |
| `set_waveform_shape` | `channel_number`, `shape` (`SINE`) | optional (sent if the instrument has it) |
| `set_offset` | `channel_number`, `value` (V) | optional |

`ola/sim_bode.py` (`SimBodeLab`: a generator, a scope that shows the same capture on two channels, and a circuit given as a
function of the frequency: `second_order`, `integrator_with_pole`, `delay`) is the simulated bench used by the tests. The scope
clips and quantises like a real one, so the scale adjustment is tested against it. The figures are checked against the exact
transfer functions (a first-order low-pass, a resonance, a loop with a pole, a loop with a delay: crossover, phase margin, gain
margin).

## Not done yet

Tried only with the simulated bench. The generator category has to be added to the library. Not done: a different amplitude at
different frequencies (a large one where the circuit attenuates, a small one near a resonance), measuring the **impedance** of a
circuit (an output impedance needs a current injection), and a built-in generator of the oscilloscope as the source.
