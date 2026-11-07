# How a cable ages: the loss against the date

Every run keeps the code of the cable it measured ([`assets.md`](assets.md)), so all the measurements of a cable can be found
again. Its **loss** normally stays the same for a long time and then grows, as a connector wears, the braid corrodes or the
cable is bent once too often. This follows it: a figure of the measurements against the date, a straight line through them and a
verdict that is given **before** the cable is out of use.

The logic is in [`ola/trend.py`](../ola/trend.py) (no Qt); [`scripts/cable_trend.py`](../scripts/cable_trend.py) runs it from a
terminal.

## What it uses

* The finished runs of the **cable measurement** ([`cable.md`](cable.md)) whose header names the code (`CBL-0042`), found in the folders
  you give (the `runs/` of the project). A run that did not finish, a run of another kind of measurement and a run without the
  figure are left out.
* **One figure** of the summary row of those runs: `max_loss_db` (the worst loss, by default) or the loss at a frequency of
  interest (`loss_868MHz_db`, `loss_868MHz_db_per_m`). `--list-figures` shows which ones the runs have.
* The date of each run, from its file name.

For the trend to mean something every measurement should have the **same sweep and the same calibration** (the same frequencies of
interest): a different sweep changes `max_loss_db` by itself.

## The line

A least-squares line through the points gives the **rate** (per year, with its uncertainty) and the scatter of the points around
it. The change counts as real only if the slope is more than **twice its uncertainty**: a few measurements that differ by the noise
of the VNA are *steady*, not aging. With **fewer than three** measurements, or all within half a day, there is not enough to say
anything and the answer is `NOT ENOUGH DATA`.

## The verdict

| | When |
|---|---|
| `FAIL` | the last measurement is **past the limit**; or the real rate of change for the worse is above `max_rate_per_year` |
| `WARNING` | the line **reaches the limit** within `warn_within_days`: the date it does is given |
| `PASS` | none of the above |
| `NOT ENOUGH DATA` | too few measurements to draw a line (and nothing already past the limit) |

All three options are optional. `higher_is_worse` is true for a loss; it is false for a figure that must stay high (a return
loss): then the limit is a floor and a falling value is the one that ages.

```bash
python scripts/cable_trend.py CBL-0042 runs --figure loss_868MHz_db --limit 3 --max-rate 0.5 --warn-days 90
python scripts/cable_trend.py CBL-0042 runs --list-figures
python scripts/cable_trend.py CBL-0042 runs --csv trend.csv
```

```
loss_868MHz_db: WARNING: +0.62/year (worse), last 1.58 of 4 measurements
  +0.62 +/- 0.03 per year, scatter 0.011
  2026-01-01 10:00  1.2  cable_CBL-0042_20260101_100000.jsonl
  ...
  - at this rate it reaches the limit 3 on 2028-03-05 (in 410 days)
```

The exit code is 0 for `PASS`, 1 for anything else, 2 for a request that cannot be used.

## In the registry window

In *Tools* > *Cables and devices* ([`assets.md`](assets.md)), **History...** of a cable has **Trend...**: the same, drawn. Choose the
figure, tick the limit, the fastest change accepted and the warning window if you want them, and *A lower value is worse* for a figure
that must stay high. The plot shows the measurements against the days since the first one, the line through them (continued to the
limit when it gets there) and the limit dashed; under it the text above. **Save as CSV...** writes the series.

## Not done yet

The trend is not printed on the label of the cable (a label is printed once, the trend changes with every measurement), and a
straight line is all there is: a cable that is steady and then falls off a cliff is seen only after the cliff. It follows one figure at a time and does not compare cables
with each other (that is [`compare.md`](compare.md)).
