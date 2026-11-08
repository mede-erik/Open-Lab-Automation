# Attenuator (`.att`)

How much an attenuator attenuates **as a function of frequency**, measured with a vector network analyzer (VNA). The VNA
is calibrated by the user beforehand (thru, at the ends of the test leads); the program does not touch the calibration, it
asks once whether it is done and to connect the attenuator between port 1 and port 2.

The attenuation is `-20 log10 |S21|` and is a **positive** number: a 10 dB attenuator reads 10 (unlike the gain of a
filter, which is negative). It is the measurement for a fixed attenuator, a pad or one setting of a step attenuator.

## What it measures

* the **attenuation** over the sweep: the mean, the lowest and the highest value and where they are, the **flatness**
  (highest minus lowest) and the **slope** (dB per GHz, a straight-line fit);
* the **deviation from the nominal value**: on average and the worst point;
* the attenuation at chosen frequencies;
* the **return loss of both ports** (S11 and S22), the worst value of each: a good attenuator is also a good match;
* a **verdict**: the whole sweep must stay inside `nominal_db` plus or minus `tolerance_db`, or inside the mask you give.

A value outside the tolerance is a **result**: the run still ends as *finished*, with `FAIL` and a warning in the log.

An attenuator that keeps its value is also a handy check of the VNA itself: measure the same one now and then
(*Tools > Compare*) and a change means the calibration has been lost, not the attenuator.

## The file

```json attenuator.att
{
  "attenuator": {"label": "10 dB SMA #3", "nominal_db": 10, "tolerance_db": 0.5, "setting": ""},
  "sweep": {"start_hz": 1000000, "stop_hz": 3000000000, "points": 301, "scale": "linear"},
  "frequencies_of_interest": [433000000, 2400000000],
  "also_return_loss": true,
  "averages": 1,
  "confirm_setup": true
}
```

| Field | Meaning |
|---|---|
| `attenuator.label` | identifies the attenuator; saved in the run |
| `attenuator.asset_id` | its code in the registry (`ATT-0007`), see [`assets.md`](assets.md); the name is filled from the card |
| `attenuator.nominal_db` | the value written on it; the deviation is measured from it |
| `attenuator.tolerance_db` | plus / minus around the nominal value; with it the verdict is made (whole sweep inside) |
| `attenuator.setting` | which step is set on a step attenuator; free text, written in the result. One setting per measurement |
| `sweep` | `start_hz`, `stop_hz`, `points`, `scale` (`linear` or `log`); optional `if_bandwidth_hz`, `power_dbm` |
| `frequencies_of_interest` | the attenuation is reported at these frequencies (inside the sweep) |
| `limits` | a **mask on the attenuation in dB** ([`ola/limits.py`](../ola/limits.py)); replaces the check on `nominal_db` and `tolerance_db`: `{"bands": [{"from": 0, "to": 6e9, "min": 9, "max": 11}]}` |
| `also_return_loss` | also read S11 and S22 (true by default) |
| `averages`, `confirm_setup` | sweeps averaged; `false` skips the question |
| `golden` | optional: check the result against a **golden sample** of the project (a good unit of the same kind): `name` and `tolerances` ([`golden.md`](golden.md#as-a-step-of-a-measurement)) |

For a step attenuator measure each setting you care about as its own run, with the same code: the card of the attenuator
is the same and the results are told apart by `setting`.

The measurement does not limit the source power: an attenuator is not harmed by the power of a VNA. Do not use it at the
power of an amplifier: the maximum power of the attenuator is on its card (`ATT` details) for you to check.

## Results

* **Curves**: `attenuation_db`, with the tolerance band or the mask drawn dashed in red; hidden at first: `S21`
  (phase, Smith chart and the Touchstone export use it), `S11` and `S22`.
* **Table `points`** (one row): the name, the nominal value, the mean / lowest / highest attenuation and where, the
  flatness, the slope, the deviations, the attenuation at each frequency of interest, the worst return loss of each
  port, the setting, and the verdict `PASS` / `FAIL` with its margin in dB.
* **Table `sweep`**: a row per frequency with the attenuation, the phase and the two return losses, for the CSV export.

## Through a cable, an adapter or a pad

What is between the plane of the calibration and the attenuator is in the result: a cable adds its loss to the attenuation. With
`correction` the fixtures that were measured are taken out (`port1`, `port2`, each a registry code `asset_id`, a `run` file
or a `touchstone` file; `mode` `complex` or `magnitude`; `model` `matched` or `full`), so the result is of the attenuator alone and
the raw measurement stays as `attenuation_raw_db` and `S21_raw`. How, and the two models, in [`deembedding.md`](deembedding.md).

## What the VNA must provide

The logical calls `set_sweep` and `read_sparameter` ([`vna-calls.md`](vna-calls.md)). `ola/sim_vna.py`
(`SimVna(attenuator_db=10, attenuator_slope_db_per_ghz=0.2)`) is a simulated VNA with an attenuator between the ports, used
by the tests.

## Not done yet

Tried only with the simulated VNA. A measurement that **removes** a cable or an attenuator already measured from the
result (de-embedding) is planned and discussed, not built: see `PLAN.md`.
