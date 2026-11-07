# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""A simulated LiteVNA: it speaks the register protocol of the User Guide over the transport
interface (write / read_exact / flush_input) and measures a network with known error terms."""

import cmath
import random
import struct

REFERENCE = 1.0e6  # amplitude of the reference wave (counts)


class SimLiteVna:
    """``connect(gamma)`` / ``connect_thru(s21)`` choose what is on the test port."""

    def __init__(self, variant=0x02, errors=(0.02 + 0.01j, -0.05 + 0.02j, 0.9 - 0.1j), seed=1):
        self.regs = {0xF0: variant, 0xF2: 7, 0xF3: 1, 0xF4: 5, 0x44: 0}
        self.rx = bytearray()
        self.buffer = bytearray()
        self.e00, self.e11, self.t = errors  # directivity, source match, tracking
        self.gamma = lambda f: 0j
        self.s21 = lambda f: 0j
        self.next_index = 0
        self.start_after_clear = 0  # index of the first record after a FIFO clear
        self.random = random.Random(seed)
        self.log = []

    # what is connected -------------------------------------------------------------
    def connect(self, gamma):
        self.gamma = gamma if callable(gamma) else (lambda f: gamma)

    def connect_thru(self, s21):
        self.s21 = s21 if callable(s21) else (lambda f: s21)

    # transport interface -----------------------------------------------------------
    def write(self, data):
        self.rx += data
        while self.rx:
            op = self.rx[0]
            size = {
                0x00: 1,
                0x0D: 1,
                0x10: 2,
                0x11: 2,
                0x12: 2,
                0x18: 3,
                0x20: 3,
                0x21: 4,
                0x22: 6,
                0x23: 10,
            }[op]
            if len(self.rx) < size:
                return
            cmd, self.rx = bytes(self.rx[:size]), self.rx[size:]
            self._execute(cmd)

    def flush_input(self):
        self.buffer.clear()

    def read_exact(self, n, timeout_ms=None):
        if len(self.buffer) < n:
            raise TimeoutError(f"the sim has {len(self.buffer)} bytes, {n} asked")
        out, self.buffer = bytes(self.buffer[:n]), self.buffer[n:]
        return out

    # the device ----------------------------------------------------------------------
    def _execute(self, cmd):
        self.log.append(cmd)
        op, addr = cmd[0], cmd[1] if len(cmd) > 1 else None
        if op == 0x0D:
            self.buffer += b"2"
        elif op in (0x10, 0x11, 0x12):
            size = {0x10: 1, 0x11: 2, 0x12: 4}[op]
            self.buffer += bytes(self.regs.get(addr + i, 0) for i in range(size))
        elif op in (0x20, 0x21, 0x22, 0x23):
            for i, value in enumerate(cmd[2:]):
                self.regs[addr + i] = value
            if op == 0x20 and addr == 0x30:  # clear the FIFO
                self.next_index = self.start_after_clear
        elif op == 0x18:
            self.buffer += b"".join(self._record() for _ in range(cmd[2]))

    def _value(self, name, size, address):
        return int.from_bytes(bytes(self.regs.get(address + i, 0) for i in range(size)), "little")

    def _record(self):
        start = self._value("start", 8, 0x00)
        step = self._value("step", 8, 0x10)
        points = self._value("points", 2, 0x20)
        index = self.next_index % points
        self.next_index += 1
        f = start + index * step
        g, tr = self.gamma(f), self.s21(f)
        m11 = self.e00 + self.t * g / (1 - self.e11 * g)
        m21 = tr  # ideal transmission tracking = 1 for the simulation
        phase = cmath.exp(1j * self.random.uniform(0, 6.28))  # random phase of the record
        sel = self.regs.get(0x44, 0)
        fwd = REFERENCE * phase
        r0 = fwd * m11 if sel in (0, 1) else 0j
        r1 = fwd * m21 if sel in (0, 2) else 0j
        parts = [fwd.real, fwd.imag, r0.real, r0.imag, r1.real, r1.imag]
        return (
            struct.pack("<6i", *[int(round(p)) for p in parts])
            + struct.pack("<H", index)
            + bytes(6)
        )
