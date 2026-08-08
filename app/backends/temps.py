"""CPU / GPU temperature helpers."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .winring0 import WinRing0

MSR_TEMPERATURE_TARGET = 0x1A2
MSR_THERM_STATUS = 0x19C  # per-core DTS (readout of the logical CPU sampled)
MSR_PACKAGE_THERM_STATUS = 0x1B1  # package DTS (closer to HWInfo "CPU Package")


@dataclass
class TempReading:
    cpu_c: Optional[float] = None
    gpu_c: Optional[float] = None
    cpu_source: str = ""  # "package" | "core" | "wmi" | ""


def _run(args: list[str]) -> str:
    try:
        cp = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return (cp.stdout or "") + (cp.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: {exc}"


def _tj_max(ring0: "WinRing0") -> int:
    target = ring0.read_msr(MSR_TEMPERATURE_TARGET)
    tj_max = (target >> 16) & 0xFF
    if tj_max < 60 or tj_max > 120:
        return 100
    return int(tj_max)


def _temp_from_therm_status(ring0: "WinRing0", msr: int, tj_max: int) -> Optional[float]:
    status = ring0.read_msr(msr)
    # Bit 31 = reading valid (when present).
    if msr == MSR_PACKAGE_THERM_STATUS and (status & (1 << 31)) == 0:
        return None
    readout = (status >> 16) & 0x7F
    return float(tj_max - readout)


def read_cpu_temp_msr(ring0: "WinRing0") -> tuple[Optional[float], str]:
    """Prefer package DTS (≈ HWInfo CPU Package); fall back to core DTS."""
    try:
        tj = _tj_max(ring0)
        pkg = _temp_from_therm_status(ring0, MSR_PACKAGE_THERM_STATUS, tj)
        if pkg is not None:
            return pkg, "package"
        core = _temp_from_therm_status(ring0, MSR_THERM_STATUS, tj)
        if core is not None:
            return core, "core"
    except Exception:
        pass
    return None, ""


def read_cpu_temp_wmi() -> Optional[float]:
    # Prefer package thermal zones via PowerShell / CIM (no extra deps).
    ps = (
        "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
        "-ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty CurrentTemperature"
    )
    out = _run(["powershell", "-NoProfile", "-Command", ps])
    if out.startswith("ERROR"):
        return None
    vals = []
    for tok in re.findall(r"\d+", out):
        try:
            # Tenths of Kelvin
            c = int(tok) / 10.0 - 273.15
            if 0 < c < 125:
                vals.append(c)
        except ValueError:
            continue
    if not vals:
        return None
    return round(max(vals), 1)


def read_gpu_temp() -> Optional[float]:
    csv = _run(
        [
            "nvidia-smi",
            "--query-gpu=temperature.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    if csv.startswith("ERROR") or "Failed" in csv:
        return None
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", csv)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


class TempMonitor:
    def __init__(self, ring0: Optional["WinRing0"] = None) -> None:
        self._ring0 = ring0

    def read_cpu(self) -> TempReading:
        cpu = None
        source = ""
        if self._ring0 is not None:
            cpu, source = read_cpu_temp_msr(self._ring0)
        if cpu is None:
            cpu = read_cpu_temp_wmi()
            source = "wmi" if cpu is not None else ""
        return TempReading(cpu_c=cpu, gpu_c=None, cpu_source=source)

    def read(self) -> TempReading:
        reading = self.read_cpu()
        reading.gpu_c = read_gpu_temp()
        return reading
