---
name: "Add Instrument to Library"
about: "Template for proposing a new instrument to be added to the instrument library (instruments_lib.json)"
title: "Add instrument: [Brand/Model]"
labels: ["instrument-library", "enhancement"]
assignees: []
---

## Instrument Information

- **Type:** <!-- e.g. power_supply, datalogger, oscilloscope, electronic_load -->
- **Series:** <!-- e.g. E36300 Series -->
- **Brand:** <!-- e.g. Keysight -->
- **Model:** <!-- e.g. E36312A -->
- **Instrument ID (if known):** <!-- e.g. E36312A -->

## Instrument Details

- **Supported Connection Types:** <!-- e.g. USB, LAN, GPIB, RS232 -->
- **Channels/Slots:** <!-- e.g. 2 channels, 4 slots, etc. -->
- **Key Features:** <!-- Short list of main features -->

## JSON Example (optional)

```json
{
  "series_id": "E36300",
  "series_name": "E36300 Series",
  "models": [
    {
      "id": "E36312A",
      "name": "E36312A",
      "interface": {
        "supported_connection_types": [
          {"type": "USB"},
          {"type": "LAN"}
        ]
      },
      "capabilities": {
        "channels": [
          {"channel_id": "CH1", "label": "Output 1"},
          {"channel_id": "CH2", "label": "Output 2"}
        ]
      }
    }
  ]
}
```

## Additional Notes

<!-- Add any other relevant information or links to datasheets/manuals -->
