# PLAN – Open Lab Automation as a generic measurement platform

Status: **draft** (2026-11-02). Items marked ❓ are still to be decided.

## 1. Goal

Move from "remote instruments + one efficiency measurement" to a generic
software in which:

- a **project** contains **several measurements** of different types (e.g. project "Pippo":
  efficiency + transient response + ripple);
- each measurement has **its own file**, with an extension that depends on the type;
- measurements are **modules**: some built in, others written by the user;
- efficiency remains the reference measurement (the project was born for it), but today it is
  **not yet validated on hardware** → it must be tried, not only ported.

Decisions already taken:

- **No backward compatibility** with the old `.eff` / `.was` / existing projects
  (the software is not in use yet). The format can be changed freely.
- Modular architecture: built-in base modules + user modules.
- **One file extension for each measurement type** (easy to recognise, copy, delete).
- **Minimum latency**: evaluated with a benchmark (see §4); orchestration in Python,
  native layer (Rust) for the transport.
- **Modules never speak SCPI**: they ask a generic instrument for actions
  ("supply → 20 V, ON") and the software translates them into the correct commands,
  with limit checks (§5).

## 2. Vocabulary

```
Project ─┬─ Instruments (.inst)             ← shared by all measurements
         ├─ Measurement "Efficiency" (.eff)  ┐
         ├─ Measurement "Transient" (.ltr)   ├─ each = instance of a measurement Type (module)
         └─ Measurement "Ripple" (.rpl)      ┘
                └─ Run (execution) ─ Points / Waveforms / Traces
```

- **Measurement type** = a module (code + parameter schema + editor).
- **Measurement** = configured instance of a type, saved in its own file.
- **Run** = a single execution of a measurement, with the data it produces.

## 3. Project format (new)

> **Implemented** in `ola/project.py` (description: `docs/engine.md`). Differences from this
> initial schema: the project file also has `"format_version": 2`; the old format
> (`eff_files`/`was_files`) is rejected with a clear error; file names
> must be simple names (no paths, `..` is rejected).

The project JSON replaces the `eff_files`/`was_files` lists with:

```json
{
  "project_name": "Pippo",
  "inst_file": "pippo.inst",
  "measurements": [
    {"id": "m1", "type": "efficiency",     "name": "Efficiency",  "file": "efficiency.eff"},
    {"id": "m2", "type": "load_transient", "name": "Transient",   "file": "transient.ltr"}
  ]
}
```

Each measurement file has a common header
(`type`, `module_version`, `api_version`, `role_bindings`) and a `params` body
defined by the module. Today's global `control_variables`/`measure_variables`
become the responsibility of each individual measurement.

## 4. Latency and layered architecture

### 4.1 Measurement on the current code (loopback, fake SCPI instrument, 300 queries)

| Implementation | Median | Max |
|---|---|---|
| Current C backend (`send` command + `send` "\n", without `TCP_NODELAY`) | **44 000 µs** | 67 ms |
| Pure Python, same scheme (2 `send`, without `TCP_NODELAY`) | **44 000 µs** | 72 ms |
| Pure Python, 1 `send` + `TCP_NODELAY` | **32 µs** | 0.7 ms |

Conclusions:

1. The bottleneck is **not the language**: C and Python give the same result.
   The cost is the combination of Nagle + delayed ACK, which adds ~44 ms to every
   query. It is a bug of the current backend (`instrument_send` makes two `send` calls and lacks
   `TCP_NODELAY`): fixing it gains a factor of ~1000.
2. With the correct transport, Python's overhead is tens of µs. On a real
   instrument a query costs 1–50 ms (network + measurement time / NPLC): the host language
   accounts for less than 1 % of it.
3. Where the language really matters: **jitter** (GIL, GUI thread, GC) when two
   actions must happen at a controlled time distance, and **throughput** in
   fast streaming/logging. For these, native code with its own thread, without the
   GIL, is needed. For true synchronisation, however, the best solution remains
   **delegating to the instrument** (hardware trigger, buffer, list mode), not to the host.
4. The current C backend only does raw TCP: USB, GPIB and serial (mentioned in the README) do not
   exist in the backend, and the SCPI commands of the sweep are hardcoded instead of coming from the
   library. The state is global and not thread-safe.

### 4.2 Choice: hybrid Python + Rust (✅ decided)

| Layer | Language | Task |
|---|---|---|
| Measurement modules, runner, UI | Python | Measurement logic, no tight timing constraints |
| Generic instrument + limits; SCPI translator **or** driver (§7.1) | Python (first version) | Driven by the library, easy to extend |
| Transport (TCP/LXI, then USB, serial, GPIB/VISA) | **Rust** | `TCP_NODELAY`, a single write, buffered reads, timeouts, thread-safe |
| Sequence executor | **Rust**, *not planned* (see §4.3) | Compiled sequence run in a native thread without the GIL; to be reconsidered only if a real case emerges |

Why Rust instead of C: the existing C code is small (≈430 lines) and must be rewritten anyway;
Rust gives memory and thread safety, ready-made crates for serial/USB, and precompiled
wheels (maturin/PyO3) that spare the user from installing a compiler
(today `gcc` is needed). Cost: contributors must be able to read Rust.
The former C backend was replaced by the Rust transport and removed (`backend/` and
`frontend/core/c_backend.py`, 2026-11-10).

Until the native layer exists, the transport can be Python (`socket`
with `TCP_NODELAY`, or `pyvisa` for USB/GPIB). The `Transport` interface is unique, so the
replacement is transparent for the modules.

### 4.3 Critical case: load impulse tests

The only case with tight timing, for now, is the load impulse/step test
(transient module, `.ltr`, and the Pulse Generator). Reasoning:

- The impulse **is not generated by the host**: the electronic load produces it internally
  (dynamic mode: levels, frequency, duty, rise/fall). The host does not have to switch
  anything at a given time, so Python's jitter does not affect the shape of the impulse.
- The timing that matters is between **load and scope**. It is obtained with the
  oscilloscope trigger on the edge (output voltage, current probe or the load's trigger
  output), not with software synchronisation.
- The host is left only with the **order of operations**, which tolerates latencies of ms:
  configure the load (dynamic, still off) → configure and arm the scope →
  wait for "armed" → enable the load → wait for the acquisition → read the waveform.
- For a single step (not periodic) the method is the same: scope in
  single-shot, armed, then step. If the load has no suitable step/dynamic mode,
  it is a limit of the instrument, to be declared in the library as a missing capability
  (and the module rejects the measurement with a clear error).

Conclusion: **no native sequence executor is needed**. Rust is limited to
transport (low latency for queries/waveforms, thread-safe). It will be reconsidered only if a
future module really requires software actions at a controlled time.

**Development rule:** optimise with numbers. A benchmark of latency and jitter is added to the repository (like the one above, plus a simulated instrument), and only what the benchmark shows to be insufficient is moved to native code.

## 5. Module system

> **Implemented** in `ola/measurement.py`, `ola/runner.py`, `ola/registry.py`; guide for
> those who write a module: `docs/measurement-modules.md`. Differences from the initial design
> below: `validate(self)` takes no arguments (it uses `self.params`); the roles are objects
> `Role(name, category, required, multiple)` read from `module.json`, not a map of
> `Capability`; stopping is checked with `ctx.checkpoint()` / `ctx.sleep()` (not
> `should_stop()` / `pause_point()`); the manifest has `entry` (`file.py:Class`); the folder of the
> built-in modules is `ola/modules/` (not `frontend/measurements/builtin/`); `schema.json` and
> `editor.py` do not exist yet (`params_schema` is in the manifest and is not applied).

### 5.1 Structure of a module

```
mymodule/
  module.json     # manifest: id, name, version, api_version, file extension (UNIQUE),
                  #           required instrument roles, Python dependencies
  measurement.py  # class implementing the Measurement interface
  schema.json     # parameter schema → editor generated automatically
  editor.py       # (optional) custom Qt editor
```

