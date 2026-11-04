# Cables and devices: codes, cards and labels

Every physical object that is measured (a cable, an antenna, a filter, an amplifier, an adapter...) can have a **code**
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

* **Code**: a prefix for the kind and a number: `CBL` cable, `ANT` antenna, `FLT` filter, `AMP` amplifier, `ADP` adapter,
  `DUT` any other device. Numbers count up per kind and are **never used again**, not even after a deletion or a restart.
  If two people work on separate copies of the file the numbers can clash: share one file.
* **Card**: name (required), what it is, manufacturer, serial number, owner, notes, the date it was created, and
  *details* that depend on the kind (a cable: type, connectors, length; an antenna: frequency range, connector, gain; a
  filter: type, frequency, connectors; an amplifier: nominal gain, supply). A detail that is a measure is stored as a
  number (`1.5 m`, `868M` become `1.5` and `868000000`), anything else as text; *Other details* takes `name = value` lines.
* **Retire** a cable that is no longer used: it stays in the list (greyed) and in its old results, and is not offered for
  new measurements. **Delete** only a card made by mistake: the results that name it keep the code but lose the card
  (the window warns, with the number of measurements).
* The file is written atomically and the previous version is kept as `assets.json.bak`; a damaged file is reported and
  **never overwritten**, so it can be repaired by hand. Keys the program does not know are kept.
* **Scan or type a code** in the box at the top: a USB barcode scanner types the code (`OLA:CBL-0042`) like a keyboard, in
  any case and with or without `OLA:`, and the card is selected. A code that is not in the registry says so.

## In the measurements

The editors of the cable, return-loss, antenna, amplifier and filter measurements have a field **"... from the registry"**:
pick the code, type it or scan the label. The name field is filled from the card if it is empty (a name you typed is kept).
A code that is not in the registry is a warning, not an error; something that is not a code marks the field.

When a run starts, **the card as it is that day** is saved in the header of the run next to the code (`assets`). If the
cable is renamed or its length corrected later, the old runs still say what it was. The **Measurements** column of the
registry counts the runs found by code in the runs folder of the open project; **History...** lists them (date,
measurement, result) and **Compare...** puts their curves together in the [comparison tool](compare.md).

## Labels

**Label...** on one or more selected cards opens the label window. A label has:

* the **code**, big and bold, always;
* a **QR code** holding `OLA:CBL-0042`. It is a normal QR code (not a *Micro* QR code, which many readers do not read);
  its modules must print at least 0.3 mm: a QR code too small for the label is flagged and can be left out;
* up to nine more lines: name, what it is, connectors, length, date, **latest measurement** (for example
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

## Not done yet

Editable label templates (they will share the template system of the HTML report planned for the beta), reading a QR code
with a camera (a USB scanner works), a trend of a cable's loss over time in the history, and tying other results (an
efficiency run) to the converter under test.
