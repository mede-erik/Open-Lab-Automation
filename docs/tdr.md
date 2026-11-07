# Time domain (`.tdr`): where along a cable a fault is

The reflection of a cable measured with a vector network analyzer (VNA), turned into the **time domain**: every change of
impedance along the line (a damaged spot, a bad connector, a section of another cable, the open or the short at the far end) is a
**peak at a distance** from the plane of the calibration. It is the measurement for finding where a coax is damaged, how long a cable
is, and what its velocity factor is, without cutting it.

## How it works

A reflection of coefficient `rho` at the delay `tau` appears in S11 as `rho * exp(-j 2 pi f tau)`: a ripple of period `1 / tau`. The
inverse Fourier transform of S11 (with a window) turns each ripple back into a peak at its delay, and the distance is

`d = c * vf * t / 2`

(`vf` the velocity factor, the 2 for the way there and back). The maths is in [`ola/tdr.py`](../ola/tdr.py). For each peak the program
sums the data at its exact delay, so the size, the **sign** and the impedance are measured, not read off the coarse curve:

* a **positive** reflection is a **higher impedance**: an open, a thinner or damaged spot;
* a **negative** one is a **lower impedance**: a short, a crushed spot, a thicker section.

## What the sweep decides

| | Formula | Example |
|---|---|---|
| **Resolution**: the smallest distance between two faults that show as two | `c vf / (2 B)`, `B` the width of the sweep | 1 GHz wide, vf 0.66: **10 cm** |
| **Range**: the distance after which the reflections wrap round | `c vf / (2 df)`, `df` the step between points | 501 points over 1 GHz (2 MHz step): **50 m** |

So: sweep **wide** for a fine resolution and use **enough points** for a long cable (the result gives both numbers). Two faults closer
than the resolution are one peak. A **window** (Hann by default) keeps the sidelobes of a strong reflection from looking like faults and from
hiding a weak one next to it; `rect` has the finest resolution and the most sidelobes (a test shows the sidelobes of no window above
the default threshold).

## The file

```json tdr.tdr
{
  "device": {"label": "antenna feed"},
  "sweep": {"start_hz": 1000000, "stop_hz": 1000000000, "points": 501},
  "velocity_factor": 0.66,
  "z0": 50,
  "window": "hann",
  "pad": 8,
  "min_reflection": 0.05,
  "expected_length_m": 5.0,
  "step_response": false,
  "averages": 1,
  "limits": {"max_fault_reflection": 0.5},
  "confirm_setup": false
}
```

| Field | Meaning |
|---|---|
| `device.label`, `device.asset_id` | the cable, and its code in the registry ([`assets.md`](assets.md)) |
| `sweep` | `start_hz`, `stop_hz`, `points`: **linear** (a logarithmic sweep is refused) and at least 16 points |
| `velocity_factor` | above 0 and at most 1: 0.66 for a solid polyethylene coax, 0.82 for a foam one, 0.95 for air. It scales **all** the distances: if it is wrong they are all wrong by the same ratio |
| `z0` | the reference impedance (50 ohm) for the impedance at each reflection |
| `window` | `hann` (the default), `hamming`, `blackman` or `rect` |
| `pad` | zero padding, 1 to 64 (8 by default): the curve is computed at that many times more points; it makes the peaks smooth and the distances exact |
| `min_reflection` | a peak below this coefficient is not counted (0.05 by default) |
| `max_distance_m` | show and look only up to this distance |
| `expected_length_m` | the length, if known: with an open or short far end the **length error** and the **velocity factor that fits** are given |
| `step_response` | also give the step response and the impedance profile (below) |
| `limits` | `max_fault_reflection`: the largest reflection allowed **before the end of the line** |

## How to measure

1. Calibrate the VNA (open / short / load, **one port**) at the plane of the connector the line goes on, over the sweep you will use.
   The distances are measured from that plane.
2. Connect the line. Leave the far end **open**, or put a **short** on it, or connect the device it feeds: the last reflection is that end.
3. The window of the connections ([`wiring.md`](wiring.md)) says this before the run.

## What you get

* **Curves**: `impulse`, the reflection `|rho|` against **distance in metres** (the curve opens with it); `S11` (hidden). With
  `step_response`: `step` and `impedance_ohm`, hidden.
* **Table `faults`**: a row for every peak: `distance_m`, `delay_ns`, `reflection`, `phase_deg`, `kind` (higher or lower impedance) and
  `impedance_ohm`.
* **Table `points`** (one row): the number of reflections, the resolution and the range, the first, the last (the end of the line) and the
  strongest reflection with their distances, and with `expected_length_m` the `length_error_m` and the `velocity_factor_estimate`
  (`vf * length / distance of the last reflection`: the velocity factor that would make the line as long as you know it is), and the verdict.

The loss of the cable **weakens the far reflections** (the round trip is twice its loss): a reflection of 1 at the end of a long, lossy
cable reads much less, and the same fault reads smaller the farther it is. The verdict counts only the reflections **before the end**: the
last peak is the open, the short or the device, not a fault. If nothing is above `min_reflection` the log says the line is matched, or the
end is too far or too weak (lower the threshold).

### Step response and impedance profile

With `step_response` the same data is also shown as the reflection of a **step** of voltage: its level is the reflection coefficient of what
the step has reached, and `impedance_ohm` is the impedance along the line (50 ohm, then the value of each section). It shows a cable **made of
sections** (a 75 ohm piece in a 50 ohm line) better than the peaks, and is worse than the peaks for small faults. It needs a sweep that **starts at
its own step** (`start_hz` a multiple of `(stop - start) / (points - 1)`: for example 2 MHz to 1 GHz in 500 points); the data below the start is the
first point with its phase continued backwards, and DC is the real part. The check says so at the field if the sweep does not fit.

## What the VNA must provide

The calls of the network analyzer category, as for the other VNA measurements ([`vna-calls.md`](vna-calls.md)): a linear sweep and S11
(`set_frequency_sweep`, `run_sweep`, `read_sparameters`). The sweep is the widest the VNA does for the best resolution. `ola/sim_vna.py`
(`SimVna(length_m=5, termination="open", fault_at_m=2, fault_gamma=0.3)`) is a simulated VNA with a cable that has a fault, used by the
tests: the distances it gives are checked against the cable, with the same result on both sets of calls.

## Not done yet

Tried only with the simulated VNA. Not done: the loss of the cable taken out of the amplitude of the far reflections (the reflection of a fault
far away reads smaller than it is), multiple reflections (echoes of echoes are not separated from faults), and a gating of the response to look
at one reflection only (to find the return loss of one connector in a chain).
