# Cable characterization (`.cbl`)

The loss of an RF cable against frequency, measured with a vector network analyzer (VNA). The VNA is
calibrated by the user beforehand, at the ends of the test leads, as for any VNA measurement; the program does not
touch the calibration. It asks once, before measuring, whether the VNA is calibrated and how to connect the cable.

## What it measures

| Mode | Connection | Parameter | Loss of the cable |
|---|---|---|---|
| `transmission` (default) | cable between port 1 and port 2 | S21 | `-20 log10 |S21|` |
| `reflection` | one end on port 1, an **open** or **short** on the other end | S11 | `-20 log10 |S11| / 2` (the signal goes to the end and back) |

With `"also_s11": true` in transmission mode the return loss and the VSWR of the cable are reported too.

## The file

```json cable.cbl
{
  "mode": "transmission",
  "sweep": {"start_hz": 1000000, "stop_hz": 3000000000, "points": 401, "scale": "linear",
            "if_bandwidth_hz": 1000, "power_dbm": -10},
  "cable": {"label": "RG58 #3", "length_m": 2.0},
  "frequencies_of_interest": [433000000, 868000000, 2400000000],
  "limits": {"bands": [{"from": 1000000, "to": 1000000000, "max": 1.5},
                       {"from": 1000000000, "to": 3000000000, "max": 3.0}]},
  "also_s11": true,
  "averages": 1,
  "confirm_setup": true
}
```

| Field | Meaning |
|---|---|
| `mode`, `termination` | `transmission` or `reflection`; for reflection `open` (default) or `short` |
| `sweep` | `start_hz`, `stop_hz`, `points`, `scale` (`linear` or `log`); optional `if_bandwidth_hz`, `power_dbm` |
| `cable.label` | identifies the cable; it is saved in the run, so a result can be tied to its cable |
| `cable.length_m` | gives the loss in dB/m and the velocity factor |
| `frequencies_of_interest` | the loss is reported at these frequencies (read from the curve; they must be inside the sweep) |
| `limits` | pass / fail limit on the loss in dB: a constant, a line, or one limit per band ([`ola/limits.py`](../ola/limits.py)) |
| `averages` | number of sweeps averaged (reduces noise) |
| `golden` | optional: check the result against a **golden sample** of the project, a good cable of the same kind: `name` and `tolerances` ([`golden.md`](golden.md#as-a-step-of-a-measurement)) |
| `confirm_setup` | `false` skips the question (for scripts) |

The editor (*Edit* in the project window, built from the module's `form.json`) checks the file while it is filled in: every problem is shown at its field, a number can be typed as `433M` or `2.4 GHz`, and the VNA is chosen from the instruments of the project.

## Results

* **Curves** (*Curves* tab): `loss_db` (positive = loss, with the limit drawn dashed in red), and, hidden at first
  and selectable in the list: `loss_db_per_m`, `group_delay_ns`, `return_loss_db` and the raw `S21` / `S11`
  (what the Smith chart, the phase and the Touchstone export use).
* **Table `points`** (one row, *Results* tab): the cable label, the loss at each frequency of interest (and per
  metre), the worst loss and where it is, the mean delay in ns, the velocity factor, the return loss, and the
  **verdict** `PASS` / `FAIL` with its margin in dB.
* **Table `sweep`**: a row per frequency, for the CSV export (`ola.runs.export_points_csv(run, csv, table="sweep")`).
* The S-parameters go to a Touchstone file (`.s1p` / `.s2p`) from the *Curves* tab.

A cable that fails its limit is a **result**: the run still ends as *finished*, with `FAIL` and a warning in the log.

## What the VNA must provide

The measurement asks for two *logical calls*, the same for every VNA; the instrument library translates them for
the model (this is the contract of the network analyzer category (`network_analyzers_series`), written in full in [`vna-calls.md`](vna-calls.md)):

| Call | Arguments | Gives |
|---|---|---|
| `set_sweep` | `start_frequency`, `stop_frequency`, `points`, `sweep_type` (`linear`/`log`), optional `if_bandwidth`, `power` | nothing |
| `read_sparameter` | `parameter` (`"S11"` or `"S21"`) | `{"frequency": [...], "values": [[re, im], ...]}`, or a plain list of complex numbers (then the frequencies are those of the sweep) |

`ola/sim_vna.py` (`SimVna`) is a simulated VNA with a cable of a given length, loss and velocity factor, used by
the tests and to try the measurement without hardware.

## A limit of every VNA: the frequency step

The delay of the cable is found from how fast the **phase** changes with frequency. If two neighbouring points
are so far apart that the phase turns by more than half a turn between them, the phase wraps and the delay (and
so the velocity factor) cannot be found. The loss is not affected. The largest useful step is `1 / (2 x delay)`:
about **45 MHz for a 1 m cable, 4.5 MHz for 10 m**. The editor shows a warning (*"the step between points is too
large ... use at least N points"*) when the sweep is too coarse for the length of the cable, and if the
measurement is run anyway the delay and velocity factor are left out, with a warning in the log, instead of
showing a wrong number.

## Not done yet

Tried only with the simulated VNA: no real instrument has been used yet. The library now has the network analyzer
category and the LiteVNA, and the measurement speaks its calls ([`vna-calls.md`](vna-calls.md)), but it has not been
tried on one.
