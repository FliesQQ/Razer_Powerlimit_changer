"""Global hotkeys via Win32 RegisterHotKey on a dedicated message-only window.

All CreateWindow / RegisterHotKey / GetMessage run on one pump thread.
Callbacks are marshalled onto the Tk main loop via root.after — never subclass
the Tk HWND (that path hard-crashes with Tk + other WndProc hooks).
"""

from __future__ import annotations

import ctypes
import queue
import threading
from ctypes import wintypes
from typing import Any, Callable, Dict, Optional


WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_NULL = 0x0000
HWND_MESSAGE = -3

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_MAP: dict[str, int] = {
    **{str(i): 0x30 + i for i in range(10)},
    **{chr(c): c for c in range(ord("a"), ord("z") + 1)},
    **{f"f{i}": 0x70 + (i - 1) for i in range(1, 25)},
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "delete": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "page up": 0x21,
    "pageup": 0x21,
    "page down": 0x22,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "+": 0xBB,
    "-": 0xBD,
    "=": 0xBB,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "\\": 0xDC,
    "[": 0xDB,
    "]": 0xDD,
    ";": 0xBA,
    "'": 0xDE,
    "`": 0xC0,
}


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def normalize_hotkey(hk: str) -> str:
    s = (hk or "").strip().lower().replace(" ", "")
    s = s.replace("control", "ctrl").replace("option", "alt")
    return s


def parse_hotkey(hk: str) -> Optional[tuple[int, int]]:
    """Return (modifiers, vk) for Win32 RegisterHotKey, or None if unsupported."""
    raw = normalize_hotkey(hk)
    if not raw:
        return None
    parts = [p for p in raw.split("+") if p]
    if not parts:
        return None
    mods = 0
    key = None
    for p in parts:
        if p in {"ctrl", "control"}:
            mods |= MOD_CONTROL
        elif p in {"alt", "menu"}:
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p in {"win", "windows", "super", "meta", "cmd"}:
            mods |= MOD_WIN
        else:
            key = p
    if not key:
        return None
    vk = VK_MAP.get(key)
    if vk is None and key.startswith("page"):
        vk = VK_MAP.get(key.replace("page", "page "))
    if vk is None:
        return None
    return mods | MOD_NOREPEAT, int(vk)


