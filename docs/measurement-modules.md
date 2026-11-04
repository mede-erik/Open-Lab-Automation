# Writing a measurement module

A *measurement module* is a folder with a manifest and a Python file. The program finds it, shows it in
the list of measurement types and runs it with the [runner](engine.md). Built-in modules live in
`ola/modules/`; yours can live in `~/.open_lab_automation/modules/` (all your projects) or in
`<project>/modules/` (one project). `ola/modules/time_log/` is a small, complete, tested example; `ola/modules/efficiency/` is a larger one
(see [efficiency.md](efficiency.md)).

## The smallest useful module

`module.json`: what the module is, which extension its files use, which instruments it needs.

```json module.json
{
  "id": "dc_check",
  "name": "DC check",
  "version": "1.0.0",
  "api_version": 1,
  "extension": ".dcc",
  "entry": "measurement.py:DcCheck",
  "description": "Sets a list of voltages on a power supply and reads them back.",
  "roles": [
    {"name": "psu", "category": "power_supply", "description": "Supply under test"}
  ],
  "params_schema": {
    "voltages": {"type": "list", "required": true, "unit": "V"},
    "settle_s": {"type": "number", "min": 0, "unit": "s", "required": false}
  }
}
```

`measurement.py`: what it does.

```python measurement.py
from ola.measurement import Measurement


class DcCheck(Measurement):
    def validate(self):
        problems = []
        volts = self.params.get("voltages")
        if not isinstance(volts, list) or not volts:
            problems.append("voltages must be a non-empty list")
        elif not all(isinstance(v, (int, float)) and v >= 0 for v in volts):
            problems.append("every voltage must be a number >= 0")
        return problems

    def setup(self, ctx):
        ctx.instrument("psu").call("set_voltage", value=0)
        ctx.instrument("psu").call("output_on")

    def run(self, ctx):
        psu = ctx.instrument("psu")
        for i, volts in enumerate(self.params["voltages"]):
            ctx.checkpoint()                          # stop and pause are honoured here
            psu.call("set_voltage", value=volts)
            ctx.sleep(self.params.get("settle_s", 0.1))
            ctx.emit_point({"set_v": volts, "read_v": psu.call("read_voltage")})
            ctx.progress(i + 1, len(self.params["voltages"]))

    def teardown(self, ctx):
        # ALWAYS runs, also after an error or a stop: leave the supply off.
        ctx.instrument("psu").call("output_off")
```

The call names (`set_voltage`, `read_voltage`, `output_on`, `output_off`) are the names of the instrument
library (`COMMAND_NAMES.md` in `Instruments_LIB`). **A module never builds SCPI**: the same module
works with any power supply the library knows.

## The manifest

| Field | Rule |
|---|---|
| `id` | `a-z`, digits and `_`, starts with a letter, 2-40 characters; unique among modules |
| `name`, `version` | strings |
| `api_version` | must be `1` (the version of this interface) |
| `extension` | `.` + 2-8 lowercase letters/digits, starts with a letter; **one per module**, never shared; not one of the reserved ones (`.json .inst .was .csv .txt .md .py .exe .dll .so .bat .sh .xml .zip .log .db .ini .cfg .yaml .yml`) |
| `entry` | `file.py:ClassName`, the class must derive from `Measurement` |
| `roles` | list of `{name, category, required=true, multiple=false, description}`; unknown fields are rejected |
| `params_schema` | free-form description of the parameters for editors; **not enforced**, your `validate()` must check |
| `description` | text shown to the user |

If two modules share an id or an extension, the first one found wins (built-in, then user folder, then
project folder) and the other is reported in `registry.problems`. An invalid manifest is reported and
skipped; it never breaks the other modules.

A **role** is what the measurement needs, not a model: `psu` of category `power_supply`. The user binds
each role to an instrument of the project (`role_bindings` in the measurement file). A role with
`multiple: true` takes a list of instruments (the time log uses it).

## What the module can use (`ctx`)

| Call | Use |
|---|---|
| `ctx.instrument(role)` | the one instrument bound to the role (`MeasurementError` if not exactly one) |
| `ctx.instruments(role)` | all instruments of the role (empty list for an unbound optional role) |
| `handle.call(name, **args)` | run a logical call, get its logical result |
| `ctx.emit_point({...}, table="points")` | one row of scalar results; `table` names another table (for example `"samples"`) |
| `ctx.ask(text, choices, default, data)` | stop and ask the user (retry / abort / skip...); returns the chosen option |
| `ctx.emit_trace(name, x, y, kind="real"\|"complex", **meta)` | a waveform, spectrum, Bode curve... |
| `ctx.progress(done, total, message)` | progress for the user |
| `ctx.log(message, level)` | a line in the run log |
| `ctx.checkpoint()` | raise `Stopped` if the user stopped, wait while paused |
| `ctx.sleep(seconds)` | like `time.sleep`, but a stop interrupts it |
| `ctx.stop_requested`, `ctx.cancel_event` | the stop flag, for your own loops |

The framework also calls `derived(values)` for every point: return a dict of computed quantities (for
example `{"efficiency": pout / pin}`) and they are added to the point. It cannot overwrite a measured value.

## Curves, limits and RF helpers

A measurement that produces a curve (a Bode plot, S-parameters, a spectrum, a waveform) emits it with
`ctx.emit_trace(name, x, y, kind="complex", **meta)`. A sweep that is repeated emits the same `name` again; the
window shows the newest. The `meta` keys that the run window understands (all optional):

