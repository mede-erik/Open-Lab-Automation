# The `vna` category: what the measurements ask of a network analyzer

The RF measurements ([cable](cable.md), [return loss](return-loss.md), [filter](filter.md), [antenna](antenna.md) and
[amplifier](amplifier.md)) never talk to a VNA directly. They ask for **logical calls**, the same for every brand, and the
instrument library translates them for the model, as it does for power supplies and oscilloscopes
([`instrument-calls.md`](instrument-calls.md)). This page is the contract of the `vna` category: what the
measurements call, and what they expect back. It is written for whoever adds the category to the library
(`Instruments_LIB/schema/vna.json` and the entries of the instruments, for example the LiteVNA67).

## What the program does *not* do

* **No calibration.** The user calibrates the VNA beforehand (at the ends of the test leads, or at the port) and the
  measurement only asks, once, whether it is done. So there are no calls for calibration standards.
* **No display, markers or math on the instrument.** The measurement reads the complex data and does the
  calculations itself ([`ola/rf.py`](../ola/rf.py)).

## The two mandatory calls

| Call | Kind | Arguments | Gives |
|---|---|---|---|
| `set_sweep` | set | `start_frequency` (Hz), `stop_frequency` (Hz), `points` (int), `sweep_type` (`linear` or `log`, in any case: the call planner converts it to the schema's `LINEAR` / `LOG` and applies the aliases `LIN` / `LOGARITHMIC`), optional `if_bandwidth` (Hz), optional `power` (dBm) | nothing |
| `read_sparameter` | query | `parameter` (`S11`, `S21`; `S12` and `S22` for a two-port instrument: the amplifier measurement needs them) | the S-parameter over the sweep (below) |

* `read_sparameter` must **return only when the sweep has finished**: the implementation starts one sweep (or waits
  for the running one to complete) and then transfers the data. The measurement does not poll.
* The sweep must have the **frequencies requested** (`start_frequency` to `stop_frequency`, `points` of them,
  linearly or logarithmically spaced). The answer carries the frequencies actually used, so an instrument that
  rounds them (or a USB analyzer that sweeps in fixed steps) is still read correctly.
* The optional arguments of `set_sweep` are only sent when the user gave them; an instrument that cannot set them
  should ignore them rather than fail (or say so in a clear error).
* A one-port instrument (only S11) supports `S11` and rejects the others with `CALL-001` (call not supported).
* The **amplifier** measurement ([`amplifier.md`](amplifier.md)) needs all four parameters, and calls `set_sweep` many times
  (a 3-point sweep with a different `power` for every step of its compression test) followed by `read_sparameter`;
  `set_sweep` with `power` should be quick, and must really change the source power before the next read.

### The answer of `read_sparameter`

```json
{"frequency": [1000000.0, 8000000.0, ...],
 "values": [[0.012, -0.994], [0.034, -0.971], ...]}
```

`frequency` in Hz and `values` as `[real, imaginary]` pairs of the S-parameter **as a ratio** (not dB), the same
length. (The measurements also accept a plain list of complex numbers, in which case the frequencies are taken from
the sweep that was set.) For an instrument that gives dB and degrees, convert to real and imaginary in the
library's parser; the measurements always work on the complex values.

## Other calls

| Call | Why |
|---|---|
| `identification_query` | **mandatory**, as in every category (the draft below has it): the string the instrument answers to `*IDN?`, or what it has |
| `set_remote` | for a serial instrument that must be put in remote mode |
| `query_sweep` | reads back what is set (the `readback` of `set_sweep`) |

## A draft of the schema file

In the format of [`Instruments_LIB/schema/README.md`](https://github.com/mede-erik/Instruments_LIB), for
`schema/vna.json` (category `vnas_series`):

```json
{
  "schema_version": 1,
  "category": "vnas_series",
  "description": "Vector network analyzers: sweep setup and S-parameter read-out",
  "types": {
    "sweep_type": {"kind": "enum", "values": ["LINEAR", "LOG"], "aliases": {"LIN": "LINEAR", "LOGARITHMIC": "LOG"}},
    "sparameter_name": {"kind": "enum", "values": ["S11", "S21", "S12", "S22"]},
    "sparameter": {"kind": "mapping",
                   "description": "dict with 'frequency' (Hz) and 'values' ([real, imaginary] pairs, ratio)"}
  },
  "calls": {
    "identification_query": {"requirement": "mandatory", "kind": "query",
                             "description": "identification string", "result": {"type": "string"}},
    "set_sweep": {
      "requirement": "mandatory", "kind": "set",
      "description": "frequency sweep: start, stop, number of points, spacing, optional IF bandwidth and power",
      "args": {
        "start_frequency": {"type": "float", "unit": "Hz", "min": 0},
        "stop_frequency": {"type": "float", "unit": "Hz", "min": 0},
        "points": {"type": "int", "min": 2},
        "sweep_type": {"type": "sweep_type", "required": false},
        "if_bandwidth": {"type": "float", "unit": "Hz", "min": 0, "required": false},
        "power": {"type": "float", "unit": "dBm", "required": false}
      }
    },
    "read_sparameter": {
      "requirement": "mandatory", "kind": "query",
      "description": "run one sweep and return the S-parameter over it",
      "args": {"parameter": {"type": "sparameter_name"}},
      "result": {"type": "sparameter"}
    }
  }
}
```

(The names of the types and the enum spelling follow what the other categories do; adjust them to the library's
conventions. What the measurements rely on are the **call names, the argument names and the shape of the answer**.)

## What each instrument needs in the library

* A **parser** for the answer. `read_sparameter` gives a mapping (`frequency`, `values`) built from what the
  instrument sends (several lines of text, or a binary block), so every entry links a named parser from
  [`ola/parsers.py`](../ola/parsers.py) with `"parse"`, as the oscilloscopes do for waveforms (`siglent_waveform`).
  It is written when the data of the real instrument are known (the LiteVNA67 is waiting for them).
* The **unit `dBm`** (the `power` argument) is not in the list of units of `Instruments_LIB/schema/README.md`
  (`V`, `V/div`, `s`, `s/div`, `Hz`, `Sa/s`, `points`, `ratio`): add it when `schema/vna.json` is added, and
  `vnas_series` to the table of categories there.

## Trying a measurement without an instrument

`ola/sim_vna.py` (`SimVna`) implements exactly these two calls on a simulated cable or antenna, and the tests of the
measurements use it. A library entry is correct when a measurement that works on `SimVna` works the same on the real
instrument.

## Notes for an instrument with a text protocol (LiteVNA)

An instrument that is commanded with text lines on a serial port (not SCPI) fits the library's `scpi` access (a plan
of write / query / read steps with parsers); the data of a sweep may be long, so the step fields for reading many
lines or a fixed number of bytes ([`engine.md`](engine.md)) matter. What has to be settled with the real
instrument: the command that starts a sweep and tells when it is done, the format of the data (text or binary), and
the real frequency range and maximum number of points.
