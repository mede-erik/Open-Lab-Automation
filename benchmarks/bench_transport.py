"""Latency benchmark for the instrument transport (loopback, fake instrument).

    python benchmarks/bench_transport.py

Compares the legacy C backend (built into a temp dir if gcc is available), the
pure-Python transport and the native Rust transport. Real instruments add their own
1-50 ms; this measures only the software overhead, which must stay negligible.
"""

import ctypes
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ola import _pyconn  # noqa: E402
from tests.fake_instrument import FakeTcpInstrument, line_server  # noqa: E402

try:
    import ola_native
except ImportError:
    ola_native = None

N = 500
BLOCK = 1_000_000


def report(name, times):
    t = sorted(times)
    print(
        f"  {name:34s} median {statistics.median(t) * 1e6:9.0f} us   "
        f"p99 {t[int(len(t) * .99)] * 1e6:9.0f} us   max {t[-1] * 1e6:9.0f} us"
    )


def legacy_c():
    if not shutil.which("gcc"):
        return None
    src = os.path.join(ROOT, "backend")
    out = os.path.join(tempfile.mkdtemp(), "libbackend.so")
    files = [os.path.join(src, f) for f in ("backend.c", "instrument.c", "platform.c", "sweep.c")]
    r = subprocess.run(
        ["gcc", "-O2", "-shared", "-fPIC", "-o", out, *files, "-I" + src, "-lm"],
        capture_output=True,
    )
    return ctypes.CDLL(out) if r.returncode == 0 else None


def bench_query():
    print(f"Query round-trip ('MEAS:VOLT?' -> float), {N} samples")
    inst = FakeTcpInstrument(line_server(lambda c: b"1.234567\n"))
    lib = legacy_c()
    if lib:
        lib.be_init()
        h, v, times = ctypes.c_int(), ctypes.c_double(), []
        lib.be_connect(ctypes.byref(h), b"127.0.0.1", inst.port, 2000)
        for _ in range(60):  # legacy is ~44 ms/query: keep the run short
            t = time.perf_counter()
            lib.be_send(h, b"MEAS:VOLT?")
            lib.be_receive_float(h, ctypes.byref(v), 2000)
            times.append(time.perf_counter() - t)
        report("legacy C backend (60 samples)", times)
    for name, cls in (
        ("pure Python", _pyconn.PyConnection),
        ("native Rust", ola_native and ola_native.Connection),
    ):
        if cls is None:
            print(f"  {name:34s} (not built)")
            continue
        inst2 = FakeTcpInstrument(line_server(lambda c: b"1.234567\n"))
        c = cls.open_tcp("127.0.0.1", inst2.port, 2000)
        times = []
        for _ in range(N):
            t = time.perf_counter()
            float(c.query("MEAS:VOLT?"))
            times.append(time.perf_counter() - t)
        report(name, times)


def bench_block():
    print(f"\nWaveform transfer (IEEE block, {BLOCK / 1e6:.0f} MB), 10 samples")
    payload = os.urandom(BLOCK)
    msg = b"#7%07d" % BLOCK + payload + b"\n"
    for name, cls in (
        ("pure Python", _pyconn.PyConnection),
        ("native Rust", ola_native and ola_native.Connection),
    ):
        if cls is None:
            print(f"  {name:34s} (not built)")
            continue
        inst = FakeTcpInstrument(line_server(lambda c: msg))
        c = cls.open_tcp("127.0.0.1", inst.port, 10000)
        times = []
        for _ in range(10):
            t = time.perf_counter()
            c.send("CURV?")
            assert len(c.read_block()) == BLOCK
            times.append(time.perf_counter() - t)
        t = sorted(times)
        print(
            f"  {name:34s} median {statistics.median(t) * 1e3:7.1f} ms   "
            f"({BLOCK / statistics.median(t) / 1e6:6.0f} MB/s)"
        )


if __name__ == "__main__":
    bench_query()
    bench_block()
