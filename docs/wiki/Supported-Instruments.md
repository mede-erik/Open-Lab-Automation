# Supported instruments

The instruments are described in the [instrument library](Instrument-Library). The library holds 91 models in 24 series. Only four models are not marked *experimental*: the three Siglent SDS800X HD oscilloscopes (partially tested) and the Agilent 34970A data logger.

| Category | Series |
|---|---|
| Power supplies | OWON ODP, Keysight E36300, TDK-Lambda GEN, Rohde & Schwarz HMP, HP E3631A |
| Electronic loads | Chroma 6330A, Keysight EL4900, Siglent SDL1000X-E |
| Oscilloscopes | Tektronix 5 Series MSO, Rigol DS1000Z, Siglent SDS HD, Digilent Analog Discovery 2 (driver) |
| Dataloggers | Agilent 34970A, Keysight 34972A, Keysight DAQ970A / DAQ973A |
| Switch units | Agilent 3499A |
| Function generators | Rigol DG1022 / DG1022A, Agilent 33120A, Digilent Analog Discovery 2 (driver) |
| Multimeters | HP 3478A, Agilent 34401A |
| Network analyzers | Zenko LiteVNA (driver), Siglent SNA, Rohde & Schwarz ZNB / ZNL / ZNLE, ZVA / ZVB / ZVT / ZVL |

## Tested on real instruments

- **Agilent 34970A** over RS-232: readings, settings, channel scans.
- **Siglent SDS824X HD** over LAN: readings, settings, 8- and 16-bit waveforms, whole-memory transfers, `.was` files.

Everything else is written from the manuals and is marked experimental. The Analog Discovery 2 needs the Digilent WaveForms runtime. Reports of tests on other instruments are welcome: see the library's `TESTING.md`.

## Adapters

- GPIB: Keysight 82357A / 82357B, NI GPIB-USB-HS, Measurement Computing USB-488, any VISA `GPIB<n>` board, Prologix GPIB-USB / GPIB-ETHERNET, AR488. See [GPIB adapters](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/gpib-adapters.md).
- LiteVNA: a serial-port VNA with its own binary protocol (driver in `ola/drivers/litevna.py`).
