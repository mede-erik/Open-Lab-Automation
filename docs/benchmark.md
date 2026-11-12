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

## Measuring a real instrument

`benchmarks/bench_hardware.py` connects to one instrument and answers: how long does it take, and
how much of that is the software?

```bash
python benchmarks/bench_hardware.py --model PSU_OWON_ODP3033 \
    --address TCPIP0::192.168.1.50::inst0::INSTR --arg channel_number=1 --json owon.json
```

It is safe: only **queries** that need no argument are run (nothing is set or switched), and
`self_test`, `reset`, calibration and clear calls are refused. By default it runs
`identification_query`, `error_query`, `read_voltage`, `read_current` and `output_state_query`,
those the model has; `--calls a,b` chooses others. `--arg NAME=VALUE` is passed to the calls whose
schema has that argument (some models need `channel_number` although the schema says it is
optional). A call that fails in the warm-up is skipped with the reason.

The output has, per call, the mean total, the part spent on the instrument and the part spent in
the software (plan, interpretation, lock, overhead) with its percentage, plus the same question
sent straight to the link without planner and lock (`--raw`, default `*IDN?`): the best the link
can do. `--json` saves the report; `--compare` shows the change against an earlier one, e.g. before
and after a change of transport or of timeouts.

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
