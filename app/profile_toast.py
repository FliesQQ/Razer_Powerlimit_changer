"""Top-right always-on-top toast for profile switch feedback."""

from __future__ import annotations

import tkinter as tk
from typing import Optional


class ProfileToast:
    """Show a short tip at the top-right, hold, then fade out."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        hold_ms: int = 2000,
        fade_ms: int = 400,
        fade_steps: int = 10,
        margin: int = 24,
    ) -> None:
        self._master = master
        self._hold_ms = max(200, int(hold_ms))
        self._fade_ms = max(100, int(fade_ms))
        self._fade_steps = max(4, int(fade_steps))
        self._margin = int(margin)
        self._win: Optional[tk.Toplevel] = None
        self._label: Optional[tk.Label] = None
        self._after_ids: list = []
        self._alpha = 0.92

    def show(self, text: str, *, subtitle: str = "") -> None:
        msg = str(text or "").strip()
        if not msg:
            return
        sub = str(subtitle or "").strip()
        display = f"{msg}\n{sub}" if sub else msg

        def _go() -> None:
            self._cancel_timers()
            self._ensure_window()
            assert self._win is not None and self._label is not None
            self._label.configure(text=display)
            self._win.attributes("-alpha", self._alpha)
            self._win.deiconify()
            self._win.lift()
            self._win.attributes("-topmost", True)
            self._place()
            # Hold, then fade.
            aid = self._master.after(self._hold_ms, self._start_fade)
            self._after_ids.append(aid)

        try:
            self._master.after(0, _go)
        except Exception:
            pass

    def destroy(self) -> None:
        self._cancel_timers()
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = None
        self._label = None

    def _cancel_timers(self) -> None:
        for aid in self._after_ids:
            try:
                self._master.after_cancel(aid)
            except Exception:
                pass
        self._after_ids.clear()

    def _ensure_window(self) -> None:
        if self._win is not None and self._win.winfo_exists():
            return
        win = tk.Toplevel(self._master)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            # Soft dark panel; matches BladePower accent.
            win.configure(bg="#0e1218")
        except Exception:
            pass
        frame = tk.Frame(win, bg="#171d27", padx=16, pady=12, highlightthickness=1, highlightbackground="#1ec8a5")
        frame.pack(fill=tk.BOTH, expand=True)
        label = tk.Label(
            frame,
            text="",
            bg="#171d27",
            fg="#e6edf5",
            font=("Segoe UI Semibold", 13),
            justify=tk.LEFT,
            anchor="e",
        )
        label.pack()
        # Ignore clicks — don't steal focus from games.
        for w in (win, frame, label):
            w.bind("<Button>", lambda _e: "break")
        self._win = win
        self._label = label

    def _place(self) -> None:
        assert self._win is not None
        self._win.update_idletasks()
        sw = int(self._win.winfo_screenwidth())
        tw = max(160, int(self._win.winfo_reqwidth()))
        th = max(40, int(self._win.winfo_reqheight()))
        x = max(0, sw - tw - self._margin)
        y = self._margin
        self._win.geometry(f"{tw}x{th}+{x}+{y}")

    def _start_fade(self) -> None:
        if self._win is None or not self._win.winfo_exists():
            return
        step_ms = max(16, self._fade_ms // self._fade_steps)
        self._fade_step(0, step_ms)

    def _fade_step(self, i: int, step_ms: int) -> None:
        if self._win is None or not self._win.winfo_exists():
            return
        if i >= self._fade_steps:
            try:
                self._win.withdraw()
                self._win.attributes("-alpha", self._alpha)
            except Exception:
                pass
            return
        # Linear fade from full alpha → 0.
        alpha = self._alpha * (1.0 - (i + 1) / float(self._fade_steps))
        try:
            self._win.attributes("-alpha", max(0.0, alpha))
        except Exception:
            pass
        aid = self._master.after(step_ms, lambda: self._fade_step(i + 1, step_ms))
        self._after_ids.append(aid)
