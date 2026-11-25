# Roadmap

The detailed design, decisions and open points are in the repository's [`PLAN.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/PLAN.md) (being translated to English). This page lists what is planned, not what is done: for what works today, see [Measurements](Measurements) and [Supported instruments](Supported-Instruments).

## Planned

- **Measurement report**: an HTML report that can be saved as PDF, built from an editable template. Results are exported as CSV (and Touchstone for RF) for now.
- **Measurement templates**: ready-made measurement files for variations of an existing module (line and load regulation, I-V curve...).
- **More measurement modules**: load transient, battery discharge.
- **Instruments without SCPI**: LiteVNA67 over serial, Analog Discovery 2 and 3 through the driver system.
- **Beta state**: the engine's module API (`api_version` 1) is to be frozen before modules written by others are promised compatibility.

## Open questions

- The design of the driver system (interface, session lifecycle, detection, runtime installation).
- Where drivers live: in the OLA repository or in the user folder, with JSON data only in the library.
- Composite devices (one physical device, several logical instruments) in the instrument file and the library.
