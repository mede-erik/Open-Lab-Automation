# Instrument identity, saved measurements and compatibility (proposal)

Status: the proposal has been largely implemented (`ola/identity.py`, `ola/compat.py`, `ola/role_mapping.py`,
`ola/project_rename.py`, `ola/vna_calibration_flow.py`; see the README). This file is kept as the design record:
the decisions taken in the discussion with the project owner are marked **Decided**.

## Goal

A project must be portable **between people**: the owner sends the project file to a friend who
runs the same measurements with *their own* instruments. At the same time every measurement that
was already made must stay linked to the apparatus that made it, and a calibration must never be
used with an instrument it was not made for.

Today a measurement names an instrument by its `instance_name`, and a run file keeps only that
name (`bindings`). A name is a label that can be changed or reused; it says nothing about which
apparatus was used, with which calibration.

## Model

| What | Refers to | Changes when the name changes or the project is passed on? |
|---|---|---|
| Measurement to do (measurement file) | a **role** (`vna`, `psu`...) and what it needs | no |
| Who fills a role (`.inst`) | an instrument of the project, by name | yes: it is what the friend replaces |
| Calibration (`.cal.json`) | **one apparatus**, by its serial number | no: with another serial it is not used |
| Measurement already made (run file) | a **snapshot** of the apparatus used | never: it is history |

### Serial number

**Decided.** The serial number is **always read from the instrument** (the 4th field of `*IDN?`,
or what a driver reads from the device), never typed by hand. If an instrument cannot give one,
the run says "not available". **Manual instruments have no serial** (they can be anything) and
nothing is asked for them.

The key `serial` of an `.inst` entry already means the RS-232 settings; the identity is *not*
stored in the `.inst`, it is read at connection and kept in the handle (`handle.identity`).

### Snapshot in the run file

The header of a run gets, next to `bindings`:

```json
"instruments": {
  "vna": [{
    "name": "VNA",
    "model_id": "VNA_Zenko_LiteVNA62",
    "serial_number": "1234567",
    "calibration": {"file": "calibrations/VNA_20261106.cal.json", "kind": "ONE_PORT",
                    "date": "2026-11-06T12:00:00", "sweep": {"start": 5e4, "stop": 6e9, "points": 201}}
  }]
}
```

Manual instruments appear with their name and type only. Runs written before this change have no
snapshot and are shown as they are. The snapshot is never rewritten, not by a rename, not when the
project is opened on another computer.

### Calibration per apparatus

A calibration record gets `serial_number`. When a VNA is connected, the calibrations of the project
for **that serial** are the only candidates: a software calibration is restored automatically if
the sweep is the same; otherwise the user is asked to calibrate. A calibration made for another
serial (the owner's, in a project received from the owner) is kept in the folder and shown in the
list, but never applied.

## Compatibility when another instrument fills a role

Separate **what the instrument can do** (characteristics, from the library) from **what the
measurement needs** (application). A multimeter that reads 100 V at most is fine for a measurement
of 40 V even if the previous one read 200 V.

### The need is learned, modules declare nothing

**Decided.** A measurement module does not declare requirements (that would add complexity to every
module). The need of a role is learned from the use:

- **Before the first run** the need is the characteristic of the instrument that was defined for the
  role: a multimeter of 200 V gives a need of 200 V. Any instrument with less than that is reported
  as lower than the previous one.
- **After a run** the need becomes **the largest value read by the instrument during the run, plus
  20 %** (the margin is one constant, `NEED_MARGIN = 1.2`). The need is the largest over the runs of
  the measurement, so it never shrinks. The 200 V multimeter that only read 33 V gives a need of
  39.6 V, and a 100 V multimeter is accepted without a word.
- A new measurement has no runs, so it starts from the first rule.

What is read is recorded by the instrument handle itself (no help from the modules): for every
numeric result of a query call it keeps the largest absolute value per logical call
(`read_voltage`, `read_current`, `read_power`, readings of a datalogger or multimeter, the voltages
of an oscilloscope waveform...). At the end of the run this goes into the `end` record of the run
file (`"observed"`), and each logical call is tied to one characteristic (`read_voltage` ->
maximum voltage, `read_current` -> maximum current, `read_power` -> maximum power...).

### Two levels of answer

1. **Blocking** (the measurement cannot be made): the sweep of a VNA outside the frequency range of
   the model, fewer ports than needed, an S-parameter the model cannot measure, more points than
   it allows. The pop-up says *"Adjust the sweep to stay inside the frequency range of the
   instrument"* and shows both ranges: the previous instrument's and the new one's. The run does
   not start until the sweep is changed.
2. **Warning** (a pop-up, the user decides *Continue* / *Cancel*): a characteristic of the new
   instrument is lower than the **need** of the role. The pop-up shows the three values: the limit
   of the new instrument, that of the previous one and the need. *"The maximum voltage the
   multimeter can read (100 V) is lower than that of the previous instrument (200 V); the
   measurements made so far needed up to 39.6 V."* When the new instrument is not lower than the
   need, nothing is shown.

**Decided:** this applies to **all** categories. When the user continues, the accepted differences
are written in the run header (`"accepted_differences": [...]`).

### Characteristics compared, by category (from the library `capabilities`)

| Category | Compared |
|---|---|
| Power supply | max voltage, max current, max power, number of channels |
| Electronic load | max voltage, current, power, operating modes |
| Oscilloscope | bandwidth, sample rate, memory depth, number of channels, vertical resolution |
| VNA | frequency range, ports, measurable S-parameters, max points, calibration kinds (**blocking**: range, ports, S-parameters, points) |
| Multimeter | functions, voltage / current / resistance ranges, integration time |
| Datalogger | number of channels, modules |
| Switch unit | slots, modules |

A manual instrument has its own limits in the `.inst` (`max_voltage`, `max_current`,
`max_power`), which are compared in the same way.

## Renaming an instrument

Renaming updates the measurement files of the project that name it, after a preview ("N
measurements will be updated"); run files are not touched (they have their snapshot).

## Opening a project from someone else

Roles without a usable instrument are listed when the project is opened or a measurement is
started; for each the application proposes the user's instruments of the right category, runs the
compatibility check above, and remembers the choice in the user's own `.inst`. Calibrations of
another apparatus are not applied (see above).

## Steps (one pull request each)

1. **Identity and snapshot:** read the serial at connection, `handle.identity`, the snapshot in the
   run header, `serial_number` in the calibration record. No change of behaviour.
2. **Rename with update of the measurements**, with preview.
3. **Observed values and need:** the handle records the largest value read per call, the `end` record
   of the run keeps it, and the need of a role is computed (largest over the runs + 20 %).
4. **Compatibility at start, power supplies, loads, oscilloscopes, multimeters, dataloggers**
   (everything the efficiency measurement and the other multi-instrument measurements use):
   warning pop-up (five languages), `accepted_differences` in the run.
5. **Compatibility at start, VNA:** blocking on the sweep, with both frequency ranges shown;
   `sparameters`.
6. **Calibration per serial:** automatic restore of a software calibration when serial and sweep
   match.
7. **Roles of a received project:** the choice of the instruments of the user.

Points 1, 3 and 4 touch `ola/runs.py`, `ola/runner.py`, `ola/instrument_handle.py` and
`ola/project_session.py`, which are shared with the measurement work.