**Extensions:** each measurement type has its own (`.eff` efficiency; proposals: `.bode`,
`.rpl` ripple, `.ltr` transient, `.tlg` logging, `.spc` spectrum, `.vna`). The
registry rejects two modules with the same extension; user modules must
declare their own.

Search locations:

1. `frontend/measurements/builtin/` – built-in modules;
2. user folder (e.g. `~/.open_lab_automation/modules/`);
3. `modules/` inside the project (modules specific to that project).

### 5.2 `Measurement` interface

```python
class Measurement:
    required_roles: dict[str, Capability]   # e.g. {"generator": "awg", "scope": "scope"}
    def validate(self, params, bound_instruments) -> list[ValidationError]
    def setup(self, ctx)            # configure instruments, safe initial state
    def run(self, ctx)              # measurement loop; uses ctx.emit_point / ctx.emit_trace,
                                    # checks ctx.should_stop() / ctx.pause_point()
    def teardown(self, ctx)         # ALWAYS called: puts the instruments back in a safe state
    def derived(self, data)         # computed quantities (efficiency, etc.)
```

The `ctx` (context) is provided by the framework: access to instruments, data output,
progress, log, cancellation. The module does **not** open windows nor write
files directly.

### 5.3 Generic instrument, roles and capabilities (the key point)

**The module knows neither SCPI nor the model.** Python (module) → generic API →
OpenLab translates into SCPI from the library **or** passes the call to a driver
(§7.1) → transport:

```python
psu = ctx.instrument("psu")        # role → real instrument from the .inst
psu.set_voltage(20.0)              # OpenLab: checks limits, translates, sends
psu.output(True)
v = dmm.measure_voltage()
```

If the value exceeds the instrument's limits (e.g. 20 V on a 15 V supply)
OpenLab **sends nothing** and raises an error with a standard code
(`[INST-xxx]`, to be added to `ERROR_CODES.md`), which the runner shows and which sends
the measurement to `teardown()`. The module cannot bypass the limits.

A measurement does not say "use the Keysight 34972A": it says "I need a *function
generator*, an *oscilloscope*". The user assigns the roles to the instruments of the
`.inst`. Instruments declare their **capabilities** in the library (e.g.
`awg`, `scope`, `dmm`, `psu`, `eload`, `spectrum`, `vna`, `power_meter`), with
the SCPI commands defined by the library (as today) or, for proprietary
instruments, with a driver (§7.1).
In this way the same module works with different instruments, and a new instrument
is added only by extending the library.

### 5.4 Safety of user modules

A user module is arbitrary Python code that drives hardware: it must be
declared explicitly (warning on first load, list in
Settings, option to disable them). The framework guarantees
`teardown()` even in case of error/stop, and the safety limits of the
instruments (max V/I/P from the library) are applied in the instrument layer,
not left to the module.

### 5.5 UI

- "Add measurement" dialog that lists the available types.
- Generic editor generated from `schema.json` (fields, ranges, units, validation).
- A single **Run** panel for all types: start/stop/pause, progress,
  live chart, data table, export.

## 6. Planned measurements

| # | Measurement | Instruments (roles) | Notes |
|---|-------------|---------------------|-------|
| 1 | **Efficiency** (built in) | PSU/source, eload, DMM/datalogger (or power meter) | Nested sweep as today. **To be validated on hardware.** |
| 2 | **Bode plot** | AWG + scope, or VNA | Frequency sweep, gain/phase. With injection for loop gain; direct VNA mode. |
| 3 | **Ripple and noise** | Scope (opt. spectrum analyzer) | Bandwidth limited to 20 MHz, p-p, RMS, ripple spectrum. |
| 4 | **Logging over time** | Datalogger/DMM/thermocouples | Several channels, configurable interval, incremental writing, live chart. |
| 5 | **Load transient response** | Eload (dynamic) + scope | Reuses the logic of the Pulse Generator; measures overshoot/undershoot and settling time. |
| 6 | Spectrum / emissions | Spectrum analyzer | Traces, markers, peak search. |
| 7 | Network analysis (S-param) | VNA | S11/S21, Touchstone export. |

Next candidates (low cost, reusing the same building blocks): line and load regulation,
PSRR, output impedance, I-V curve, power-on/power-off sequence.

## 6b. RF measurements and roadmap

Decisions of 2026-11-03 (discussion with the user):

- **A real module for each measurement**, separate and updatable separately (no "does-everything" module
  with modes). The common functions live in shared libraries without Qt (`ola/rf.py`...), not in the modules.
- **Measurements with the VNA** (the VNA arrives calibrated from the user, who calibrates on the instrument;
  the module only shows a reminder "is the VNA calibrated?" with Continue/Cancel). The reasoning is general,
  not about the limits of a single VNA: 1. **cable characterisation** (S21 as the main mode, S11 with
  open/short as the second: loss in dB, values at chosen frequencies, dB/m, group delay and velocity
  factor, check against a limit); 2. **return loss / VSWR**; 3. **filter** (passband, -3 dB cut-off,
  ripple, out-of-band attenuation, Q); 4. **antenna impedance** (Z = R + jX, Smith chart,
  resonance, band at VSWR < 2).
- **Common pieces to do first**: measurements that produce curves (traces) in the run window;
  trace chart (logarithmic X axis, amplitude/phase/Re/Im, several curves, markers, limit lines,
  **Smith chart**); **CSV export of the traces and Touchstone** (`.s1p`/`.s2p`); RF calculation
  functions (dB, VSWR, impedance, group delay); pass/fail verdict with limits per
  frequency or band; one editor for each measurement type (today only efficiency).
- **Order**: 1. common pieces; 2. cable; 3. return loss, filter, antenna; 4. (measurement models:
  line/load regulation, I-V curve); 5. ripple, Bode, transient; then spectrum, battery discharge.
- **Report**: for now only **CSV** (and Touchstone). An **HTML report saveable as PDF, with a
  customisable template**, is postponed until the measurements work and the software is in beta (entry
  in the "Future features" section of the README).
- **Comparison of results** (e.g. two cables): not inside the measurement, but as a **tool in the Tools menu**
  (like the Hex/Dec converter): two results are chosen and overlaid.
- **Cable label** (tool in the Tools menu): generate a label template to print with the data that
  identify the cable, to link each measurement to its cable. To be designed **after** the measurements
  of section 3 (return loss, filter, antenna).
- **Measurement models** (pre-filled files chosen from "New measurement"): line/load regulation and I-V
  curve are the efficiency module with other formulas; battery discharge requires a stop condition
  (minimum voltage) which the module does not have today.

Instruments still missing: `vna` category in the library (LiteVNA67 data pending; starting with a
simulated VNA), function generator and spectrum analyser categories, drivers for Analog Discovery,
testing any measurement on real hardware.

## 7. New instruments to add to the library

High priority (needed for measurements 2–7):

- **Function generator / AWG** – essential for Bode and transients.
- **Spectrum analyzer** (required).
- **VNA** (required).

Medium priority:

- **Standalone bench multimeter (DMM)**, in addition to the datalogger.
- **Power meter / power analyzer** (Yokogawa WT, etc.): true power measurement
  for a more accurate efficiency measurement, especially on AC / distorted waveforms.
- **Source-Measure Unit (SMU)**: I-V curves, characterisation.

Low priority / future:

- **LCR meter / impedance analyzer** (characterisation of capacitors and inductors).
- **Programmable AC source**.
- **Frequency counter**.
- **Relay matrix / multiplexer** (several measurement points with a single instrument).

### Categories to add to the library (✅ approved list)

Today the library has: `power_supplies`, `dataloggers` (+ `datalogger_modules`), `switch_units`,
`multimeters`, `oscilloscopes`, `electronic_loads` (keys `*_series`). Proposal of new
categories, each with its own **set of generic actions** (the "verbs" that
the modules will use, mapped to SCPI in the library) and its own declared **limits**:

