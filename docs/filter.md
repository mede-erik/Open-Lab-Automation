# Filter (`.flt`)

The frequency response of a filter, measured with a vector network analyzer (VNA): low-pass, high-pass, band-pass or
band-stop. The VNA is calibrated by the user beforehand (at the ends of the test leads); the program does not touch
the calibration, it asks once whether it is done and to connect the filter between port 1 and port 2.

## What it measures

S21, from which, relative to the **peak** of the response (or the highest point of the passband you give) and the
level `edge_db` below it (3 dB by default):

| Filter | What is found |
|---|---|
| low-pass | the **cut-off**: the first frequency above the peak where the gain falls to that level |
| high-pass | the **cut-off**: the last frequency below the peak where the gain rises to it |
| band-pass | the **lower and upper edge** around the peak, the **bandwidth**, the **centre** (geometric mean of the edges) and the **Q** (centre / bandwidth) |
| band-stop (notch) | the **depth** and the frequency of the notch, its edges, the bandwidth and the Q |

For all of them: the **insertion loss** at the peak, the **gain** at chosen frequencies, the **ripple** in the passband
(if you give one), the **group delay**, the **return loss** in the passband (with `also_s11`), and a **verdict** against a
mask. If an edge is not inside the sweep (the response never falls that far) the log says *"could not find the
cut-off: widen the sweep"* and that figure is left out; it is not made up.

## The file

```json filter.flt
{
  "filter": {"type": "bandpass", "label": "868 MHz SAW #4"},
  "sweep": {"start_hz": 800000000, "stop_hz": 940000000, "points": 561, "scale": "linear"},
  "edge_db": 3,
  "passband": {"from_hz": 863000000, "to_hz": 870000000},
  "frequencies_of_interest": [868000000, 915000000],
  "limits": {"bands": [{"from": 863000000, "to": 870000000, "min": -4},
                       {"from": 900000000, "to": 940000000, "max": -20}]},
  "also_s11": true,
  "averages": 1,
  "confirm_setup": true
}
```

| Field | Meaning |
|---|---|
| `filter.type` | `lowpass`, `highpass`, `bandpass` or `bandstop` |
| `filter.label` | identifies the filter; it is saved in the run |
| `sweep` | `start_hz`, `stop_hz`, `points`, `scale` (`linear` or `log`); optional `if_bandwidth_hz`, `power_dbm` |
| `edge_db` | how far below the peak the edges are (3 by default) |
| `passband` | optional `from_hz` / `to_hz`: where the ripple is measured and the reference level is taken |
| `frequencies_of_interest` | the gain is reported at these frequencies (inside the sweep) |
| `limits` | a **mask on the gain in dB** ([`ola/limits.py`](../ola/limits.py)). The gain is negative: `min: -4` means *at least -4 dB* (the filter must pass), `max: -20` means *at most -20 dB* (the filter must reject). Constants, lines and bands can be mixed |
| `also_s11` | also read S11 (return loss in the passband) |
| `averages`, `confirm_setup` | sweeps averaged; `false` skips the question |
| `golden` | optional: check the result against a **golden sample** of the project (a good unit of the same kind): `name` and `tolerances` ([`golden.md`](golden.md#as-a-step-of-a-measurement)) |

The sweep decides what can be found: it must include the edges and some of the stop band. For a narrow filter use
enough points (a step much smaller than the bandwidth). The editor (*Edit* in the project window, from the module's
`form.json`) shows every problem at its field and accepts numbers such as `868M` or `2.4 GHz`.

## Results

* **Curves** (*Curves* tab): `S21`, shown in dB with the **mask drawn dashed in red**, or as phase or on the Smith
  chart; hidden at first and selectable: `group_delay_ns` and `S11`.
* **Table `points`** (one row): the type and name of the filter, the insertion loss and where the peak is, the
  cut-off or edges, bandwidth, centre, Q, notch depth, ripple, the gain at each frequency of interest, the
  return loss, and the verdict `PASS` / `FAIL` with its margin in dB.
* **Table `sweep`**: a row per frequency with the gain in dB and the phase, for the CSV export; the S-parameters go to
  a Touchstone file from the *Curves* tab.

A filter that fails its mask is a **result**: the run still ends as *finished*, with `FAIL` and a warning in the log.

## Through a cable, an adapter or a pad

What is between the plane of the calibration and the filter is in the result: a cable adds its loss to the insertion loss. With
`correction` the fixtures that were measured are taken out (`port1`, `port2`, each a registry code `asset_id`, a `run` file
or a `touchstone` file; `mode` `complex` or `magnitude`; `model` `matched` or `full`), so the result is of the filter alone and
the raw measurement stays as `S21_raw`. How, and the two models, in [`deembedding.md`](deembedding.md).

## What the VNA must provide

The two logical calls `set_sweep` and `read_sparameter` ([`vna-calls.md`](vna-calls.md)). `ola/sim_vna.py`
(`SimVna(filter_type="bandpass", ...)`) is a simulated VNA with a Butterworth filter between the ports, used by the
tests; the figures the module finds are checked against the formulas of that filter.

## Not done yet

Tried only with the simulated VNA. Not measured yet: the roll-off (dB per octave or decade), the shape factor
(60 dB / 3 dB bandwidth) and the group-delay variation as figures of their own (the delay is available as a curve).
