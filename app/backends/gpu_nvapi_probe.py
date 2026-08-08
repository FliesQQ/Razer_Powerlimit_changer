"""Optional NVAPI power-limit probe (expected unsupported on Razer laptops)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NvapiProbeResult:
    supported: bool
    message: str


def probe_gpu_power_write() -> NvapiProbeResult:
    """Best-effort note: absolute watt writes are OEM-locked on this machine."""
    return NvapiProbeResult(
        supported=False,
        message=(
            "本机 GPU 绝对 TDP 不可通过 nvidia-smi/NVAPI 写入；"
            "请使用 Synapse GPU 低/中/高。"
        ),
    )
