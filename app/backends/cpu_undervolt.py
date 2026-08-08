"""Intel FIVR undervolt via MSR 0x150 (XTU / ThrottleStop compatible)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .winring0 import WinRing0

MSR_VOLTAGE = 0x150

# Plane indices commonly used by XTU / ThrottleStop on modern Intel.
PLANE_CORE = 0
PLANE_GPU = 1
PLANE_CACHE = 2
PLANE_UNCORE = 3
PLANE_ANALOGIO = 4
# E-core related offset; on some HX parts XTU exposes a separate cache UV.
# Plane 3 is used as best-effort for "Efficient Cores Cache".
PLANE_ECORE_CACHE = 3

# OC Mailbox: bit 63 = busy/command latch (must be set on every write).
BIT_BUSY = 1 << 63
BIT_READ = 1 << 36
BIT_WRITE = 1 << 32


@dataclass
class UndervoltSettings:
    core_mv: float = 0.0
    cache_mv: float = 0.0
    ecache_mv: float = 0.0


def _to_offset_bits(mv: float) -> int:
    """Encode millivolts into MSR voltage-offset field."""
    x = int(round(mv * 1.024)) & 0xFFF
    return (x << 21) & 0xFFE00000


def _from_offset_bits(bits: int) -> float:
    x = (bits >> 21) & 0xFFF
    if x & 0x800:  # sign extend 12-bit
        x -= 0x1000
    return x / 1.024


class CpuUndervoltBackend:
    def __init__(self, ring0: "WinRing0") -> None:
        self._r0 = ring0
        self.last_locked = False

    def _wait_ready(self, timeout_s: float = 0.05) -> int:
        deadline = time.perf_counter() + timeout_s
        last = 0
        while True:
            last = self._r0.read_msr(MSR_VOLTAGE)
            if (last & BIT_BUSY) == 0:
                return last
            if time.perf_counter() >= deadline:
                return last
            time.sleep(0.001)

    def read_plane(self, plane: int) -> float:
        # Read request: busy | plane | read-command (bit36).
        cmd = BIT_BUSY | BIT_READ | ((plane & 0xF) << 40)
        self._r0.write_msr(MSR_VOLTAGE, cmd)
        val = self._wait_ready()
        return round(_from_offset_bits(val & 0xFFE00000), 3)

    def write_plane(self, plane: int, mv: float) -> float:
        # Write: busy | plane | read-bit | write-bit | offset payload.
        payload = (
            BIT_BUSY
            | BIT_READ
            | BIT_WRITE
            | ((plane & 0xF) << 40)
            | _to_offset_bits(mv)
        )
        self._r0.write_msr(MSR_VOLTAGE, payload)
        self._wait_ready()
        return self.read_plane(plane)

    def read(self) -> UndervoltSettings:
        return UndervoltSettings(
            core_mv=self.read_plane(PLANE_CORE),
            cache_mv=self.read_plane(PLANE_CACHE),
            ecache_mv=self.read_plane(PLANE_ECORE_CACHE),
        )

    def apply(self, settings: UndervoltSettings) -> UndervoltSettings:
        self.write_plane(PLANE_CORE, settings.core_mv)
        self.write_plane(PLANE_CACHE, settings.cache_mv)
        try:
            self.write_plane(PLANE_ECORE_CACHE, settings.ecache_mv)
        except OSError:
            # Some firmware lock uncore/E-cache plane; core/cache still applied.
            pass
        got = self.read()
        # If we asked for a non-zero UV but all planes stay 0, firmware likely locked
        # undervolt (Plundervolt / Overclocking Lock / UV Protection).
        wanted = any(abs(v) > 0.5 for v in (settings.core_mv, settings.cache_mv, settings.ecache_mv))
        got_zero = all(abs(v) < 0.5 for v in (got.core_mv, got.cache_mv, got.ecache_mv))
        self.last_locked = bool(wanted and got_zero)
        return got

    def restore_zero(self) -> UndervoltSettings:
        return self.apply(UndervoltSettings(0.0, 0.0, 0.0))
