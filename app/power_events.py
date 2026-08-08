"""Detect sleep/hibernate resume and invoke a callback (Windows)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Callable, Optional


WM_POWERBROADCAST = 0x0218
PBT_APMRESUMECRITICAL = 0x0006
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMESTANDBY = 0x0008
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMSUSPEND = 0x0004

DEVICE_NOTIFY_CALLBACK = 2
GWLP_WNDPROC = -4

_RESUME_WPARAMS = {
    PBT_APMRESUMECRITICAL,
    PBT_APMRESUMESUSPEND,
    PBT_APMRESUMESTANDBY,
    PBT_APMRESUMEAUTOMATIC,
}


class ResumeWatcher:
    """
    Multi-path resume detection:
    1) Subclass Tk root WndProc for WM_POWERBROADCAST (main thread)
    2) PowerRegisterSuspendResumeNotification callback
    3) Wall-clock vs monotonic drift poller (Modern Standby / missed msgs)
    """

    def __init__(self, root, on_resume: Callable[[], None]) -> None:
        self.root = root
        self.on_resume = on_resume
        self._armed = False
        self._last_fire = 0.0
        self._keep: list = []
        self._notify_handle = None
        self._old_wndproc = None
        self._last_wall = time.time()
        self._last_mono = time.monotonic()

    def start(self) -> None:
        self.root.after(200, self._install_wndproc_hook)
        self._install_suspend_resume_notify()
        self.root.after(2000, self._poll_clock_drift)

    def _fire(self) -> None:
        now = time.monotonic()
        # Debounce duplicate notifications from multiple sources.
        if now - self._last_fire < 2.0:
            return
        self._last_fire = now
        try:
            self.on_resume()
        except Exception:
            pass

    def _schedule_fire(self) -> None:
        # Defer onto Tk main loop (safe from any thread).
        try:
            self.root.after(0, self._fire)
        except Exception:
            self._fire()

    def _install_wndproc_hook(self) -> None:
        try:
            user32 = ctypes.windll.user32
            hwnd = int(self.root.winfo_id())
            if not hwnd:
                self.root.after(500, self._install_wndproc_hook)
                return

            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(
                LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )

            get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
            call_proc = user32.CallWindowProcW

            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            set_long.restype = ctypes.c_void_p
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_long.restype = ctypes.c_void_p
            call_proc.argtypes = [
                ctypes.c_void_p,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            call_proc.restype = LRESULT

            old = get_long(hwnd, GWLP_WNDPROC)
            self._old_wndproc = old

            def wnd_proc(h, msg, wparam, lparam):
                if msg == WM_POWERBROADCAST and int(wparam) in _RESUME_WPARAMS:
                    self._schedule_fire()
                return call_proc(old, h, msg, wparam, lparam)

            proc = WNDPROC(wnd_proc)
            self._keep.append(proc)
            set_long(hwnd, GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p))
        except Exception:
            pass

    def _install_suspend_resume_notify(self) -> None:
        try:
            powrprof = ctypes.WinDLL("powrprof")
            CALLBACK = ctypes.WINFUNCTYPE(
                wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p
            )

            class DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS(ctypes.Structure):
                _fields_ = [
                    ("Callback", CALLBACK),
                    ("Context", ctypes.c_void_p),
                ]

            def _cb(context, ntype, setting):
                if int(ntype) in _RESUME_WPARAMS or int(ntype) == PBT_APMRESUMESUSPEND:
                    self._schedule_fire()
                return 0

            cb = CALLBACK(_cb)
            params = DEVICE_NOTIFY_SUBSCRIBE_PARAMETERS(cb, None)
            self._keep.extend([cb, params])
            handle = ctypes.c_void_p()
            # HRESULT-style: 0 == S_OK
            hr = powrprof.PowerRegisterSuspendResumeNotification(
                DEVICE_NOTIFY_CALLBACK,
                ctypes.byref(params),
                ctypes.byref(handle),
            )
            if hr == 0:
                self._notify_handle = handle
                self._powrprof = powrprof
        except Exception:
            self._notify_handle = None

    def _poll_clock_drift(self) -> None:
        wall = time.time()
        mono = time.monotonic()
        d_wall = wall - self._last_wall
        d_mono = mono - self._last_mono
        # During sleep, wall time advances but monotonic often does not.
        if d_wall - d_mono > 4.0:
            self._schedule_fire()
        self._last_wall = wall
        self._last_mono = mono
        try:
            self.root.after(2000, self._poll_clock_drift)
        except Exception:
            pass

    def stop(self) -> None:
        try:
            if self._notify_handle is not None and getattr(self, "_powrprof", None):
                self._powrprof.PowerUnregisterSuspendResumeNotification(self._notify_handle)
        except Exception:
            pass
        self._notify_handle = None
