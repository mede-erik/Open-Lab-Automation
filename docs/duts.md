# Devices under test (DUT): the archive

A **DUT** is what is tested in a measurement: an antenna, a filter, a converter, anything else. It is **not** part
of the set-up of the measurement, so it is kept apart from the **components** (cables, low-noise amplifiers,
attenuators and adapters, see [`assets.md`](assets.md)), which sit in the signal path, have an effect on the
measurement and can be used for a correction or de-embedding. A DUT is **optional**: a measurement can be made without
naming one, and then nothing is remembered about it.

The design and the stages are in [`PLAN.md`](../PLAN.md#12-devices-under-test-dut-archive). This page describes what is
built. The logic is in [`ola/duts.py`](../ola/duts.py) (no Qt); the windows are `DutsDialog`, `DutEditDialog` and
`DutVersionsDialog` in `frontend/ui/`. The measurements name their DUT from the archive ([below](#in-a-measurement)); the
efficiency file takes a DUT, a version and a [variant](#the-variant-of-a-run) too.

## The window

*Tools* > **DUT...** (or `python -m frontend.ui.DutsDialog`). The list shows the code, the category, the name, the
version in use now, what it is, the date and whether the DUT is active or retired; it can be filtered by category and a
retired DUT can be hidden.

* **New... / Edit...**: the card. A new DUT asks for the category first (it suggests the details) and, if wanted, its first
  version.
* **Versions...**: the versions of the selected DUT: add one (free text and an optional note), retire one or bring it back.
* **Retire / Delete**: a retired DUT stays in the list, greyed, and in its old results; deleting asks first and the code is
  not given again.
* **History...**: the measurements made on the selected DUT, found by its code (and by the codes it had before), with
  *Compare* ([`compare.md`](compare.md)). The *Measurements* column counts them in the runs folder of the open project.
* **Label...**: the labels of the selected DUTs, with the window of the components ([`assets.md`](assets.md)): the code, a QR
  code, the name, the version, the key figures of its category (an antenna: frequency range and gain; a filter: type and
  frequency; a converter: topology, input to output voltage and power) and the latest measurement.
* **Scan or type a code**: a USB barcode scanner types `OLA:DUT-0001` in the box and the DUT is selected. The code a card had
  before the move from the components (`ANT-0003`) finds it too.

## The card

* **Code**: `DUT-0001`, one sequence for every category, never used again, not even after a deletion.
* **Name**: chosen by the user to recognise it (`Pippo`); **category**: `antenna`, `filter`, `converter` or `generic`; a
  description, manufacturer, serial number, owner, notes and *details* that depend on the category (an antenna: frequency
  range, connector, gain; a filter: type, frequency, connectors; a converter: topology, input and output voltage,
  maximum power).
* **Versions**: any number, in the order they were made. A version is **free text** (`rev A`, `RFB`, `V01`), written
  the way it is used in the lab. The same text twice is refused (a capital or a space around it does not make another one).
  A version can be **retired**: it stays, so that its old results still make sense, and it is no longer the current one.
* **Identity (`uid`)**: as for the components, a random identifier that never changes, so a run keeps finding the DUT
  whatever its code.

The card is the card of a component with a list of versions, so the labels of the components
([`labels`](../ola/labels.py), QR `OLA:DUT-0001`) print a DUT without a layout of their own. The lines a DUT label shows by
default are still to be defined.

## The file

One JSON file for **all projects**: `~/.open_lab_automation/duts.json`, or the file named by the environment variable
`OLA_DUTS_FILE`. It is written like the registry of components: atomically, the previous version kept as `duts.json.bak`,
keys it does not know kept, a damaged file reported and not overwritten.

```python
from ola.duts import DutRegistry

archive = DutRegistry()
dut = archive.create("converter", "Pippo", version="rev A")      # DUT-0001
archive.add_version(dut.id, "rev B", "new inductor")
archive.current_version(dut.id)                                  # "rev B"
archive.find("OLA:dut-1")                                        # a QR or a scanner gives the code
```

## In a measurement

The measurements whose subject is a device under test (`return_loss`, `antenna`, `filter`, `bode`, `regulation`, `ripple`
and `resistive_efficiency`) take, in `device` (in `filter` for the filter measurement):

| Key | What |
|---|---|
| `dut_id` | the code of a DUT of the archive (`DUT-0001`); optional: a measurement can be made without naming one |
| `version` | the version of that DUT, free text; optional |
| `label` | the name written in the results; filled from the card when it is empty |

In the editor of each of them there are two fields: **Device under test (DUT archive)**, with the cards (the antenna form
only offers antennas, the filter form only filters), and **Version of the DUT**, which lists the versions that are not retired
and puts the one in use now when a DUT is chosen. The version can be typed too: a name the DUT does not have is a warning, not an
error. `amplifier`, `tdr`, `cable` and `attenuator` do not name a DUT: what they characterise is a component, so their
`device` stays a code of the registry of components (`asset_id`).

The header of every run keeps the **card of that day** with its versions (`"duts": {"DUT-0001": {...}}`), as it does for the
components, so a result says which device it was made on and in which version, whatever happens to the card later; the
comparison tool names the run after it. A file made before the archive names its device with an `asset_id`: it works as it
did, and the editor offers it again as a `dut_id` once the card has moved (below).

## The variant of a run

The same DUT, in the same version, is often measured more than once with a small change in between: a part changed in the
bill of materials (`R100 = 100 ohm`), a fan switched on or off. That is a **variant** of the run, not a new version of the DUT.
It is a few named values, written in the editor one `name = value` per line (the field *Variant of this run*, under the
version) and stored in the file as `device.variant` (`filter.variant` for the filter):

```json
{"device": {"dut_id": "DUT-0001", "version": "rev A", "variant": {"R100": "100 ohm", "fan": "on"}}}
```

* It is **optional**, and free: the names and the values are text (a number is kept as text too). A line that is not
  `name = value`, with no name or no value, or a name twice, marks the field and writes nothing wrong.
* The header of a run keeps the parameters of the file, so **the variant stays with its results**. The comparison tool shows
  it in the label of the run (`DUT-0001 Pippo [R100=100 ohm, fan=on] - 2026-11-03`), and the history of a DUT has a
  *Variant* column when any of its runs has one.
* In the editors the variant is a **table** (name, value) with *Add row* and *Remove*, and a list of the names used before.
* **At every start** of an efficiency (`.eff`, `.rfe`), regulation or ripple measurement that names a DUT, the program asks
  *what is different since the last run*: a table with the variant of the **last run of that DUT** already filled in (the
  file's variant if there is none), the names of the earlier runs to choose from, and *Start* / *Cancel*. The answer is the
  variant of **that run only**: it goes in the header of the run, and the measurement file is not changed. A run without a
  person (unattended) does not ask. The other measurements keep the variant of their file.
* You can also change it by editing the measurement file, or keep one measurement per variant in the project.
* The comparison does not group by variant yet.

## The efficiency file

The efficiency measurement has no form: its editor has the same fields in the box under the name of the parameters. In the
file, `device` takes, all optional: `name` (written by hand), `dut_id` (a code of the archive), `version` and `variant`:

```json
{"device": {"name": "Pippo", "dut_id": "DUT-0001", "version": "rev A", "variant": {"fan": "off"}}}
```

Choosing a DUT in the editor fills the name and the version in use if they are empty; a name or a version already typed is
kept. The header of the run keeps the card of that day, as for the other measurements.

## Moving the antennas and filters from the components

Antennas, filters and the generic `DUT` cards used to be in the registry of components. At the start of the program
`archive.migrate_from(components)` moves them (kinds `antenna`, `filter`, `other`), and a message says how many moved:

* the card keeps its data and its `uid`, so the runs it was measured in still find it;
* it gets the next `DUT` code, and the code it had goes to `former_codes`: **a label already stuck on the antenna
  (`ANT-0003`) still finds the card**. A card that already has a `DUT` code keeps it, unless the archive has that code for
  another device;
* the archive is written first and the components after, so a stop in the middle loses nothing, and doing it again moves
  only what is left. The registry of components keeps its `.bak`. The registry of components has no antenna, filter or
  generic kind any more.
