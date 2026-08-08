"""G-Helper-like software fan curves for Razer Blade (temp → RPM)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence


DEFAULT_CPU_CURVE: list[tuple[int, int]] = [
    (40, 2200),
    (55, 2800),
    (70, 3600),
    (80, 4500),
    (90, 5500),
]
DEFAULT_GPU_CURVE: list[tuple[int, int]] = [
    (40, 2200),
    (55, 3000),
    (70, 3800),
    (80, 4800),
    (90, 5500),
]

RPM_MIN = 2000
RPM_MAX = 5500


def normalize_points(points: Sequence[Sequence[float]]) -> list[tuple[int, int]]:
    cleaned: list[tuple[int, int]] = []
    for p in points:
        if len(p) < 2:
            continue
        t = int(round(float(p[0])))
        r = int(round(float(p[1])))
        r = max(RPM_MIN, min(RPM_MAX, r))
        cleaned.append((t, r))
    cleaned.sort(key=lambda x: x[0])
    # Deduplicate temps (keep last).
    out: list[tuple[int, int]] = []
    for t, r in cleaned:
        if out and out[-1][0] == t:
            out[-1] = (t, r)
        else:
            out.append((t, r))
    return out or list(DEFAULT_CPU_CURVE)


def interpolate_rpm(temp_c: float, points: Sequence[tuple[int, int]]) -> int:
    pts = normalize_points(points)
    if temp_c <= pts[0][0]:
        return pts[0][1]
    if temp_c >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        t0, r0 = pts[i]
        t1, r1 = pts[i + 1]
        if t0 <= temp_c <= t1:
            if t1 == t0:
                return r1
            ratio = (temp_c - t0) / (t1 - t0)
            return int(round(r0 + (r1 - r0) * ratio))
    return pts[-1][1]


@dataclass
class FanCurveConfig:
    enabled: bool = False
    cpu_points: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_CPU_CURVE))
    gpu_points: list[tuple[int, int]] = field(default_factory=lambda: list(DEFAULT_GPU_CURVE))
    interval_s: float = 2.0

    @staticmethod
    def from_dict(d: Optional[dict]) -> "FanCurveConfig":
        d = d or {}
        cpu = normalize_points(d.get("cpu") or DEFAULT_CPU_CURVE)
        gpu = normalize_points(d.get("gpu") or DEFAULT_GPU_CURVE)
        return FanCurveConfig(
            enabled=bool(d.get("enabled", False)),
            cpu_points=cpu,
            gpu_points=gpu,
            interval_s=float(d.get("interval_s", 2.0)),
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "cpu": [list(p) for p in self.cpu_points],
            "gpu": [list(p) for p in self.gpu_points],
            "interval_s": self.interval_s,
        }


class FanCurveController:
    """Background loop: read temps → interpolate → set zone RPMs."""

    def __init__(
        self,
        *,
        synapse,
        temps,
        get_config: Callable[[], FanCurveConfig],
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._synapse = synapse
        self._temps = temps
        self._get_config = get_config
        self._on_status = on_status
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_cpu_rpm: Optional[int] = None
        self._last_gpu_rpm: Optional[int] = None
        self.last_status = "曲线未启动"
        self.last_cpu_c: Optional[float] = None
        self.last_gpu_c: Optional[float] = None
        self.last_cpu_rpm: Optional[int] = None
        self.last_gpu_rpm: Optional[int] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="FanCurve")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None

    def force_tick(self) -> None:
        self._tick(force=True)

    def _set_status(self, text: str) -> None:
        self.last_status = text
        if self._on_status:
            try:
                self._on_status(text)
            except Exception:
                pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                cfg = self._get_config()
                if cfg.enabled and self._synapse is not None:
                    self._tick(force=False)
                    sleep_s = max(1.0, float(cfg.interval_s))
                else:
                    sleep_s = 2.0
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"曲线错误: {exc}")
                sleep_s = 3.0
            self._stop.wait(sleep_s)

    def _tick(self, *, force: bool) -> None:
        cfg = self._get_config()
        if not cfg.enabled or self._synapse is None:
            return
        reading = self._temps.read()
        self.last_cpu_c = reading.cpu_c
        self.last_gpu_c = reading.gpu_c

        cpu_temp = reading.cpu_c if reading.cpu_c is not None else 50.0
        gpu_temp = reading.gpu_c if reading.gpu_c is not None else cpu_temp

        cpu_rpm = interpolate_rpm(cpu_temp, cfg.cpu_points)
        gpu_rpm = interpolate_rpm(gpu_temp, cfg.gpu_points)
        # Round to 100 RPM steps (EC coding).
        cpu_rpm = max(RPM_MIN, min(RPM_MAX, (cpu_rpm // 100) * 100))
        gpu_rpm = max(RPM_MIN, min(RPM_MAX, (gpu_rpm // 100) * 100))

        changed = (
            force
            or self._last_cpu_rpm is None
            or self._last_gpu_rpm is None
            or abs(cpu_rpm - self._last_cpu_rpm) >= 100
            or abs(gpu_rpm - self._last_gpu_rpm) >= 100
        )
        if changed:
            # Custom + manual fan mode, then per-zone RPM.
            self._synapse.set_perf_mode(4, 1)  # CUSTOM + manual
            self._synapse.set_max_fan(False)
            self._synapse.set_fan_rpm_zone(1, cpu_rpm)
            self._synapse.set_fan_rpm_zone(2, gpu_rpm)
            self._last_cpu_rpm = cpu_rpm
            self._last_gpu_rpm = gpu_rpm
            # Brief settle; avoid readback (wakes Synapse).
            time.sleep(0.05)

        self.last_cpu_rpm = cpu_rpm
        self.last_gpu_rpm = gpu_rpm
        self._set_status(
            f"曲线: CPU {cpu_temp:.0f}°C→{cpu_rpm}  GPU {gpu_temp:.0f}°C→{gpu_rpm}"
        )
