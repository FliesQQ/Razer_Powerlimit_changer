"""Intel RAPL package power limit (PL1/PL2) via MSR + MMIO (ThrottleStop-style)."""

from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .winring0 import WinRing0

MSR_RAPL_POWER_UNIT = 0x606
MSR_PKG_POWER_LIMIT = 0x610
MSR_PKG_ENERGY_STATUS = 0x611  # cumulative package energy (wraps at 32-bit)

# PCI host bridge MCHBAR (bus 0, device 0, function 0), then RAPL MMIO.
PCI_MCHBAR_REG = 0x48
MCHBAR_RAPL_LIMIT_OFF = 0x59A0


@dataclass
class PowerLimits:
    pl1_w: float
    pl2_w: float
    tau_s: float
    pl1_enabled: bool = True
    pl2_enabled: bool = True
    pl1_clamp: bool = True
    pl2_clamp: bool = True


@dataclass
class RaplUnits:
    power_w: float
    energy_j: float
    time_s: float


@dataclass
class MmioRaplInfo:
    available: bool
    mchbar: int = 0
    raw: int = 0
    locked: bool = False
    pl1_w: float = 0.0
    pl2_w: float = 0.0
    pl1_enabled: bool = False
    pl2_enabled: bool = False
    message: str = ""


def _run_on_cpu0(fn):
    """Package RAPL MSRs are most reliable when written from CPU0."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetCurrentThread()
    old = kernel32.SetThreadAffinityMask(handle, ctypes.c_size_t(1))
    try:
        return fn()
    finally:
        if old:
            kernel32.SetThreadAffinityMask(handle, ctypes.c_size_t(old))


class CpuRaplBackend:
    def __init__(self, ring0: "WinRing0") -> None:
        self._r0 = ring0
        self._units: Optional[RaplUnits] = None
        self.last_target: Optional[tuple[float, float, float]] = None
        self._energy_prev: Optional[int] = None
        self._energy_t_prev: Optional[float] = None
        self.last_package_power_w: Optional[float] = None
        self.last_mmio: Optional[MmioRaplInfo] = None
        self.last_mmio_action: str = ""

    def read_package_energy_raw(self) -> int:
        def _read():
            return self._r0.read_msr(MSR_PKG_ENERGY_STATUS) & 0xFFFFFFFF

        return int(_run_on_cpu0(_read))

    def sample_package_power_w(self) -> Optional[float]:
        """
        Instantaneous-ish CPU Package power from RAPL energy delta.
        Call periodically (≥0.5s). First call seeds and returns None/last.
        """
        u = self.units()
        now = time.perf_counter()
        energy = self.read_package_energy_raw()
        prev_e = self._energy_prev
        prev_t = self._energy_t_prev
        self._energy_prev = energy
        self._energy_t_prev = now
        if prev_e is None or prev_t is None:
            return self.last_package_power_w
        dt = now - prev_t
        if dt < 0.2:
            return self.last_package_power_w
        delta = energy - prev_e
        if delta < 0:
            delta += 1 << 32  # 32-bit wrap
        watts = (delta * u.energy_j) / dt
        if watts < 0 or watts > 400:
            return self.last_package_power_w
        self.last_package_power_w = round(watts, 1)
        return self.last_package_power_w

    def units(self) -> RaplUnits:
        if self._units is None:

            def _read_units():
                raw = self._r0.read_msr(MSR_RAPL_POWER_UNIT)
                power = 1.0 / (1 << (raw & 0xF))
                energy = 1.0 / (1 << ((raw >> 8) & 0x1F))
                time_u = 1.0 / (1 << ((raw >> 16) & 0xF))
                return RaplUnits(power_w=power, energy_j=energy, time_s=time_u)

            self._units = _run_on_cpu0(_read_units)
        return self._units

    def read(self) -> PowerLimits:
        u = self.units()

        def _read():
            return self._r0.read_msr(MSR_PKG_POWER_LIMIT)

        raw = _run_on_cpu0(_read)
        pl1 = ((raw >> 0) & 0x7FFF) * u.power_w
        pl2 = ((raw >> 32) & 0x7FFF) * u.power_w
        tau = self._decode_tau((raw >> 17) & 0x7F, u.time_s)
        return PowerLimits(
            pl1_w=round(pl1, 3),
            pl2_w=round(pl2, 3),
            tau_s=round(tau, 3),
            pl1_enabled=bool((raw >> 15) & 1),
            pl2_enabled=bool((raw >> 47) & 1),
            pl1_clamp=bool((raw >> 16) & 1),
            pl2_clamp=bool((raw >> 48) & 1),
        )

    def _mchbar_base(self) -> int:
        raw = self._r0.read_pci_dword(0, 0, 0, PCI_MCHBAR_REG)
        if (raw & 1) == 0:
            raise OSError("MCHBAR 未启用（PCI 0:0.0+0x48 bit0=0）")
        return int(raw) & ~0x7FFF

    def _phys(self):
        from .physmem import get_physmem

        mchbar = self._mchbar_base()
        return get_physmem(self._r0, probe_address=mchbar + MCHBAR_RAPL_LIMIT_OFF)

    def read_mmio(self) -> MmioRaplInfo:
        """Read MMIO PACKAGE_RAPL_LIMIT at MCHBAR+0x59A0 (effective min with MSR)."""
        try:
            u = self.units()
            mchbar = self._mchbar_base()
            addr = mchbar + MCHBAR_RAPL_LIMIT_OFF
            from . import physmem as physmem_mod

            raw = self._phys().read_qword(addr)
            locked = bool((raw >> 63) & 1)
            pl1_en = bool((raw >> 15) & 1)
            pl2_en = bool((raw >> 47) & 1)
            pl1 = ((raw >> 0) & 0x7FFF) * u.power_w if pl1_en else 0.0
            pl2 = ((raw >> 32) & 0x7FFF) * u.power_w if pl2_en else 0.0
            backend = physmem_mod.backend_name() or "?"
            info = MmioRaplInfo(
                available=True,
                mchbar=mchbar,
                raw=raw,
                locked=locked,
                pl1_w=round(pl1, 1),
                pl2_w=round(pl2, 1),
                pl1_enabled=pl1_en,
                pl2_enabled=pl2_en,
                message=(
                    f"MMIO[{backend}] PL1={pl1:.0f}W PL2={pl2:.0f}W "
                    f"{'已锁' if locked else '未锁'} "
                    f"使能={int(pl1_en)}/{int(pl2_en)}"
                ),
            )
            self.last_mmio = info
            return info
        except Exception as exc:  # noqa: BLE001
            info = MmioRaplInfo(available=False, message=f"MMIO 不可用: {exc}")
            self.last_mmio = info
            return info

    def unlock_mmio_disable_limits(self) -> MmioRaplInfo:
        """
        Optional ThrottleStop-style MMIO neutralize (disabled by default).

        Writing the MMIO lock bit persists until reboot and is unsafe when we
        cannot reliably verify the write. Prefer raising Razer EC CPU boost so
        firmware itself lifts the MMIO floor.
        """
        info = self.read_mmio()
        if not info.available:
            self.last_mmio_action = info.message
            return info
        self.last_mmio_action = (
            f"MMIO 只读诊断（不写入）: {info.message}"
        )
        return info

    def _build_msr(self, pl1_w: float, pl2_w: float, tau_s: float) -> int:
        u = self.units()

        def _read():
            return self._r0.read_msr(MSR_PKG_POWER_LIMIT)

        raw = _run_on_cpu0(_read)
        # Never set the MSR lock bit; preserve only if firmware already locked.
        lock = raw & (1 << 63)
        pl1_bits = min(0x7FFF, int(round(pl1_w / u.power_w))) & 0x7FFF
        pl2_bits = min(0x7FFF, int(round(pl2_w / u.power_w))) & 0x7FFF
        tau_bits = self._encode_tau(tau_s, u.time_s) & 0x7F

        new_val = 0
        new_val |= pl1_bits
        new_val |= 1 << 15
        new_val |= 1 << 16
        new_val |= tau_bits << 17
        new_val |= pl2_bits << 32
        new_val |= 1 << 47
        new_val |= 1 << 48
        new_val |= lock
        return new_val

    def apply(self, pl1_w: float, pl2_w: float, tau_s: float = 48.0) -> PowerLimits:
        if pl1_w <= 0 or pl2_w <= 0:
            raise ValueError("PL1/PL2 must be positive")

        # Read-only MMIO diagnose — do NOT lock/write MMIO (needs reboot to undo).
        try:
            mm = self.read_mmio()
            if mm.available:
                self.last_mmio_action = f"MMIO 诊断: {mm.message}"
            else:
                self.last_mmio_action = (
                    "MMIO 暂不可读（不影响以 EC CPU boost + MSR 调功耗）。"
                    f" {mm.message}"
                )
        except Exception as exc:  # noqa: BLE001
            self.last_mmio_action = f"MMIO 诊断失败: {exc}"

        new_val = self._build_msr(pl1_w, pl2_w, tau_s)

        def _write():
            self._r0.write_msr(MSR_PKG_POWER_LIMIT, new_val)
            time.sleep(0.02)
            self._r0.write_msr(MSR_PKG_POWER_LIMIT, new_val)

        _run_on_cpu0(_write)
        self.last_target = (float(pl1_w), float(pl2_w), float(tau_s))
        got = self.read()
        if abs(got.pl1_w - pl1_w) > 2.0 or abs(got.pl2_w - pl2_w) > 2.0:
            _run_on_cpu0(_write)
            got = self.read()
        return got

    def reassert(self) -> Optional[PowerLimits]:
        """MSR-only reassert — do not touch MMIO / EC (avoids fighting XTU/IET)."""
        if not self.last_target:
            return None
        pl1, pl2, tau = self.last_target
        new_val = self._build_msr(pl1, pl2, tau)

        def _write():
            self._r0.write_msr(MSR_PKG_POWER_LIMIT, new_val)

        _run_on_cpu0(_write)
        return self.read()

    @staticmethod
    def _encode_tau(seconds: float, time_unit: float) -> int:
        if seconds <= 0:
            seconds = 1.0
        best = 0
        best_err = float("inf")
        for y in range(32):
            for z in range(4):
                t = (2**y) * (1.0 + z / 4.0) * time_unit
                err = abs(t - seconds)
                if err < best_err:
                    best_err = err
                    best = (z << 5) | y
        return best

    @staticmethod
    def _decode_tau(bits: int, time_unit: float) -> float:
        y = bits & 0x1F
        z = (bits >> 5) & 0x3
        return (2**y) * (1.0 + z / 4.0) * time_unit
