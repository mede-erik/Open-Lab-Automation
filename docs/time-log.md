# Time log (`.tlg`)

Reads one or more values from the instruments at a fixed interval and records them against time: the temperatures of a heat run,
the output voltage of a supply over a night, the current of a battery. It is the module for anything that has no sweep, only a
value that changes.

## How it works

For every sample the module asks each **channel** for one value, with a logical call of the library, and writes one row:
`t_s` (the time at which the reading of the sample **started**, from the start of the run) and one column for each channel.

The samples are scheduled **from the start**, not from the end of the previous one: a slow reading shortens the next wait, it does
not move all the following samples later, so the log does not drift. If the readings take longer than the interval the samples
follow one another without waiting.

The log ends after `samples` samples, or when the next sample would fall after `duration_s`. If a reading fails the log **stops
with an error** and what was recorded is kept.

## The file

```json temperatures.tlg
{
  "interval_s": 1.0,
  "duration_s": 3600,
  "channels": [
    {"name": "vout", "instrument": "dmm1", "call": "read_voltage"},
    {"name": "temp1", "instrument": "daq", "call": "measure_temperature", "args": {"channels": "101"}}
  ]
}
```

| Field | Meaning |
|---|---|
| `interval_s` | the time between two samples, at least 0.001 s |
| `duration_s` | stop after this time, above 0 |
| `samples` | or stop after this many samples, at least 1. **One of the two is needed**, otherwise the log would never end; with both, the first limit reached ends it |
| `channels` | a non-empty list; each channel has a `name` (unique, it becomes the column), the `instrument` (the name of one of the instruments chosen for the run) and the `call` (a logical call of the library that gives a value, [`instrument-calls.md`](instrument-calls.md)); `args` (an object) is optional |

The `instrument` of a channel must be one of the instruments chosen in the editor: if it is not, the run does not start and says
which ones are bound.

## How to use it

1. Choose the instruments in the editor (they are the role `instruments`, any category, as many as you need) and give each channel
   the **name** of the instrument it reads.
2. Choose an interval that the instrument can follow: a datalogger reading many channels, or a DMM at a slow rate, can take
   seconds for one sample.
3. Watch the progress: with `duration_s` the total is worked out as `duration / interval + 1` samples.
4. Stop it at any moment with the stop button; the samples already read stay in the run.

The window of the connections ([`wiring.md`](wiring.md)) shows the instruments before the run.

## Not done yet

Reading several channels of the same instrument is one call for each channel, not one call for all (a datalogger scan reads them
one by one). A limit or an alarm on a value, and a log that continues across a stop, are not there.
