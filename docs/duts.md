# Devices under test (DUT): the archive

A **DUT** is what is tested in a measurement: an antenna, a filter, a converter, anything else. It is **not** part
of the set-up of the measurement, so it is kept apart from the **components** (cables, low-noise amplifiers,
attenuators and adapters, see [`assets.md`](assets.md)), which sit in the signal path, have an effect on the
measurement and can be used for a correction or de-embedding. A DUT is **optional**: a measurement can be made without
naming one, and then nothing is remembered about it.

The design and the stages are in [`PLAN.md`](../PLAN.md#12-devices-under-test-dut-archive). This page describes what is
built. The logic is in [`ola/duts.py`](../ola/duts.py) (no Qt). **There is no window yet** and the measurements do not name
a DUT from the archive yet: the next stage (the efficiency file takes a name typed by hand until then).

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

## Moving the antennas and filters from the components

Until now antennas, filters and the generic `DUT` cards were in the registry of components. `archive.migrate_from(components)`
moves them (kinds `antenna`, `filter`, `other`):

* the card keeps its data and its `uid`, so the runs it was measured in still find it;
* it gets the next `DUT` code, and the code it had goes to `former_codes`: **a label already stuck on the antenna
  (`ANT-0003`) still finds the card**. A card that already has a `DUT` code keeps it, unless the archive has that code for
  another device;
* the archive is written first and the components after, so a stop in the middle loses nothing, and doing it again moves
  only what is left. The registry of components keeps its `.bak`.

Nothing calls it yet: the window of the archive will, the first time it is opened.
