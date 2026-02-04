---
name: "Add Instrument to Library"
about: "Template for proposing a new instrument to be added to the instrument library (instruments_lib.json)"
title: "Add instrument: [Brand/Model]"
labels: ["instrument-library", "enhancement"]
assignees: []
---

## Instrument Information

- **Instrument Type:** <!-- power_supplies_series, dataloggers_series, oscilloscopes_series, electronic_loads_series -->
- **Manufacturer:** <!-- e.g. Keysight Technologies, Rohde & Schwarz, etc. -->
- **Series:** <!-- e.g. E36300 Series, RSB Series, etc. -->
- **Model:** <!-- e.g. E36312A, RTB2004, etc. -->
- **Full Model Name:** <!-- e.g. Keysight E36312A -->

## Connection Interface

- **Supported Connection Types:** <!-- Check all that apply: LXI, GPIB, USB, RS232, TCPIP -->
- **Default Communication Protocol:** <!-- e.g. SCPI, Proprietary, etc. -->
- **VISA Resource ID Format:** <!-- e.g. TCPIP0::{IP_ADDRESS}::inst0::INSTR -->

## Capabilities

### General
- **Number of Channels/Slots:** <!-- e.g. 3 channels, 8 slots, etc. -->
- **Special Features:** <!-- e.g. Over Voltage Protection, Remote Sensing, Trigger Output, etc. -->

### Channel/Slot Specifications (if applicable)
For each channel/slot, provide:
- **Channel ID:** <!-- e.g. CH1, CH2, SLOT1, etc. -->
- **Label:** <!-- e.g. "Channel 1 (0-6V)", "Slot 1 - Type K Thermocouple" -->
- **Range/Specifications:** <!-- e.g. Voltage: 0-25V, Current: 0-5A, Temp: -200°C to +1372°C -->
- **Resolution:** <!-- e.g. 3 decimal places, 0.1°C -->
- **Units:** <!-- V, A, W, °C, °F, etc. -->

## SCPI Commands

### Common Commands (Series-Level)
Provide the standard SCPI commands used across the series:
```
*IDN? - Identification Query
*RST - Reset
*CLS - Clear Status
SYST:ERR? - Error Query
<!-- Add other common commands -->
```

### Model-Specific Commands
Provide any model-specific SCPI commands:
```
<!-- Add model-specific commands if different from series -->
```

## Documentation

- **Datasheet URL:** <!-- Link to manufacturer's datasheet -->
- **Programming Manual URL:** <!-- Link to SCPI/programming manual -->
- **User Manual URL:** <!-- Link to user manual -->
- **Local Documentation Path:** <!-- e.g. docs/Keysight/E36300_Series/E36312A_manual.pdf -->

## Complete JSON Structure

```json

```

## Testing

- [ ] Tested with physical hardware
- [ ] Verified SCPI commands work correctly
- [ ] Tested all connection types listed
- [ ] Verified all channels/slots work as specified
- [ ] Documentation paths are correct and accessible

## Validation Checklist

- [ ] All required fields are filled
- [ ] JSON structure is valid and properly formatted
- [ ] SCPI commands follow the series standard
- [ ] Channel/slot specifications are complete and accurate
- [ ] Documentation links are valid
- [ ] Naming conventions follow the pattern: `TYPE_Manufacturer_Model`
- [ ] Series ID follows the pattern: `Manufacturer_ModelSeries_Series`

## Additional Notes

<!-- Add any other relevant information, known issues, limitations, or special configuration notes -->
