# Instrument library

The instrument library is a separate repository, [`mede-erik/Instruments_LIB`](https://github.com/mede-erik/Instruments_LIB), mounted here as the `Instruments_LIB/` submodule. It is **data only**: a JSON file that describes each model, and schemas that define the logical calls of each category.

## What it contains

- `instruments_lib.json`: 91 models in 24 series, grouped in categories (power supplies, electronic loads, oscilloscopes, dataloggers and their modules, switch units, multimeters, function generators, network analyzers).
- `schema/`: the logical calls of each category (the contract between OLA and the library), and the format of a library entry.
- `docs/COMMANDS.md` and `COMMAND_NAMES.md`: the canonical call names and the command of each model.
- `TESTING.md`: how to test a model on a real instrument and report the result.

## The rule

**One logical call, one name, for every brand.** `set_voltage` is the same call for an OWON and for a Keysight supply; the library says which SCPI string each model needs. Software that uses the calls never has to know the brand.

## Adding a model

1. Add the entry to `instruments_lib.json` (interfaces, capabilities, commands). New models are `"experimental": true` until someone has tried them on hardware.
2. Check it: `pytest tests/test_library_integrity.py` in the OLA repository, and the library's own checks.
3. Try it: `python scripts/instrument_shell.py` (real or `--sim`) and `TESTING.md` in the library.

## Status

Models are experimental unless noted in [Supported instruments](Supported-Instruments).

