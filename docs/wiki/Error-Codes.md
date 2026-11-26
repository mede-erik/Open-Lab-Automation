# Error codes

Every error has a code in the form `[RESOURCE-XXX]`: a short prefix for the resource or component and a three-digit number. The codes are shown to the user and written to the log, without brackets, with the stack trace.

```
[11:20:08] ERROR-VISA-002-Cannot open device at TCPIP0::192.168.1.104::INSTR
```

The full list, with the cause and the fix for each code, is in [`ERROR_CODES.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/ERROR_CODES.md).

## Prefixes

| Prefix | Area |
|---|---|
| `TRN` | instrument transport (connection, I/O, timeout, closed) |
| `CALL` | instrument calls (not supported, invalid argument, step failed) |
| `SCPI` | SCPI syntax, parameter and device errors |
| `VISA` | VISA connection and communication |
| `GPIB` | GPIB adapters and their driver |
| `INST` | instrument configuration (`.inst` file) |
| `LIB` | instrument library |
| `PROJ` | project files |
| `MEAS` | the *Measurements* tab: measurement files, their runs and results |
| `AST` | the registry of cables and devices, DUTs and their labels |
| `DATA` | data acquisition and storage |
| `DL` | datalogger configuration |
| `TOOL` | tools (pulse generator, power limits) |
| `CFG` | application configuration |
| `FILE`, `VALID`, `NET`, `UI`, `SYS` | files, input validation, network, interface, system |

A timeout reaches you as `TRN-003`. `GPIB-005` is documented for reference but is not raised by the current code.

## Reporting a problem

When you open an issue, copy the code shown in the error message, for example `[DL-001]`. It makes the problem much faster to find.

## For developers

- Raise the exception type of the component with its code; do not invent a new prefix without adding a section to `ERROR_CODES.md`.
- `tests/test_core_errorhandler.py` fails if a code used in the source is not documented.
