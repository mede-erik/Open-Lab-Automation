# Antenna impedance (`.ant`)

The impedance of an antenna (or of any one-port) against frequency, measured with a vector network analyzer
(VNA), with the **Smith chart** in front. The VNA is calibrated by the user **at the port** the antenna connects to
(a one-port calibration: open, short, load); the program does not touch the calibration, it asks once whether it is
done and to connect the antenna to port 1. It is the companion of [`return-loss.md`](return-loss.md): the same S11,
read as an impedance.

## What it gives

* the **impedance** `R + jX` at every frequency (also as the curves `resistance_ohm` and `reactance_ohm`), and the
  S11 on the **Smith chart**, which is the view the window opens with (a point under the mouse reads the
  reflection coefficient, the impedance and the VSWR);
* the **resonances**: a *series resonance* is where the reactance crosses zero going from negative to positive,
  and is where an antenna is matched (the resistance there is its radiation resistance plus losses); a crossing the
  other way is an *anti-resonance*, with a high resistance. The one with the lowest VSWR is reported as the main
  one;
* the **best match** (lowest VSWR) and the impedance there;
* the **usable band**, where the VSWR stays at or under `vswr_max` (2 by default), and its **fractional bandwidth**
  in percent of the centre frequency;
* at each **frequency of interest**: `R`, `X`, `|Z|`, the VSWR, the return loss, and the **series component that
  would cancel the reactance** there: a capacitor if `X` is positive (`C = 1 / (2 pi f X)`), an inductor if it is
  negative (`L = -X / (2 pi f)`). It is a starting point for a matching network, not a design: it cancels the
  reactance but not a resistance different from 50 ohm;
* a **verdict** `PASS` / `FAIL` on the return loss against a limit, if you give one.

## The file

```json antenna.ant
{
  "sweep": {"start_hz": 800000000, "stop_hz": 950000000, "points": 601, "scale": "linear"},
  "device": {"label": "868 MHz whip #2"},
  "z0": 50,
  "vswr_max": 2.0,
  "frequencies_of_interest": [840000000, 868000000, 900000000],
  "limits": {"bands": [{"from": 860000000, "to": 876000000, "min": 10}]},
  "averages": 1,
  "confirm_setup": true
}
```

The fields are those of the return-loss measurement ([`return-loss.md`](return-loss.md#the-file)): `sweep`, `device.label`,
`z0`, `vswr_max`, `frequencies_of_interest`, `limits` (on the **return loss** in dB, normally a minimum), `averages`,
`confirm_setup`. The editor (*Edit* in the project window) is built from the module's `form.json`.

## Results

* **Curves** (*Curves* tab): `S11` on the Smith chart or in any other view; hidden at first and selectable:
  `resistance_ohm`, `reactance_ohm`, `return_loss_db` (with the limit) and `vswr`. The S11 goes to a Touchstone
  `.s1p` file from the same tab.
* **Table `points`** (one row): the antenna name, the best match, the series resonance (frequency, resistance,
  VSWR), the list of resonances and anti-resonances, the usable bands and the fractional bandwidth, the impedance
  and the cancelling component at each frequency of interest, and the verdict.
* **Table `sweep`**: a row per frequency (`R`, `X`, VSWR, return loss), for the CSV export.

If the antenna does not resonate inside the sweep, the log says so; if the VSWR is above the limit everywhere, it
says that too.

## Through a cable: the VSWR of the antenna alone

An antenna measured at the end of a cable looks **better matched than it is**: the reflection goes down the cable and
back and the loss of the cable weakens it twice (a cable of 3 dB loses 6 dB on the way, so a return loss of 6 dB looks
like 12 dB, and a VSWR of 3 like 1.6). The correction takes the cable out, using the measurements you already made of it
([`cable.md`](cable.md)):

```json
"correction": {"cable": {"asset_id": "CBL-0042"}}
```

The antenna can be corrected too: the cable must then be known **with its phase** (measured in transmission, or in reflection with an open or short): a cable known only by its loss is refused, because the impedance needs the phase. Then everything the antenna measurement gives is of the antenna alone, the impedance and the Smith chart included.

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

The two logical calls `set_sweep` and `read_sparameter` (S11 here), in [`vna-calls.md`](vna-calls.md).
`SimVna(termination="antenna")` is a simulated VNA with a resonant antenna on port 1, used by the tests.

## Things to know

* The reference plane is where the VNA was calibrated: an antenna measured through a cable that was not part of the
  calibration shows the impedance **at the VNA end** of that cable, rotated on the Smith chart by its length.
* An antenna in a room is measured with the room: keep it away from metal and people while sweeping.

## Not done yet

Tried only with the simulated VNA. Not done: port extension (moving the reference plane by an electrical length),
and a full matching-network design (L-network, stub) from the measured impedance.
