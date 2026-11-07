# Taking a cable, an adapter or a pad out of a measurement (de-embedding)

The VNA is calibrated at the end of its test leads. What is between that plane and the device you measure (a longer
cable, an adapter, a pad) is **in the result**: it adds its loss and delay, and it makes a mismatched device look better
matched. If the cable or the pad has already been measured, the program takes it out, so that the result is of the **device
alone** and its loss is not charged to the device.

There are two situations:

| The device is... | Measurement | The fixture is named in | See |
|---|---|---|---|
| behind a cable on **one port** (a reflection: an antenna, an input) | return loss, antenna | `correction.cable` | [`return-loss.md`](return-loss.md), [`antenna.md`](antenna.md) |
| between **two ports**, with a cable / adapter / pad on **port 1, port 2 or both** | filter, attenuator | `correction.port1`, `correction.port2` | this page |

The maths is in [`ola/deembed.py`](../ola/deembed.py) (one port) and [`ola/fixtures.py`](../ola/fixtures.py) (two ports).

## How to name a fixture

Each fixture (`cable`, `port1`, `port2`) is named in **one** way:

| Field | The fixture is... |
|---|---|
| `asset_id` | its code in the registry ([`assets.md`](assets.md)): the **newest finished measurement** of that code in the runs folder of the project (a cable measurement, or for a two-port measurement an attenuator measurement too). The file used is saved in the header of the run. If there is none, the run does not start and says to measure it first |
| `run` | a run file (`.jsonl`) of a cable or attenuator measurement |
| `touchstone` | a `.s2p` file written **as seen from the VNA**: port 1 at the VNA end, port 2 at the device end, **for both port 1 and port 2** (the one on port 2 is turned round by the program). `reversed: true` for a file written the other way round. (A `.s1p` is for the one-port cable: the far end open or short, `termination`) |

## The two models and the two modes (two ports)

```json
"correction": {"port1": {"asset_id": "CBL-0042"}, "port2": {"asset_id": "ATT-0003"},
               "mode": "complex", "model": "matched"}
```

* **`model: matched`** (the default): what is taken out is assumed **well matched**, so it only attenuates and delays:
  `S21 = S21 measured / (T1 * T2)`, and the reflections are divided by the round trip of their own fixture
  (`S11 / T1^2`, `S22 / T2^2`). It needs only the transmission `T` of each fixture. Right for a cable, and for a pad with a good
  return loss.
* **`model: full`**: the fixtures have **reflections of their own** (an adapter, a pad, a bad connector). The measurement is
  cut in the **transfer matrices**: `T measured = T1 * T device * T2`, so `T device = inv(T1) * T measured * inv(T2)`. It is
  exact for any fixture. It needs **all four S-parameters** measured (the program reads them: `S11 S21 S12 S22`), and fixtures
  **with their reflections**: a `.s2p` file, or the run of an **attenuator measurement** (which has `S11` and `S22`). A cable
  measured only in transmission has no reflections and is refused here (use `matched` for it).
* **`mode: complex`** (the default when the fixtures have a phase): the phase is used too, so the corrected S-parameters
  are complete (the group delay of the device alone, the Smith chart). **`mode: magnitude`**: only the size of the
  transmission is taken out and the measured phase is kept: enough when only the **loss** of the fixture is known (a cable
  measured in reflection, or a run that kept only the loss curve). It can only be used with the `matched` model.

A cable measured in **reflection** (open or short at the far end) has only the size of its transmission (the sign of its
phase is ambiguous), so as a two-port fixture it works in `magnitude` mode.

## What you get

* The curves are of the **device alone**: the filter's `S21`, the attenuator's `attenuation_db`, the return losses. The
  measurement as it came stays as `S21_raw` (and `attenuation_raw_db`), drawn together with the corrected one.
* The summary says `corrected`, `correction_model`, `correction_mode`, the loss of the fixture on each port
  (`fixture_loss_port1_db`, `fixture_loss_port2_db`) and what it was before (`raw_insertion_loss_db`,
  `raw_mean_attenuation_db`).
* The window of the connections ([`wiring.md`](wiring.md)) draws the fixtures in the diagram and tells how to connect them.

## How to calibrate and measure

* Calibrate at the end of the **test leads, without the fixtures**: they are not part of the calibration, their loss is
  what the correction takes out.
* Use the **same cable / pad that was measured**, in the **same position** (a cable bent differently has a different phase,
  and a pad has a slightly different match).
* Measure the fixture with enough points for its length (the phase must not turn by more than 140 degrees between two
  points: the program warns) and over **at least the frequency range of the measurement**: the fixture data is
  interpolated and must cover the sweep.

## When it does not fit

* Where the corrected **reflection** would exceed 1 it is limited just under 1 and the log says how many points (a warning):
  the fixture does not match this measurement (another cable, a calibration plane that is not where it was).
* Where the corrected **S21 is above 0 dB** the log says so: right for an amplifier, otherwise the fixture data does not
  fit (a filter or a pad cannot have gain).
* The matched model leaves the fixture's own reflection behind: the error is small for a cable and for a good pad; use `full`
  when it is not. The tests check both against exact synthetic networks: the full model recovers the device to
  10^-6 through mismatched fixtures on both ports, the matched one is exact for matched ones.

## Not done yet

The amplifier and the cable measurements do not take fixtures out yet (their set-up already puts an attenuator inside the
calibration, which is the usual way). Fixtures measured with their own S-parameters in several steps (a chain of adapters) can
be combined by measuring the chain as one fixture. A fixture's effect on **noise** is not part of this (it is only about
S-parameters).
