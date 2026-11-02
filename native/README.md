# ola_native – low-latency instrument transport

Rust implementation of the byte-stream link to instruments (TCP/LXI and serial), exposed
to Python through PyO3. It replaces the C backend (`backend/`) for I/O.

* TCP: `TCP_NODELAY`, deadline-bounded buffered reads, command + terminator in one write.
* Serial / USB-CDC: baud, data bits, parity, stop bits.
* IEEE 488.2 definite-length blocks (waveforms), `read_exact`, `read_until`, custom terminators.
* The GIL is released during every blocking call.
* Errors carry `[TRN-xxx]` codes (see `ERROR_CODES.md`).

The Python entry point is `ola.transport`; it falls back to a pure-Python implementation
with identical behaviour if this module is not installed (`OLA_TRANSPORT=python` forces it).

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
