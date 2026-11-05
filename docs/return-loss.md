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

## Through a cable: the VSWR of the antenna alone

An antenna measured at the end of a cable looks **better matched than it is**: the reflection goes down the cable and
back and the loss of the cable weakens it twice (a cable of 3 dB loses 6 dB on the way, so a return loss of 6 dB looks
like 12 dB, and a VSWR of 3 like 1.6). The correction takes the cable out, using the measurements you already made of it
([`cable.md`](cable.md)):

```json
"correction": {"cable": {"asset_id": "CBL-0042"}}
```

The cable is named with **one** of:

| Field | The cable is... |
|---|---|
| `asset_id` | its code in the registry ([`assets.md`](assets.md)). The program takes the **newest finished measurement of that cable** in the runs folder of the project and keeps the file it used in the header of the run. If there is none the run does not start and says to measure the cable first |
| `run` | a run file (`.jsonl`) of a cable measurement |
| `touchstone` | a `.s2p` file (the cable in transmission) or a `.s1p` (the cable with an open or a short at the far end: say which with `termination`) |

`mode` is `complex` (with the phase of the cable) or `magnitude` (the loss alone); without it, `complex` if the cable
has a phase. The maths is in [`ola/deembed.py`](../ola/deembed.py): the reflection of the antenna is
`S11 measured / T^2`, where `T^2` is what the cable does to a signal that goes to the far end and comes back (the
`S21` of the cable squared, or the `S11` of an open, or minus the `S11` of a short).

* **How to calibrate**: at the end of the **test lead, without the cable**. The cable is not part of the calibration: its
  loss is what the correction takes out. Use the **same cable** that was measured, in the same position (bend it as it was).
* **What you get**: the curves `return_loss_db` and `vswr` are of the device alone, and the measurement as it came stays as
  `return_loss_raw_db` (drawn together with the corrected one), `vswr_raw` and `S11_raw`, so the two can be compared; the
  sweep table has the `*_raw` columns; the summary says `corrected`, `correction_source`, `correction_mode`,
  `cable_loss_one_way_db` and `raw_min_vswr`, `raw_max_vswr`, `raw_best_return_loss_db`.
* **The cable must cover the sweep** (it can be measured wider, not narrower), and be measured with enough points for its
  length (the phase must not turn by more than 140 degrees between two points: the cable data is flagged otherwise).
* **Assumption**: the cable is **well matched**: its own reflections are not part of the correction. For a good cable this is
  fine; with a poor connector the correction is an approximation.
* **When it does not fit**: where the corrected reflection would exceed 1 (more than a device can reflect: another cable, a
  calibration at a different place) it is limited just under 1 and the log says how many points, as a warning.

## What the VNA must provide

The two logical calls `set_sweep` and `read_sparameter` (S11 here), described in [`vna-calls.md`](vna-calls.md).
`ola/sim_vna.py` (`SimVna(termination="antenna")`) is a simulated VNA with a resonant antenna on port 1, used by the
tests (`termination="antenna_via_cable"` puts the same antenna at the end of the cable: a test checks that the correction
recovers the VSWR of the antenna alone).

## Not done yet

Tried only with the simulated VNA; no real instrument has been used (the `vna` category of the library is still to be
written). The **impedance of an antenna** as a measurement of its own, with the Smith chart front and centre, is the
next module.
