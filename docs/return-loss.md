# Return loss / VSWR (`.rtl`)

How well a device is matched to the line, measured with a vector network analyzer (VNA): an antenna, an adapter, an
attenuator, the input of an amplifier. The VNA is calibrated by the user **at the port** the device connects to (a
one-port calibration: open, short, load) before measuring; the program does not touch the calibration, it asks once
whether it is done and to connect the device to port 1.

## What it measures

S11, from which:

* the **return loss** in dB: `-20 log10 |S11|`; bigger is a better match (a perfect match is infinite, 10 dB is a
  common minimum, a total reflection is 0 dB);
* the **VSWR**: `(1 + |S11|) / (1 - |S11|)`, from 1 (perfect) upwards; a total reflection is shown as 100;
* the **impedance** `R + jX` at every frequency, and at the best match;
* the **usable bands**: where the VSWR stays at or under a limit (2 by default). For an antenna this is its
  bandwidth.

## The file

```json return_loss.rtl
{
  "sweep": {"start_hz": 800000000, "stop_hz": 950000000, "points": 301, "scale": "linear"},
  "device": {"label": "868 MHz antenna #2"},
  "z0": 50,
  "vswr_max": 2.0,
  "frequencies_of_interest": [868000000, 900000000],
  "limits": {"bands": [{"from": 860000000, "to": 876000000, "min": 10}]},
  "averages": 1,
  "confirm_setup": true
}
```

| Field | Meaning |
|---|---|
| `sweep` | `start_hz`, `stop_hz`, `points`, `scale` (`linear` or `log`); optional `if_bandwidth_hz`, `power_dbm` |
| `device.label` | identifies the device; it is saved in the run |
| `z0` | reference impedance of the VNA, 50 ohm by default |
| `vswr_max` | the bands where the VSWR is at most this are reported (2 by default, must be above 1) |
| `frequencies_of_interest` | return loss and VSWR are reported at these frequencies (inside the sweep) |
| `limits` | pass / fail on the **return loss in dB**, normally a minimum: `{"min": 10}`, or per band as above ([`ola/limits.py`](../ola/limits.py)) |
| `averages` | number of sweeps averaged |
| `confirm_setup` | `false` skips the question (for scripts) |

The editor (*Edit* in the project window) comes from the module's `form.json`: every problem is shown at its field and
numbers can be typed as `868M` or `2.4 GHz`.

## Results

* **Curves** (*Curves* tab): `return_loss_db` (with the limit drawn dashed in red) and, hidden at first and selectable
  in the list, `vswr` and the raw `S11` (what the **Smith chart** and the Touchstone `.s1p` export use).
* **Table `points`** (one row): the device label, the best match (return loss, VSWR, frequency), the impedance
  there, the worst match, the return loss and VSWR at each frequency of interest, the number of usable bands, the
  widest band (from, to, width), all the bands as text, and the **verdict** `PASS` / `FAIL` with its margin in dB.
* **Table `sweep`**: a row per frequency (return loss, VSWR, R, X), for the CSV export.

A device that fails its limit is a **result**: the run still ends as *finished*, with `FAIL` and a warning in the log.
If the VSWR is above the limit everywhere, the log says so (and there are no usable bands).

## What the VNA must provide

The two logical calls `set_sweep` and `read_sparameter` (S11 here), described in [`vna-calls.md`](vna-calls.md).
`ola/sim_vna.py` (`SimVna(termination="antenna")`) is a simulated VNA with a resonant antenna on port 1, used by the
tests.

## Not done yet

Tried only with the simulated VNA; no real instrument has been used (the `vna` category of the library is still to be
written). The **impedance of an antenna** as a measurement of its own, with the Smith chart front and centre, is the
next module.