| Category | Generic actions (examples) | Declared limits |
|---|---|---|
| `function_generator` | waveform, frequency, amplitude, offset, output on/off, 50 Ω/HiZ load, sweep, burst | max Vpp, max f |
| `spectrum_analyzer` | centre/span, RBW/VBW, reference level, trace, marker, peak search | f range, max input level |
| `vna` | f start/stop, points, IFBW, power, S parameter, calibration, complex trace | f range, max power |
| `multimeter` | function (V/I/R…), range, NPLC, trigger, reading | range per function |
| `power_analyzer` | V/I/P/PF, integration, range, filter | max V/I |
| `smu` | force V/I, compliance, measure V/I, sweep | max V/I/P |

Lower priority, but to be created as categories anyway: `lcr_meter`,
`ac_source`, `frequency_counter`. (`multimeter` and `switch_matrix` already exist in the
library as `multimeters_series` and `switch_units_series`.)

**For now only categories, no instrument in the library:** the categories are created
empty. Exceptions, as a test bench (§7.1): the **LiteVNA67** (category `vna`) and,
later, the **Analog Discovery 2** (composite device).

### 7.1 Non-SCPI instruments: LiteVNA67 (commands over serial) and Analog Discovery 2/3 (driver)

Many hobbyist instruments are not SCPI. They are a primary target of the project and
fall into two different cases:

1. **LiteVNA67** (same protocol as the LiteVNA64): it is controlled with **strings over
   serial**. It is compatible with the current structure of the library (like the
   HP datalogger with serial interface): for each action the library contains the
   string to send. No driver is needed.
2. **Analog Discovery 2 and 3** (Digilent): they are driven only with the **WaveForms SDK**
   (runtime installed on the PC), not with text commands. For these a
   **driver** is needed. The same driver family for AD2 and AD3.

> To be verified in the field: the real protocol of the LiteVNA67 (text and/or binary; the
> author will send VID/PID and information) and the functions of the WaveForms SDK.

#### Two access modes

(Vocabulary agreed with the library/planner session: `access` = `scpi` | `driver`. `scpi` means "text step plan run by the generic executor" and also covers non-SCPI text protocols such as the LiteVNA.)

| `access` | Who speaks to the instrument | What the library describes | Examples |
|---|---|---|---|
| `scpi` | OpenLab's generic translator | Table verb → string to send (SCPI or not), transport (LAN, serial, …), how to interpret the answers, limits | SCPI instruments, HP serial datalogger, **LiteVNA67** |
| `driver` | **A driver** (code, one per family) | Identity, capabilities, limits, detection, **driver name** | **Analog Discovery 2/3** (WaveForms family) |

The key point: **in both cases the measurement module sees the same interface**.
The command translator and the drivers implement the same contracts per category
(`PowerSupply`, `Scope`, `FunctionGenerator`, `Vna`, …):

```python
class Vna(Protocol):                       # contract of the "vna" category
    def set_sweep(self, f_start, f_stop, points, ifbw=None, power_dbm=None): ...
    def read_sparam(self, name: str) -> ComplexTrace: ...   # "S11", "S21", ...
```

The command translator generates strings (SCPI for an oscilloscope, the commands of the
LiteVNA for the VNA); the AD2 driver calls the SDK. The module writes
`vna.read_sparam("S21")` and that is all.

#### Where things live

- **Library (JSON, data only, no code):** identity, categories/capabilities,
  declared limits, detection rules (USB VID/PID, port name) and, for `driver`,
  the **driver id**. For `scpi`: the strings and the rules for interpreting the answers. A data repository must not be able to run code on the user's PC.
- **Drivers (Python code), only for the instruments that need them:** in this repo (`frontend/drivers/`, built in) or in
  a user folder. They use **the same mechanism as the measurement modules**
  (manifest, `api_version`, registry, warning for third-party code): the system has two
  kinds of module, *measurement* and *driver*.
- If the library cites a driver that is not installed, the instrument appears as **not
  supported** with a clear message, not as a runtime error.

Example of an `scpi` entry (LiteVNA67 over serial, indicative schema):

```json
{
  "id": "litevna_67", "name": "LiteVNA67", "access": "scpi",
  "connection": {"transport": "serial", "usb": {"vid": "TODO", "pid": "TODO"},
                 "baud": "TODO", "terminator": "TODO"},
  "capabilities": {
    "vna": {"f_min_hz": "TODO", "f_max_hz": "TODO", "points_max": "TODO"}
  },
  "commands": {
    "vna.set_sweep": "TODO  (command with placeholders {f_start} {f_stop} {points})",
    "vna.read_sparam": {"send": "TODO", "parse": "complex_lines"}
  }
}
```

Example of a `driver` entry (Analog Discovery, indicative schema):

```json
{
  "id": "analog_discovery_2", "name": "Analog Discovery 2", "access": "driver",
  "driver": "digilent_waveforms",
  "requires": ["WaveForms runtime"],
  "capabilities": {
    "scope": {"channels": 2, "...": "from datasheet"},
    "function_generator": {"channels": 2, "...": "from datasheet"}
  }
}
```

Limit of the `scpi` model: if the LiteVNA answers are **binary** or require
parsing that cannot be described with the standard rules (float, list of floats, lines of
complex numbers, binary block with header), an extension of the answer format is needed,
or, as a last resort, a small driver. This is decided when the real answers of the device are seen.

The real values (VID/PID, ranges, points) must be taken from the device and the manual;
here they are placeholders.

#### Composite instruments: one device, several logical instruments

The AD2 is a 2-channel oscilloscope, a 2-channel waveform generator, ± power supplies, a voltmeter, digital I/O, a logic analyser, an
impedance analyser… in **a single USB device**. The library today has "one type per model":
it must be extended to **several capabilities per model**. In the `.inst` the device is inserted
once and **exposes logical instruments** (`ad2.scope`, `ad2.awg`, `ad2.psu`, …) to which the
roles of the measurements are assigned. Two rules follow:

- **Shared session:** the device is opened only once and all the logical instruments
  share it, with a lock (one device = one handle, used by only one measurement
  at a time).
- **Hardware synchronisation:** the AD2 can start scope and generator together
  (cross triggers). The capabilities expose options such as
  `scope.trigger_source = "awg"`, used by modules such as Bode and transient; for
  separate instruments the external trigger is used. This solves in hardware the
  timing problem of the impulse tests (§4.3).

#### What stays the same (and is guaranteed above the driver)

- **Limits:** the check (e.g. voltage > declared maximum) sits in the **generic
  instrument layer, above** the drivers. A driver cannot bypass it, so safety is
  identical for SCPI and for drivers.
- **Errors:** drivers raise the standard `[INST-xxx]` errors; a missing dependency (e.g. WaveForms not
  installed, serial port busy) = explicit error with instructions.
- **Automatic detection:** for USB devices `Add instrument` can list the
  connected ones (VID/PID, WaveForms `enumerate`) instead of asking for an address to be typed.
- **Simulation:** every contract has a simulated implementation to develop and
  test without hardware (already planned in Phase 0).

#### Impact on Rust

- The Rust transport serves all the `scpi` instruments (LiteVNA serial, HP datalogger
  TCP/LXI and serial): serial and binary reads are in scope from the start.
- The `driver`s that **use a third-party SDK** (AD2/AD3, WaveForms) call it
  directly (ctypes/Python binding) and do not go through the Rust transport: there is no
  byte stream to handle.

#### Test bench

The plan uses the author's two real instruments as validation of the architecture:

1. **LiteVNA67** → first `vna` instrument in `scpi` mode over serial (validates
   the format of the answers and the serial transport).
2. **Analog Discovery 2** (then 3) → first `driver`: composite instrument: `scope` + `function_generator`
   (+ `psu`/voltmeter) → allows trying **Bode**, **ripple** and **transient**
   without other hardware.

### 7.2 The existing library already defines the "verbs" (branch `claude/charming-bell-768j4j`)

Reading of the work in progress on `instruments_lib` (another agent + the author; **I do not modify
that repo until the work is merged**). What it implies for this plan:

