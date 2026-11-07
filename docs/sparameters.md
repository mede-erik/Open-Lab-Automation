# S-parameters (`.spm`)

One or more sweeps of a vector network analyzer (VNA), recorded as **complex curves**: the raw S-parameters of a device, to be
looked at, compared or saved as a Touchstone file. It is the simplest of the VNA measurements and the one to use when none of the
others (return loss, filter, amplifier, antenna, cable, time domain) is the question you are asking.

## What it measures

For every sweep, each requested S-parameter (`S11`, `S21`, `S12`, `S22`) is a complex trace over frequency, and one row of the
table `points` gives:

* the sweep number, its time `t_s` from the start of the run, and whether the data were `calibrated`;
* for each parameter: the **minimum** magnitude in dB and the **frequency of the minimum** (`S11_min_db`, `S11_min_hz`; for a
  reflection the best match, for a transmission a notch or a resonance of a trap) and the **maximum** magnitude (`S21_max_db`: the
  passband of a filter, the gain of an amplifier).

It makes no judgement: there is no limit and no verdict. For a verdict use the measurement that asks the question
([`return-loss.md`](return-loss.md), [`filter.md`](filter.md), [`amplifier.md`](amplifier.md), ...).

## The file

```json sparameters.spm
{
  "start_hz": 1000000,
  "stop_hz": 1000000000,
  "points": 201,
  "sparameters": ["S11", "S21"],
  "sweeps": 3,
  "interval_s": 1.0,
  "if_bandwidth_hz": 1000,
  "power_dbm": -10,
  "require_calibration": false
}
```

| Field | Meaning |
|---|---|
| `start_hz`, `stop_hz`, `points` | the sweep: `stop_hz` above `start_hz`, at least 2 points. It is **linear** |
| `sparameters` | what to read, from `S11`, `S21`, `S12`, `S22`; `["S11"]` by default; no repeated name |
| `sweeps` | how many sweeps (1 by default) |
| `interval_s` | the time between the **starts** of two sweeps (0 by default). It is scheduled from the start of the run, so a slow sweep shortens the next wait and the log does not drift; if the sweep is slower than the interval the sweeps follow one another |
| `if_bandwidth_hz` | the IF bandwidth: lower is less noise and a slower sweep. Only for a model that has it |
| `power_dbm` | the source power. Only for a model that has it |
| `require_calibration` | `true` stops the run if the data are not calibrated; `false` (the default) records them and writes **one** warning in the log |

## How to measure

1. **Calibrate** the VNA for the sweep you will use, at the plane of the connectors where the device goes. A change of the start,
   the stop, the points or the IF bandwidth afterwards can make the calibration invalid: the data then say `calibrated: false`.
2. Connect the device, with the ports that match the parameters you ask for (`S21` needs both ports).
3. Start the run. The sweeps are shown as they arrive; a repeated measurement gives one curve for every sweep (to watch a
   filter drift with temperature, for example).

The results can be exported as CSV, and as **Touchstone** (`.s1p` or `.s2p`) for the RF programs.

## What the VNA must provide

The calls of the network analyzer category ([`vna-calls.md`](vna-calls.md)): `set_frequency_sweep`, `run_sweep` and
`read_sparameters`, and, only if you ask for them, `set_if_bandwidth` and `set_source_power`. Every VNA of the library works the
same way. `ola/sim_vna.py` is a simulated one used by the tests.

## Not done yet

Not tried on a real VNA, only on the simulation. A logarithmic sweep is not offered here: the measurements that need one
([`filter.md`](filter.md)) ask for it themselves.
