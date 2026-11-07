# Checking against a golden sample

A **golden sample** is a run of a unit that is known to be good: the cable that came with a calibration certificate, the
filter that passed the acceptance test. A new run is checked against it and the answer is a verdict, `PASS` or `FAIL`, with the
reasons. It is the question *"is this one like the good one?"* where a limit asks *"is this one under a number?"*.

The logic is in [`ola/golden.py`](../ola/golden.py) (no Qt); [`scripts/golden_check.py`](../scripts/golden_check.py) runs it
from a terminal. The comparison window ([`compare.md`](compare.md)) shows the same two runs side by side.

## The golden sample

* **Any finished run** can be one. `set_golden` copies the run file into the `golden/` folder of the project under a name
  (`<project>/golden/RG58.jsonl`); a run that did not finish is refused. A new `set_golden` of the same name replaces it.
* It must be the **same kind of measurement** as what is checked (a cable against a cable), measured over a sweep that
  **covers** the one you check (below).
* Keep one for each kind of cable (or filter, or amplifier), not one for each unit: the point is to compare a unit with the good
  one of its kind.

## The tolerances

```json tolerances.json
{
  "curves": [
    {"trace": "S21", "view": "loss_db", "tolerance": [[1000000, 0.1], [300000000, 0.5], [3000000000, 1.2]]}
  ],
  "summary": {"loss_868MHz_db": {"abs": 0.1, "rel": 0.05}, "max_loss_db": 0.5},
  "min_overlap": 0.9
}
```

| Field | Meaning |
|---|---|
| `curves` | the curves to compare: `trace` (`S21`...), `view` (`loss_db`, `magnitude_db`, `phase`, `value`... as in the comparison window; `value` by default) and the `tolerance` |
| `tolerance` of a curve | a number (plus or minus that at every frequency), a **line** `[[frequency, tolerance], ...]` (straight between the points, flat outside: a cable can differ more at 3 GHz than at 10 MHz), or `{"upper": u, "lower": l}` for an asymmetric one: the run may be `u` above the golden curve and `l` below it (a cable that is more lossy than the good one is the failure, a less lossy one is not) |
| `summary` | figures of the one-row summary, each with a number (absolute) or `{"abs": x, "rel": r}`: `rel` is a fraction of the golden value, and if both are given the **larger** allowance counts |
| `min_overlap` | the part of the golden points that the run must cover, from above 0 to 1 (0.9 by default) |

The curves are compared **at the frequencies of the golden curve**, where the run has data (the run is read between its points; nothing is
made up outside its range). A run of a narrower sweep proves nothing about the missing part, so it **fails** unless it covers at
least `min_overlap` of the golden curve.

## The answer

`PASS` if every check is within its tolerance, `FAIL` if one is not, `NO DATA` if there was nothing to check. For each curve:
the largest difference with its sign and where, the RMS, and how many points are out of tolerance. For each figure: the two values, the
difference and what was allowed. A curve or a figure that the run (or the golden sample) does not have **fails with a sentence**,
it is not skipped.

```
FAIL: 1 of 2 checks ok  (RG58 #3 - 2026-11-05 10:00 against golden RG58)
  ok   S21 (loss_db): largest difference +0.4 at 3e+09, RMS 0.21
  FAIL loss_868MHz_db: 1.62 against 1.34 (difference +0.28, allowed 0.1)
```

## From a terminal

```bash
python scripts/golden_check.py --set myproject RG58 runs/cable_golden_20261103_100000.jsonl
python scripts/golden_check.py runs/cable_20261105_100000.jsonl RG58 --project myproject \
    --curve S21:loss_db:0.5 --figure loss_868MHz_db:5%
python scripts/golden_check.py runs/new.jsonl runs/golden.jsonl --spec tolerances.json
```

The exit code is 0 for `PASS`, 1 for `FAIL` or `NO DATA`, 2 for a request that cannot be used (a wrong tolerance, two different
kinds of measurement, a file that cannot be read), so a script can act on it.

## Not done yet

The check is not yet a step of a measurement or a button of the comparison window, and a report does not include it (see *Future
features* in the README). Tolerances are written by hand: there is no way yet to work them out from several good units.
