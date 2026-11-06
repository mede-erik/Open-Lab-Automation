# Instrument calls, steps and transports

How a logical call such as `set_voltage` ends up as bytes on a wire, and what to expect when something
goes wrong. For the big picture see [engine.md](engine.md).

```
call + arguments   --(call planner)-->   plan   --(Instrument.run)-->   steps   --(transport)-->   bytes
set_voltage(5)                           access + steps                  write "VOLT 5"             TCP / serial / VISA
```

The **call planner** (logical call + arguments + instrument model to a plan, using the instrument
library) is developed separately from the executor described here; the executor only needs the plan.

## Plan

```python
{"call": "set_voltage", "access": "scpi",
 "steps": [{"op": "write", "text": "INST:NSEL 2"}, {"op": "write", "text": "VOLT 5"}]}
```

| `access` | What runs it |
|---|---|
| `scpi` | the steps go through the transport (also used for non-SCPI text protocols, e.g. a serial instrument with its own commands) |
| `driver` | a driver object: `{"driver": {"function": "...", "args": {...}}}`; for instruments that have no command interface, e.g. Analog Discovery through its SDK |

Any other value is rejected with `ValueError`. A plan may be a dict or an object with the same attributes
(`call`, `access`, `steps` / `driver`).

## Steps (`ola/steps.py`)

| `op` | Fields | What it does | Result |
|---|---|---|---|
| `write` | `text` | send `text` + the write terminator | `None` |
| `query` | `text`, `returns`, `timeout_ms` | send `text`, then read one answer | the answer, converted |
| `read` | `returns`, `timeout_ms` | read an answer **without sending anything** (instruments that talk when addressed, e.g. the HP 3478A on GPIB) | the answer, converted |
| `delay` | `ms` | wait (a stop interrupts it) | `None` |

`text` is the final string: placeholders are already substituted and it has no terminator.

`returns` (for `query` and `read`):

| Value | Result |
|---|---|
| `string` (default) | text, terminator removed (`\r\n` and `\n` both) |
| `float` | `float(answer)` |
| `int` | `"1"`, `"+1"` and `"1.0"` are accepted, `"1.5"` fails the step |
| `binary` | `bytes` of an IEEE 488.2 block (`#<d><length><data>`), e.g. a waveform. Use it whenever the data can contain the byte `0x0A`: a `string` read stops at the first newline. |

`timeout_ms` overrides the connection's default for that step (long acquisitions). **Unknown fields and
invalid combinations are rejected when the plan is loaded** (`ValueError`), before anything is sent: a
typo cannot reach an instrument.

## Running a plan (`ola/instrument.py`)

```python
instrument = Instrument("psu1", transport)          # or Instrument("ad2", driver=my_driver)
raw = instrument.run(plan, cancel=stop_event)       # list of raw results, one per step
```

* **One lock per instrument, held for the whole call**, delays included: the two steps of
  `INST:NSEL 2` + `VOLT 5` cannot be interleaved with another thread's calls. Other instruments have their
  own locks and are not blocked.
* The first failing step stops the call: `StepFailedError` (`CALL-004`) with `call`, `step_index` and
  `cause` (the original `TRN-xxx` exception).
* After a failure or a cancel, the next call first discards pending input, so a late answer is never
  taken for the answer of the next command.
* `cancel` (a `threading.Event`) interrupts a `delay` and stops the call between steps; the call raises
  `Aborted`, which is not an instrument error (the runner turns it into the STOPPED state).
* No transport, or a driver plan without a driver: `CallNotSupportedError` (`CALL-001`).
* A driver plan returns a one-element list `[result]`; the driver is any object with
  `call(function, args)`.

Turning the raw results into the logical value (response maps, splitting, booleans) is the planner's job
(`plan.interpret(raw)`), not the executor's.

## Transports

| Function | For | Notes |
|---|---|---|
| `ola.transport.open_tcp(host, port=5025)` | LXI instruments with a raw socket | **Not** VXI-11: `TCPIP0::ip::inst0::INSTR` is VXI-11 and not every instrument also accepts the socket on 5025 |
| `ola.transport.open_serial(path, baud, ...)` | serial and USB-CDC instruments | baud, data bits, parity, stop bits |
| `ola._visa.VisaConnection.open(resource, timeout_ms)` | USB-TMC, GPIB, VXI-11, ASRL through pyvisa | backend `""` = installed VISA, `"@py"` = pure-Python pyvisa-py |
| `ola.sim.SimTransport(responder)` | tests and dry runs | records everything sent in `.log` |

All of them implement the same `Transport` contract (`ola/transport.py`). `ola.transport` uses the
native Rust module when it is installed, and an identical pure-Python implementation otherwise
(`OLA_TRANSPORT=python` forces it).

### Why it is fast

A query is a single write of command + terminator with `TCP_NODELAY` on, answered through a buffered read
with a deadline: about 35 us on loopback with Rust, 55 us in pure Python (`benchmarks/bench_transport.py`).
The old C backend took 44 ms per query because it sent the command and the terminator separately without
`TCP_NODELAY`, which triggers the Nagle / delayed-ACK delay. Real instruments take 1-50 ms per query
themselves, so the instrument dominates and the transport adds nothing visible.

### Terminators

Default: `\n` to send, `\n` expected (a `\r` before it is removed). Change them with
`set_terminators(write_term, read_term)`. When you wrap an existing pyvisa resource with
`VisaConnection(resource, peer, timeout_ms, pyvisa)`, the adapter **adopts the resource's terminators**
(pyvisa's default write termination is `"\r\n"`) and **never leaves the resource modified**: it sets the
timeout / read termination for one operation and restores them, so the rest of the application can keep
using the same resource.

### RS-232 checklist

What worked on a real HP/Agilent 34970A (57600 baud, 8N, XON/XOFF, null-modem cable, `pyvisa-py`), and
what to check when the first query times out:

1. **Cable.** A straight cable instead of a null-modem cable makes *every* query time out.
2. **Line settings are the application's job.** The adapter does not set baud / data bits / parity / stop
   bits / flow control: set them on the pyvisa resource before the first call. A plain `open_resource`
   gives 9600 8N1 without flow control, which is right only if the instrument is set that way.
3. **Terminators.** Set them explicitly from the library (`set_terminators`), do not rely on the pyvisa default.
4. **Backend.** NI-VISA may not know a path such as `ASRL/dev/ttyUSB0::INSTR`; `pyvisa-py` does.
   `pyvisa-py` opens raw-socket resources lazily, so a refused connection shows up at the first read or write
   (as `TRN-001`), not at `open`.
5. Some instruments need remote mode on RS-232 (`set_remote`) before they answer.

## Errors

Transport exceptions derive from `TransportError`; `TransportTimeout` and `TransportClosed` are subclasses.
Their message starts with the code and the `code` attribute holds it.

| Code | Meaning |
|---|---|
| `TRN-001` | connection failed (also a refused connection on a lazily opened socket) |
| `TRN-002` | I/O error |
| `TRN-003` | timeout: no complete answer in time |
| `TRN-004` | connection closed |
| `TRN-005` | protocol error (for example a block that does not start with `#`) |
| `TRN-006` | invalid argument |
| `CALL-004` | a step of a call failed; `cause` has the `TRN-xxx` |

Details and remedies for every code are in [`ERROR_CODES.md`](../ERROR_CODES.md).
