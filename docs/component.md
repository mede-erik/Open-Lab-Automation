# Component impedance: inductors, capacitors, resistors (`.cmp`)

The impedance of a two-terminal component against frequency, measured with a vector network analyzer (VNA): an inductor
and its winding capacitance, a capacitor with its ESR and lead inductance, a resistor, a ferrite bead or a common-mode
choke. The measurement gives `|Z|`, `R`, `X`, the inductance or the capacitance, the quality factor `Q`, the
**self-resonance**, and checks a nominal value.

## How the component is connected

The VNA measures a reflection or a transmission; how the component sits between its ports decides which impedances are
measured well (`ola/component.py`):

| `method` | Connection | `Z` from | Good for |
|---|---|---|---|
| `reflection` | from the centre of port 1 to ground | `S11`: `Z = z0 (1 + S11) / (1 - S11)` | a few ohm to a few hundred ohm (near 50 ohm) |
| `series` | in series between port 1 and port 2 (series-thru) | `S21`: `Z = 2 z0 (1 - S21) / S21` | **high** impedances: inductors, small capacitors, ferrites and chokes (tens of ohm to tens of kilohm) |
| `shunt` | from a thru line between the ports to ground (shunt-thru) | `S21`: `Z = z0 S21 / (2 (1 - S21))` | **low** impedances: large capacitors and their ESR, milliohm to a few ohm |

The two transmission methods need only `S11` and `S21`: they work with a VNA that measures in one direction (the
LiteVNA). If many points fall outside the range of the chosen method (a reflection close to total, a series transmission
close to zero, a shunt one close to one) the log names the method that suits the component better.

## The file

```json component.cmp
{
  "device": {"label": "L3, 100 nH 0603"},
  "sweep": {"start_hz": 1000000, "stop_hz": 1000000000, "points": 801, "scale": "log"},
  "method": "series",
  "kind": "inductor",
  "nominal": {"value": 1e-7, "tolerance_pct": 5, "frequency_hz": 10000000},
  "frequencies_of_interest": [10000000, 100000000],
  "z0": 50,
  "averages": 1,
  "confirm_setup": true
}
```

| Field | Meaning |
|---|---|
| `device.label` | identifies the component (saved with every run) |
| `sweep` | as in every VNA measurement; a **logarithmic** sweep shows a component over decades of frequency |
| `method` | `reflection`, `series` (the default) or `shunt` |
| `kind` | `auto` (found from the reactance below the first resonance), `inductor`, `capacitor` or `resistor` |
| `nominal` | optional: `value` (H, F or ohm; the editor takes `100n`, `4.7p`), `tolerance_pct` (10 by default) and `frequency_hz` where it is checked. It needs a `kind` other than `auto` |
| `frequencies_of_interest` | `|Z|`, `R`, `X`, the value and `Q` are reported there |
| `z0` | the reference impedance of the VNA (50 ohm by default) |
| `golden`, `averages`, `confirm_setup` | as in the other VNA measurements |

## Results

* **Curves**: `z_abs_ohm` (shown first); hidden and selectable: `r_ohm`, `x_ohm`, `l_nh` for an inductor or `c_pf` for a
  capacitor, `q`, and the measured `S11` or `S21` (the Touchstone export uses it).
* **Table `sweep`**: a row per frequency (`R`, `X`, `|Z|`, phase, `Q`, the inductance or the capacitance).
* **Table `points`**: the kind, the lowest and highest `|Z|`, the **self-resonances** (`self_resonance_hz` and
  `self_resonance_kind`: `parallel` for an inductor, where `|Z|` peaks; `series` for a capacitor, where it dips to the ESR),
  the values at the frequencies of interest (`l_h_10MHz`, `c_f_1MHz`, `r_10MHz_ohm`, `q_10MHz`...), and with `nominal`:
  `measured_value`, `deviation_pct` and the `verdict` (`PASS` within the tolerance). A component that is the other kind at
  the frequency of the check (an inductor above its resonance) is `FAIL`.

The value is the **effective** one at each frequency: a capacitor's lead inductance makes it look larger as the frequency
rises, an inductor's winding capacitance does the same to it. Check the nominal value well below the self-resonance.

## How to measure

1. **Calibrate** at the plane where the component connects: open, short and load on port 1 for `reflection`; for `series`
   and `shunt`, also a thru between the two ports (on the test fixture, if there is one).
2. Solder or clamp the component as the method says, with leads as short as possible: every millimetre is inductance in
   series with it.
3. Start the run.

## What the VNA must provide

The calls of the network analyzer category ([`vna-calls.md`](vna-calls.md)): one S-parameter per run (`S11` or `S21`).
`ola/sim_vna.py` has `SimComponent`, the simulated component of the tests.

## Not done yet

Not tried on a real VNA, only on the simulation. A test fixture with its own length is not taken out yet (calibrate on the
fixture instead). Two-port components (a transformer, a common-mode choke in differential mode) are not covered.
