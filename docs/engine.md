# The engine: how a measurement runs

This page explains how the pieces of `ola/` fit together, what happens during a run and which
guarantees you can rely on. The one-page overview is in the [README](../README.md#engine-ola-and-native);
to write a measurement see [measurement-modules.md](measurement-modules.md); for instrument
calls, steps and transports see [instrument-calls.md](instrument-calls.md).

The engine has **no Qt dependency**: `import ola` works without PyQt6, so everything here can be
used from the GUI, from scripts and from tests.

## The layers

```
measurement module        ola/modules/<id>/measurement.py   what to measure
   |  handle.call("set_voltage", value=5)                    logical calls, never SCPI
   v
Runner                    ola/runner.py                      thread, stop/pause, events
   v
instrument layer          ola/instrument.py, ola/steps.py    steps under one lock per instrument
   v
transport                 ola/transport.py                   TCP / serial (Rust or Python)
                          ola/_visa.py                       USB-TMC / GPIB / VXI-11 (pyvisa)
```

A *measurement* never touches a socket or a command string. It asks an **instrument handle** for a
logical call (`set_voltage`, `read_current`, ...) and gets a logical value back. The handle turns the
call into *steps* (write / query / read / delay), the **instrument layer** runs them, the
**transport** moves the bytes. Each layer can be replaced or simulated on its own, which is how
the tests work without hardware (`ola/sim.py`).

## Life of a run

```
Runner(measurement, {role: handle}, stop_event=...)
  start()                          checks, then starts the thread
     1. every required role has an instrument, no unknown role, none too many
     2. measurement.validate() returns no problem
        -> otherwise MeasurementError and NOTHING has been sent to any instrument
  thread:
     state RUNNING
     measurement.setup(ctx)        bring the instruments to the initial state
     measurement.run(ctx)          the measurement; ctx.emit_point / emit_trace / progress / log
     measurement.teardown(ctx)     ALWAYS, also after an error or a stop
     state FINISHED | STOPPED | FAILED
```

### States

| State | Meaning |
|---|---|
| `idle` | created, not started |
| `running` / `paused` | normal operation; `pause()` takes effect at the next checkpoint |
| `waiting` | the measurement asked the user a question and waits for `answer()` (see below) |
| `stopping` | `stop()` was called, the run is winding down |
| `finished` | `run()` returned normally |
| `stopped` | the user stopped it (also when a stop interrupted an instrument call, or the operator pressed Cancel in the prompt of a manual instrument: error code `CALL-006`) |
| `failed` | `setup` / `run` / `teardown` raised; see `runner.error` |

`finished`, `stopped` and `failed` are final. A `Runner` is **single use**.

### Guarantees

* `teardown` runs after every outcome. If both `run` and `teardown` fail, both errors are kept
  (`runner.error`, the first one in the fields, the second one in `error["also"]`).
* `ctx.checkpoint()` and `ctx.sleep()` do not raise inside `teardown`, so cleanup is never cut short
  by the stop request that caused it.
* A stop is cooperative: it is honoured within about 50 ms at a `checkpoint()` / `sleep()`, and it
  also interrupts a long `delay` *inside* an instrument call if the handle was built with the
  runner's stop event (see below). A loop that never calls `checkpoint()` cannot be stopped.
* A broken listener (for example a GUI slot that raises) never stops the measurement.
* `derived()` can add computed values to a point (for example efficiency) but can never overwrite a
  measured key; if it raises, the point is recorded without them and a warning is logged once.

### Asking the user

A measurement can stop and ask, for example when an instrument does not do what it was told:

```python
choice = ctx.ask("vin differs by 20%", ["retry", "abort", "skip"], default="abort",
                 data={"variable": "vin", "error_rel": 0.2})
```

The runner goes to the `waiting` state and publishes a `question` event; the interface shows it (a pop-up
with one button per choice) and calls `runner.answer(question["id"], choice)`. `runner.pending_questions`
lists the open ones for an interface that was not listening yet. `answer()` refuses a choice that is not
offered (`ValueError`) and an unknown id (`MeasurementError`). If the user stops the run while the question
is open, the run ends as `stopped`; nothing stays blocked. The question and the answer are written in the run
file, so the data says what was decided.

For scripts and tests without a user: `Runner(..., unattended="skip")` answers every question at once with
that choice (or with the question's default if it is not offered).

### Stop and the shared event

Instrument handles are built before the runner, so the stop event is created by the caller and shared:

```python
cancel = threading.Event()                       # one per run
handle = InstrumentHandle(..., cancel=cancel)    # passed to Instrument.run on every call
runner = Runner(measurement, {"psu": [handle]}, stop_event=cancel)
```

`runner.stop()` sets it. `ctx.cancel_event` and `runner.stop_event` are the same object.

## Events

Everything a run reports is an `Event(kind, data, t)`. Listeners are called **in the runner thread**;
a GUI must hand the event to its own thread (for example a Qt signal, or `runner.drain()` from a
timer when `collect=True`).

| `kind` | `data` |
|---|---|
| `state` | `state`, `run_id` |
| `point` | `table` (`points` by default), `index` (row number in that table), `elapsed_s`, `values` (for `points`: measured + derived) |
| `trace` | `name`, `trace_kind` (`real` / `complex`), `x`, `y`, `meta`; complex `y` are `[re, im]` pairs |
| `progress` | `done`, `total`, `message` |
| `log` | `level` (`info` / `warning` / `error`), `message` |
| `error` | `phase` (`run` / `teardown`), `type`, `message`, `code`, `traceback` |
| `question` | `id`, `text`, `choices`, `default`, `data` (see "Asking the user") |
| `answered` | `id`, `choice`, `auto` (true if given by an unattended run) |

## Files

### Run file (`ola/runs.py`)

Results are written **while the measurement runs**, one JSON object per line (JSON Lines), so a crash
loses nothing. `RunWriter` is a listener; `read_run()` reads a file back (it tolerates a truncated last
line) and `export_points_csv()` writes the rows of one table to CSV. A measurement can keep several
tables of rows (`ctx.emit_point(values, table="samples")`); `"points"` is the main one, the others come
back from `read_run()` under `run["tables"]`; `run["questions"]` has the questions and the answers.

```
{"kind": "run",   "run_id": ..., "measurement": ..., "module_version": ..., "params": {...}, "bindings": {...}}
{"kind": "point", "table": "points", "index": 0, "elapsed_s": 0.5, "values": {...}, "t": ...}
{"kind": "trace", "name": "ch1", "trace_kind": "real", "x": [...], "y": [...], "meta": {...}, "t": ...}
{"kind": "log" | "error", ...}
{"kind": "question", "id": ..., "text": ..., "choices": [...], "data": {...}}
{"kind": "answered", "id": ..., "choice": "retry", "auto": false}
{"kind": "end",   "state": "finished" | "stopped" | "failed", "error": null | {...}}
```

A file without the final `end` line is an interrupted run. Traces are stored inline as JSON; very long
waveforms will get a binary sidecar later.

### Project (`ola/project.py`)

A project has several measurements, **one file per measurement**; the file extension identifies the
type (`.tlg` for the time log), so files can be recognised, copied and deleted one by one.

```json
{"format_version": 2, "project_name": "Pippo", "inst_file": "pippo.inst",
 "measurements": [{"id": "m1", "type": "time_log", "name": "Temperatures", "file": "temperatures.tlg"}]}
```

Each measurement file holds `type`, `module_version`, `api_version`, `role_bindings` (role to instrument
name or list of names) and `params`. File names in a project must be plain names; a name with a path
(`../x`) is rejected. Keys the program does not know are kept when the project is saved. The old
`eff_files` / `was_files` format is **not read** (decision recorded in `PLAN.md`).

## Errors

| Code | Raised by | Meaning |
|---|---|---|
| `TRN-001`..`TRN-006` | transport | connect, I/O, timeout, closed, protocol, invalid argument (see `ERROR_CODES.md`) |
| `CALL-004` | instrument layer | a step of a call failed; carries `call`, `step_index`, `cause` |
| `MeasurementError` | runner / registry / project | a measurement cannot start: bad parameters, missing role, unknown type |

Every exception has a `code` attribute where it makes sense; the runner copies it into `runner.error`.

## Testing without hardware

* `ola.sim.SimTransport(responder)` records what is sent and answers through a function.
* Measurements are tested with a fake handle (an object with `name` and `call(name, **args)`), see
  `tests/measurement_helpers.py`.
* `tests/fake_instrument.py` is a scriptable fake instrument on a real TCP socket or a pseudo-terminal.
* `pytest tests` runs everything, once with the native transport and once with `OLA_TRANSPORT=python`
  (CI should do both).

## The run window

`frontend/ui/RunWindow.py` runs a `Runner` and shows it live. As with the efficiency editor it is split in two:
`ola/run_view.py` (`RunModel`) follows the events and decides what is shown, so it is tested without a screen;
the window only draws it. A timer takes `runner.drain()` every 100 ms.

* **Top:** the state (ready, running, paused, *waiting for your answer*, finished, stopped, failed), a progress
  bar, the time elapsed and an estimate of the time left (time spent waiting for the user is not counted), and
  the buttons Start, Pause / Resume, Stop and Export CSV. If the measurement cannot start (an instrument is
  missing, the parameters are not valid) the reasons are shown and nothing is sent to any instrument.
* **Results:** the table of points, growing while the measurement runs.
* **Plot:** any numeric column against any other, with one line for each value of a third column (by
  default: efficiency against the fastest sweep, one line per slower parameter). Drawn with `QPainter`, so it
  follows the dark or light theme and needs no extra library.
* **Log:** messages, warnings and errors.
* **Questions:** when the measurement asks something (`ctx.ask`) a pop-up shows the question with one button per
  choice; the safe choice (for example *abort*) is the default and is in bold. The pop-up cannot be closed
  without an answer; if the run is stopped meanwhile it closes by itself. The answer goes to `runner.answer`.
  Closing the window while the run is going asks first, then stops the run.

`python -m frontend.ui.RunWindow` runs an efficiency measurement on the simulated lab of `ola/demo_lab.py`
(`--fault` makes the data logger disagree with the supply for a few readings, to see the pop-up). Strings are
in `frontend/lang/modules/run/<lang>.json`.

## Not done yet

The measurement modules other than `time_log` and `efficiency`, opening the editor and the run window from the project window ("Avvia misura"), the driver system
for Analog Discovery, the serial-text step fields for the LiteVNA67 (`until`, `lines`, `size`, `flush`)
and the retirement of the old C backend. The plan and the status are in [`PLAN.md`](../PLAN.md).
