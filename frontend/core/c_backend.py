# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""
Python ctypes wrapper for the C backend shared library.

Provides high-level access to instrument communication via raw TCP sockets (LXI).
The C backend handles timing-critical operations:
- Sweep loops with precise settling time
- Direct TCP instrument I/O (send SCPI, receive responses)
- Cross-platform socket handling (Linux .so / Windows .dll)

Usage:
    from frontend.core.c_backend import CBackend

    CBackend.load()
    handle = CBackend.connect("192.168.1.100", 5025)
    CBackend.send(handle, "*IDN?")
    response = CBackend.receive(handle)
    CBackend.disconnect(handle)
"""

import ctypes
import os
import platform
from typing import Callable, Optional

_PROGRESS_CB = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_int)


def _find_library() -> str:
    backend_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "backend",
    )
    names = {
        "Linux": "libbackend.so",
        "Windows": "backend.dll",
        "Darwin": "libbackend.dylib",
    }
    lib_name = names.get(platform.system(), "libbackend.so")
    lib_path = os.path.join(backend_dir, lib_name)
    if not os.path.isfile(lib_path):
        alt = os.path.join(backend_dir, "libbackend.so")
        if os.path.isfile(alt):
            return alt
        raise FileNotFoundError(
            f"C backend library not found at {lib_path}. "
            f"Run 'backend/build.sh' or compile manually."
        )
    return lib_path


class CBackendError(Exception):
    """Raised when a C backend operation fails."""


class CBackend:
    _lib: Optional[ctypes.CDLL] = None

    @classmethod
    def load(cls, lib_path: Optional[str] = None) -> None:
        if cls._lib is not None:
            return

        path = lib_path or _find_library()
        cls._lib = ctypes.CDLL(path)
        cls._setup_funcs()

        ret = cls._lib.be_init()
        if ret != 0:
            raise CBackendError(cls._lib.be_last_error())

    @classmethod
    def _setup_funcs(cls) -> None:
        lib = cls._lib

        lib.be_version.restype = ctypes.c_char_p

        lib.be_last_error.restype = ctypes.c_char_p

        lib.be_connect.argtypes = [
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.be_connect.restype = ctypes.c_int

        lib.be_disconnect.argtypes = [ctypes.c_int]
        lib.be_disconnect.restype = ctypes.c_int

        lib.be_send.argtypes = [ctypes.c_int, ctypes.c_char_p]
        lib.be_send.restype = ctypes.c_int

        lib.be_receive.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.be_receive.restype = ctypes.c_int

        lib.be_receive_float.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        lib.be_receive_float.restype = ctypes.c_int

        lib.be_receive_int.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        lib.be_receive_int.restype = ctypes.c_int

        lib.be_sweep_run.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            _PROGRESS_CB,
        ]
        lib.be_sweep_run.restype = ctypes.c_int

    @classmethod
    def unload(cls) -> None:
        if cls._lib is not None:
            cls._lib.be_cleanup()
            cls._lib = None

    @classmethod
    def version(cls) -> str:
        if cls._lib is None:
            return "not loaded"
        raw = cls._lib.be_version()
        return raw.decode("utf-8") if raw else "unknown"

    @classmethod
    def connect(
        cls, host: str, port: int = 5025, timeout_ms: int = 5000
    ) -> int:
        if cls._lib is None:
            raise CBackendError("CBackend not loaded. Call CBackend.load() first.")
        handle = ctypes.c_int(-1)
        ret = cls._lib.be_connect(
            ctypes.byref(handle),
            host.encode("utf-8"),
            port,
            timeout_ms,
        )
        if ret != 0:
            msg = cls._lib.be_last_error()
            raise CBackendError(
                f"Connection failed to {host}:{port}: "
                f"{msg.decode('utf-8') if msg else f'error {ret}'}"
            )
        return handle.value

    @classmethod
    def disconnect(cls, handle: int) -> None:
        if cls._lib is None:
            return
        cls._lib.be_disconnect(handle)

    @classmethod
    def send(cls, handle: int, command: str) -> None:
        if cls._lib is None:
            raise CBackendError("CBackend not loaded.")
        ret = cls._lib.be_send(handle, command.encode("utf-8"))
        if ret != 0:
            msg = cls._lib.be_last_error()
            raise CBackendError(
                f"Send failed: {msg.decode('utf-8') if msg else f'error {ret}'}"
            )

    @classmethod
    def receive(
        cls, handle: int, buf_size: int = 4096, timeout_ms: int = 5000
    ) -> str:
        if cls._lib is None:
            raise CBackendError("CBackend not loaded.")
        buf = ctypes.create_string_buffer(buf_size)
        ret = cls._lib.be_receive(handle, buf, buf_size, timeout_ms)
        if ret < 0:
            msg = cls._lib.be_last_error()
            raise CBackendError(
                f"Receive failed: {msg.decode('utf-8') if msg else f'error {ret}'}"
            )
        return buf.value.decode("utf-8", errors="replace").strip()

    @classmethod
    def query(
        cls, handle: int, command: str, timeout_ms: int = 5000
    ) -> str:
        cls.send(handle, command)
        return cls.receive(handle, timeout_ms=timeout_ms)

    @classmethod
    def receive_float(cls, handle: int, timeout_ms: int = 5000) -> float:
        if cls._lib is None:
            raise CBackendError("CBackend not loaded.")
        value = ctypes.c_double(0.0)
        ret = cls._lib.be_receive_float(handle, ctypes.byref(value), timeout_ms)
        if ret != 0:
            msg = cls._lib.be_last_error()
            raise CBackendError(
                f"Float receive failed: {msg.decode('utf-8') if msg else f'error {ret}'}"
            )
        return value.value

    @classmethod
    def sweep_run(
        cls,
        instruments: list[int],
        channels: list[int],
        set_values: list[float],
        settling_time_s: float = 0.1,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> tuple[list[float], list[float]]:
        if cls._lib is None:
            raise CBackendError("CBackend not loaded.")
        n_points = len(set_values)
        if n_points == 0:
            return [], []
        if n_points > 100000:
            raise CBackendError("Too many sweep points (max 100000).")

        n_instruments = min(len(instruments), len(channels))
        if n_instruments < 1:
            raise CBackendError("At least one instrument and channel required.")

        c_instruments = (ctypes.c_int * n_instruments)(*instruments)
        c_channels = (ctypes.c_int * n_instruments)(*channels)
        c_set_values = (ctypes.c_double * n_points)(*set_values)
        c_voltages = (ctypes.c_double * n_points)()
        c_currents = (ctypes.c_double * n_points)()

        cfg = _build_sweep_config(
            c_instruments, c_channels, c_set_values,
            n_instruments, n_points, settling_time_s,
        )

        c_cb = _PROGRESS_CB(progress_cb) if progress_cb else _PROGRESS_CB()

        ret = cls._lib.be_sweep_run(
            ctypes.cast(ctypes.byref(cfg), ctypes.c_void_p),
            c_voltages,
            c_currents,
            c_cb,
        )
        if ret != 0:
            msg = cls._lib.be_last_error()
            raise CBackendError(
                f"Sweep failed: {msg.decode('utf-8') if msg else f'error {ret}'}"
            )

        return list(c_voltages), list(c_currents)


def _build_sweep_config(
    instruments, channels, set_values,
    n_instruments, n_points, settling_time_s,
):
    class _SweepConfig(ctypes.Structure):
        _fields_ = [
            ("n_instruments", ctypes.c_int),
            ("instruments", ctypes.POINTER(ctypes.c_int)),
            ("channels", ctypes.POINTER(ctypes.c_int)),
            ("n_points", ctypes.c_int),
            ("set_values", ctypes.POINTER(ctypes.c_double)),
            ("settling_time_s", ctypes.c_double),
        ]

    cfg = _SweepConfig()
    cfg.n_instruments = n_instruments
    cfg.instruments = ctypes.cast(instruments, ctypes.POINTER(ctypes.c_int))
    cfg.channels = ctypes.cast(channels, ctypes.POINTER(ctypes.c_int))
    cfg.n_points = n_points
    cfg.set_values = ctypes.cast(set_values, ctypes.POINTER(ctypes.c_double))
    cfg.settling_time_s = settling_time_s
    return cfg
