"""Screen brightness via dxva2 with PowerShell/WMI fallback (Windows)."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
from ctypes import wintypes
from typing import Optional

MONITOR_DEFAULTTOPRIMARY = 1
AC_OFFLINE = 0
AC_ONLINE = 1


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [
        ("hPhysicalMonitor", wintypes.HANDLE),
        ("szPhysicalMonitorDescription", wintypes.WCHAR * 128),
    ]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


def is_ac_power() -> bool:
    """True when on AC. Unknown → treat as battery (avoid falsely maxing brightness)."""
    st = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return False
    if st.ACLineStatus == AC_ONLINE:
        return True
    if st.ACLineStatus == AC_OFFLINE:
        return False
    return False


def clamp_brightness(val: int, oled_mode: bool) -> int:
    min_val = 60 if oled_mode else 0
    return max(min_val, min(100, int(val)))


def _last_win_error(prefix: str) -> str:
    code = ctypes.get_last_error()
    if not code:
        return prefix
    return f"{prefix} (WinError {code}: {ctypes.FormatError(code).strip()})"


class NativeBrightnessBackend:
    """dxva2 brightness — avoids spawning PowerShell each time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handles: list[wintypes.HANDLE] = []
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._dxva2 = ctypes.WinDLL("dxva2", use_last_error=True)

        self._user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
        self._user32.MonitorFromPoint.restype = wintypes.HMONITOR

        self._dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [
            wintypes.HMONITOR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL

        self._dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes = [
            wintypes.HMONITOR,
            wintypes.DWORD,
            ctypes.POINTER(PHYSICAL_MONITOR),
        ]
        self._dxva2.GetPhysicalMonitorsFromHMONITOR.restype = wintypes.BOOL

        self._dxva2.DestroyPhysicalMonitors.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(PHYSICAL_MONITOR),
        ]
        self._dxva2.DestroyPhysicalMonitors.restype = wintypes.BOOL

        self._dxva2.GetMonitorBrightness.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._dxva2.GetMonitorBrightness.restype = wintypes.BOOL

        self._dxva2.SetMonitorBrightness.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self._dxva2.SetMonitorBrightness.restype = wintypes.BOOL

    def _destroy_handles_unlocked(self) -> None:
        if not self._handles:
            return
        arr = (PHYSICAL_MONITOR * len(self._handles))()
        for i, h in enumerate(self._handles):
            arr[i].hPhysicalMonitor = h
        self._dxva2.DestroyPhysicalMonitors(wintypes.DWORD(len(arr)), arr)
        self._handles.clear()

    def _refresh_handles_unlocked(self) -> tuple[bool, str]:
        self._destroy_handles_unlocked()
        hmon = self._user32.MonitorFromPoint(POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        if not hmon:
            return False, _last_win_error("获取主显示器失败")

        count = wintypes.DWORD(0)
        if not self._dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count)):
            return False, _last_win_error("获取物理显示器数量失败")
        if count.value <= 0:
            return False, "未检测到可控亮度的物理显示器"

        arr = (PHYSICAL_MONITOR * count.value)()
        if not self._dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, count, arr):
            return False, _last_win_error("获取物理显示器句柄失败")

        self._handles = [arr[i].hPhysicalMonitor for i in range(count.value)]
        return True, ""

    def _ensure_handles_unlocked(self) -> tuple[bool, str]:
        if self._handles:
            return True, ""
        return self._refresh_handles_unlocked()

    @staticmethod
    def _percent_to_native(percent: int, min_v: int, max_v: int) -> int:
        if max_v <= min_v:
            return int(percent)
        return int(round(min_v + (max_v - min_v) * (percent / 100.0)))

    @staticmethod
    def _native_to_percent(cur_v: int, min_v: int, max_v: int) -> int:
        if max_v <= min_v:
            return max(0, min(100, int(cur_v)))
        pct = int(round((cur_v - min_v) * 100.0 / (max_v - min_v)))
        return max(0, min(100, pct))

    def set_percent(self, val: int) -> tuple[bool, str]:
        target_pct = max(0, min(100, int(val)))
        with self._lock:
            ok, reason = self._ensure_handles_unlocked()
            if not ok:
                return False, f"亮度设置失败：{reason}"

            for _retry in range(2):
                for handle in self._handles:
                    min_v = wintypes.DWORD(0)
                    cur_v = wintypes.DWORD(0)
                    max_v = wintypes.DWORD(100)
                    if self._dxva2.GetMonitorBrightness(
                        handle, ctypes.byref(min_v), ctypes.byref(cur_v), ctypes.byref(max_v)
                    ):
                        native_target = self._percent_to_native(
                            target_pct, min_v.value, max_v.value
                        )
                    else:
                        native_target = target_pct
                    if self._dxva2.SetMonitorBrightness(handle, wintypes.DWORD(native_target)):
                        return True, f"亮度已设置为 {target_pct}%"

                ok, reason = self._refresh_handles_unlocked()
                if not ok:
                    return False, f"亮度设置失败：{reason}"

            return False, f"亮度设置失败：{_last_win_error('调用 SetMonitorBrightness 失败')}"

    def get_percent(self) -> Optional[int]:
        with self._lock:
            ok, _ = self._ensure_handles_unlocked()
            if not ok:
                return None

            for _retry in range(2):
                for handle in self._handles:
                    min_v = wintypes.DWORD(0)
                    cur_v = wintypes.DWORD(0)
                    max_v = wintypes.DWORD(100)
                    if self._dxva2.GetMonitorBrightness(
                        handle, ctypes.byref(min_v), ctypes.byref(cur_v), ctypes.byref(max_v)
                    ):
                        return self._native_to_percent(cur_v.value, min_v.value, max_v.value)
                ok, _ = self._refresh_handles_unlocked()
                if not ok:
                    return None
            return None

    def shutdown(self) -> None:
        with self._lock:
            self._destroy_handles_unlocked()


