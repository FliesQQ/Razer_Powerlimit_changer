"""Razer Blade Synapse-compatible GPU/fan control via HID feature reports."""

from __future__ import annotations

import random
import threading
import time
from enum import IntEnum
from typing import Optional

try:
    import hid
except ImportError:  # pragma: no cover
    hid = None  # type: ignore


RAZER_VID = 0x1532
PACKET_SIZE = 90
DEFAULT_PID = 0x029F

# Import known Blade PIDs for prefer-order probing.
try:
    from .razer_devices import PREFERRED_PIDS as _PREFERRED_PIDS
except Exception:  # pragma: no cover
    _PREFERRED_PIDS = [DEFAULT_PID]


class GpuLevel(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


class CpuBoost(IntEnum):
    """Razer EC custom-mode CPU boost (Blade 16 2023 USB capture)."""

    LOW = 0  # ~factory quiet / ~55W envelope
    MEDIUM = 1
    HIGH = 2
    BOOST = 3
    OVERCLOCK = 4


LEVEL_NAMES = {
    GpuLevel.LOW: "low",
    GpuLevel.MEDIUM: "medium",
    GpuLevel.HIGH: "high",
}
NAME_TO_LEVEL = {v: k for k, v in LEVEL_NAMES.items()}

CPU_BOOST_NAMES = {
    CpuBoost.LOW: "low",
    CpuBoost.MEDIUM: "medium",
    CpuBoost.HIGH: "high",
    CpuBoost.BOOST: "boost",
    CpuBoost.OVERCLOCK: "overclock",
}
NAME_TO_CPU_BOOST = {v: k for k, v in CPU_BOOST_NAMES.items()}

# Approximate EC envelopes on Blade 16 (community / Synapse Custom tables).
# Not MSR Tau — firmware power/thermal policy.
EC_CPU_BOOST_HINT = {
    CpuBoost.LOW: "≈PL1~55W，基本无短时超发",
    CpuBoost.MEDIUM: "≈持续~60W，短时可到~80–90W",
    CpuBoost.HIGH: "≈更高持续，短时更高",
    CpuBoost.BOOST: "≈增强档（雷云 Boost）",
    CpuBoost.OVERCLOCK: "≈超频档（需雷云 CPU 超频）",
}


class PerfMode(IntEnum):
    BALANCED = 0
    CUSTOM = 4
    SILENT = 5


def cpu_boost_for_pl1(pl1_w: float) -> CpuBoost:
    """
    Map target PL1 to EC CPU boost.

    Never auto-select OVERCLOCK (4): that tier is tied to Synapse「CPU 超频」toggle
    and would make EC_CPU stick on overclock while the Synapse slider still shows 高/增强.
    """
    w = float(pl1_w)
    if w <= 55:
        return CpuBoost.LOW
    if w <= 70:
        return CpuBoost.MEDIUM
    if w <= 95:
        return CpuBoost.HIGH
    return CpuBoost.BOOST


def _crc(buf: bytearray) -> int:
    c = 0
    for i in range(2, 88):
        c ^= buf[i]
    return c & 0xFF


def build_packet(command: int, args: bytes) -> bytes:
    buf = bytearray(PACKET_SIZE)
    buf[0] = 0x00
    buf[1] = random.randint(1, 255)
    buf[5] = len(args) & 0xFF
    buf[6] = (command >> 8) & 0xFF
    buf[7] = command & 0xFF
    buf[8 : 8 + len(args)] = args
    buf[88] = _crc(buf)
    return bytes(buf)


def parse_packet(data: bytes) -> tuple[int, int, int, bytes]:
    if len(data) < PACKET_SIZE:
        data = data + bytes(PACKET_SIZE - len(data))
    status = data[0]
    txn = data[1]
    cmd = (data[6] << 8) | data[7]
    size = min(data[5], 80)
    args = data[8 : 8 + max(size, 8)]
    return status, txn, cmd, args


class SynapseGpuBackend:
    def __init__(self, product_id: Optional[int] = DEFAULT_PID) -> None:
        if hid is None:
            raise RuntimeError("hidapi package not installed (pip install hidapi)")
        self._product_id = product_id
        self._dev = None
        self._path: Optional[bytes] = None
        self._io_lock = threading.RLock()
        self._last_cpu_boost: Optional[CpuBoost] = None
        self._last_gpu_boost: Optional[GpuLevel] = None

    def open(self) -> None:
        from .razer_devices import PREFERRED_PIDS, RAZER_VID as _VID

        pools = []
        # Prefer known Blade laptop PIDs (2023 series first via PREFERRED_PIDS order).
        if self._product_id:
            pools.append(hid.enumerate(_VID, self._product_id))
        for pid in PREFERRED_PIDS:
            if self._product_id and pid == self._product_id:
                continue
            pools.append(hid.enumerate(_VID, pid))
        pools.append(hid.enumerate(_VID, 0))

        seen: set[bytes] = set()
        candidates = []
        for devices in pools:
            for info in devices:
                path = info.get("path")
                if not path or path in seen:
                    continue
                seen.add(path)
                candidates.append(info)
        if not candidates:
            raise RuntimeError("No Razer HID devices found (VID 0x1532)")

        def rank(info: dict) -> tuple:
            iface = info.get("interface_number")
            return (0 if iface == 2 else 1, iface if iface is not None else 99)

        candidates.sort(key=rank)
        last_err: Exception | None = None

        # Prefer MI_02 quickly without long verified probes (avoids waking Synapse).
        for info in candidates:
            if info.get("interface_number") != 2:
                continue
            try:
                d = hid.device()
                d.open_path(info["path"])
                self._dev = d
                self._path = info["path"]
                return
            except Exception as e:
                last_err = e

        for info in candidates:
            try:
                d = hid.device()
                d.open_path(info["path"])
                self._dev = d
                self._path = info["path"]
                return
            except Exception as e:
                last_err = e
                try:
                    d.close()
                except Exception:
                    pass

        raise RuntimeError(f"Failed to open Razer EC interface: {last_err}")

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    def _ensure(self) -> None:
        if self._dev is None:
            self.open()

    def _send_fast(self, command: int, args: bytes, repeats: int = 2) -> None:
        """SET-only path: no readback (fast, less likely to relaunch Synapse)."""
        with self._io_lock:
            self._ensure()
            assert self._dev is not None
            for _ in range(max(1, repeats)):
                report = build_packet(command, args)
                try:
                    self._dev.send_feature_report(b"\x00" + report)
                except Exception:
                    # Re-open once on failure.
                    try:
                        self.close()
                        self.open()
                        assert self._dev is not None
                        self._dev.send_feature_report(b"\x00" + report)
                    except Exception:
                        pass
                time.sleep(0.008)

    def _exchange_raw(
        self,
        command: int,
        args: bytes,
        *,
        max_attempts: int = 3,
        read_tries: int = 6,
    ) -> tuple[bytes, int, int]:
        with self._io_lock:
            self._ensure()
            assert self._dev is not None
            last_err: Exception | None = None
            for attempt in range(max_attempts):
                report = build_packet(command, args)
                expected_txn = report[1]
                try:
                    self._dev.send_feature_report(b"\x00" + report)
                except Exception as exc:
                    last_err = exc
                    continue
                for _ in range(read_tries):
                    time.sleep(0.012)
                    try:
                        raw = self._dev.get_feature_report(0, PACKET_SIZE + 1)
                    except Exception as exc:
                        last_err = exc
                        continue
                    if not raw or len(raw) < 10:
                        continue
                    raw_b = bytes(raw)
                    body = raw_b[1 : 1 + PACKET_SIZE] if len(raw_b) >= PACKET_SIZE + 1 else raw_b
                    if len(body) < PACKET_SIZE:
                        body = body + bytes(PACKET_SIZE - len(body))
                    status, txn, cmd, out_args = parse_packet(body)
                    if cmd == command and txn == expected_txn and status in (0x01, 0x02, 0x03, 0x04):
                        return out_args, status, cmd
                time.sleep(0.02 * (attempt + 1))
            raise RuntimeError(f"HID read timeout 0x{command:04X}: {last_err}")

    def get_perf_mode(self) -> tuple[int, int]:
        out, _, _ = self._exchange_raw(0x0D82, bytes([0, 1, 0, 0]))
        return int(out[2]), int(out[3])

    def set_perf_mode(self, perf_mode: int, fan_mode: int = 0) -> None:
        for zone in (1, 2):
            self._send_fast(0x0D02, bytes([0x01, zone, int(perf_mode) & 0xFF, int(fan_mode) & 0xFF]))

    def set_perf_mode_custom(self) -> None:
        self.set_perf_mode(PerfMode.CUSTOM, 0)

    def set_gpu_boost(self, level: GpuLevel) -> None:
        # Blade 16 capture: 0d07 argc=3 args=01 02 <gpu_level>
        self._send_fast(0x0D07, bytes([0x01, 0x02, int(level) & 0xFF]))
        self._last_gpu_boost = GpuLevel(int(level))

    def set_cpu_boost(self, level: CpuBoost | int) -> None:
        # Blade 16 capture: 0d07 argc=3 args=01 01 <cpu_level>
        self._send_fast(0x0D07, bytes([0x01, 0x01, int(level) & 0xFF]))
        self._last_cpu_boost = CpuBoost(int(level))

    def get_cpu_boost(self) -> CpuBoost:
        last_err: Exception | None = None
        for args in (bytes([0x01, 0x01, 0x00]), bytes([0x00, 0x01, 0x00])):
            try:
                out, _, _ = self._exchange_raw(
                    0x0D87, args, max_attempts=1, read_tries=3
                )
                val = CpuBoost(int(out[2]) & 0xFF)
                self._last_cpu_boost = val
                return val
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        raise RuntimeError(f"get_cpu_boost failed: {last_err}")

    def get_gpu_boost(self) -> GpuLevel:
        last_err: Exception | None = None
        for args in (bytes([0x01, 0x02, 0x00]), bytes([0x00, 0x02, 0x00])):
            try:
                out, _, _ = self._exchange_raw(
                    0x0D87, args, max_attempts=1, read_tries=3
                )
                val = GpuLevel(int(out[2]) & 0xFF)
                self._last_gpu_boost = val
                return val
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        raise RuntimeError(f"get_gpu_boost failed: {last_err}")

    def peek_boosts(self) -> tuple[str, str]:
        """UI-friendly readout; keep last good value on HID timeout."""
        from app.i18n import format_ec_line, t

        try:
            cpu = self.get_cpu_boost()
            name = CPU_BOOST_NAMES.get(cpu, str(int(cpu)))
            cpu_txt = format_ec_line(name, int(cpu), stale=False, hint=True)
        except Exception:
            if self._last_cpu_boost is not None:
                cpu = self._last_cpu_boost
                name = CPU_BOOST_NAMES.get(cpu, str(int(cpu)))
                cpu_txt = format_ec_line(name, int(cpu), stale=True, hint=False)
            else:
                cpu_txt = t("read_fail_timeout")
        try:
            gpu = self.get_gpu_boost()
            name = LEVEL_NAMES.get(gpu, str(int(gpu)))
            gpu_txt = format_ec_line(name, int(gpu), stale=False, hint=False)
        except Exception:
            if self._last_gpu_boost is not None:
                gpu = self._last_gpu_boost
                name = LEVEL_NAMES.get(gpu, str(int(gpu)))
                gpu_txt = format_ec_line(name, int(gpu), stale=True, hint=False)
            else:
                gpu_txt = t("read_fail_timeout")
        return cpu_txt, gpu_txt

    def preserve_cpu_boost(self, fn):
        """Run HID writes without letting Custom/fan mode drop EC CPU boost to low (~55W)."""
        prev = None
        try:
            prev = self.get_cpu_boost()
        except Exception:
            prev = None
        try:
            return fn()
        finally:
            if prev is not None:
                try:
                    self.set_cpu_boost(prev)
                except Exception:
                    pass

    def read_boost_state(self) -> str:
        """Best-effort EC CPU/GPU boost readout for diagnostics."""
        parts: list[str] = []
        try:
            cpu = self.get_cpu_boost()
            hint = EC_CPU_BOOST_HINT.get(cpu, "")
            parts.append(f"EC_CPU={CPU_BOOST_NAMES.get(cpu, cpu)}{(' ' + hint) if hint else ''}")
        except Exception as exc:  # noqa: BLE001
            parts.append(f"EC_CPU=读失败({exc})")
        try:
            gpu = self.get_gpu_boost()
            parts.append(f"EC_GPU={LEVEL_NAMES.get(gpu, gpu)}")
        except Exception as exc:  # noqa: BLE001
            parts.append(f"EC_GPU=读失败({exc})")
        try:
            mode, fan = self.get_perf_mode()
            parts.append(f"mode={mode}/fan={fan}")
        except Exception:
            pass
        return " | ".join(parts)

    def ensure_cpu_boost_at_least(self, level: CpuBoost | int = CpuBoost.BOOST) -> CpuBoost:
        """Raise EC CPU boost only if current tier is lower; never force OVERCLOCK."""
        want = CpuBoost(min(int(level), int(CpuBoost.BOOST)))
        try:
            cur = self.get_cpu_boost()
            if int(cur) >= int(want):
                return cur
        except Exception:
            pass
        self.set_cpu_boost(want)
        return want

    def ensure_cpu_boost(self, level: CpuBoost | int = CpuBoost.BOOST) -> CpuBoost:
        """Force EC CPU boost (capped at BOOST unless caller explicitly wants OVERCLOCK)."""
        lvl = CpuBoost(int(level))
        self.set_cpu_boost(lvl)
        return lvl

    def set_max_fan(self, enabled: bool) -> None:
        self._send_fast(0x070F, bytes([0x02 if enabled else 0x00]))

    def get_fan_rpm(self, zone: int = 1) -> int:
        # Fan telemetry is polled often — keep HID retries short to avoid UI stalls.
        out, _, _ = self._exchange_raw(
            0x0D81,
            bytes([0, int(zone) & 0xFF, 0]),
            max_attempts=2,
            read_tries=4,
        )
        return int(out[2]) * 100

    def get_fans_rpm(self) -> tuple[int, int]:
        z1 = self.get_fan_rpm(1)
        try:
            z2 = self.get_fan_rpm(2)
        except Exception:
            z2 = z1
        return z1, z2

    def set_fan_rpm_zone(self, zone: int, rpm: int) -> None:
        """
        Set one fan zone target RPM.

        Important (Blade EC behavior):
        - fan_mode=0 (auto): EC owns the curve and can fully stop at low temp.
        - fan_mode=1 (manual) + coded RPM: fixed speed; many firmwares ignore 0
          or clamp to ~2000, so "manual 0" cannot replicate auto stop.

        Therefore rpm<=0 hands the zone back to auto (same path as 档位「自动」);
        rpm>0 uses manual + coded RPM/100.
        """
        rpm = int(rpm)
        if rpm < 0 or rpm > 5500:
            raise ValueError("风扇转速需在 0-5500 RPM（0=交回 EC 自动，低温可停转）")
        z = 1 if int(zone) <= 1 else 2
        if rpm <= 0:
            # Match apply_fan("auto"): CUSTOM + auto fan mode per zone.
            self._send_fast(0x0D02, bytes([0x01, z, int(PerfMode.CUSTOM) & 0xFF, 0x00]))
            return
        self._send_fast(0x0D02, bytes([0x01, z, int(PerfMode.CUSTOM) & 0xFF, 0x01]))
        coded = max(1, min(55, rpm // 100))
        self._send_fast(0x0D01, bytes([0x01, z, coded]))

    def set_fan_rpm(self, rpm: int) -> None:
        self.set_fan_rpm_zone(1, rpm)
        self.set_fan_rpm_zone(2, rpm)

    def apply_fan(self, fan_mode: str = "auto", fan_rpm: int = 3000) -> str:
        mode = (fan_mode or "auto").lower()
        if mode == "max":
            self.set_perf_mode(PerfMode.CUSTOM, 0)
            self.set_max_fan(True)
            return "max"
        if mode == "manual":
            rpm = int(fan_rpm)
            self.set_max_fan(False)
            # 0 → per-zone auto (can stop); >0 → manual fixed RPM.
            self.set_fan_rpm(rpm)
            return f"manual:{rpm}"
        self.set_perf_mode(PerfMode.CUSTOM, 0)
        self.set_max_fan(False)
        return "auto"

    def apply(
        self,
        level_name: str,
        max_fan: bool = False,
        fan_mode: Optional[str] = None,
        fan_rpm: int = 3000,
        cpu_boost: Optional[CpuBoost | int] = None,
        pl1_w: Optional[float] = None,
        *,
        touch_cpu_boost: bool = True,
    ) -> str:
        level = NAME_TO_LEVEL.get(level_name.lower())
        if level is None:
            raise ValueError(f"Invalid gpu_level: {level_name}")
        if fan_mode is None:
            fan_mode = "max" if max_fan else "auto"
        fan_mode = fan_mode.lower()

        if touch_cpu_boost:
            if cpu_boost is None:
                cpu_boost = (
                    cpu_boost_for_pl1(pl1_w) if pl1_w is not None else CpuBoost.BOOST
                )
            cpu_boost = CpuBoost(int(cpu_boost))

        fan_msg = self.apply_fan(fan_mode, fan_rpm)
        if fan_mode == "manual":
            self.set_max_fan(False)
            if touch_cpu_boost:
                self.set_cpu_boost(cpu_boost)  # type: ignore[arg-type]
            self.set_gpu_boost(level)
            # set_fan_rpm chooses auto (0) vs manual (>0) per zone.
            self.set_fan_rpm(int(fan_rpm))
        else:
            self.set_perf_mode_custom()
            # CPU boost MUST be set when we own TDP — custom defaults to CPU low (~55W).
            if touch_cpu_boost:
                self.set_cpu_boost(cpu_boost)  # type: ignore[arg-type]
            self.set_gpu_boost(level)
            if fan_mode == "max":
                self.set_max_fan(True)
        cpu_tag = (
            CPU_BOOST_NAMES.get(CpuBoost(int(cpu_boost)), str(cpu_boost))  # type: ignore[arg-type]
            if touch_cpu_boost
            else "keep"
        )
        return f"{level_name.lower()}|cpu={cpu_tag}|fan={fan_msg}"
