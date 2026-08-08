"""Windows logon auto-start (Task Scheduler preferred, Run key fallback)."""

from __future__ import annotations

import subprocess
import sys
import winreg
from pathlib import Path

TASK_NAME = "BladePower"
RUN_VALUE = "BladePower"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command(*, minimized: bool = True) -> str:
    """Command line used for auto-start."""
    flag = " --minimized" if minimized else ""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return f'"{exe}"{flag}'
    # Dev: prefer pythonw to avoid console flash; fall back to python.
    py = Path(sys.executable).resolve()
    # Prefer pythonw.exe beside python.exe
    pyw = py.with_name("pythonw.exe")
    runner = pyw if pyw.is_file() else py
    script = Path(__file__).resolve().parents[1] / "run_app.py"
    return f'"{runner}" "{script}"{flag}'


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        return int(p.returncode), out
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def _task_exists() -> bool:
    code, _ = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    return code == 0


def _run_key_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except OSError:
        return False


def is_enabled() -> bool:
    return _task_exists() or _run_key_enabled()


def enable() -> tuple[bool, str]:
    """
    Register auto-start at user logon with highest privileges when possible.
    Returns (ok, message).
    """
    tr = launch_command(minimized=True)
    code, out = _run(
        [
            "schtasks",
            "/Create",
            "/TN",
            TASK_NAME,
            "/TR",
            tr,
            "/SC",
            "ONLOGON",
            "/RL",
            "HIGHEST",
            "/F",
        ]
    )
    if code == 0:
        # Prefer task only — remove legacy Run key if present.
        _clear_run_key()
        return True, "已通过任务计划程序设置开机自启（最高权限，登录时静默启动）"

    # Fallback: HKCU Run (may UAC-prompt because app re-elevates).
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, tr)
        return True, f"任务计划失败，已改用注册表启动项（可能弹出 UAC）: {out or 'ok'}"
    except OSError as exc:
        return False, f"开机自启设置失败: 任务计划={out or code}; 注册表={exc}"


def disable() -> tuple[bool, str]:
    msgs: list[str] = []
    ok = True
    if _task_exists():
        code, out = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
        if code != 0:
            ok = False
            msgs.append(f"删除任务失败: {out or code}")
        else:
            msgs.append("已删除计划任务")
    if _run_key_enabled():
        if _clear_run_key():
            msgs.append("已清除注册表启动项")
        else:
            ok = False
            msgs.append("清除注册表启动项失败")
    if not msgs:
        msgs.append("开机自启本来未启用")
    return ok, "；".join(msgs)


def _clear_run_key() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> tuple[bool, str]:
    return enable() if enabled else disable()