- **The generic verbs are the call names of the library** (`COMMAND_NAMES.md`):
  `set_voltage`, `read_voltage`, `output_on`, `set_mode`, `set_trigger_level`,
  `query_waveform_data`… with *mandatory* and *optional* calls per category.
  There is no need to invent a second vocabulary: the Python contracts of the categories
  (`PowerSupply`, `Scope`, …) are a thin layer on top of these names, and for the
  `driver`s (AD2/AD3) they must implement the same names.
- **Rule of the library, to respect in the code:** the software never builds SCPI
  strings; a missing call means "not supported by this instrument", never replaced by a guessed
  string. It is translated into an explicit error `[INST-xxx]` ("call not supported"), not into an attempt.
- **Structure of a call:** `set` / `query` with `syntax` (placeholders `{name}`),
  `args`, `return_type` (`string|int|float|binary`) and `parameters` (`type`, `values`).
  `return_type: binary` corresponds to `read_block()` of the transport.
- **Per-model override** (`replace` / `null` = removed / `{"patch": …}` deep-merge):
  the resolution is in `LoadInstruments.resolve_model_commands()`. The instrument layer
  must use that resolution, not duplicate it. Today it sits in `frontend/core`, which
  imports PyQt6: it must be extracted into a module without Qt (e.g. `ola/library.py`) with
  `LoadInstruments` as a thin wrapper.
- **Limits** read from `capabilities` (e.g. `voltage_output.min/max` per channel, for power supplies; `max_voltage_v`, `max_current_a`, `max_power_w` for loads): the basis of the
  "20 V on a 15 V supply" check.
- **Calls with several commands** (in progress in the other branch: some instruments need two for the
  same action): the executor must treat a call as a **sequence of steps**, not as a string. Points to define with the other
  agent: (a) exact schema (list of steps? steps with `query`?); (b) the steps must be sent
  **atomically** (e.g. `INST:NSEL 2` then `VOLT 5`: another thread must not be able to change channel in the middle → a lock per instrument in the generic layer,
  not only per single query); (c) whether the library can indicate that the steps can be joined in a single message (separator `;`) to reduce latency, or whether
  they must always be sent separately (safe default: separate).
  Note: the removed `backend/sweep.c` did this by hand (`INST:NSEL` + `VOLT`).
- **Connection types** of the library: `LXI`, `USB-TMC`, `SERIAL`, `GPIB`, with
  VISA-style addresses. The Rust transport covers today **raw TCP (port 5025) and
  serial**. Gaps to close: **USB-TMC** and **GPIB** (via `pyvisa` as an alternative
  implementation of `Transport`, or `rusb` for USB-TMC), and the fact that
  `TCPIP0::ip::inst0::INSTR` is **VXI-11**, not a raw socket: not all LXI instruments
  accept socket 5025 (some only VXI-11/HiSLIP). The library should
  indicate which mode/port to use for each model.

The same work must be done for the existing categories: list the generic verbs that
were scattered across `RemoteControlTab` and the removed `sweep.c`.

Every new instrument requires: type + capabilities in the library, SCPI commands
in the JSON, a configuration dialog and (if needed) an extension of the `.inst` editor.

## 8. Data

- Generic `Run` model (renaming of `SweepSession`), with:
  `run_id`, `measurement_id`, `started_at`, parameters used (snapshot),
  instruments used.
- Three kinds of data besides scalar points: **time series**, **waveforms/traces**
  (scope, spectrum), **complex data** (VNA, Bode).
- Incremental saving during the run (a crash does not lose everything).
- CSV export in every case; other formats (Touchstone, xlsx) per module.
- Derived quantities as formulas between variables (e.g. `eta = Pout/Pin`).

## 9. Development phases

**Phase 0 – Base** *(done, except the efficiency regression)*
- **Immediate fix of the C transport** *(replaced by the new transport; the C code was not touched)*: `TCP_NODELAY` + a single `send` per command
  (from ~44 ms to ~30 µs per query), with tests.
- Latency/jitter benchmark in the repository and a simulated instrument (mock) to develop
  and test without hardware.
- Regression test on the current efficiency pipeline *(not done: efficiency will be rewritten)*.

**Phase 1 – Core** *(done, for the part in `ola/`)*
- `Transport` interface (Python implementation) and generic instrument layer
  (verbs → SCPI from the library, limit checks, `[INST-xxx]` errors).
- New project format (`measurements[]`), new `ProjectDatabaseManager`.
- `Measurement` interface, `Capability`, execution context, runner in a thread.
- Generic `Run` model.

**Phase 2 – Modules** *(registry done; generic editor, efficiency and Run panel still to do)*
- Module registry/loader (built-in + user + project) with manifest.
- Generic editor from `schema.json`.
- Efficiency rewritten as the first built-in module.
- Single Run panel (live, stop/pause, export).

**Phase 3 – First new measurements** *(only logging over time is done)*
- Logging over time (the simplest: validates the runner and the time data).
- Ripple and noise.
- AWG instrument in the library → Bode (with scope).
- Load transient.

**Phase 3b – Native layer (Rust)** *(done: TCP and serial; USB-TMC/GPIB go through pyvisa)*
- Rust transport (TCP, then serial/USB), exposed to Python via PyO3/maturin.
- No native sequence executor (§4.3).

**Phase 4 – Advanced instruments**
- Spectrum analyzer, VNA, RF measurements (6, 7).
- Bode via VNA.

**Phase 5 – Refinement**
- Documentation to write a module (with an example module) *(done: `docs/measurement-modules.md`, example verified by a test)*.
- Comparison between runs, reports, derived formulas.
- Validation of efficiency on real hardware.

## 9b. Progress status

- ✅ **Rust transport** (`native/`): TCP (`TCP_NODELAY`), serial, IEEE 488.2 blocks,
  timeouts with deadline, GIL released, `TRN-xxx` errors. 13 Rust tests; complete `///` documentation
  (`#![warn(missing_docs)]`, no warnings).
- ✅ **Python layer** (`ola/`): `ola.transport` uses the native module or, if absent,
  an equivalent Python implementation (same test suite on both).
- ✅ **Benchmark** (`benchmarks/bench_transport.py`), median on loopback: current C backend
  44 ms; Python 55 µs; Rust 34 µs (p99 101 µs); transfer of 1 MB: Python
  552 MB/s, Rust 2124 MB/s.
- ✅ **Step executor** (`ola/instrument.py`, `ola/steps.py`): a call is a
  list of steps `write`/`query`/`delay` (+ `timeout_ms`, `returns` float|int|string|binary)
  run under **one lock per instrument** for the whole call; stop at the first error
  → `CALL-004` with the step index; after an error the pending input is discarded;
  cancellation (`cancel`) also during a `delay`; dispatcher for the `driver` plans
  (AD2/AD3). The maps and the interpretation of the answers stay in the planner
  (other session). Simulated instrument: `ola/sim.py`.
- ✅ **pyvisa adapter** (`ola/_visa.py`): same interface as the transport, for
  USB-TMC, GPIB and VXI-11. Tested with `pyvisa-py` on sockets; **not** tested with a real VISA
  library nor on hardware.
- ✅ **Agreement with the "library/planner" session** (branch `claude/charming-bell-768j4j`):
  planner and library resolution live in `ola/` (without Qt); a single transport;
  format of the steps and of the plan agreed; item 14 (export of the plan) postponed.
  The merge order of the two branches is decided by the author.
- ✅ **Measurement core** (Phase 1, only new files in `ola/`, without Qt):
  `measurement.py` (class `Measurement`, `MeasurementContext`, roles, events),
  `runner.py` (thread: setup → run → teardown **always**; stop, pause, errors with code and
  traceback; derived values; listeners), `registry.py` (modules from `module.json`: discovery
  **runs no code**, the code of non-built-in modules is loaded only with explicit permission;
  unique id and file extension), `project.py` (project with `measurements[]`, one file per
  measurement, safe file names), `runs.py` (results written during the run, JSON Lines,
  readable even after a crash; CSV export), first module `ola/modules/time_log`
  (`.tlg`, drift-free sampling). Interface to the instruments: `handle.call(name,
  **arguments)`, to be connected to library + planner + executor (work of the other session).
