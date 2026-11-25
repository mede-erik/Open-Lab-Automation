# Measurements

Every measurement is a **module** in `ola/modules/`. Each has a guide in the repository `docs/` folder, and each can be run with simulated instruments to try it without hardware.

## Power

| Measurement | File | What it does | Guide |
|---|---|---|---|
| Efficiency | `.eff` | Sweeps parameters of a converter, reads input and output power, computes efficiency with safe formulas (never `eval`) | [efficiency](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/efficiency.md) |
| Line and load regulation | `.reg` | Output against input voltage and against load current; output resistance in mΩ | [regulation](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/regulation.md) |
| Ripple and noise | `.rpl` | Peak-to-peak, rms, ripple frequency and harmonics, with an oscilloscope; optionally against load current | [ripple](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/ripple.md) |
| Time log | `.tlg` | One or more values at a fixed interval (temperature, voltage over a night) | [time-log](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/time-log.md) |

## RF (with a vector network analyzer)

| Measurement | File | What it does | Guide |
|---|---|---|---|
| S-parameters | `.spm` | Raw S-parameters as complex curves, Touchstone export | [sparameters](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/sparameters.md) |
| Return loss / VSWR | `.rtl` | S11: return loss, VSWR, impedance, bandwidth of a match | [return-loss](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/return-loss.md) |
| Filter | `.flt` | Low-pass, high-pass, band-pass, band-stop: insertion loss, edges, Q, ripple, group delay, pass/fail mask | [filter](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/filter.md) |
| Amplifier | `.amp` | Gain, match, isolation, stability (K, μ), 1 dB compression point; protects amplifier and VNA | [amplifier](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/amplifier.md) |
| Attenuator | `.att` | Attenuation against frequency, flatness, pass/fail against a tolerance or mask | [attenuator](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/attenuator.md) |
| Antenna impedance | `.ant` | R + jX against frequency, Smith chart, resonances, matching component | [antenna](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/antenna.md) |
| Cable characterization | `.cbl` | Loss per metre, group delay, velocity factor, pass/fail limit | [cable](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/cable.md) |
| Time domain (TDR) | `.tdr` | Where along a cable a fault is, length and velocity factor from the reflection | [tdr](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/tdr.md) |

## Frequency response (function generator and oscilloscope)

| Measurement | File | What it does | Guide |
|---|---|---|---|
| Bode plot | `.bod` | Gain and phase against frequency; bandwidth, phase margin, gain margin | [bode](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/bode.md) |

The Bode plot needs a function generator in the library. The Analog Discovery 2 provides one through its driver.

## Cross-cutting features

- **Connections**: every measurement has a wiring diagram shown before the start ([wiring](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/wiring.md)).
- **De-embedding**: a cable, adapter or pad already measured can be taken out of a result ([deembedding](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/deembedding.md)).
- **Golden samples**: each run can be checked against a known-good unit, with a `PASS`/`FAIL` verdict ([golden](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/golden.md)).
- **Registry**: measured objects get a code and a label ([assets](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/assets.md)).

## Writing your own

Measurements can be added without changing the GUI: see [Writing a measurement module](Writing-a-Measurement-Module). A module can also declare a form (`form.json`) and get an editor with no code of its own.
