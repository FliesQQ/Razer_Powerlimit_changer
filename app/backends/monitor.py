"""Read GPU power telemetry via nvidia-smi."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class GpuPowerStatus:
    name: str = ""
    power_draw_w: Optional[float] = None
    ceiling_w: Optional[float] = None
    default_w: Optional[float] = None
    min_w: Optional[float] = None
    max_w: Optional[float] = None
    raw_error: str = ""


def _run(args: list[str]) -> str:
    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return (cp.stdout or "") + (cp.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


def _parse_float(text: str) -> Optional[float]:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*W?", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


class MonitorBackend:
    def read_gpu(self) -> GpuPowerStatus:
        status = GpuPowerStatus()
        csv = _run(
            [
                "nvidia-smi",
                "--query-gpu=name,power.draw,power.limit,power.default_limit,power.min_limit,power.max_limit",
                "--format=csv,noheader,nounits",
            ]
        )
        if csv.startswith("ERROR") or "Failed" in csv or "not found" in csv.lower():
            # Fall back to query POWER section.
            q = _run(["nvidia-smi", "-q", "-d", "POWER"])
            status.raw_error = csv.strip()[:200]
            for line in q.splitlines():
                line = line.strip()
                if line.startswith("Product Name") or "GPU 0000" in line:
                    continue
                if "Instantaneous Power Draw" in line or line.startswith("Power Draw"):
                    status.power_draw_w = _parse_float(line.split(":")[-1])
                elif "Current Power Limit" in line:
                    status.ceiling_w = _parse_float(line.split(":")[-1])
                elif "Default Power Limit" in line and status.default_w is None:
                    status.default_w = _parse_float(line.split(":")[-1])
                elif "Min Power Limit" in line:
                    status.min_w = _parse_float(line.split(":")[-1])
                elif "Max Power Limit" in line:
                    status.max_w = _parse_float(line.split(":")[-1])
            return status

        parts = [p.strip() for p in csv.strip().split(",")]
        if len(parts) >= 1:
            status.name = parts[0]
        if len(parts) >= 2:
            status.power_draw_w = _parse_float(parts[1])
        if len(parts) >= 3:
            status.ceiling_w = _parse_float(parts[2])
        if len(parts) >= 4:
            status.default_w = _parse_float(parts[3])
        if len(parts) >= 5:
            status.min_w = _parse_float(parts[4])
        if len(parts) >= 6:
            status.max_w = _parse_float(parts[5])

        # Ceiling often only in -q POWER on laptops.
        if status.ceiling_w is None:
            q = _run(["nvidia-smi", "-q", "-d", "POWER"])
            for line in q.splitlines():
                if "Current Power Limit" in line:
                    status.ceiling_w = _parse_float(line.split(":")[-1])
                    break
        return status

    def read_gpu_sensors(self) -> tuple[Optional[float], Optional[float]]:
        """Return (power_draw_w, temperature_c) in one nvidia-smi call."""
        csv = _run(
            [
                "nvidia-smi",
                "--query-gpu=power.draw,temperature.gpu",
                "--format=csv,noheader,nounits",
            ]
        )
        if csv.startswith("ERROR") or "Failed" in csv or "not found" in csv.lower():
            g = self.read_gpu()
            return g.power_draw_w, None
        parts = [p.strip() for p in csv.strip().split(",")]
        power = _parse_float(parts[0]) if parts else None
        temp = None
        if len(parts) >= 2:
            try:
                temp = float(parts[1])
            except ValueError:
                temp = _parse_float(parts[1])
        return power, temp