- 📌 **User decisions (2026-11-03):** no backward compatibility with the old
  `.eff` (it will be rewritten and rethought: no reader nor converter) and with the old
  project format; the "Start measurement" button in the GUI will be made when the measurement types
  are defined.
- ✅ **`backend/` (C) retired** (2026-11-10): the folder, `frontend/core/c_backend.py`, its test, the
  build step of the CI and of `run.sh` were removed. `backend/sweep.c` used fixed SCPI
  (`INST:NSEL`, `VOLT`, `MEAS:VOLT?`...) against the rule "only library commands", and nothing in
  `frontend/` or `ola/` called it. The transport of `ola/` (`ola.transport`, Rust or Python) replaces it.
- ✅ **Documentation** (2026-11-03): "Engine" section in `README.md`; guides in `docs/`
  (`engine.md`, `measurement-modules.md`, `instrument-calls.md`); docstrings on all public
  elements of `ola/`; `Transport` contract (`ola/transport.py`) verified on
  all implementations. **Documentation kept aligned by tests**
  (`tests/test_docs.py`, `tests/test_transport_contract.py`): they fail if a docstring is missing,
  if a file of `ola/` is not in the README, if a `TRN-xxx` code is not in `ERROR_CODES.md`, if
  a relative link is broken or if the example of `docs/measurement-modules.md` does not work.
  Total: 201 Python tests (with the native transport and with `OLA_TRANSPORT=python`).
