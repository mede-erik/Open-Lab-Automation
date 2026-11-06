# Instrument identity, saved measurements and compatibility (proposal)

Status: proposal, decisions taken in the discussion with the project owner are marked **Decided**.
Nothing here is implemented yet.

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

Two levels of answer:

1. **Blocking** (the measurement cannot be made): only where the physics is clear. For a VNA: the
   sweep outside the frequency range of the model, fewer ports than needed, a required
   S-parameter that the model cannot measure, more points than it allows. The run does not start.
2. **Warning** (a pop-up, the user decides *Continue* / *Cancel*): a characteristic of the new
   instrument is **lower than that of the previous one** (the one in the last run snapshot of
   that measurement) and the measurement does not state a need that shows it fits. The pop-up shows
   both values: *"The maximum voltage the multimeter can read (100 V) is lower than that of the
   previous instrument (200 V)."* When the measurement states its need and it fits (40 V), nothing is
   shown. When the measurement states a need that does *not* fit, the pop-up says so and shows
   need and limit.

**Decided:** this applies to **all** categories. When the user continues, the accepted differences
are written in the run header (`"accepted_differences": [...]`), so it stays traceable.

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

### What the measurement needs

A measurement module may declare `requirements(params)`: a dict such as `{"voltage_max": 40.0,
"frequency": [5e4, 1e9], "ports": 2}` computed from its parameters (an efficiency sweep knows its
largest voltage, an S-parameters measurement its sweep). A module that declares nothing is compared
with the previous instrument only. `requirements` is optional and does not change existing modules.

## Renaming an instrument

Renaming updates the measurement files of the project that name it, after a preview ("N
measurements will be updated"); run files are not touched (they have their snapshot).

## Opening a project from someone else

Roles without a usable instrument are listed when the project is opened or a measurement is
started; for each the application proposes the user's instruments of the right category, runs the
compatibility check above, and remembers the choice in the user's own `.inst`. Calibrations of
another apparatus are not applied (see above).

## Steps (one pull request each)

1. **Identity and snapshot:** read the serial at connection, `handle.identity`, the snapshot in the run
   header, `serial_number` in the calibration record. No change of behaviour.
2. **Rename with update of the measurements**, with preview.
3. **Compatibility at start:** characteristics per category, warning pop-up (five languages),
   blocking for the VNA, `accepted_differences` in the run.
4. **Calibration per serial:** automatic restore of a software calibration when serial and sweep
   match.
5. **Roles of a received project:** the choice of the instruments of the user.

Points 1 and 3 touch `ola/runs.py`, `ola/project_session.py` and the measurement modules, which are
shared with the measurement work: they are agreed with it before they are written.

## Open questions

- Where does the "previous instrument" come from when a measurement has never been run: from the
  last run of the project with the same role, or none (then only the stated needs are checked)?
- Should a VNA sweep outside the range be blocking also when the user could still want a partial
  sweep? Proposed: blocking, the user can change the sweep.
- Which modules declare `requirements` first: `sparameters` (frequency, ports) and the efficiency
  measurement (voltage, current, power).
