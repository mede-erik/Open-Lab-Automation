# RF amplifier (`.amp`)

An RF amplifier measured with a vector network analyzer (VNA) with two ports: **gain**, **match**, **isolation**,
**stability** and, optionally, the **compression point**. The VNA is calibrated by the user beforehand, **with the
attenuators that will be in the test**; the program does not touch the calibration, it asks once whether it is done,
how to connect the amplifier, and reminds of the two power limits (below).

## Protect the amplifier and the VNA

A VNA source can overdrive an amplifier, and an amplifier can overdrive a VNA port. The measurement helps:

* `sweep.power_dbm` is the VNA **source power**: keep it low (for example -30 dBm). Without it the VNA keeps whatever
  it had and the editor warns.
* `input_attenuation_db`: an attenuator between the source and the amplifier (as in the calibration). The power that
  reaches the amplifier is lower by that much.
* `max_input_dbm`: the largest power the amplifier input can take. A sweep or a compression test that would go above
  it (**after** the attenuator) is an **error, and nothing is sent to the instrument**.
* **Output**: the amplifier output power is not known in advance; the set-up question reminds the user to check that
  it cannot exceed the maximum input of the VNA (put an attenuator at the output, calibrated in).
* After a compression test the source power is **put back** to `sweep.power_dbm`, also if the test is stopped or
  fails, so the amplifier is not left at a high drive.

## What it gives

From the four S-parameters, read in one sweep (the amplifier is not reciprocal, so `S12` and `S22` are needed):

| Quantity | From | Notes |
|---|---|---|
| **gain** | `S21` in dB | peak gain and where, gain at chosen frequencies, **flatness** (max - min) in the band |
| **band** | the gain curve | the **edges** where the gain is `gain_edge_db` (3) below its peak, and the bandwidth; if an edge is outside the sweep the log says so |
| **input / output return loss** | `S11` / `S22` | the worst value in the band |
| **reverse isolation** | `-S12` in dB | the smallest (worst) value in the band |
| **stability** | all four | the Rollett factor **K**, `|delta|` and the factor **mu** (see below), at every frequency |
| **compression point** | a power sweep | optional, see below |
| **verdict** | `limits` | a mask on the gain in dB |

### Stability

`mu` is a number per frequency. If it is **above 1 at every frequency**, the amplifier is *unconditionally stable*
(it cannot oscillate with any passive source and load); this is the same as `K > 1` and `|delta| < 1`. The summary says
`unconditionally_stable` yes or no, the smallest `K` and `mu`, and, if not stable, the **frequency bands** where it can
oscillate (also a warning in the log). **It is only checked inside the sweep**: an amplifier can oscillate where you did not
measure; sweep wider than the band you use, down to a few MHz and up to well above it.

### Compression point

With `compression` the source power is stepped at one frequency and the gain read at every step:

```json
"compression": {"frequency_hz": 868000000, "start_dbm": -40, "stop_dbm": -5, "step_db": 1, "compression_db": 1}
```

The powers are VNA source powers; the **small-signal gain** is the one at the lowest power, and the compression point is where
the gain has fallen `compression_db` (1 by default) below it. Reported: the input and output power there. The input
power is at the amplifier input (the source power minus `input_attenuation_db`). If the gain never falls that far the log
says *"compression not reached: raise stop_dbm"*. Start low enough to be in the linear range: if the gain already
falls at the lowest powers the log says so.

## The file

```json amplifier.amp
{
  "device": {"label": "LNA #1"},
  "sweep": {"start_hz": 700000000, "stop_hz": 1050000000, "points": 351, "scale": "linear", "power_dbm": -30},
  "input_attenuation_db": 0,
  "max_input_dbm": 0,
  "passband": {"from_hz": 820000000, "to_hz": 920000000},
  "gain_edge_db": 3,
  "frequencies_of_interest": [868000000],
  "compression": {"frequency_hz": 868000000, "start_dbm": -40, "stop_dbm": -5, "step_db": 1},
  "limits": {"bands": [{"from": 820000000, "to": 920000000, "min": 15}]},
  "averages": 1,
  "confirm_setup": true
}
```

`device.label` identifies the amplifier; `passband` (optional) is where the flatness, the worst return loss and the
isolation are taken (the whole sweep by default); `limits` is a mask on the **gain in dB** ([`ola/limits.py`](../ola/limits.py)),
for example `{"min": 18}`. The editor (*Edit* in the project window, from the module's `form.json`) shows every
problem at its field, including the protection errors.
`golden` (optional) checks the result against a **golden sample** of the project, a good amplifier of the same kind, for
example the gain `S21` in `magnitude_db` within 1 dB ([`golden.md`](golden.md#as-a-step-of-a-measurement)).

## Results

* **Curves** (*Curves* tab): `S21` in dB with the mask drawn dashed in red; hidden at first and selectable: `S11`, `S22`,
  `S12` (their Smith chart and the Touchstone `.s2p` export use them), `stability_mu`, `stability_k`, and, with a
  compression test, `gain_vs_power_db` and `pout_dbm` against the **input power**. Those two share no axis with
  the frequency curves: select them alone.
* **Table `points`** (one row): everything above; **`sweep`**: a row per frequency (gain, return losses, isolation,
  K, mu); **`compression`**: a row per power (input power, gain, output power).

A gain below the mask, or an amplifier that can oscillate, is a **result**: the run ends as *finished*, with
`FAIL` / `unconditionally_stable: no` and a warning in the log.

## What the VNA must provide

The two logical calls `set_sweep` and `read_sparameter`, for all four parameters `S11`, `S21`, `S12`, `S22`
([`vna-calls.md`](vna-calls.md)). The compression test calls `set_sweep` again for **every power** (a 3-point sweep
around the frequency with that source power) and reads `S21`, so a library entry should make `set_sweep` with `power`
quick. `ola/sim_vna.py` (`SimAmplifier`) is a simulated VNA with an amplifier that compresses (its 1 dB point is known),
used by the tests.

## Not done yet

Tried only with the simulated VNA. Not measured: noise figure (needs a different method), the intermodulation
(IP3, two tones), the harmonics, and the gain at several temperatures; and the compression point is found at one
frequency per run.
