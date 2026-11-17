# Time log (`.tlg`)

Reads one or more values from the instruments at a fixed interval and records them against time: the temperatures of a heat run,
the output voltage of a supply over a night, the current of a battery. It is the module for anything that has no sweep, only a
value that changes.

## How it works

The log has one or more **sources**, one for each instrument. Each source reads its instrument at its own **interval**: a
multimeter every hour, a datalogger every ten minutes, the internal readings of a supply every five minutes. For every sample a
source asks its instrument for each of its **readings** (a logical call of the library, with optional arguments) and writes one
row in its own **table**, named after the source, with `t_s` (the time at which the reading of the sample **started**, from the
start of the run) and one column for each reading.

The samples are scheduled **from the start**, not from the end of the previous one: a slow reading shortens the next wait, it does
not move the following samples later, so the log does not drift. If a reading takes longer than the interval of its source, the
samples that fell due in the meantime are **skipped** and a warning is written to the log.

Each source ends after its `samples`, or when its next sample would fall after the common `duration_s`. Without `duration_s` every
source needs `samples`, otherwise the log would never end. If a reading fails the log **stops with an error** and what was recorded
is kept.

## The file

```json temperatures.tlg
{
  "duration_s": 86400,
  "sources": [
    {"name": "dmm", "instrument": "dmm1", "interval_s": 3600,
     "readings": [{"name": "vout", "call": "read_voltage"}]},
    {"name": "daq", "instrument": "daq", "interval_s": 600, "samples": 500,
     "readings": [{"name": "temp1", "call": "measure_temperature", "args": {"channels": "101"}}]},
    {"name": "psu", "instrument": "psu1", "interval_s": 300,
     "readings": [{"name": "v", "call": "read_voltage", "channel": 1}, {"name": "i", "call": "read_current", "channel": 1}]}
  ]
}
```

| Field | Meaning |
|---|---|
| `duration_s` | the whole log: no sample is taken after it. Optional, above 0 |
| `sources` | a non-empty list, one entry per instrument |
| `name` | the name of the source: it is also the name of its table in the results. Unique, not `points` nor `t_s` |
| `instrument` | the name of one of the instruments chosen for the run |
| `interval_s` | the time between two samples of this source, at least 0.001 s |
| `samples` | how many samples the source takes, at least 1. Optional when `duration_s` is given |
| `readings` | a non-empty list. Each reading has a `name` (unique in the source, it becomes the column; `t_s` is reserved), a `call` (a logical call of the library that gives a value, [`instrument-calls.md`](instrument-calls.md)), an optional `channel` (integer, see below) and optional `args` (an object) |

### The readings an instrument has inside

Any instrument of the project can be read: the voltage, current and power of a supply or of an electronic load, the value of a
multimeter, and so on. The editor offers, for the instrument of a source, **its readings** (`read_...` and `measure_...` calls that
give a number, with their unit), not every command of the model: the status and calibration queries are left out.

A reading can name a **`channel`**. A supply with several outputs takes it as the `channel_number` of the call; a **multichannel
load** has the channel selected first (`select_channel`); an instrument that has no channels refuses a reading that names one, and
the run does not start. A load with one input and a multimeter have no channel. The editor fills in channel 1 when the call takes one.

A datalogger is better read with the scan below: one call reads all its channels. Reading it channel by channel with
`measure_...` calls is possible but needs the arguments of the call (`channels`, `range`...) in `args`.

The `instrument` of a source must be one of the instruments chosen in the editor: if it is not, the run does not start and says which
ones are bound.

### A datalogger read with one scan

A datalogger can be read **all its channels together**: a source with `"scan": true` has `channels` instead of `readings`. The
channels are the ones of the instrument file (`channel_id`, `meas_type`, optional `range`, `resolution`, `probe_type`,
`sensor_type`, `attenuation`); a channel with an `attenuation` has its value divided by it, as in the remote control tab. The datalogger is configured once at the start of the run, and every sample is one scan whose values go to the
channels in channel-number order. The same channel checks as the remote control tab apply, so a channel the datalogger cannot
configure is refused before the run starts.

```json datalogger.tlg
{
  "sources": [
    {"name": "daq", "instrument": "daq", "interval_s": 600, "samples": 500, "scan": true,
     "channels": [
       {"name": "temp1", "channel_id": "101", "meas_type": "TEMP", "probe_type": "TCouple", "sensor_type": "K"},
       {"name": "vout", "channel_id": "103", "meas_type": "VOLT:DC", "range": "10"}]}
  ]
}
```

### The editor

The time log has its own editor, opened by the Measurements tab. It lists the sources, one for each instrument of the file, and for
the selected one it shows the name, the instrument, the interval, the samples and either the readings (the calls offered are those
of the instrument's model in the library) or, for a datalogger scan, the **channels defined for it in the instrument file**: they are listed with a tick box (all ticked at
first, with *All* and *None* buttons) and only the ticked ones are logged. Their settings (range, probe, sensor, attenuation...) are
copied from the instrument file when the log is saved, so open and save the editor again after changing them. A channel that the file no
longer has stays in the list, marked, until it is unticked. The duration is at the top. **Save** asks the
time-log module whether the file is valid, and shows the problems instead of saving if it is not.

### The earlier format

A file with `channels` and a single `interval_s` is still read, as before: all the channels are sampled together at that interval
and written to the main table of the results (`points`). Each channel names its own `instrument`. It cannot be mixed with `sources`
in the same file.

```json old-temperatures.tlg
{
  "interval_s": 1.0,
  "duration_s": 3600,
  "channels": [
    {"name": "vout", "instrument": "dmm1", "call": "read_voltage"},
    {"name": "temp1", "instrument": "daq", "call": "measure_temperature", "args": {"channels": "101"}}
  ]
}
```

## How to use it

1. Choose the instruments in the editor (they are the role `instruments`, any category, as many as you need).
2. Give each source the instrument it reads and an interval that the instrument can follow: a datalogger reading many channels, or
   a DMM at a slow rate, can take seconds for one sample.
3. Watch the progress: the total is the sum of the `samples` of the sources; a source without `samples` counts the samples that fit in `duration_s` at its interval.
4. Stop it at any moment with the stop button; the samples already read stay in the run.

The window of the connections ([`wiring.md`](wiring.md)) lists the sources, in order, before the run.

## Not done yet

A limit or an alarm on a value, and a log that continues across a stop, are not there. The readings of a source are not
checked against the instrument's limits before the run.
