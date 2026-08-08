"""Razer Blade laptop HID identity / 2023-series compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    import hid
except ImportError:  # pragma: no cover
    hid = None  # type: ignore


RAZER_VID = 0x1532

# OpenRazer / community-confirmed laptop keyboard/EC PIDs.
BLADE_MODELS: dict[int, dict[str, str]] = {
    0x029D: {
        "name": "Blade 14 (2023)",
        "series": "2023",
        "model": "RZ09-0482",
        "cpu_note": "多为 AMD Ryzen：CPU PL/降压(MSR)通常不可用，GPU/风扇 HID 可试",
    },
    0x029E: {
        "name": "Blade 15 (2023)",
        "series": "2023",
        "model": "RZ09-0428",
        "cpu_note": "Intel：CPU/GPU/风扇预期可用，GPU 瓦数档因显卡 SKU 而异",
    },
    0x029F: {
        "name": "Blade 16 (2023)",
        "series": "2023",
        "model": "RZ09-0483",
        "cpu_note": "主要验证机型：CPU/GPU/风扇均已实测路径",
    },
    0x02A0: {
        "name": "Blade 18 (2023)",
        "series": "2023",
        "model": "RZ09-0484",
        "cpu_note": "协议同类预期可用；风扇上限/GPU 高档瓦数可能与 16 寸不同",
    },
    0x028C: {
        "name": "Blade 14 (2022)",
        "series": "2022",
        "model": "RZ09-0427",
        "cpu_note": "未完整验证",
    },
    0x02B6: {
        "name": "Blade 14 (2024)",
        "series": "2024",
        "model": "RZ09-0508",
        "cpu_note": "未完整验证",
    },
    0x02B8: {
        "name": "Blade 18 (2024)",
        "series": "2024",
        "model": "RZ09-0509",
        "cpu_note": "未完整验证",
    },
}

# Prefer probing known Blade PIDs before scanning all Razer devices.
PREFERRED_PIDS: list[int] = [
    0x029F,
    0x02A0,
    0x029E,
    0x029D,
    0x02B6,
    0x02B8,
    0x028C,
]


@dataclass
class RazerDeviceInfo:
    product_id: int
    name: str
    series: str
    model: str
    cpu_note: str
    interface_number: Optional[int] = None
    path: Optional[bytes] = None

    @property
    def pid_hex(self) -> str:
        return f"0x{self.product_id:04X}"

    @property
    def is_2023(self) -> bool:
        return self.series == "2023"


def _meta(pid: int) -> dict[str, str]:
    return BLADE_MODELS.get(
        pid,
        {
            "name": f"Razer USB {pid:#06x}",
            "series": "unknown",
            "model": "-",
            "cpu_note": "未知机型：将尝试通用 HID 协议",
        },
    )


def detect_blade_device() -> Optional[RazerDeviceInfo]:
    """Find a Razer Blade EC/keyboard HID interface (prefer MI_02)."""
    if hid is None:
        return None

    by_pid: dict[int, list[dict]] = {}
    for pid in PREFERRED_PIDS:
        for info in hid.enumerate(RAZER_VID, pid):
            by_pid.setdefault(pid, []).append(info)
    # Fallback: any Razer device that looks like a Blade product string.
    if not by_pid:
        for info in hid.enumerate(RAZER_VID, 0):
            pid = int(info.get("product_id") or 0)
            prod = (info.get("product_string") or "").lower()
            if pid in BLADE_MODELS or "blade" in prod:
                by_pid.setdefault(pid, []).append(info)

    if not by_pid:
        return None

    # Prefer validated / preferred PID order, then MI_02.
    for pid in PREFERRED_PIDS:
        if pid not in by_pid:
            continue
        infos = sorted(
            by_pid[pid],
            key=lambda d: (0 if d.get("interface_number") == 2 else 1, d.get("interface_number") or 99),
        )
        info = infos[0]
        meta = _meta(pid)
        return RazerDeviceInfo(
            product_id=pid,
            name=meta["name"],
            series=meta["series"],
            model=meta["model"],
            cpu_note=meta["cpu_note"],
            interface_number=info.get("interface_number"),
            path=info.get("path"),
        )

    pid = next(iter(by_pid))
    infos = by_pid[pid]
    info = infos[0]
    meta = _meta(pid)
    return RazerDeviceInfo(
        product_id=pid,
        name=meta["name"],
        series=meta["series"],
        model=meta["model"],
        cpu_note=meta["cpu_note"],
        interface_number=info.get("interface_number"),
        path=info.get("path"),
    )


def compatibility_summary(device: Optional[RazerDeviceInfo]) -> str:
    if device is None:
        return (
            "未检测到雷蛇笔记本 HID。本工具 GPU/风扇依赖 Blade EC 协议，"
            "对 2023 系列（14/15/16/18）协议大体同类，但仅 Blade 16 2023 做过完整实测。"
        )
    lines = [
        f"检测到: {device.name} ({device.model}, PID {device.pid_hex})",
        device.cpu_note,
    ]
    if device.is_2023:
        lines.append(
            "2023 系列：GPU 档/风扇 HID 预期兼容；CPU PL/降压需 Intel + WinRing0；"
            "各机型 GPU 高档瓦数与风扇最高转速可能不同。"
        )
    else:
        lines.append("非 2023 验证机型：功能为 best-effort，请先小范围测试风扇/GPU 档。")
    return "\n".join(lines)
