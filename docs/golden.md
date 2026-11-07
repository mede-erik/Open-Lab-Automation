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
| `rows` | for a measurement that gives a **table of rows** (ripple for each load current, efficiency for each input and output, regulation, S-parameters for each sweep): `{"match": [columns], "columns": {column: tolerance}}`. The rows are paired by the values of the `match` columns, and each of the `columns` is checked over all the pairs, with the same tolerance as a figure (a number, or `abs` / `rel`) |
| `min_overlap` | the part of the golden points (or rows) that the run must cover, from above 0 to 1 (0.9 by default) |

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

## In the comparison window

The tab **Golden sample** of *Compare results* ([`compare.md`](compare.md)) does the same with the runs that are open: the
**reference** run (★) is the golden sample and every other ticked run is checked against it. Choose the curve and its view, the
tolerance and its **side** (above and below, only above: more loss is the failure, only below), the part of the golden curve that
must be covered, and a tolerance for any figure of the summary (`0.3`, or `5%` of the golden value; empty = not checked); **Check**
gives the verdict of each run with its reasons. **Keep the reference as golden sample...** writes it in the `golden/` folder of the
project under a name, and **Open a golden sample...** opens one from there as the reference.

## As a step of a measurement

Every measurement but the time log can check itself at the end of the run: the VNA measurements (**cable**, **filter**,
**amplifier**, **attenuator**, **return loss**, **antenna**, **time domain**), the **Bode plot**, and those that give a table of rows
(**ripple**, **regulation**, **efficiency**, **S-parameters**). In their file

```json
"golden": {"name": "RG58 1m",
           "tolerances": {"curves": [{"trace": "loss_db", "tolerance": 0.3}], "summary": {"max_loss_db": 0.2}}}
```

The project finds the golden sample by its **name** in its `golden/` folder (a run is refused before it starts if there is none, with
the names that are there) and saves the file it used (`golden.run`) in the header of the run. The run gets a table `golden` (one row
for each check: `check`, `passed`, `difference`, `at`, `margin`, `detail`) and `golden_verdict` (`PASS`, `FAIL` or `NO DATA`) and
`golden_failed` in its summary row. Like a limit, a failed check is a **result**: the run still finishes, with warnings in the log. Any
curve the measurement draws can be checked, in any view (`value` by default): the cable's `loss_db`, the filter's and the amplifier's
`S21` in `magnitude_db`, the attenuator's `attenuation_db`, the `return_loss_db` of the return loss and of the antenna... The editors of
these measurements have the two fields.

A measurement with a **table of rows** has no summary row to put the verdict in: its rows are checked with `rows` at the end of the
run, and the verdict is the one row of the table `golden_result` (`golden_verdict`, `golden_failed`). For example:

| Measurement | `rows` |
|---|---|
| ripple (one row per load current) | `{"match": ["load_current_a"], "columns": {"pp_v": 0.005, "rms_v": {"rel": 0.2}}}` |
| efficiency (one row per point of the sweep) | `{"match": ["vin", "iout"], "columns": {"efficiency": 0.5}}`: the derived columns (the efficiency formula) are there too |
| regulation (one row per point) | `{"match": ["test", "vin", "i"], "columns": {"vout": 0.01}}` |
| S-parameters (one row per sweep) | `{"match": ["sweep"], "columns": {"S21_max_db": 0.2}}`; the `curves` are those of the last sweep |

(In the code: one line at the start of the measurement, `ctx = recording(ctx, "filter", params)`, keeps the curves and checks the
summary row before it goes out; a measurement of many rows passes `summary_row=False` and calls `finish(ctx)` at the end of its
run. A new module gets the step the same way.)

## Tolerances from several good units

Instead of writing the tolerances by hand, measure **a few good units** besides the golden one and let the program work them out
(`derive_tolerances`): for each curve, how far each good unit is from the golden one, **times a factor** (2 by default) and at least a
**floor** (0.05); the result is a tolerance **line** of the frequency, in flat stretches that each take the largest difference in
them (so every unit it was made from passes), and an absolute tolerance for each figure of the summary.

* In the comparison window: tick the golden sample (the reference) and the good units, then **Suggest from the ticked runs**: the
  tolerance of the curve (the largest of the line) and of each figure are filled in. Look at them, then **Check**.
* From a terminal, writing a file to use with `--spec` or in a measurement:

```bash
python scripts/golden_check.py --derive runs/golden.jsonl runs/good1.jsonl runs/good2.jsonl \
    --derive-curve S21:loss_db --factor 2 --out tolerances.json
```

With two or three good units the spread is a rough guess: keep the factor at 2 or more, and widen the tolerances by hand where the
units happen to agree too well (the floor is there for that).

## Not done yet

A report does not include the check (see *Future features* in the README). The time log has no step (a log has no good unit to
compare with). `derive_tolerances` works out `rows` too (`rows={"match": [...], "columns": [...]}`), but only from Python: the
comparison window and `--derive` fill in curves and summary figures.