- ✅ **Efficiency measurement** (new `.eff`; `ola/modules/efficiency/`, `ola/efficiency_spec.py`,
  `ola/formula.py`, `ola/sweep.py`; guide `docs/efficiency.md`). User decisions (2026-11-03):
  parameters with names chosen by the user, each with a *setting* and/or *readings* (also several
  readings of the same parameter, for example from the power supply and from the datalogger); in the formulas
  `vin` is the set value and `vin@daq` the reading with that label (the choice of the reading
  is explicit); **ordered list** of parameters that can be reordered: the first one changes first and is
  the innermost sweep; for each point: wait, N readings at a chosen interval, **average of the
  readings** and formulas on the averages; if the independent reading deviates from the setting beyond the
  tolerance the measurement **stops and asks** (Retry / Cancel / Skip); validation happens
  **while the dialog is being filled in** (`validate_params`, errors with the path of the field).
  In the core: several tables of rows (`points`, `samples`), `ctx.ask` / `runner.answer`, state
  `waiting`. Tried only on simulated instruments.
  **Outputs, cooldown and power-on order** (2026-11-03): each set parameter can have an
  `output` block (calls `on`, `off` and, optionally, `state`; and `mode`): `keep_on` (default),
  `off_during_cooldown` and `always_on` ("always active"). The **cooldown** (`timing.cooldown_s`) is a
  rest of the converter **between one sweep and the next, not between points**: when the innermost sweep
  has finished its round and an outer parameter advances, the `off_during_cooldown` outputs switch off,
  it waits, then the parameters are set again and the outputs switched back on; there is no cooldown after the last
  sweep. The **power-on order** is a separate list (`power_order`, reorderable; switch-off in
  reverse order; default = order of the parameters) that **excludes** the always-active outputs: these switch on
  before everything else. If the output has a `state` call the program asks whether it is already
  on: if it is, it leaves it as is; if it is off, it switches it on; an always-active output is **never**
  switched off (neither in the cooldown nor at the end, after an error, a stop or a cancellation). A `shutdown`
  that switches it off is a validation error. An output managed by the program (to be switched off at the end of the measurement) that
  is already on at start is still switched off at the end of the measurement (user decision), but **before touching
  any instrument** a pop-up appears listing it and asks Continue / Cancel (to modify the
  file); Cancel ends the measurement as "stopped" without changing or switching off anything. The `state`
  call is needed; without it, validation warns that the check is not possible.
  **GUI, efficiency editor** (2026-11-03): Qt-free model `ola/efficiency_editor.py` (29 tests) +
  thin PyQt6 window `frontend/ui/EfficiencyEditorDialog.py` (offscreen tests with pytest-qt). Each
  field is linked to a path of the parameters; errors in red/warnings in amber on the field, list of
  problems with double click to go to the field, summary line (points, sweeps, cooldowns, time).
  Tabs: Parameters (list sortable with Up/Down), Times, Formulas, Power-on order (+ extra calls),
  File preview. Strings in `frontend/lang/modules/efficiency/{en,it,fr,es,de}.json`
  (test: same keys in all languages). Saving with errors only after confirmation.
  **GUI, run window** (2026-11-03): Qt-free model `ola/run_view.py` (`RunModel`: state,
  progress and remaining time without counting the user's waits, table, log, open questions, series
  for the charts) + thin window `frontend/ui/RunWindow.py` (Start/Pause/Resume/Stop, live table, QPainter chart without external libraries with one line for each value of a parameter, log,
  CSV export) and **pop-up for the measurement's questions** (one button per choice, the safe one is
  the default and in bold, it cannot be closed without an answer, it closes by itself if the measurement is stopped).
  Strings in `frontend/lang/modules/run/{en,it,fr,es,de}.json`. Demo with simulated instruments
  (`ola/demo_lab.py`): `python -m frontend.ui.RunWindow [--fault]`.
  **GUI, connection with the project** (2026-11-03): `ola/project_session.py` (`ProjectSession`, without
  Qt, tested) + `frontend/ui/ProjectWindow.py`: list of the project's measurements (format 2) with the
  reason if one cannot be used, New (type chosen among the modules), Edit (efficiency editor for
  `.eff`, validated JSON editor for the other types), **Start measurement** (opens the run window; results in
  `runs/` in the project folder), Rename, Remove (file kept or deleted on request), list of the runs
  with CSV export. The instruments come from the application through `connect(name) -> handle`; without it, "Start" explains that they are not connected.
  **Integration in `main_window.py`** (2026-11-03): the placeholder "Avvia Efficienza - in arrivo" is
  replaced by the **Measurements** tab (`ProjectWindow`; it does not touch the parts modified by the
  `wonderful-mccarthy` branch). The old flow (`eff_files`, list on the left) stays as it is.
  **Real `connect`** (2026-11-03): `ola/connection.py` (`ProjectConnector`, without Qt) reads the `.inst`
  and returns the handle: manual instrument (pop-up `ManualPrompter`: Done/Cancel, Cancel stops the
  measurement as "stopped", Stop closes the pop-up) or library instrument opened at its
  `visa_address` (remote mode `set_remote` for serial ones); connections kept open between the
  runs, new handle at each run with the stop event; errors in one sentence that says what to
  check. `frontend/ui/connector_setup.py` builds it for the application from the library; if the library
  or the engine is missing it gives a function that explains why. **Tried** with the real code of the
  `charming-bell` branch merged in a local worktree (45 tests + full test: project → `.inst` → library
  → simulated instrument → run finished with the data); on the branch the tests of `connection.py` are
  skipped until `ola.library`/`instrument_handle` are merged. **Not tried on real instruments.**
  Status of the branches (2026-11-03, verified): `main` contains PRs #3 and #4; PR #5 (`charming-bell`, with
  library, handle and manual instruments used by `ola/connection.py`) is open. The conflict between
  `charming-bell` and `wonderful-mccarthy` (`ci.yml`, `check_translations.py`) is resolved. This branch merges
  into `main` without conflicts: it is best to open the PR **after** PR #5, so that the tests of `connection.py` are
  not skipped.
  **Update**: PR #5 is merged into `main` and `main` is merged into this branch (without conflicts): the tests of
  `connection.py` now run (717 tests pass with the `Instruments_LIB` submodule initialised; without it,
  the library tests fail). README rows added for the files of the library session.
  **Common pieces for the RF measurements** (2026-11-03, 1st part of the roadmap §6b): `ola/rf.py` (dB, insertion and
  return loss, VSWR, impedance, group delay, velocity factor, value at a frequency, level crossings, Touchstone `.s1p/.s2p` read and write),
  `ola/limits.py` (pass/fail limits: constant, line, bands; `Verdict`), CSV export of the traces and Touchstone from a
  run file (`ola/runs.py`), traces in the `RunModel`, **"Curves" tab** in the run window
  (list with checkboxes, views module/loss/phase/Re/Im/**Smith**, logarithmic X axis, limit lines
  from the trace `meta`, reading under the mouse, export) with `frontend/ui/trace_plot.py`
  (`TracePlot`, `SmithChart`, without external libraries). **Still missing among the common pieces**: an editor for each measurement type
  (today only efficiency; the others use JSON) and the comparison tool in the Tools menu.
  **Cable measurement + module-based editor** (2026-11-03, point 2 of the roadmap §6b): module `cable` (`.cbl`):
  loss of an RF cable with a VNA (calibrated beforehand by the user) in transmission (S21) or reflection
  (S11 with open/short, loss = half), in dB and dB/m, at chosen frequencies, group delay and velocity
  factor, return loss/VSWR, PASS/FAIL verdict against a limit (a failed limit is a **result**, not
  an error). Initial question about calibration and connection (pop-up with a summary of the sweep).
  Warning if the sweep is too coarse for the cable length (the phase wraps: delay and velocity factor
  cannot be computed, the loss can; the module does not invent the number). Logical calls required from the
  VNA: `set_sweep` and `read_sparameter` (contract of the `vna` category, to be written in the library).
  `ola/sim_vna.py` = simulated VNA with a cable. **Editor without code**: `form.json` next to the `module.json`
  + `ola/form_model.py` + `frontend/ui/FormEditorDialog.py` (fields with SI prefixes, module problems
  beside each field, required role without an instrument = error, conditional fields, 5 languages): the
  other RF modules reuse it. Traces with `meta.hidden` start unselected in the Curves tab.
  **Tried only with the simulated VNA**; the `vna` category in the library and the LiteVNA67 are missing.
  **Return loss / VSWR** (2026-11-03, point 3 of the roadmap §6b): module `return_loss` (`.rtl`): S11 of a
  device (antenna, adapter...) with a VNA calibrated at the port: return loss, VSWR (capped at 100),
  impedance, best and worst match, **usable bands** where the VSWR stays below a threshold
  (the band of an antenna), PASS/FAIL verdict on the return loss (minimum limit). Editor from `form.json`.
  The parts common to the modules with a VNA are in `ola/vna_common.py` (check of sweep and common parameters,
  question about calibration and connection, `set_sweep`, reading and averaging of `read_sparameter`,
  normalisation of the data); the cable module was rebuilt on them. `rf.bands_where`; `SimVna`
  now also has a resonant antenna. **Contract of the `vna` category for the library**:
  `docs/vna-calls.md` (the two calls `set_sweep` and `read_sparameter`, shape of the answer, draft of
  `schema/vna.json`), with a test that keeps it aligned with `SimVna`. Still to do: filter, antenna
  impedance (Smith chart) and the `vna` category in the library (the other session is about to start it).
  **Filter** (2026-11-03, point 3 of the roadmap §6b): module `filter` (`.flt`): response of a
  low-pass/high-pass/band-pass/band-stop filter with a VNA (S21): insertion loss, cut-off frequency or -3 dB edges
  **relative to the peak** (or to the maximum of the given passband), bandwidth, centre, Q,
  notch depth, in-band ripple, gain at chosen frequencies, group delay, return loss
  (S11 optional) and a **pass/fail mask on the gain in dB** (minimum in band, maximum out of band;
  drawn on the dB view). An edge outside the sweep is declared in the log and omitted, not
  invented. `rf.level_crossings` (crossings with direction); `SimVna` now has a Butterworth filter
  (low-pass/high-pass/band-pass/band-stop): the figures found are compared with the filter formulas.
  Run window: the Curves tab opens by itself when the result is a curve (≤ 1 row in the
  table) and the `*_hz` columns show the unit (868 MHz). Still to do: roll-off, shape factor and
  **antenna impedance** (Smith chart), then the comparison tool and the cable label.
  **Antenna impedance** (2026-11-03, point 3 of the roadmap §6b): module `antenna` (`.ant`): S11 read
  as impedance: `R + jX` as a function of frequency, **Smith chart** as the opening view (the trace asks for
  `default_view: "smith"`), series resonances (X from negative to positive: where the antenna is
  matched) and anti-resonances, best match, usable band and fractional band, and at the chosen frequencies
  the impedance and the **series component that cancels the reactance** (capacitor if X > 0,
  inductor if X < 0). It does not design a matching network nor do port extension.
  **RF amplifier** (2026-11-03, user request): module `amplifier` (`.amp`) with a two-port VNA:
  gain (peak, flatness, -3 dB band), input and output return loss, reverse isolation,
  **stability** (K, |Δ|, μ: `rf.two_port_stability`; not unconditionally stable = warning with the bands)
  and, if requested, **1 dB compression point** from a power sweep at one frequency. **Protections**:
  low `sweep.power_dbm` (warning if missing), `input_attenuation_db`, `max_input_dbm` (a power that exceeds it is an error and nothing starts),
  initial question with the reminder about the output limits, and the source power is **restored** after the
  compression test even if it fails or is stopped. It needs S11, S21, S12, S22 (updated `vna` contract) and many `set_sweep` calls with `power`.
  `SimAmplifier` (known compression) for the tests. Not measured: noise figure, IP3, harmonics.
  **Comparison tool** (2026-11-03, requested by the user as a tool in the Tools menu, not inside
  the measurement): `ola/compare.py` (without Qt) + `frontend/ui/CompareDialog.py`. Two or more run files are chosen; each run has the name saved with it (cable/filter/device) and the date. **Curves**:
  overlaid in any view (dB, loss, phase, Smith) or **difference from the reference** (other −
  reference, only where both have data) with maximum, mean and RMS; **Summary**: the figures side by side with
  the change from the reference; **Tables**: for runs with many points (efficiency) one column
  against another. Exports CSV and PNG. Entry in the Tools menu and a *Compare...* button in the project window.
  Verified on real runs of simulated cables (the differences follow the cable length).
  Still to do: comparison with a reference sample saved in the project, and the cable label.
  **Cable label and register of cables and devices** (2026-11-04, discussed and decided with the user:
  "as you recommend, use a sign and make the general version"): `ola/assets.py` (single JSON register for all
  projects, `~/.open_lab_automation/assets.json` or `OLA_ASSETS_FILE`; codes `CBL-0042` per type, **never
  reused**; atomic writing with `.bak`; damaged file reported and not overwritten; lookup from a
  scanner `OLA:cbl-2`), `ola/labels.py` (layout in mm: single, **flag** for thin cables, **sheets** with the
  positions already used skipped; normal QR with `segno`, never Micro QR; rows that do not fit are dropped from the end **and
  reported**; SVG), `frontend/ui/label_paint.py` (preview, PNG, PDF at real size; a test checks **every
  module of the QR** in the image) and the windows `AssetsDialog` (Tools > Cables and devices: cards, scanning,
  retire/delete, history with Compare, labels), `AssetEditDialog`, `LabelDialog`. The RF measurements have the
  "from the register" field (choose/write/scan; the name fills in by itself; unknown code = warning) and each
  run saves **that day's card** in the header; the comparison recognises the cables from the code.
  Choices: the loss is not a fixed datum on the label but an optional "last measurement" line to reprint; no
  direct printing (PDF at 100 %); general register (cable, antenna, filter, amplifier, adapter,
  other). Defect found from the screenshot and fixed: the estimate of the text width was too
  optimistic for capitals (now per character, checked in the tests against the real Qt width).
  Still to do: editable label templates (with the HTML report system), the trend of a cable's loss
  over time, reading the QR with the camera.
  **Attenuator** (2026-11-04, user request): module `attenuator` (`.att`): attenuation (positive) of an attenuator
  as a function of frequency with the VNA, mean/minimum/maximum, flatness, slope, deviation from the nominal value,
  return loss of the two ports, verdict on nominal ± tolerance or on a mask (out of tolerance = result, not
  error); one setting per measurement (`setting`). In the register the new type **ATT** (nominal value, tolerance, maximum power and
  frequency, connectors) and the label line "main data" (`10 dB, 6 GHz, 2 W`; also `20 dB gain` for the
  amplifiers). `SimVna(attenuator_db=, attenuator_slope_db_per_ghz=)`. Guide: `docs/attenuator.md`.
  **To discuss/to do: de-embedding** (removing from the result a cable or attenuator already measured): planned first step =
  subtraction in dB on S21 only, with the warning "corrected in magnitude only" (approximation: reflections not removed);
  then possibly the complex version with Touchstone files (full S-parameters). The measured values stay saved
  and the correction is applied on top, indicating the code of the object removed.
  **Ripple and noise** (2026-11-04, before the measurements "to do" chosen by the user): module `ripple` (`.rpl`) with an
  oscilloscope (and an optional electronic load): peak-to-peak, RMS of the AC part (AC coupling and 20 MHz limit by default),
  ripple frequency and harmonics from the spectrum (Hann window), noise = RMS of what remains after removing the peaks,
  the worst among several acquisitions, verdict on `max_pp_v`/`max_rms_v` (out of limit = result),
  and **ripple as a function of the load current** (the load is switched off in teardown even after an error).
  Warnings: signal touching the edge of the screen, few converter levels (scale too coarse), fewer than 5 periods in the record, sampling below 5× the frequency. New common pieces: `ola/spectrum.py` (FFT, peaks, noise; reusable for the spectrum) and `ola/sim_scope.py`. The test against the real library showed that the memory depth accepts only discrete values per model (10k, 100k, 1M...): documented, the planner error is clear.
  Guide: `docs/ripple.md`. Not tried on hardware. To add: ripple as the input voltage varies, switching peaks as figures of their own.
  **Wiring diagram** (2026-11-04, user request: "when the measurement is initialised, a wiring diagram of the devices is shown"): `ola/wiring.py` (without Qt) reads a `wiring.json` that each module carries
  with it (it is updated together with the module): nodes (instruments and the device under test) on a grid, ports, connections with
  the cable label, notes; the texts in the 5 languages with `{parameter|default}` and `when` conditions (the amplifier
  shows the attenuator only if there is one, the cable port 2 or the open/short end, the ripple the load only with
  `conditions`); under each instrument the names linked to the role. Drawing in mm with the same primitives as the labels
  (also SVG). `frontend/ui/WiringDialog.py`: before the start a Start/Cancel question with the tick "show before
  each measurement" (remembered in QSettings), the "Connections..." button in the project window, Save SVG.
  Available for the RF, ripple and efficiency measurements (here a **typical** diagram); the time log does not have one. Guide:
  `docs/wiring.md`. To do: the pins inside the device, the datalogger channels and the shunt in the
  efficiency diagram, a printable version in the report.
  **Wiring diagram, second version** (2026-11-04, user request: better drawings, his own images, and the written list "connect X to Y"):
  `wiring.json` now has `steps` (numbered sentences, also with `foreach` over the parameters of the file:
  for efficiency "Connect channel 101 of daq1 to «vin» of the converter", for each set parameter and for each
  reading with a channel; likewise for the time log) and `images` (drawings of the user next to `wiring.json`, chosen according to the
  parameters, without extension = .svg/.png/.jpg/.webp, `{lang}` for the language, `optional` to avoid a warning if missing:
  the modules already list the expected names, see `docs/wiring.md`). Without an image the program's drawing remains. The window
  shows the image, the numbered list and the notes; `python -m frontend.ui.WiringDialog <module> [file] [language]` to try it.
  To do: a free text per parameter in the efficiency editor ("converter input, pin +") so that the sentences
  say where the cable goes instead of only the name of the parameter.
  **Line and load regulation** (2026-11-04, user choice: "let's go with 3, a datalogger can also be used instead of the multimeter"):
  a real module `regulation` (`.reg`), not a model of the efficiency measurement. Power supply + electronic load +
  voltmeter (role `meter`: any instrument that answers `measure_dc_voltage`, so
  **datalogger or multimeter**, with its own `args`: the datalogger wants `range`, `resolution` and `channels`, the multimeter
  numbers and no channels). Line test (variable Vin at fixed current: deviation in mV, % and mV/V) and load test
  (variable current at fixed Vin: % "no load → full load" and output resistance in mΩ), input read **at the converter**
  on request (it shows the drop in the cables), verdict on limits. Safety: load at 0 A before switching on
  the power supply, `safety` (maximum Vin/current) refuses before switching on anything, load and power supply
  switched off in teardown even after an error. The test on the real library found that `measure_dc_voltage` requires
  `range` and `resolution` (and the 34401A numbers, not `AUTO`/`DEF`; the HP 3478A does not have the call): documented in the form and
  in the guide. `ola/sim_bench.py` (simulated bench). Guide: `docs/regulation.md`. Not tried on hardware. To do: cross
  regulation (several outputs), over temperature, load transient (separate measurement).
  **VSWR corrected for the cable loss** (2026-11-05, user choice among the VSWR variants: "VSWR corrected for the
  cable loss"; it is the first step of the de-embedding discussed): `ola/deembed.py` (without Qt). An antenna measured at the
  end of a cable looks better matched than it is (the cable attenuates the reflection twice); with the cable already
  measured it is removed: `Γ = S11 measured / T²`. The cable is indicated with the **register code** (the project takes the last
  finished measurement of that cable and saves in the header which file it used; if there is none, the measurement does not start),
  with a cable measurement file or with a Touchstone file (.s2p in transmission, .s1p with open/short). Two modes: **complex** (with the
  phase: also corrects impedance and Smith) and **magnitude only** (only the loss: enough for VSWR and return loss; the antenna
  rejects it because the impedance needs the phase). Used by `return_loss` and `antenna` with `correction`; the raw curves stay
  next to the corrected ones. Declared assumption: well-matched cable (its reflections do not enter). If the corrected
  reflection exceeds 1 it is limited and reported. `SimVna(termination="antenna_via_cable")`. Wiring diagram and
  images 14-15. Still to do the same for the S21 parameters (filter, attenuator) and the version with transfer matrices
  (cable not well matched).
  **Two-port de-embedding** (2026-11-06, "go ahead with deembedding ideas"): `ola/fixtures.py`. A device measured
  through cables, adapters or attenuators on port 1, port 2 or both; the accessory already measured is removed (by
  **register code**: cable or attenuator, the last finished measurement of the project, saved in the header; or a
  measurement file or a `.s2p` written "as seen by the VNA", port 2 is flipped by the program). Two models:
  **matched** (`S21/(T1·T2)`, reflections divided by the round trip: right for a cable only) and **full**
  (transfer matrices `T = T1·Tdut·T2`: exact for any accessory, even unmatched; it reads all four S parameters and wants accessories with reflections: .s2p or an attenuator measurement); two modes: **complex** and **magnitude only**
  (if only the loss is known). Used by `filter` and `attenuator` with `correction`; raw curves next to the corrected ones
  (`S21_raw`, `attenuation_raw_db`); warnings if the corrected reflection exceeds 1 or the S21 exceeds 0 dB. The tests compare
  both models with exact synthetic networks (the full one recovers the device to 1e-6 with accessories misaligned on
  both ports). `SimVna(fixture1_m, fixture2_m)`. Single guide `docs/deembedding.md` (also for the one-port case).
  Images 16-17. To do: amplifier and cable with accessories; chains of adapters measured in pieces.
  **Placeholders for the wiring images** (2026-11-06): `docs/wiring-images.md` updated (17 images, section
  on the placeholders) and a placeholder `.svg` file for each one in the module folder, written by
  `scripts/make_picture_placeholders.py` from the list (it never overwrites a real drawing; `--check` says how far it has gone). The program **ignores** a placeholder (it contains `OLA-PLACEHOLDER`) and shows its own
  diagram until the user replaces it with their drawing (same name, or a `.png` next to it).
  **RF measurements and the real VNA library** (2026-11-06): the library category in `main` is `network_analyzers_series` with
  `set_frequency_sweep`, `run_sweep`, `read_sparameters(sparameters=[...])` (and optional `set_if_bandwidth`, `set_source_power`; linear sweep), while my six measurements used `set_sweep`/`read_sparameter` (scale, IF bandwidth, power): with a real LiteVNA they would have failed.
  Adapter in `ola/vna_common.py` (`uses_library_calls`: checks `set_frequency_sweep` and `read_sparameters`): if the instrument
  has the library calls they are used (one sweep for all the parameters, the list goes with the reading,
  `calibrated: false` warns; `set_if_bandwidth`, `set_source_power` and `set_sweep_type` if the instrument has them), otherwise the
  simple ones (simulation). What the instrument cannot do (the LiteVNA does not have the three optional ones) is reported in the log and
  left as it is; the amplifier's **compression test**, which varies the power, works with `set_source_power` and is otherwise
  rejected before switching anything on. Corrected after checking against the real schema in the library's `main` (the draft had
  `select_sparameters`, removed). `SimVna(library_calls=True)`; a test checks
  that the six measurements give the same numbers with the two contracts and that the calls exist for the LiteVNA 62/64/67.
  `docs/vna-calls.md` rewritten (correct category). The logarithmic sweep (`set_sweep_type`) is added by the library session.
  **Bode plot** (2026-11-07, user choice: "go ahead with the Bode plot, then with the VNA"): module `bode` (`.bod`) with a
  function generator and an oscilloscope. At each frequency: generator, timebase to show N periods, **one acquisition,
  two channels** (`read_waveform_full` with `stop=False` for the second) and **fit of a sine at the known frequency** on each
  (`ola.spectrum.fit_sine`, least squares: gain = ratio of the amplitudes, phase = difference of the phases; it also copes with
  noise 5 times the signal); **automatic vertical scales** (recapture if it saturates or fills too little, also taking the
  noise into account). Phase continuous along the sweep. Results: complex curve `H` (Bode), -3 dB band, peak and, with `loop`,
  crossover frequency, **phase margin** and **gain margin**, verdict on the limits (a value that is not found is not
  invented: the limit fails with the reason). Safety: generator off while preparing, maximum amplitude refused before
  switching on, switched off in teardown. The library lacks the **function_generator** category: calls proposed in
  `docs/bode.md` (`set_output_state`, `set_frequency`, `set_amplitude`, opt. `set_waveform_shape`, `set_offset`) to be passed to the
  library session. `ola/sim_bode.py` (simulated bench). Image 18. To do: different amplitude at different frequencies,
  output impedance (current injection), the oscilloscope's internal AWG as the source.
  **Time domain (TDR) with the VNA** (2026-11-07, "then with the VNA": the first of the extensions): module `tdr` (`.tdr`) and `ola/tdr.py`
  (without Qt). From S11 on a linear sweep, impulse response with a window (Hann by default) and zero padding: each reflection is a
  peak at `d = c·vf·t/2`; for each peak the complex reflection by summing the data at the exact delay (magnitude, **sign**: higher
  impedance = open, lower = short) and the impedance; **resolution** `c·vf/(2B)` and **range** `c·vf/(2·df)` declared; expected
  length → length error and **velocity factor** that fits; step response and impedance profile for a cable in
  sections (requires start = multiple of the step; below the start the phase of the first point continued backwards, DC = real part),
  verdict on the reflections **before the end** (the last peak is the open/short/device). `SimVna(fault_at_m, fault_gamma)`.
  Guide `docs/tdr.md`, image 19. To do: removing the cable loss from the amplitude of the far reflections, multiple echoes,
  gating to measure a single reflection. The other two VNA extensions are done (2026-11-07):
  **comparison with a "good" sample** (`ola/golden.py`, `scripts/golden_check.py`, `docs/golden.md`: tolerance on the curves as a number,
  a line over frequency or asymmetric, absolute/relative tolerance on the summary figures, minimum coverage of the sweep, verdict with
  the reasons, sample saved in `<project>/golden/`) and **trend over time of a cable's loss** (`ola/trend.py`,
  `scripts/cable_trend.py`, `docs/trend.md`: least-squares line, a real change only if the slope exceeds twice its
  uncertainty, verdict PASS/WARNING/FAIL/NOT ENOUGH DATA with the date on which the limit is reached). Then (2026-11-08): the **Reference
  sample** tab in the comparison window (the ★ reference is the sample, tolerance on the curve with the side, tolerances on the figures,
  save/open in `golden/`), the **golden-sample step of the cable measurement** (`golden.name` + `tolerances`, resolved from the project into `golden.run`, table
  `golden` and `golden_verdict` in the summary, fields in the editor) and the **Trend...** window from the cable's history (`TrendDialog`: chart
  with measurements, line and limit, verdict, CSV). Then: the sample step in all the VNA measurements (filter,
  amplifier, attenuator, return loss, antenna) with `GoldenRecorder` (one line in `run`), and the **tolerances derived from several good
  pieces** (`derive_tolerances`: maximum deviation × factor, a minimum floor, piecewise-flat line that is never narrower than the pieces
  used; button *Propose from the ticked results* and `golden_check.py --derive`). Then the step also in Bode, TDR and in the measurements with
  a table of rows (ripple, regulation, efficiency, S-parameters): `rows` = rows matched by columns (`match`) and tolerance per
  column, verdict in the `golden_result` table (`summary_row=False` + `finish(ctx)`). Also `derive_tolerances` for `rows` (from Python).
- ⏳ Not done yet: trying the `connect` on real instruments (requires the library/handle branch to be merged),
  module and fields for the LiteVNA67 text serial (`until`/`lines`/`size`/`flush`, awaiting the device data), driver system for AD2/AD3, wheel pipeline and CI.

## 10. Open points

- ✅ Rust for the native layer (transport).
- ✅ Category list approved; only categories, no instrument except the VNA.
- ✅ Impulse tests: handled by the dynamic mode of the load + scope trigger (§4.3).
- ✅ `thermal_chamber` removed from the categories.
- ✅ LiteVNA67: `scpi` mode over serial, like the current instruments (§7.1).
- ✅ AD2/AD3: `driver` category with mandatory WaveForms runtime.
- ❓ **Design of the driver system** (interface, session lifecycle,
  detection, runtime installation): to be discussed.
- ❓ **Where the drivers live**: proposal = code in the OpenLab repo / user folder,
  JSON library data only. To be confirmed.
- ❓ **LiteVNA67**: the author will send VID/PID, protocol and specifications (pending).
- ❓ **Model of composite devices** in the `.inst` and in the library (§7.1).
- ✅ Generic verbs = library call names (§7.2); only those of the new categories remain to be defined,
  in the library repository.
- ✅ **Calls with several commands** (§7.2): `write`/`query`/`read`/`delay` steps under a lock per
  instrument; joining with `;` is left out of v1.
- ✅ **Connections**: USB-TMC/GPIB/VXI-11 via pyvisa (`ola/_visa.py`, tried only with `pyvisa-py`);
  the mode for each model (raw socket / VXI-11 / serial) is declared by the library in the `interface` block
  (work of the other session). Open: `rusb` for native USB-TMC (not necessary now).
- ✅ **Extraction** of `resolve_model_commands()` into a module without Qt: done in the other session's branch
  (`ola/library.py`), not yet in `main`.
- ❓ **Instrument library**: `Instruments_LIB` is a separate repo (`instruments_lib`):
  the new categories must be created there in coordination with this repo.
- ✅ **User modules**: Python only; loading a non-built-in module requires explicit permission
  (`allow_user_code`), discovering it does not. Documented in `docs/measurement-modules.md`.
- ❓ **Freeze `api_version` 1** (`Measurement` / `ctx` interface): to be done before promising compatibility to modules written by others.
- ❓ **Languages**: each module carries its own optional `lang/` (proposal).
