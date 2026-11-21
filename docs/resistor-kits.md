# Kits of resistors

The power resistors of a bench are the same from one measurement to the next, so they are kept **once**, in a **kit**, like a cable in the
registry ([`assets.md`](assets.md)): a name, the value, the tolerance and the power rating of each resistor, and the relay of the
multiplexer that connects it if it is always wired to the same one. A measurement then says *"the resistor R22 of the kit PWR"* instead of
writing the values again.

The logic is in [`ola/resistor_kits.py`](../ola/resistor_kits.py) (no Qt); the window is `frontend/ui/ResistorKitsDialog.py`.
Today the [efficiency with a resistive load](resistive-efficiency.md) uses them: its editor picks resistors from a kit and
can save the resistors typed in as a new kit (an existing kit is never changed).

## The window (*Tools* > *Resistor kits...*)

* The list of kits on the left, with **New kit**, **Rename** and **Delete** (after a question).
* The resistors of the selected kit in a table you edit: **name**, **resistance** (in ohms; a value can be typed with a prefix, `4.7k`,
  `2.2M`), **tolerance** (percent), **power** (watts), **relay** (the channel of the multiplexer) and a **note**. *Add resistor* adds a row
  with a free name, *Remove resistor* takes out the selected one.
* **Save** writes the file. A value that is not a number, or that cannot be used (a resistance of 0, a tolerance of 100 %, two resistors
  with the same name), is said and **nothing is written**; the table cannot be left while it has an error.
* **Copy the reference** puts `{"kit": "PWR", "ref": "R22"}` for the selected resistor on the clipboard, to paste into the `loads` of a
  measurement.

## Using a kit in a measurement

```json loads.json
{
  "resistor_kit": "PWR",
  "loads": [
    {"name": "10R", "ref": "R10"},
    {"name": "22||47", "parallel": [{"ref": "R22"}, {"ref": "R47"}]},
    {"name": "10+(22||47)", "series": [{"kit": "PWR", "ref": "R10"},
                                       {"parallel": [{"ref": "R22"}, {"ref": "R47", "channel": "305"}]}]}
  ]
}
```

* `{"kit": "PWR", "ref": "R22"}` names the kit; with `resistor_kit` in the measurement `{"ref": "R22"}` is enough. A resistor that names its
  own kit uses it.
* What the entry says besides `kit` and `ref` **wins over the kit**: `"channel": "305"` above connects R47 to another relay for this
  measurement only, without touching the kit. The name of a load is its own; a load that is only a reference is called as the resistor.
* The project looks the resistors up **when the measurement starts** and writes their values (and `kit` / `ref`, to know where they
  came from) into the **header of the run**: the values that were used stay with the results whatever happens to the kit later. An unknown
  kit or resistor stops the run before anything is switched on and says what there is (*"the kit 'PWR' has no resistor 'R99' (it has: R10,
  R22, R47)"*).
* The editor of the measurement cannot check values it does not have: it accepts the references, says so in a warning on `loads`, and the
  rating and relay checks are done when the measurement starts (with the values from the kit).

## The file

`~/.open_lab_automation/resistor_kits.json` (or the file in `$OLA_RESISTOR_KITS_FILE`), the same folder as the registry of cables. It is
written whole, to a temporary file first, and the previous version is kept as `resistor_kits.json.bak`:

```json resistor_kits.json
{
  "format_version": 1,
  "kits": {
    "PWR": {
      "note": "the power resistors of the bench",
      "resistors": [
        {"name": "R10", "r_ohm": 10, "tol_pct": 1, "power_w": 50, "channel": "201"},
        {"name": "R22", "r_ohm": 22, "tol_pct": 1, "power_w": 50, "channel": "202", "note": "blue one"},
        {"name": "R47", "r_ohm": 47, "tol_pct": 5, "power_w": 25, "channel": "203"}
      ]
    }
  }
}
```

A file that cannot be read is refused with its path and the reason; the program keeps working without the kits.

## Not done yet

A kit is a list of **nominal** values. The resistors do not have a code of their own, are not measured and do not have a history, as the cables
do ([`assets.md`](assets.md)); power resistors drift with the currents they carry, so this needs a measurement of each resistor from time to
time, and it is left for later. The kits are in the user's file, not in the project: a project that moves to another computer needs the
file too (the values used in a run are in its header, so the results are never lost).
