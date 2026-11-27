# Quartz crystal (`.xtl`)

The **equivalent circuit** of a quartz crystal (or a ceramic resonator) measured with a vector network analyzer (VNA):
its series and parallel resonances, the motional resistance, inductance and capacitance, the capacitance of its electrodes,
its quality factor, the frequency it runs at with the load capacitance of its datasheet, and a check of that frequency in
ppm.

## The model

A crystal is modelled by the **Butterworth-Van Dyke** circuit: a *motional* arm `Rm`, `Lm`, `Cm` in series, with the
capacitance of the electrodes `C0` in parallel. The crystal is put **in series between port 1 and port 2** (series-thru),
and its impedance is `Z = 2 z0 (1 - S21) / S21` ([`ola/crystal.py`](../ola/crystal.py)):

* `fs`, the **series resonance**: where the reactance crosses zero going up, at the peak of `S21`; `Rm` is the resistance
  there;
* `Lm` from the slope of the reactance at `fs` (`dX / dw = 2 Lm`), `Cm = 1 / (ws^2 Lm)`, `Q = ws Lm / Rm`;
* `fp`, the **parallel resonance**: the reactance falls back through zero, at the dip of `S21`; `C0 = Cm fs / (2 (fp - fs))`;
* with the **load capacitance** `CL` of the datasheet: `fL = fs (1 + Cm / (2 (C0 + CL)))`, the frequency in a
  parallel-resonant oscillator, and the **pulling** `dfL / dCL` in ppm per pF.

## The file

```json crystal.xtl
{
  "device": {"label": "Y1, 10 MHz HC-49"},
  "sweep": {"start_hz": 9990000, "stop_hz": 10040000, "points": 2001},
  "nominal_frequency_hz": 10000000,
  "tolerance_ppm": 30,
  "load_capacitance_pf": 18,
  "z0": 50,
  "averages": 1,
  "require_calibration": false,
  "confirm_setup": true
}
```

| Field | Meaning |
|---|---|
| `sweep` | **narrow and linear** around the resonance: a crystal of Q 30000 at 10 MHz is only a few hundred hertz wide. It should cover `fs` and, a few tens of kilohertz above it, `fp`; at least 10 points across the resonance (the editor warns) |
| `nominal_frequency_hz` | optional: the offset in ppm is reported, of `fL` when a load is given, else of `fs` |
| `tolerance_ppm` | optional, with the nominal frequency: the verdict on the offset |
| `load_capacitance_pf` | optional: the load the crystal is specified for |
| `z0`, `golden`, `averages`, `require_calibration`, `confirm_setup` | as in the other VNA measurements ([`vna-calls.md`](vna-calls.md#common-parameters-of-the-vna-measurements)) |

## Results

* **Curves**: `s21_db` (the peak is `fs`, the dip `fp`); hidden: `x_ohm`, `r_ohm` and the measured `S21`.
* **Table `points`**: `fs_hz`, `rm_ohm`, `lm_h`, `cm_f`, `q`, and when the parallel resonance is in the sweep `fp_hz` and
  `c0_f`; with a load `fl_hz` and `pulling_ppm_per_pf`; with a nominal frequency `offset_ppm` and the `verdict`. A crystal
  off its frequency is a **result**: the run ends as *finished*, with `FAIL`.

The series resonance found is where the reactance of the whole crystal is zero: `C0` moves it above the resonance of the
motional arm alone by a fraction of a ppm (the tests check this on a simulated crystal of known values).

## How to measure

1. **Calibrate** for the narrow sweep: open, short and load on port 1 and a thru, at the plane where the crystal goes
   (on the test fixture). A low **IF bandwidth** (`if_bandwidth_hz`, 100 Hz or less) keeps the noise down.
2. Keep the source power low (`power_dbm`, -10 dBm or less): a crystal driven too hard changes its frequency.
3. Put the crystal in series between the two ports with short leads, and start the run.

## What the VNA must provide

Only `S21` ([`vna-calls.md`](vna-calls.md)): it works with a forward-only VNA such as the LiteVNA. `ola/sim_vna.py` has
`SimCrystal`, the simulated crystal of the tests.

## Not done yet

Not tried on a real VNA, only on the simulation. The fixture is not taken out (calibrate on it); the IEC 60444 pi-network
method and the spurious modes of a crystal are not covered.
