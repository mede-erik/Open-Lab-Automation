# ola_native – low-latency instrument transport

Rust implementation of the byte-stream link to instruments (TCP/LXI and serial), exposed
to Python through PyO3. It replaced the former C backend (removed in November 2026) for I/O.

* TCP: `TCP_NODELAY`, deadline-bounded buffered reads, command + terminator in one write.
* Serial / USB-CDC: baud, data bits, parity, stop bits.
* IEEE 488.2 definite-length blocks (waveforms), `read_exact`, `read_until`, custom terminators.
* The GIL is released during every blocking call.
* Errors carry `[TRN-xxx]` codes (see `ERROR_CODES.md`).

The Python entry point is `ola.transport`; it falls back to a pure-Python implementation
with identical behaviour if this module is not installed (`OLA_TRANSPORT=python` forces it).

## Layout

| File | Content |
|---|---|
| `src/conn.rs` | `Connection`: TCP / serial link, buffered deadline-bounded reads, blocks, terminators |
| `src/error.rs` | `Error` with the stable `TRN-001`..`TRN-006` codes |
| `src/python.rs` | PyO3 bindings (feature `python`); a `Mutex` serialises use of one connection from several threads |
| `tests/tcp.rs` | integration tests against a fake instrument on a real socket, including the 44 ms latency regression |

Public items are documented with `///` and the crate builds with `#![warn(missing_docs)]`; read the API
with `cargo doc --no-deps --open`. The Python-side contract of the same operations is
`ola.transport.Transport`; how it fits in the engine is in [`docs/engine.md`](../docs/engine.md).

## Build

```bash
pip install maturin
cd native
maturin build --release        # wheel in native/target/wheels (one wheel for Python >= 3.10)
pip install target/wheels/ola_native-*.whl
```

For development: `maturin develop --release` inside a virtualenv.

## Test and benchmark

```bash
cd native && cargo test        # Rust unit/integration tests (no Python needed)
pytest tests                   # same behaviour tests, native and pure-Python
python benchmarks/bench_transport.py
```
