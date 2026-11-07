# Comparing results (*Tools* > *Compare results*)

A tool to put saved results next to each other: two cables, a filter before and after a change, the same
amplifier on two days. Open it from the **Tools** menu (it starts in the `runs/` folder of the open project), or from
the project window with **Compare...** on the runs of the selected measurement. From the command line:
`python -m frontend.ui.CompareDialog run1.jsonl run2.jsonl`.

The logic is in [`ola/compare.py`](../ola/compare.py) (no Qt, tested on real run files); the window is
`frontend/ui/CompareDialog.py`.

## What it compares

Run files, `runs/<measurement>_<date>_<time>.jsonl`, the ones every run writes while it goes. Add them with **Add...**;
tick the ones to show. Each run has a name, by default **the name saved with it** (the cable, filter, amplifier or antenna
name of the measurement file) **and the date**: `RG58 #3 - 2026-11-03 10:00`; **Rename** changes it. The first run is the
**reference**; **Use as reference** changes it (marked with a star).

A file that cannot be used (empty, damaged, not a run file) is reported by name and left out; a run that was interrupted is
still read. Runs of different kinds of measurement can be loaded together, with a note: only what they have in common can
be compared.

## Curves

The curves the runs have in common (the list says *"S21 (2 of 3 runs)"*), in any view that suits them: the value, magnitude
in dB, **loss**, phase, real or imaginary part, or the **Smith chart**; with a logarithmic frequency axis if the
measurement asked for one. A read-out under the mouse gives the value of every curve there.

* **Overlay**: all the curves on the same axes.
* **Difference from the reference**: `other - reference` for every other run, at the frequencies of the reference where
  both have data (nothing is made up outside the range of the other curve), with the **largest difference** and where,
  the mean and the RMS: *"RG316 #1: largest +1.732 at 3 GHz, mean +1.154, RMS 1.225"*. Choose another reference and the
  sign reverses.
* **Export curves (CSV)**: one column pair per run (their frequencies may differ); **Save image** writes the plot as PNG.

## Summary

The figures of the summary rows (for the RF measurements: the loss at the frequencies of interest, the worst loss, the
delay, the cut-off, the verdict...) side by side, each with its **change from the reference** in brackets; text
(`cable`, `verdict`) is shown as it is. Frequencies are written with their unit; a change that is only rounding noise is not
shown.

## Tables

For runs with many points (an efficiency measurement): any numeric column against another, one line per run, and per
value of a third column if you want one (efficiency against `vin`, a line for each `iout`, for the old and the new
version of a converter).

## Golden sample

The **reference** run (★) is a unit known to be good, and every other ticked run is checked against it: a tolerance on one curve (on
both sides of it, or only above or only below), the part of the golden curve the run must cover, and a tolerance for any figure of the
summary. **Check** gives `PASS` or `FAIL` for each run with the reasons. The reference can be kept in the `golden/` folder of the project,
and a golden sample kept there opened as the reference. See [`golden.md`](golden.md).

## Not done yet

A report that includes the comparison (see *Future features* in the README). Checking a run against a **golden sample** with a
verdict is done, but not from this window yet: see [`golden.md`](golden.md). The loss of a cable against the date is in
[`trend.md`](trend.md).
