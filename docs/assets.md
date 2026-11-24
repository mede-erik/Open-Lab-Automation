# Cables and devices: codes, cards and labels

Every **component** of a measurement (a cable, an amplifier, an attenuator, an adapter), the things that sit in the signal path, have an
effect on the result and can be used for a correction or de-embedding, can have a **code**
(`CBL-0042`) and a **card** that says what it is. The code is printed on a **label** stuck on the object, with a QR
code, and is saved in every measurement made on it, so a result always says **which** cable it was made on, and a
cable has a history. Open it from **Tools > Cables and devices**; from the command line:
`python -m frontend.ui.AssetsDialog [runs folder ...]`.

The logic is in [`ola/assets.py`](../ola/assets.py) (the registry), [`ola/labels.py`](../ola/labels.py) (layout, QR code,
SVG) and `frontend/ui/label_paint.py` (PDF and images); the windows are `AssetsDialog`, `AssetEditDialog` and
`LabelDialog` in `frontend/ui/`. All of it is tested without a screen, including every module of the QR code in a
rendered label.

## The registry

One JSON file for **all projects** (a cable is used in many): `~/.open_lab_automation/assets.json`, or the file named by
the environment variable `OLA_ASSETS_FILE` (for example in a shared folder). It holds cards only, not results.

* **Code**: a prefix for the kind and a number: `CBL` cable, `AMP` amplifier, `ATT` attenuator, `ADP` adapter. Antennas, filters and any
  other device under test are **not** components: they are in the [DUT archive](duts.md) (`DUT-0001`). Numbers count up per kind and are **never used again**, not even after a deletion or a restart.
  If two people work on separate copies of the file the numbers can clash: share one file.
* **Identity (`uid`)**: every card also has a `uid`, a random identifier that never changes. The code is what you see and print, but it can change (two registries joined into a shared archive may force a new code, and the old one is kept in `former_codes`). A run saves the card of that day with its `uid`, so the history of a cable follows the `uid`, and two different cables that once had the same code are not mixed. Runs made before the `uid` existed are found by the code (and the former codes). Planned use: `docs/proposals/shared-archive.md`.
* **Card**: name (required), what it is, manufacturer, serial number, owner, notes, the date it was created, and
  *details* that depend on the kind (a cable: type, connectors, length; an amplifier: nominal gain, supply; an attenuator: nominal value, tolerance, maximum power and frequency, connectors). A detail that is a measure is stored as a
  number (`1.5 m`, `868M` become `1.5` and `868000000`), anything else as text; *Other details* takes `name = value` lines.
* **Retire** a cable that is no longer used: it stays in the list (greyed) and in its old results, and is not offered for
  new measurements. **Delete** only a card made by mistake: the results that name it keep the code but lose the card
  (the window warns, with the number of measurements).
* The file is written atomically and the previous version is kept as `assets.json.bak`; a damaged file is reported and
  **never overwritten**, so it can be repaired by hand. Keys the program does not know are kept.
* **Scan or type a code** in the box at the top: a USB barcode scanner types the code (`OLA:CBL-0042`) like a keyboard, in
  any case and with or without `OLA:`, and the card is selected. A code that is not in the registry says so.

## In the measurements

The editors of the cable, amplifier and [attenuator](attenuator.md) measurements, and the correction of the others (a cable or a pad taken out of the
result), have a field **"... from the registry"**. The device under test of the other measurements is a [DUT](duts.md):
pick the code, type it or scan the label. The name field is filled from the card if it is empty (a name you typed is kept).
A code that is not in the registry is a warning, not an error; something that is not a code marks the field.

When a run starts, **the card as it is that day** is saved in the header of the run next to the code (`assets`). If the
cable is renamed or its length corrected later, the old runs still say what it was. The **Measurements** column of the
registry counts the runs found by code in the runs folder of the open project; **History...** lists them (date,
measurement, result), **Compare...** puts their curves together in the [comparison tool](compare.md) and **Trend...** shows how a figure
of the measurements (the loss of a cable) changes with the date, with a verdict before the cable is out of use ([`trend.md`](trend.md)).

## Labels

**Label...** on one or more selected cards opens the label window. A label has:

* the **code**, big and bold, always;
* a **QR code** holding `OLA:CBL-0042`. It is a normal QR code (not a *Micro* QR code, which many readers do not read);
  its modules must print at least 0.3 mm: a QR code too small for the label is flagged and can be left out;
* up to ten more lines: name, what it is, the **key figures** (an attenuator `10 dB, 6 GHz, 2 W`, an amplifier `20 dB gain`), connectors, length, date, **latest measurement** (for example
  `0.6 dB @ 868MHz, 2026-11-03`, from the newest run of the object; it is only as current as that run, so print it again after a
  new measurement), owner, serial number, notes. Lines that do not fit are left out from the end (notes first) and
  listed under the preview, never hidden silently.

Formats: a **single label** (50 x 25, 40 x 20, 62 x 29 mm for a Brother QL tape, 70 x 37), a **flag** for a thin cable
(60 x 15 mm: the same text either side of a dashed fold line; wrap it round the cable and stick it to itself; no QR code on
a flag narrower than 8 mm, the code is written larger), or a **sheet of labels** for a normal printer (A4: 3 x 8, 3 x 7, 5 x 13,
2 x 7), with the number of places **already used** so a partly used sheet can be finished.

*Save PDF* writes every label at its **real size** (one page per label, or one A4 page per sheet); *Save image* (PNG, 300 dpi)
and *Save SVG* write the label on show. Print the PDF with the printer's own program at **100 %** (not "fit to page"). The
program does not drive printers itself.

The QR code needs the `segno` package (`pip install segno`, in `requirements.txt`); without it the window says so and
a label without the QR code still works.

## Your own label templates

**Templates...** in the label window opens the editor of your own formats, kept in one file shared by all projects
(`~/.open_lab_automation/label_templates.json`, or the file named by `OLA_LABEL_TEMPLATES`). A template has a **name**, a
**size** in mm (width 10-300, height 8-200), the layout (**single label** or **flag**), the margin, QR code and border on or
off, and the **lines**: one text per row with the data of the card between braces.

* The places are `{id}`, `{name}`, `{version}`, `{description}`, `{specs}`, `{connectors}`, `{length}`, `{date}`,
  `{last_measurement}`, `{owner}`, `{serial}` and `{notes}`; the menu under the box inserts one. `Rev {version}`, `S/N {serial}`
  and `{owner} - {date}` are lines. `{serial}` is the bare number (the built-in line adds `S/N`).
* A line whose places are **all empty** is not printed (a card without a version has no `Rev` line); one empty place among
  others leaves no gap. A name between braces that is not in the list is an error.
* A line must show the code `{id}`: that line is the big bold one. The QR code always holds `OLA:<code>` and its content cannot be
  edited, so a scan always gives the code back (at most 12 lines of 80 characters).
* Lines that do not fit are left out **from the end** and listed under the preview, as for the built-in formats.
* *New* copies the format selected in the label window (a built-in one or one of yours) as a starting point. A template that is
  not valid is not saved and the window says why; a damaged file is reported and never overwritten. The templates are listed in
  the format box (QR and border can still be changed there); the sheets keep the lines of the built-in format.

## Not done yet

Reading a QR code with a camera (a USB scanner that types the code works). The trend of a cable's loss is in [trend.md](trend.md); an efficiency run
names its converter under test as a name typed by hand (see [efficiency.md](efficiency.md)); the devices under
test have their own archive, not this registry ([duts.md](duts.md)).
