"""Razer Blade Synapse-compatible GPU/fan control via HID feature reports."""

from __future__ import annotations

import random
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


LEVEL_NAMES = {
    GpuLevel.LOW: "low",
    GpuLevel.MEDIUM: "medium",
    GpuLevel.HIGH: "high",
}
NAME_TO_LEVEL = {v: k for k, v in LEVEL_NAMES.items()}


class PerfMode(IntEnum):
    BALANCED = 0
    CUSTOM = 4
    SILENT = 5


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
        self._send_fast(0x0D07, bytes([0x00, 0x02, int(level) & 0xFF]))

    def get_gpu_boost(self) -> GpuLevel:
        out, _, _ = self._exchange_raw(0x0D87, bytes([0x00, 0x02, 0x00]))
        return GpuLevel(out[2])

    def set_max_fan(self, enabled: bool) -> None:
        self._send_fast(0x070F, bytes([0x02 if enabled else 0x00]))

    def get_fan_rpm(self, zone: int = 1) -> int:
        out, _, _ = self._exchange_raw(0x0D81, bytes([0, int(zone) & 0xFF, 0]))
        return int(out[2]) * 100

    def get_fans_rpm(self) -> tuple[int, int]:
        z1 = self.get_fan_rpm(1)
        try:
            z2 = self.get_fan_rpm(2)
        except Exception:
            z2 = z1
        return z1, z2

    def set_fan_rpm_zone(self, zone: int, rpm: int) -> None:
        rpm = int(rpm)
        if rpm < 2000 or rpm > 5500:
            raise ValueError("风扇转速需在 2000-5500 RPM")
        coded = max(1, min(55, rpm // 100))
        z = 1 if int(zone) <= 1 else 2
        self._send_fast(0x0D01, bytes([0, z, coded]))

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
            self.set_perf_mode(PerfMode.CUSTOM, 1)
            self.set_max_fan(False)
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
    ) -> str:
        level = NAME_TO_LEVEL.get(level_name.lower())
        if level is None:
            raise ValueError(f"Invalid gpu_level: {level_name}")
        if fan_mode is None:
            fan_mode = "max" if max_fan else "auto"
        fan_mode = fan_mode.lower()

        fan_msg = self.apply_fan(fan_mode, fan_rpm)
        if fan_mode == "manual":
            self.set_perf_mode(PerfMode.CUSTOM, 1)
            self.set_gpu_boost(level)
            self.set_fan_rpm(int(fan_rpm))
        else:
            self.set_perf_mode_custom()
            self.set_gpu_boost(level)
            if fan_mode == "max":
                self.set_max_fan(True)
        # No readback on apply path (speed + less Synapse churn).
        return f"{level_name.lower()}|fan={fan_msg}"