class PowerShellBrightnessBackend:
    """WMI/CIM fallback when dxva2 is unavailable."""

    def __init__(self) -> None:
        self._creationflags = (
            subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )

    def _run_ps(self, cmd: str) -> Optional[subprocess.CompletedProcess]:
        try:
            return subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                creationflags=self._creationflags,
            )
        except OSError:
            return None

    def set_percent(self, val: int) -> tuple[bool, str]:
        target_pct = max(0, min(100, int(val)))
        ps_cmds = [
            (
                "Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods | "
                f"ForEach-Object {{ $_.WmiSetBrightness(1,{target_pct}) }} | Out-Null"
            ),
            (
                "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
                f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @"
                f"{{ Timeout=1; Brightness={target_pct} }} | Out-Null"
            ),
        ]
        errors: list[str] = []
        for cmd in ps_cmds:
            proc = self._run_ps(cmd)
            if proc is None:
                errors.append("无法启动 PowerShell")
                continue
            if proc.returncode == 0:
                return True, f"亮度已设置为 {target_pct}%"
            detail = (proc.stderr or proc.stdout or "").strip()
            errors.append(detail or f"PowerShell ExitCode={proc.returncode}")
        reason = "；".join(errors[-2:]) if errors else "未知错误"
        return False, f"亮度设置失败：{reason}"

    def get_percent(self) -> Optional[int]:
        ps_cmd = (
            "$b=(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness "
            "-ErrorAction SilentlyContinue | "
            "Select-Object -First 1 -ExpandProperty CurrentBrightness); "
            "if($null -ne $b){$b}else{exit 2}"
        )
        proc = self._run_ps(ps_cmd)
        if proc is None or proc.returncode != 0:
            return None
        try:
            return int((proc.stdout or "").strip())
        except ValueError:
            return None

    def shutdown(self) -> None:
        return None


class HybridBrightnessBackend:
    """Prefer native API; auto-fallback to PowerShell/WMI."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._native = NativeBrightnessBackend()
        self._fallback = PowerShellBrightnessBackend()
        self._prefer_fallback = False

    def set_prefer_fallback(self, enabled: bool) -> None:
        with self._lock:
            self._prefer_fallback = bool(enabled)

    def is_prefer_fallback(self) -> bool:
        with self._lock:
            return self._prefer_fallback

    def get_mode_label(self) -> str:
        with self._lock:
            if self._prefer_fallback:
                return "compat"
            return "native"

    def _mark_fallback(self) -> None:
        self._prefer_fallback = True

    def set_percent(self, val: int) -> tuple[bool, str]:
        with self._lock:
            if not self._prefer_fallback:
                ok, msg = self._native.set_percent(val)
                if ok:
                    return True, msg
                fb_ok, fb_msg = self._fallback.set_percent(val)
                if fb_ok:
                    self._mark_fallback()
                    return True, f"{fb_msg}（已自动启用兼容回退）"
                return False, msg

            fb_ok, fb_msg = self._fallback.set_percent(val)
            if fb_ok:
                return True, fb_msg
            ok, msg = self._native.set_percent(val)
            if ok:
                self._prefer_fallback = False
                return True, f"{msg}（已恢复原生模式）"
            return False, fb_msg

    def get_percent(self) -> Optional[int]:
        with self._lock:
            if self._prefer_fallback:
                v = self._fallback.get_percent()
                if v is not None:
                    return v
                v = self._native.get_percent()
                if v is not None:
                    self._prefer_fallback = False
                return v

            v = self._native.get_percent()
            if v is not None:
                return v
            v = self._fallback.get_percent()
            if v is not None:
                self._mark_fallback()
            return v

    def shutdown(self) -> None:
        with self._lock:
            self._native.shutdown()
            self._fallback.shutdown()
