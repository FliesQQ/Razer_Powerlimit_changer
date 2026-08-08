"""Hotkey capture widget — records pressed combo / single key."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional


_KEYSYM_MAP = {
    "return": "enter",
    "escape": "esc",
    "prior": "page up",
    "next": "page down",
    "space": "space",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "left": "left",
    "right": "right",
    "up": "up",
    "down": "down",
    "plus": "+",
    "minus": "-",
    "equal": "=",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "backslash": "\\",
    "bracketleft": "[",
    "bracketright": "]",
    "semicolon": ";",
    "apostrophe": "'",
    "grave": "`",
}

_MOD_KEYS = {
    "control_l",
    "control_r",
    "alt_l",
    "alt_r",
    "shift_l",
    "shift_r",
    "meta_l",
    "meta_r",
    "win_l",
    "win_r",
    "super_l",
    "super_r",
}


def event_to_hotkey(event: tk.Event) -> Optional[str]:
    """Convert a Tk KeyPress event to keyboard-library style hotkey string."""
    keysym = (event.keysym or "").lower()
    if not keysym or keysym in _MOD_KEYS:
        return None

    # Numpad / special
    if keysym.startswith("kp_"):
        keysym = keysym[3:]
    if keysym in _KEYSYM_MAP:
        key = _KEYSYM_MAP[keysym]
    elif len(keysym) == 1:
        key = keysym
    elif keysym.startswith("f") and keysym[1:].isdigit():
        key = keysym
    else:
        key = keysym.replace("_", " ")

    state = int(event.state)
    mods: list[str] = []
    if state & 0x4:  # Control
        mods.append("ctrl")
    if state & 0x1:  # Shift
        # Avoid shift+digit producing shifted symbol confusion; keep shift for letters/function
        mods.append("shift")
    # Alt: Windows often 0x20000; also 0x8 (Mod1) on some platforms
    if (state & 0x20000) or (state & 0x8):
        mods.append("alt")

    # Single modifier-only already filtered; allow single key without mods.
    parts = mods + [key]
    return "+".join(parts)


class HotkeyCapture(ttk.Frame):
    """Entry that captures the next key/combo press into a StringVar."""

    def __init__(self, master, textvariable: tk.StringVar, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.var = textvariable
        self._listening = False
        self.entry = ttk.Entry(self, textvariable=self.var, width=22)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn = ttk.Button(self, text="录制", width=6, command=self.start_capture)
        self.btn.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(self, text="清除", width=5, command=self.clear).pack(side=tk.LEFT, padx=(2, 0))
        self.hint = ttk.Label(self, text="")
        self.hint.pack(side=tk.LEFT, padx=(6, 0))
        self.entry.bind("<KeyPress>", self._on_key, add="+")
        self.entry.bind("<FocusOut>", self._on_focus_out, add="+")

    def clear(self) -> None:
        self.var.set("")
        self._stop_capture()

    def start_capture(self) -> None:
        self._listening = True
        self.btn.state(["disabled"])
        self.hint.configure(text="请按下快捷键…")
        self.entry.focus_set()

    def _stop_capture(self) -> None:
        self._listening = False
        self.btn.state(["!disabled"])
        self.hint.configure(text="")

    def _on_focus_out(self, _event=None) -> None:
        if self._listening:
            self._stop_capture()

    def _on_key(self, event: tk.Event):
        # Always suppress typing into the entry; we only accept captured combos.
        if not self._listening and event.keysym.lower() not in _MOD_KEYS:
            # If user focuses and presses a key without clicking 录制, still capture.
            self._listening = True
            self.hint.configure(text="请按下快捷键…")
        if not self._listening:
            return "break"
        hk = event_to_hotkey(event)
        if not hk:
            return "break"
        self.var.set(hk)
        self._stop_capture()
        return "break"
