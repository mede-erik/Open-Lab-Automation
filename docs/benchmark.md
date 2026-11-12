# Benchmark mode

Answers one question: **where does the time go?** At the end of a measurement (or of any run) the
software tells how long the instruments took to answer, how long each logical call cost and how
much of that is the software itself, so latency can be reduced with numbers instead of guesses
(the rule of `PLAN.md`: optimise only what the benchmark shows to be slow).

It is off by default and then costs one variable check per instrumented place.

## Turning it on

| How | Use |
|-----|-----|
| `OLA_BENCH=1 python frontend/launcher.py` | The whole GUI: every run is measured. Nothing else changes. |
| `build_runner(ref, bench=True)` / `Runner(..., bench=True)` | From code; `bench=None` follows `OLA_BENCH`. |
| `python benchmarks/bench_engine.py` | A repeatable loop on a simulated power supply: no hardware needed. |

The report is published as a `bench` event, written to the run file as a `{"kind": "bench"}` line
(`read_run(path)["bench"]`) and printed in the log of the run. Show or compare it later:

```bash
python scripts/bench_report.py runs/efficiency_20261112_101500.jsonl
python scripts/bench_report.py new.jsonl --compare old.jsonl      # median of every row, in %
```

## What is measured

All times are in milliseconds (`time.perf_counter_ns`); every row has `n`, mean, median, p95, min,
max and total.

| Table | Meaning |
|-------|---------|
| **Measurement thread** | Wall time of the thread that runs the measurement, split into *waiting by design* (`ctx.sleep`, questions to the user), *instrument calls*, *publishing results* (writer and listeners) and *the rest* (the measurement's own code). |
| **Calls** | Every `handle.call`, per instrument. Parts, mean per call: `plan` (library lookup and building the steps), `lock` (waiting for another thread's call on the same instrument), `io` (steps executed on the instrument), `delay` (the `delay` steps of the library), `interp` (raw answer to logical value) and `overhead` (the rest: what the software adds). |
| **Steps** | Every step of every call, per instrument and command; numbers are replaced by `#` (`VOLT 5` and `VOLT 12` are one row). |
| **Instrument response** (`rx`) | For a query, the wait for the answer after the command was sent: the response time of the instrument plus the link. `tx` is the time to send. |
| **Delays** | Deliberate pauses of the library (settling after a command). They are not latency of the software. |
| **Phases, Publishing, Listeners** | `setup` / `run` / `teardown`; one point or trace published; each listener, e.g. `RunWriter`. |
| **Connections** | Opening each instrument and reading its identity. |

How to read it: a high `rx` is the instrument or the link (change timeouts, address, transport); a
high `plan` or `overhead` is the software and is where to optimise; a high `lock` means two threads
use the same instrument; `delay` and `wait` are time the measurement asks for on purpose.

Limits: the simulated transport answers inside `send`, so with it the response time shows up in
`tx` and not in `rx`; on a real link `rx` is the answer wait. Pause time is not counted as a wait
(it ends in the rest). Samples are capped at 1 000 000 per run (`dropped` in the report).

## Where it is in the code

`ola/bench.py` holds the collector, the report and the text format. The hooks are
`InstrumentHandle.call` (calls and their parts), `Instrument` (lock wait, steps, drivers),
`Runner` (phases, publishing, listeners, the report), `MeasurementContext.sleep` and questions
(waits) and `ProjectConnector` (connections). A new place to measure is
`with bench.span("category", "name"):`; it is a no-op when the benchmark is off.
