# Taking a cable, an adapter or a pad out of a measurement (de-embedding)

The VNA is calibrated at the end of its test leads. What is between that plane and the device you measure (a longer
cable, an adapter, a pad) is **in the result**: it adds its loss and delay, and it makes a mismatched device look better
matched. If the cable or the pad has already been measured, the program takes it out, so that the result is of the **device
alone** and its loss is not charged to the device.

Every VNA measurement that can be behind a fixture uses the **same de-embedding** ([`ola/fixtures.py`](../ola/fixtures.py)),
with the same parameters and the same two models. There are two situations:

| The device is... | Measurement | The fixture is named in | See |
|---|---|---|---|
| behind a cable, an adapter or a pad on **one port** (a reflection: an antenna, an input; a cable measured in reflection) | return loss, antenna, cable in reflection | `correction.port1` (or `correction.cable`, the name used before, still read) | [one port](#one-port) |
| between **two ports**, with a cable / adapter / pad on **port 1, port 2 or both** | filter, attenuator, amplifier, cable in transmission | `correction.port1`, `correction.port2` | [two ports](#the-two-models-and-the-two-modes-two-ports) |

The maths is in [`ola/fixtures.py`](../ola/fixtures.py) (`deembed_one_port`, `deembed_two_port`); reading a cable
measurement (in transmission, in reflection or by its loss) is in [`ola/deembed.py`](../ola/deembed.py).

The time domain (TDR) takes nothing out: the distance it gives starts at the plane of the calibration, so a cable in front
of the line is part of the distance.

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

## One port

```json
"correction": {"port1": {"asset_id": "ATT-0003"}, "mode": "complex", "model": "full"}
```

The reflection of the device behind the fixture is computed from the reflection that is measured (`m`):

* **`model: matched`** (the default): `S11 = m / RT`, with `RT = S21 * S12` of the fixture, the **round trip** through it. A
  cable measured in **reflection** (open or short at the far end) gives `RT` directly, **with its phase** (`S11` of an open,
  `-S11` of a short): it is the best one-port fixture of all, even though its transmission alone has a sign that is not known.
  This is the cable correction the return loss and the antenna measurements had before; it gives the same numbers.
* **`model: full`**: the fixture's own reflections are taken out too: `S11 = (m - e00) / (RT + e11 (m - e00))`, with `e00` its
  `S11` (seen from the VNA) and `e11` its `S22` (seen from the device). Exact for any fixture, but it needs one with its
  reflections: a `.s2p` file or the run of an attenuator measurement; and the phase (`mode: complex`).
* **`mode: magnitude`** divides by the size of `RT` only: enough for the VSWR and the return loss when only the loss of the
  fixture is known; the antenna measurement, which needs the impedance, refuses it.

The fixture may be a cable run (in transmission, in reflection or by its loss), an attenuator run, a `.s1p` (a cable with
its far end `open` or `short`, `termination`) or a `.s2p` (`reversed` for a file written from the device side). An
`asset_id` finds the newest finished **cable or attenuator** measurement of that code.

## Not with the manual reversal

With `manual_reversal` (a VNA that drives port 1 only, [`vna-calls.md`](vna-calls.md#a-vna-that-measures-in-one-direction-manual-reversal))
the device is turned round but its fixtures stay on the ports, so `S22` and `S12` would be corrected with the wrong
fixture. The editor refuses a `correction` together with `manual_reversal`.

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

## In the amplifier and the cable measurements

* **Amplifier**: the fixtures (an attenuator in front of the input, the cables) are taken out of the four S-parameters like
  in the filter; the measurement as it came stays as `S21_raw`. The **compression test**, at one frequency, takes them out as
  **losses**: the one on port 1 lowers the power that reaches the amplifier (the input power reported is at the amplifier),
  both lower the gain that is read (the gain reported is the amplifier's). Putting the attenuator inside the calibration, as
  before, is still a good way and needs no correction.
* **Cable**: in transmission, adapters or short cables between the test leads and the cable under test are taken out of
  `S21` (and of `S11`); in reflection, the adapter on port 1 is taken out of `S11` as a one-port fixture.

## Not done yet

Fixtures measured with their own S-parameters in several steps (a chain of adapters) can
be combined by measuring the chain as one fixture. A fixture's effect on **noise** is not part of this (it is only about
S-parameters).
