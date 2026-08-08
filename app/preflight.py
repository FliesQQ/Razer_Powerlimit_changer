"""Startup dependency checks + official download helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class DepLevel(str, Enum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


@dataclass
class Dependency:
    id: str
    name: str
    level: DepLevel
    ok: bool
    detail: str = ""
    download_url: str = ""
    # Optional direct installer URL for assisted download (may break over time).
    installer_url: str = ""
    installer_name: str = ""


@dataclass
class PreflightReport:
    items: list[Dependency] = field(default_factory=list)
    device_summary: str = ""
    cpu_vendor: str = ""
    can_continue: bool = True
    blockers: list[str] = field(default_factory=list)

    @property
    def missing_required(self) -> list[Dependency]:
        return [d for d in self.items if d.level == DepLevel.REQUIRED and not d.ok]

    @property
    def missing_any(self) -> list[Dependency]:
        return [d for d in self.items if not d.ok]


DOWNLOADS = {
    "xtu": {
        "url": "https://www.intel.com/content/www/us/en/download/17881/intel-extreme-tuning-utility-intel-xtu.html",
        "installer_url": "",
        "installer_name": "",
    },
    "afterburner": {
        "url": "https://www.msi.com/Landing/afterburner",
        "installer_url": "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup.zip",
        "installer_name": "MSIAfterburnerSetup.zip",
    },
    "nvidia": {
        "url": "https://www.nvidia.com/Download/index.aspx",
        "installer_url": "",
        "installer_name": "",
    },
    "synapse": {
        "url": "https://www.razer.com/synapse-3",
        "installer_url": "",
        "installer_name": "",
    },
    "vc_redist": {
        "url": "https://aka.ms/vs/17/release/vc_redist.x64.exe",
        "installer_url": "https://aka.ms/vs/17/release/vc_redist.x64.exe",
        "installer_name": "vc_redist.x64.exe",
    },
}


def _nvidia_smi_ok() -> tuple[bool, str]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        # Common install path
        cand = Path(r"C:\Windows\System32\nvidia-smi.exe")
        exe = str(cand) if cand.is_file() else None
    if not exe:
        return False, "未找到 nvidia-smi（需 NVIDIA 驱动）"
    try:
        cp = subprocess.run(
            [exe, "-L"],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        out = (cp.stdout or "").strip()
        if cp.returncode != 0 or not out:
            return False, "nvidia-smi 无法列出 GPU"
        return True, out.splitlines()[0][:120]
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _cpu_vendor() -> str:
    try:
        import platform

        name = platform.processor() or ""
        # More reliable on Windows via env / WMI-ish registry is overkill; use cpuinfo from wmic fallback.
        if not name:
            cp = subprocess.run(
                ["wmic", "cpu", "get", "Name"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            name = cp.stdout or ""
        low = name.lower()
        if "intel" in low:
            return "Intel"
        if "amd" in low or "ryzen" in low:
            return "AMD"
        # Try registry CentralProcessor
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                low = str(val).lower()
                if "intel" in low:
                    return "Intel"
                if "amd" in low or "ryzen" in low:
                    return "AMD"
                return str(val)[:60]
        except Exception:
            return name[:60] or "Unknown"
    except Exception:
        return "Unknown"


def _winring0_ok() -> tuple[bool, str]:
    try:
        from app.paths import vendor_winring0_dir

        d = vendor_winring0_dir()
        dll = d / "WinRing0x64.dll"
        sysf = d / "WinRing0x64.sys"
        if dll.is_file() and sysf.is_file():
            return True, str(d)
        return False, f"缺少 WinRing0x64.dll/.sys（期望目录: {d}）"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _xtu_ok() -> tuple[bool, str]:
    try:
        from app.backends.xtu_detect import detect_xtu_path

        p = detect_xtu_path()
        if p:
            return True, str(p)
        return False, "未安装 Intel XTU（降压备用/对照可选）"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _afterburner_ok() -> tuple[bool, str]:
    try:
        from app.backends.afterburner import AfterburnerBackend

        ab = AfterburnerBackend()
        if ab.available:
            return True, str(ab.exe)
        return False, "未安装 MSI Afterburner（可选：档位联动超频配置）"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _synapse_ok() -> tuple[bool, str]:
    # Synapse is NOT required for HID; detect for user awareness only.
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Razer" / "Synapse3" / "WPFUI" / "Framework" / "Razer Synapse 3.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Razer" / "RazerAppEngine" / "RazerAppEngine.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Razer" / "Synapse3",
    ]
    for c in candidates:
        if c.exists():
            return True, str(c)
    return False, "未检测到雷云 Synapse（本工具 GPU/风扇不依赖它；有时可并存）"


def run_preflight() -> PreflightReport:
    from app.backends.razer_devices import compatibility_summary, detect_blade_device

    report = PreflightReport()
    report.cpu_vendor = _cpu_vendor()
    device = detect_blade_device()
    report.device_summary = compatibility_summary(device)

    wr_ok, wr_detail = _winring0_ok()
    report.items.append(
        Dependency(
            id="winring0",
            name="WinRing0 驱动文件",
            level=DepLevel.REQUIRED,
            ok=wr_ok,
            detail=wr_detail,
            download_url="",  # bundled; do not fetch from random mirrors
        )
    )

    blade_ok = device is not None
    report.items.append(
        Dependency(
            id="razer_hid",
            name="雷蛇笔记本 HID (Blade EC)",
            level=DepLevel.REQUIRED,
            ok=blade_ok,
            detail=(
                f"{device.name} PID {device.pid_hex}"
                if device
                else "未找到 Blade 设备（请确认是雷蛇笔记本且未禁用 HID）"
            ),
            download_url=DOWNLOADS["synapse"]["url"],
        )
    )

    nv_ok, nv_detail = _nvidia_smi_ok()
    report.items.append(
        Dependency(
            id="nvidia",
            name="NVIDIA 驱动 (nvidia-smi)",
            level=DepLevel.RECOMMENDED,
            ok=nv_ok,
            detail=nv_detail,
            download_url=DOWNLOADS["nvidia"]["url"],
        )
    )

    xtu_ok, xtu_detail = _xtu_ok()
    report.items.append(
        Dependency(
            id="xtu",
            name="Intel Extreme Tuning Utility",
            level=DepLevel.OPTIONAL if report.cpu_vendor != "AMD" else DepLevel.OPTIONAL,
            ok=xtu_ok or report.cpu_vendor == "AMD",
            detail=xtu_detail if report.cpu_vendor != "AMD" else "AMD 平台可跳过 XTU",
            download_url=DOWNLOADS["xtu"]["url"],
        )
    )

    ab_ok, ab_detail = _afterburner_ok()
    meta_ab = DOWNLOADS["afterburner"]
    report.items.append(
        Dependency(
            id="afterburner",
            name="MSI Afterburner",
            level=DepLevel.OPTIONAL,
            ok=ab_ok,
            detail=ab_detail,
            download_url=meta_ab["url"],
            installer_url=meta_ab["installer_url"],
            installer_name=meta_ab["installer_name"],
        )
    )

    syn_ok, syn_detail = _synapse_ok()
    report.items.append(
        Dependency(
            id="synapse",
            name="Razer Synapse（可选）",
            level=DepLevel.OPTIONAL,
            ok=True,  # never block
            detail=("已安装: " + syn_detail) if syn_ok else syn_detail,
            download_url=DOWNLOADS["synapse"]["url"],
        )
    )

    # CPU note as soft blocker warning for AMD
    if report.cpu_vendor == "AMD":
        report.items.append(
            Dependency(
                id="cpu_msr",
                name="Intel MSR 功耗/降压",
                level=DepLevel.OPTIONAL,
                ok=False,
                detail="当前 CPU 为 AMD：CPU PL1/PL2 与 MSR 降压不可用，仅 GPU/风扇可用",
            )
        )

    report.blockers = [d.name for d in report.missing_required]
    report.can_continue = len(report.blockers) == 0
    return report


def open_download(dep: Dependency) -> None:
    if dep.download_url:
        webbrowser.open(dep.download_url)


def download_and_launch_installer(
    dep: Dependency,
    *,
    progress: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Download optional installer to a temp folder and launch it.
    Returns local path. Raises on failure.
    """
    if not dep.installer_url:
        raise RuntimeError(f"{dep.name} 无稳定直链，请打开官网下载页手动安装")

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    dest_dir = Path(tempfile.gettempdir()) / "BladePower_installers"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = dep.installer_name or Path(dep.installer_url).name or f"{dep.id}_setup.exe"
    dest = dest_dir / name

    log(f"正在下载 {dep.name} …")
    urllib.request.urlretrieve(dep.installer_url, dest)  # noqa: S310 - official vendor URL
    log(f"下载完成: {dest}")

    # Zip → user must extract; exe → launch
    if dest.suffix.lower() == ".zip":
        log("已下载为 ZIP，正在打开所在文件夹（请解压后运行安装程序）")
        subprocess.Popen(["explorer", "/select,", str(dest)])
        return str(dest)

    log("正在启动安装程序…")
    os.startfile(str(dest))  # noqa: S606
    return str(dest)
