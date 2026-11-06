# Ripple and noise (`.rpl`)

The ripple and the noise on the output of a supply (a rail of a converter, a linear regulator, a battery charger),
measured with an oscilloscope. The scope channel is put across the output, **AC coupled** and limited to **20 MHz**, the
usual way to quote ripple and noise, and the whole acquisition memory is read and analysed.

## What it measures

From the volts at the probe tip:

* the **peak-to-peak** value, the positive and negative peaks (from the mean) and the **rms** of the AC part;
* the DC level (the mean: meaningful with DC coupling, about 0 with AC coupling) and, with `device.nominal_v`, the
  peak-to-peak as a percentage of the nominal voltage;
* from the **spectrum** (Hann window): the **frequency of the ripple**, the highest peaks (the fundamental and its
  harmonics, with their amplitudes) and the **noise**: the rms of what is left once the peaks are taken away. The
  amplitude of a peak is good to about 3 %;
* with `captures` above 1 the capture is repeated, and the **worst** peak-to-peak and the mean of them are also given;
* with `conditions` (a list of load currents and an electronic load) one row for each current: **ripple against load**;
* a **verdict** against `limits` (`max_pp_v`, `max_rms_v`). Too much ripple is a **result**, the run still ends as
  *finished*, with `FAIL` and a warning in the log.

## The file

```json ripple.rpl
{
  "device": {"label": "5 V rail", "nominal_v": 5.0},
  "scope": {"channel": 1, "probe_attenuation": 1, "coupling": "AC", "bandwidth_limit_hz": 20000000,
            "volts_per_div": 0.01, "time_per_div": 0.000002, "memory_depth": 100000},
  "trigger": {"level_v": 0, "slope": "RISE", "mode": "AUTO"},
  "captures": 3,
  "capture_wait_s": 0,
  "conditions": {"currents_a": [0.0, 1.0, 2.0], "settle_s": 0},
  "limits": {"max_pp_v": 0.05, "max_rms_v": 0.01},
  "confirm_setup": false
}
```

| Field | Meaning |
|---|---|
| `device.label`, `device.asset_id` | what is measured, and its code in the registry ([`assets.md`](assets.md)); the name is filled from the card |
| `device.nominal_v` | the output voltage, to give the ripple as a percentage (optional) |
| `scope.channel` | the channel of the oscilloscope |
| `scope.probe_attenuation` | 1 for a coax connection or a 1:1 probe, 10 for a 10:1 probe. Set the same on the probe |
| `scope.coupling` | `AC` (the ripple only, the default in the editor) or `DC` |
| `scope.bandwidth_limit_hz` | 20 MHz is the usual way to quote ripple and noise; 0 = full bandwidth (the spikes too) |
| `scope.volts_per_div`, `scope.offset_v` | optional; without them the scope keeps its settings. Use a small scale (10 mV/div) for ripple of some tens of millivolts, so that the converter has enough levels |
| `scope.time_per_div`, `scope.memory_depth` | optional. At least 5 periods of the ripple must fit in the record. Most oscilloscopes accept only some memory depths (`10000`, `100000`, `1000000`...): another value is refused with a message that says so |
| `scope.acquisition` | `NORMAL`, `AVERAGE` or `HIRES` (optional) |
| `scope.bits` | 8 (the default) to 16: the resolution of the transfer |
| `trigger` | `level_v`, `slope` (`RISE`, `FALL`, `EITHER`) and `mode` (`AUTO`, `NORMAL`); optional. With AC coupling 0 V is the middle of the ripple |
| `captures` | number of captures (1 to 100) |
| `capture_wait_s` | seconds to wait after starting an acquisition before reading it (0.5 by default) |
| `conditions` | `currents_a` (load currents, at most 50) and `settle_s`: needs an electronic load bound to the role `load`. It is set to constant current, switched on at the first current and **switched off at the end, also after an error or a stop** |
| `spectrum`, `peaks` | compute the spectrum (the frequency of the ripple and the noise need it) and how many peaks to report (5 by default) |
| `limits` | `max_pp_v` and `max_rms_v`, in volts |
| `confirm_setup` | `false` skips the question |

The measurement asks once to connect the probe: **across the output capacitor, with the ground spring and not a long
ground lead**. A long lead picks up the switching spikes and shows them as ripple, which is the most common mistake.

## Results

* **Curves**: `waveform` (the signal against time, thinned to at most 4000 points but keeping every peak), and `spectrum_dbv`
  (dBV rms against frequency on a logarithmic axis), hidden at first. With `conditions` one pair for each current:
  `waveform @ 1 A`.
* **Table `points`**: one row (one per load current with `conditions`) with the figures above, the number of samples and
  the sample rate, the coupling and the bandwidth limit used, and the verdict with the reasons in the log.

**Warnings** in the log say when the figures cannot be trusted: the signal touches the edge of the screen (the peaks are
cut), only a few different levels are in the record (the resolution of the oscilloscope is the limit: use a smaller V/div),
fewer than 5 periods of the ripple in the record, or a sample rate below 5 times the ripple frequency.

## What the oscilloscope must provide

The logical calls of the oscilloscope category ([`Instruments_LIB/COMMAND_NAMES.md`](../Instruments_LIB/COMMAND_NAMES.md)):
`set_channel_state`, `set_probe_attenuation`, `set_channel_coupling`, `set_channel_bandwidth_limit`, `set_channel_scale`,
`set_channel_offset`, `set_timebase_scale`, `set_acquisition_type`, `set_acquisition_depth`, the trigger calls,
`run_acquisition`, and the transfer of the whole memory (`handle.read_waveform_full`, which stops the acquisition and
reads it in blocks). A test plans every one of them for the Siglent SDS824X HD, the Rigol DS1054Z and the Tektronix MSO54.
`ola/sim_scope.py` (`SimScope`, `SimLoad`) is a simulated oscilloscope on a switching supply, used by the tests; the figures
the module finds are checked against what the simulation contains. The spectrum is computed by [`ola/spectrum.py`](../ola/spectrum.py).

## Not done yet

Tried only with the simulated oscilloscope. Not measured yet: ripple against input voltage (a power supply on the input
could be swept as the load is), the spikes at the switching edges as figures of their own (the full-bandwidth waveform shows
them), and the check of the scope bandwidth itself.