class HotkeyService:
    def __init__(self, root=None) -> None:
        self._root = root
        self._registered_kb: list[str] = []
        self._win_ids: dict[int, Callable[[], None]] = {}
        self._next_id = 1
        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._cmds: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._life_lock = threading.Lock()
        self._backend_kb = None
        self._mode = "none"  # win32 | keyboard | none
        try:
            import keyboard as _keyboard

            self._backend_kb = _keyboard
        except Exception:
            self._backend_kb = None

    def bind_root(self, root) -> None:
        self._root = root

    @property
    def available(self) -> bool:
        return True

    @property
    def mode(self) -> str:
        return self._mode

    def _dispatch(self, cb: Callable[[], None]) -> None:
        def _safe() -> None:
            try:
                cb()
            except Exception:
                pass

        root = self._root
        if root is not None:
            try:
                root.after(0, _safe)
                return
            except Exception:
                pass
        threading.Thread(target=_safe, daemon=True, name="HotkeyCb").start()

    def _wake_pump(self) -> None:
        hwnd = self._hwnd
        if hwnd:
            try:
                ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), WM_NULL, 0, 0)
            except Exception:
                pass

    def _run_on_pump(self, fn: Callable[[], Any], timeout: float = 3.0) -> Any:
        """Execute fn on the message-pump thread (required for RegisterHotKey)."""
        box: dict[str, Any] = {}
        done = threading.Event()

        def wrap() -> None:
            try:
                box["r"] = fn()
            except Exception as exc:  # noqa: BLE001
                box["e"] = exc
            finally:
                done.set()

        self._cmds.put(wrap)
        self._wake_pump()
        if not done.wait(timeout):
            raise TimeoutError("hotkey pump command timed out")
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def _ensure_pump(self) -> bool:
        with self._life_lock:
            if self._thread is not None and self._thread.is_alive() and self._hwnd:
                return True
            self._stop.clear()
            self._ready.clear()
            self._hwnd = None

            def _pump() -> None:
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                hwnd = 0
                try:
                    hwnd = int(
                        user32.CreateWindowExW(
                            0,
                            "STATIC",
                            "BladePowerHotkeys",
                            0,
                            0,
                            0,
                            0,
                            0,
                            # Must be typed HWND; bare -3 fails on 64-bit Python.
                            wintypes.HWND(HWND_MESSAGE),
                            None,
                            kernel32.GetModuleHandleW(None),
                            None,
                        )
                        or 0
                    )
                    self._hwnd = hwnd or None
                finally:
                    self._ready.set()

                if not hwnd:
                    return

                msg = MSG()
                try:
                    while not self._stop.is_set():
                        # Drain commands first (register/unregister must be here).
                        while True:
                            try:
                                cmd = self._cmds.get_nowait()
                            except queue.Empty:
                                break
                            try:
                                cmd()
                            except Exception:
                                pass

                        r = user32.MsgWaitForMultipleObjects(
                            0, None, False, 100, 0x04FF
                        )
                        if self._stop.is_set():
                            break
                        while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                            if msg.message == WM_QUIT:
                                self._stop.set()
                                break
                            if msg.message == WM_HOTKEY:
                                cb = self._win_ids.get(int(msg.wParam))
                                if cb is not None:
                                    self._dispatch(cb)
                            elif msg.message != WM_NULL:
                                user32.TranslateMessage(ctypes.byref(msg))
                                user32.DispatchMessageW(ctypes.byref(msg))
                        _ = r
                finally:
                    try:
                        for hid in list(self._win_ids.keys()):
                            user32.UnregisterHotKey(
                                wintypes.HWND(hwnd), ctypes.c_int(hid)
                            )
                    except Exception:
                        pass
                    self._win_ids.clear()
                    try:
                        user32.DestroyWindow(wintypes.HWND(hwnd))
                    except Exception:
                        pass
                    if self._hwnd == hwnd:
                        self._hwnd = None

            self._thread = threading.Thread(
                target=_pump, daemon=True, name="HotkeyMsgPump"
            )
            self._thread.start()

        if not self._ready.wait(timeout=3.0):
            return False
        return bool(self._hwnd)

    def clear(self) -> None:
        self._clear_win32_keys()
        self._clear_keyboard()

    def _clear_keyboard(self) -> None:
        if not self._backend_kb:
            self._registered_kb.clear()
            return
        for hk in list(self._registered_kb):
            try:
                self._backend_kb.remove_hotkey(hk)
            except Exception:
                pass
        self._registered_kb.clear()

    def _clear_win32_keys(self) -> None:
        if not self._hwnd or not (self._thread and self._thread.is_alive()):
            self._win_ids.clear()
            return

        def _unreg() -> None:
            user32 = ctypes.windll.user32
            hwnd = self._hwnd
            if not hwnd:
                self._win_ids.clear()
                return
            for hid in list(self._win_ids.keys()):
                try:
                    user32.UnregisterHotKey(wintypes.HWND(hwnd), ctypes.c_int(hid))
                except Exception:
                    pass
            self._win_ids.clear()

        try:
            self._run_on_pump(_unreg)
        except Exception:
            self._win_ids.clear()

    def shutdown(self) -> None:
        try:
            self.clear()
        except Exception:
            pass
        self._stop.set()
        self._wake_pump()
        hwnd = self._hwnd
        if hwnd:
            try:
                ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), WM_QUIT, 0, 0)
            except Exception:
                pass
        th = self._thread
        if th is not None and th.is_alive():
            th.join(timeout=1.5)
        self._thread = None
        self._hwnd = None
        self._mode = "none"

    def _register_win32(self, mapping: Dict[str, Callable[[], None]]) -> list[str]:
        if not self._ensure_pump():
            return list(mapping.keys())

        def _reg() -> list[str]:
            failed: list[str] = []
            user32 = ctypes.windll.user32
            hwnd = self._hwnd
            if not hwnd:
                return list(mapping.keys())
            for hk, cb in mapping.items():
                parsed = parse_hotkey(hk)
                if parsed is None:
                    failed.append(hk)
                    continue
                mods, vk = parsed
                hid = self._next_id
                self._next_id += 1
                ok = bool(
                    user32.RegisterHotKey(
                        wintypes.HWND(hwnd),
                        ctypes.c_int(hid),
                        wintypes.UINT(mods),
                        wintypes.UINT(vk),
                    )
                )
                if not ok:
                    mods2 = mods & ~MOD_NOREPEAT
                    ok = bool(
                        user32.RegisterHotKey(
                            wintypes.HWND(hwnd),
                            ctypes.c_int(hid),
                            wintypes.UINT(mods2),
                            wintypes.UINT(vk),
                        )
                    )
                if not ok:
                    failed.append(hk)
                    continue
                self._win_ids[hid] = cb
            return failed

        try:
            failed = self._run_on_pump(_reg)
        except Exception:
            return list(mapping.keys())
        if self._win_ids:
            self._mode = "win32"
        return list(failed or [])

    def _register_keyboard(self, mapping: Dict[str, Callable[[], None]]) -> list[str]:
        failed: list[str] = []
        if not self._backend_kb:
            return list(mapping.keys())
        for hk, cb in mapping.items():
            try:
                norm = normalize_hotkey(hk)

                def _cb(fn=cb):
                    self._dispatch(fn)

                self._backend_kb.add_hotkey(norm, _cb, suppress=False)
                self._registered_kb.append(norm)
            except Exception:
                failed.append(hk)
        if self._registered_kb:
            self._mode = "keyboard"
        return failed

    def register_map(self, mapping: Dict[str, Callable[[], None]]) -> list[str]:
        cleaned: Dict[str, Callable[[], None]] = {}
        for hk, cb in mapping.items():
            key = normalize_hotkey(hk)
            if key:
                cleaned[key] = cb

        self.clear()
        self._mode = "none"
        if not cleaned:
            return []

        failed = self._register_win32(cleaned)
        if not failed and self._win_ids:
            return []

        if self._win_ids and failed:
            retry = {k: cleaned[k] for k in failed if k in cleaned}
            return self._register_keyboard(retry)

        self._clear_win32_keys()
        return self._register_keyboard(cleaned)

    def reregister(self, mapping: Dict[str, Callable[[], None]]) -> list[str]:
        return self.register_map(mapping)
