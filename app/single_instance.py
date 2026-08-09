"""Ensure only one BladePower process runs (Windows named mutex)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Optional

MUTEX_NAME = "Local\\BladePower_SingleInstance_Mutex"
ERROR_ALREADY_EXISTS = 183
_mutex_handle: Optional[wintypes.HANDLE] = None


def try_acquire() -> bool:
    """
    Acquire the process-wide mutex.
    Returns False if another instance already holds it.
    """
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        # If mutex creation fails, allow start rather than hard-blocking.
        return True
    err = int(kernel32.GetLastError())
    if err == ERROR_ALREADY_EXISTS:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        return False
    _mutex_handle = handle
    return True


def release() -> None:
    global _mutex_handle
    if _mutex_handle:
        try:
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        except Exception:
            pass
        _mutex_handle = None


def activate_existing(window_title: str = "Blade 16 功耗快捷切换") -> bool:
    """Best-effort: bring an existing main window to the foreground."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, window_title)
        if not hwnd:
            return False
        # Restore if minimized.
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


def ensure_single_instance(*, show_message: bool = True) -> bool:
    """
    Return True if this process may continue.
    On duplicate: try activate existing UI, optionally warn, then False.
    """
    if try_acquire():
        return True
    activate_existing()
    if show_message and sys.stderr is not None:
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "BladePower",
                "程序已在运行中，只允许同时打开一个实例。",
            )
            root.destroy()
        except Exception:
            print("BladePower 已在运行中。", file=sys.stderr)
    return False
