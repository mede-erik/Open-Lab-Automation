# The network analyzer category: what the measurements ask of a VNA

The RF measurements ([cable](cable.md), [return loss](return-loss.md), [filter](filter.md), [antenna](antenna.md),
[amplifier](amplifier.md) and [attenuator](attenuator.md)) never talk to a VNA directly. They ask for **logical calls**, the
same for every brand, and the instrument library translates them for the model, as it does for power supplies and
oscilloscopes ([`instrument-calls.md`](instrument-calls.md)). The calls of the category are defined in the library:
`Instruments_LIB/schema/vna.json`, category `network_analyzers_series` (the LiteVNA62, 64 and 67 so far).

The measurements speak **two sets of calls**, and use the first one whenever the instrument has it
(`ola/vna_common.py`, `uses_library_calls`):

| | Calls | Used for |
|---|---|---|
| **The library's category** | `set_frequency_sweep`, `run_sweep`, `read_sparameters`, and the optional `set_if_bandwidth`, `set_source_power`, `set_sweep_type` | every real instrument of the library |
| **The simple calls** | `set_sweep`, `read_sparameter` | the simulated VNA (the default of `SimVna`) and any instrument that has them |

Which one is used does not change what a measurement gives: the same measurement on `SimVna()` and on
`SimVna(library_calls=True)` gives the same numbers (a test checks it for the six measurements).

## What the program does *not* do

* **No calibration in the measurements.** The user calibrates the VNA beforehand (at the ends of the test leads, or at the
  port, or with the guided calibration of the library) and the measurement asks, once, whether it is done. If the instrument
  says its data are **not calibrated** (`calibrated: false`), the log warns.
* **No display, markers or math on the instrument.** The measurement reads the complex data and does the calculations
  itself ([`ola/rf.py`](../ola/rf.py)).

## The library's calls

| Call | Arguments | What the measurement does |
|---|---|---|
| `set_frequency_sweep` | `start_frequency` (Hz), `stop_frequency` (Hz), `points` | sets the sweep (linear unless `set_sweep_type` says otherwise) |
| `run_sweep` | | starts a sweep, once for every sweep averaged |
| `read_sparameters` | `sparameters`: the list of what is needed, such as `["S11", "S21"]` (the amplifier asks for all four) | gives the frequencies and those S-parameters of that sweep |
| `set_if_bandwidth` (optional) | `value` (Hz) | sent when the file gives `if_bandwidth_hz` |
| `set_source_power` (optional) | `value` (dBm) | sent when the file gives `power_dbm`; the **compression test** of the amplifier steps it |
| `set_sweep_type` (optional) | `sweep_type`: `LINEAR` or `LOG` | sent **after** `set_frequency_sweep` (which always sets a linear sweep) when the instrument has it |

All the parameters come from **one** sweep (faster than one sweep for each). The answer of `read_sparameters`:

```json
{"frequency": [1000000.0, 8000000.0],
 "parameters": {"S11": {"real": [0.012, 0.034], "imaginary": [-0.994, -0.971]}},
 "calibrated": true}
```

The measurements work on what comes back: the frequencies actually used are the ones that are plotted, and a parameter that
was asked and is missing from the answer is an error that names what the instrument gave. The first draft of the category had a
`select_sparameters` call: it **no longer exists**, the list goes with `read_sparameters`, and an instrument that has only the
draft calls is not recognised as speaking the library's category.

### What an instrument may not have, and what the measurements do about it

The three optional calls are not on every instrument (the Siglent SNA / SHN and the R&S ZNx / ZVx have the first two; the
LiteVNA has none of them and sweeps linearly). When a measurement file asks for something the instrument cannot do, the
measurement **warns in the log and goes on**, nothing is sent for it:

* `scale: log` without `set_sweep_type`, or with an instrument that has the call but answers that `LOG` is not handled (the LiteVNA): the sweep is linear (the frequencies of the answer are the ones used);
* `if_bandwidth_hz` without `set_if_bandwidth`, `power_dbm` without `set_source_power`: the instrument keeps its own setting.

The one measurement that depends on it is the **compression test of the amplifier**, which steps the source power: with an
instrument that has no `set_source_power` the run is refused **before** the question and before anything is sent ("the compression
test steps the source power of the VNA, and this VNA has no call to set it"). The rest of the amplifier measurement works. At the
end of the test the power is put back to the one of the sweep.

## The simple calls

| Call | Arguments | Gives |
|---|---|---|
| `set_sweep` | `start_frequency`, `stop_frequency`, `points`, optional `sweep_type` (`linear` or `log`), `if_bandwidth`, `power` | |
| `read_sparameter` | `parameter` (`S11`, `S21`, `S12`, `S22`) | `{"frequency": [...], "values": [[re, im], ...]}` (a plain list of complex numbers is accepted too) |

`read_sparameter` returns only when the sweep has finished. The optional arguments of `set_sweep` are only sent when the user
gave them. `ola/sim_vna.py` (`SimVna`) implements these on a simulated cable, filter, attenuator, antenna or amplifier, and the
tests use it: **a measurement that works on `SimVna` must work the same on a real instrument**, whichever calls it has.
`SimVna(library_calls=True)` answers the library's calls instead (and refuses the simple ones, as a real instrument would); `library_extras=False` leaves out the two optional ones, as the LiteVNA does.

## What a library entry for a VNA needs

* A **parser** or a driver for the answer: `read_sparameters` gives a mapping (`frequency`, `parameters`, `calibrated`) built
  from what the instrument sends. The LiteVNA has a driver ([`ola/drivers/litevna.py`](../ola/drivers/litevna.py)) with a software
  calibration; for an SCPI analyzer the parser is `vna_sparameters` in [`ola/parsers.py`](../ola/parsers.py).
* The access of the instrument in the `.inst` file of the project is of type `network_analyzer`.

## Not done yet

Measurements with a real VNA have not been made yet: all the RF measurements were tried on the simulation, and the calls they
send were planned for the LiteVNA62, 64 and 67 of the library (a test does it with the library's real schema). `set_sweep_type`
is in the library's PR Instruments_LIB#5 and not in `main` yet: the measurement already uses it, after `set_frequency_sweep`.
