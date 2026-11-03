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