| key | meaning |
|---|---|
| `xlabel`, `ylabel` | axis titles (`ylabel` is used for a real trace) |
| `x_unit` | unit of x, for the tick labels: `"Hz"` gives `1 MHz`, `2 GHz` |
| `log_x` | `True`: the x axis starts logarithmic (frequency sweeps) |
| `limits` | `{"view": "loss_db", "min": [[f, v], ...], "max": [[f, v], ...]}`: limit lines, dashed in red, drawn when the window shows that view |

A **complex** trace can be shown as magnitude (dB), loss (dB, positive), phase, real part, imaginary part, or on
the **Smith chart**. The window exports a trace to CSV and the S-parameters (traces called `S11`, `S21`, `S12`,
`S22`) to Touchstone (`ola.runs.export_trace_csv`, `ola.runs.export_touchstone`).

Helpers, so that a module does not rewrite them: `ola.rf` (dB, insertion and return loss, VSWR, impedance from the
reflection coefficient, group delay, velocity factor, a curve at one frequency, level crossings, Touchstone files)
and `ola.limits` (`parse_limits({"max": 1.5})` -> `check(freq, y)` gives a pass / fail `Verdict`, and
`lines(freq)` gives the limit as curves to put in `meta["limits"]`).

## An editor with no code: `form.json`

A module that puts a `form.json` next to its `module.json` gets an editor window for its files with no code of its
own (`frontend/ui/FormEditorDialog.py`, opened by *Edit* in the project window). The form lists the fields:

```json
{"sections": [
  {"title": {"en": "Sweep", "it": "Sweep"},
   "fields": [
     {"path": "sweep.start_hz", "kind": "number", "unit": "Hz", "label": {"en": "Start frequency", "it": "Frequenza iniziale"}},
     {"path": "sweep.scale", "kind": "choice", "label": "Spacing",
      "choices": [{"value": "linear", "label": "Linear"}, {"value": "log", "label": "Logarithmic"}]},
     {"path": "termination", "kind": "choice", "visible_if": {"path": "mode", "equals": "reflection"}, "choices": [...]}]}]}
```

* `path`: where the value is in `params` (`sweep.start_hz`); for a field of kind `instrument` it is the name of a
  **role**, and the file records the instrument chosen for it (`role_bindings`). A required role with no
  instrument is an error at its field.
* `kind`: `text`, `number`, `int`, `bool`, `choice`, `numlist` (a list of numbers), `json` (an object typed as
  JSON, for what has no field of its own: limits), `instrument`. Numbers can be typed with an SI prefix
  (`433M`, `2.4 GHz`); an empty field means "not given" and removes the key.
* `label`, `help`, `placeholder`, the `title` of a section and the `label` of a choice are a text or
  `{"en": ..., "it": ..., "fr": ..., "es": ..., "de": ...}` (the language of the application, then English).
* `visible_if`: `{"path": ..., "equals": ...}` or `{"path": ..., "in": [...]}`: the field is shown only then.

The **problems** shown at each field are the ones the module reports itself: give the measurement a method
`check()` that returns `ola.efficiency_spec.Problem(path, message, severity)` for every wrong thing (`severity`
`"error"` stops the measurement, `"warning"` does not), and make `validate()` return the errors as sentences. A
module with only `validate()` still works: its problems are listed without a field. A built-in module may also
define `default_params()` in `measurement.py`: the starting point of a new file. The model behind the window is
`ola/form_model.py` (`FormModel`), tested without a screen.

## A connection diagram: `wiring.json`

A module that puts a `wiring.json` next to its `module.json` has a **connection diagram**: how the instruments and the
device under test are connected. It is shown before the measurement starts (a window with *Start* and *Cancel*, which
the user can turn off with a tick) and by the *Connections...* button of the project window. The file is data, so it
is updated with the module; see [`wiring.md`](wiring.md) for the format. Add `"when": "scope.channel"`-style
conditions to show a part only when the parameters ask for it, and `{path|default}` to write a parameter into a text.

## Rules

* **Call `ctx.checkpoint()` or `ctx.sleep()` in every loop.** A loop that never does cannot be stopped or paused.
* **Do not catch `Stopped`** (nor a bare `except:`); put cleanup in `teardown`.
* **`teardown` must be safe to run at any point**, even if `setup` never finished: it can run after an
  error in the first call. Do not assume the outputs are on.
* **`validate()` has no I/O**: it only checks the parameters. If it returns problems, nothing is sent to any instrument.
* **No windows, no files, no sockets** in a module: results go through `ctx`, the framework stores them.
* A raised exception fails the run (state `failed`, with the traceback); the data already emitted is kept.

## Trying it without hardware

A handle is any object with a `name` and a `call(name, **args)` method, so a fake is three lines:

```python
from ola.registry import ModuleRegistry
from ola.runner import Runner

registry = ModuleRegistry([("path/to/modules", False)])
registry.discover()
measurement = registry.create("dc_check", {"voltages": [1, 2]}, allow_user_code=True)
runner = Runner(measurement, {"psu": [MyFakeHandle("psu1")]})
runner.start(); runner.join()
print(runner.state, [e.data["values"] for e in runner.drain() if e.kind == "point"])
```

`allow_user_code=True` is required for any module that is not built in: loading it runs its code, so the
program asks the user first. Finding modules (`discover()`) never runs any code.

## Checklist for a new module

1. Folder with `module.json` and the entry file; unique `id` and `extension`.
2. `validate()` for every parameter; `teardown()` that leaves the instruments safe.
3. `ctx.checkpoint()` / `ctx.sleep()` in the loops.
4. A test with a fake handle (see `tests/test_time_log.py`): normal run, a failing read, and a stop.
5. Add it to the README table if it is built in (`ola/modules/<id>/`).
6. A `wiring.json` if the measurement needs instruments connected to something ([`wiring.md`](wiring.md)).
