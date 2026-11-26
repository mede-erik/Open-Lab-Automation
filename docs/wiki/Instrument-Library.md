# Instrument library

The instrument library is a separate repository, [`mede-erik/Instruments_LIB`](https://github.com/mede-erik/Instruments_LIB), mounted here as the `Instruments_LIB/` submodule. It is **data only**: a JSON file that describes each model, and schemas that define the logical calls of each category.

## What it contains

- `instruments_lib.json`: the models, grouped in series and categories. At the time of writing (November 2026) it has 130 models in 34 series and 11 categories: power supplies, electronic loads, oscilloscopes, dataloggers and their modules, switch units, multimeters, function generators, network analyzers, RF signal generators, spectrum analyzers. The README of the library has the current numbers.
- `schema/`: the logical calls of each category (the contract between OLA and the library), and the format of a library entry.
- `COMMAND_NAMES.md` and `docs/COMMANDS.md`: the canonical call names and the command of each model.
- `TESTING.md`: how to test a model on a real instrument, what to report, and the rule for the `experimental` flag.
- `docs/`: the manuals of the instruments, and design proposals.

## The rule

**One logical call, one name, for every brand.** `set_voltage` is the same call for an OWON and for a Keysight supply; the library says which SCPI string each model needs. Software that uses the calls never has to know the brand.

## Adding a model

1. Add the entry to `instruments_lib.json` (interfaces, capabilities, commands). New models are `"experimental": true` until someone has tried them on hardware.
2. Check it: `pytest tests/test_library_integrity.py` in the OLA repository (every call of every model must plan), and the library's own conformance check.
3. Try it: `python scripts/instrument_shell.py` (real or `--sim`), and follow `TESTING.md` in the library.
4. A change to the library is made and merged in the library repository first; then a pull request in OLA moves the submodule pointer.

## Which library a package contains

The nightly package takes the newest commit of the library's `main`. Alpha, beta, release-candidate and final packages take the latest published release of the library, so a library release is published before the program is tagged.

## Status of the models

See [Supported instruments](Supported-Instruments) and the library README, which says which models are tested and how.
