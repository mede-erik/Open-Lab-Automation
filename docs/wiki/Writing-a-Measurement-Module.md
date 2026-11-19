# Writing a measurement module

A measurement module is a folder with a manifest and a Python file. OLA finds it, lists it in *New measurement* and runs it with the engine's runner.

## Where modules live

| Folder | Scope |
|---|---|
| `ola/modules/` | built in, shipped with OLA |
| `~/.open_lab_automation/modules/` | your modules, all projects |
| `<project>/modules/` | one project |

Finding a module never runs its code. A module that is not built in needs your explicit permission to load (`allow_user_code`).

## The smallest useful module

`module.json` says what the module is, its file extension, its instruments (roles), its parameters and the entry point. The Python file defines a `Measurement` subclass with `setup`, `run` and `teardown`.

The reference examples in the repository:

- `ola/modules/time_log/`: small, complete, tested. Start here.
- `ola/modules/efficiency/`: larger, with formulas and questions to the user.

The full walkthrough, with a working example that the test suite runs, is [`docs/measurement-modules.md`](https://github.com/mede-erik/Open-Lab-Automation/blob/main/docs/measurement-modules.md).

## Instruments

Modules never send SCPI. They ask for a role and make a logical call:

```python
handle = ctx.instrument("psu")
handle.call("set_voltage", value=5)
```

The call names and arguments are defined in the instrument library (`Instruments_LIB/schema/`). If the library does not have the call a measurement needs, add it there first (see the [Instrument library](Instrument-Library) page).

## Editors without code

A module can ship a `form.json` next to `module.json`: sections and fields (text, number with SI prefixes, choice, list, JSON, instrument), some shown only for certain values of another field. OLA builds the editor from it. The module's `check()` reports problems, shown at the field that has them.

## Safety

- Set every output to a safe state in `setup`, and always switch it off in `teardown`, even after an error or a stop.
- Refuse out-of-limit settings before anything is switched on.
- Do not let a single bad reading stop the run silently: report it as a result, or ask the operator.
