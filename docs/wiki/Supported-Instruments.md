# Supported instruments

The instruments are described in the [instrument library](Instrument-Library). The table below is the list the application's README gives; the library's own README has the up-to-date list of models and of which ones have been tested.

| Category | Series |
|---|---|
| Power supplies | OWON ODP, Keysight E36300, TDK-Lambda GEN, Rohde & Schwarz HMP, HP E3631A |
| Electronic loads | Chroma 6330A, Keysight EL4900, Siglent SDL1000X-E |
| Oscilloscopes | Tektronix 5 Series MSO, Rigol DS1000Z, Siglent SDS HD, GW Instek GDS-1000B, Digilent Analog Discovery 2 (driver) |
| Dataloggers | Agilent 34970A, Keysight 34972A, Keysight DAQ970A / DAQ973A |
| Switch units | Agilent 3499A |
| Function generators | Rigol DG1022 / DG1022A, Agilent 33120A, Digilent Analog Discovery 2 (driver) |
| Multimeters | HP 3478A, Agilent 34401A |
| Network analyzers | Zenko LiteVNA (driver), Siglent SNA, Rohde & Schwarz ZNB / ZNL / ZNLE, ZVA / ZVB / ZVT / ZVL |

The library also describes RF signal generators (Keysight EXG and MXG) and spectrum analyzers (Rigol, Siglent). No measurement module uses them yet.

## What "tested" means

A model is **experimental** until its commands have been run on a real instrument. The library's README says exactly which models are not experimental and how each was tested; the rule for changing the flag is in its `TESTING.md`. The README of the application says which instruments the software itself was tried with: the Agilent 34970A over RS-232 and the Siglent SDS824X HD over LAN (readings, settings, 8- and 16-bit waveforms, whole-memory transfers, `.was` files).

The Analog Discovery 2 needs the Digilent WaveForms runtime. Reports of tests on other instruments are welcome: see [Contributing](Contributing).

## Adapters

- GPIB: Keysight 82357A / 82357B, NI GPIB-USB-HS, Measurement Computing USB-488, any VISA `GPIB<n>` board, Prologix GPIB-USB / GPIB-ETHERNET, AR488. See [GPIB adapters](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/gpib-adapters.md). None has been tried on a real adapter yet.
- LiteVNA: a serial-port VNA with its own binary protocol (driver in `ola/drivers/litevna.py`).
