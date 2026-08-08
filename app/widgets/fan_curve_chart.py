"""Canvas-based fan curve editor (temp → RPM)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from app.backends.fan_curve import RPM_MAX, RPM_MIN, normalize_points


TEMP_MIN = 30
TEMP_MAX = 100


class FanCurveChart(ttk.Frame):
    """
    Interactive curve: drag points on a canvas.
    Syncs bidirectionally with a StringVar of "t,rpm; t,rpm; …".
    """

    def __init__(
        self,
        master,
        *,
        title: str,
        textvariable: tk.StringVar,
        on_change: Optional[Callable[[], None]] = None,
        width: int = 420,
        height: int = 180,
        **kwargs,
    ) -> None:
        super().__init__(master, **kwargs)
        self.title = title
        self.var = textvariable
        self.on_change = on_change
        self._points: list[tuple[int, int]] = []
        self._drag_idx: Optional[int] = None
        self._pad = {"l": 42, "r": 12, "t": 16, "b": 28}

        head = ttk.Frame(self)
        head.pack(fill=tk.X)
        ttk.Label(head, text=title).pack(side=tk.LEFT)
        ttk.Button(head, text="加点", width=6, command=self._add_point).pack(side=tk.RIGHT, padx=2)
        ttk.Button(head, text="删点", width=6, command=self._del_point).pack(side=tk.RIGHT, padx=2)

        self.canvas = tk.Canvas(self, width=width, height=height, bg="#1a1a1a", highlightthickness=1)
        self.canvas.pack(fill=tk.BOTH, expand=True, pady=(4, 2))
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", lambda _e: self.redraw())

        ttk.Entry(self, textvariable=self.var).pack(fill=tk.X, pady=(2, 0))
        self.var.trace_add("write", self._on_var_write)
        self._suppress_var = False
        self._load_from_var()
        self.redraw()

    def _load_from_var(self) -> None:
        try:
            pts = self._parse_text(self.var.get())
        except Exception:
            pts = [(40, 2200), (70, 3600), (90, 5500)]
        self._points = [(int(t), int(r)) for t, r in pts]

    @staticmethod
    def _parse_text(text: str) -> list[tuple[int, int]]:
        parts = []
        for chunk in (text or "").replace("|", ";").split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "," in chunk:
                a, b = chunk.split(",", 1)
            elif ":" in chunk:
                a, b = chunk.split(":", 1)
            else:
                continue
            try:
                parts.append((float(a.strip()), float(b.strip())))
            except ValueError:
                continue
        return normalize_points(parts)

    def _on_var_write(self, *_args) -> None:
        if self._suppress_var:
            return
        self._load_from_var()
        self.redraw()

    def _emit_var(self) -> None:
        self._points = normalize_points(self._points)
        text = "; ".join(f"{t},{r}" for t, r in self._points)
        self._suppress_var = True
        try:
            self.var.set(text)
        finally:
            self._suppress_var = False
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def _plot_box(self) -> tuple[int, int, int, int]:
        w = max(self.canvas.winfo_width(), 40)
        h = max(self.canvas.winfo_height(), 40)
        return (
            self._pad["l"],
            self._pad["t"],
            w - self._pad["r"],
            h - self._pad["b"],
        )

    def _to_canvas(self, temp: float, rpm: float) -> tuple[float, float]:
        l, t, r, b = self._plot_box()
        temp = max(TEMP_MIN, min(TEMP_MAX, temp))
        rpm = max(RPM_MIN, min(RPM_MAX, rpm))
        x = l + (temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN) * (r - l)
        y = b - (rpm - RPM_MIN) / (RPM_MAX - RPM_MIN) * (b - t)
        return x, y

    def _from_canvas(self, x: float, y: float) -> tuple[int, int]:
        l, t, r, b = self._plot_box()
        if r <= l or b <= t:
            return TEMP_MIN, RPM_MIN
        temp = TEMP_MIN + (x - l) / (r - l) * (TEMP_MAX - TEMP_MIN)
        rpm = RPM_MIN + (b - y) / (b - t) * (RPM_MAX - RPM_MIN)
        temp = int(round(max(TEMP_MIN, min(TEMP_MAX, temp))))
        rpm = int(round(max(RPM_MIN, min(RPM_MAX, rpm)) / 100.0) * 100)
        return temp, rpm

    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        l, t, r, b = self._plot_box()
        # Grid
        c.create_rectangle(l, t, r, b, outline="#555555")
        for temp in range(TEMP_MIN, TEMP_MAX + 1, 10):
            x, _ = self._to_canvas(temp, RPM_MIN)
            c.create_line(x, t, x, b, fill="#2a2a2a")
            c.create_text(x, b + 10, text=str(temp), fill="#888888", font=("Segoe UI", 8))
        for rpm in range(RPM_MIN, RPM_MAX + 1, 500):
            _, y = self._to_canvas(TEMP_MIN, rpm)
            c.create_line(l, y, r, y, fill="#2a2a2a")
            c.create_text(l - 4, y, text=str(rpm), fill="#888888", font=("Segoe UI", 8), anchor="e")
        c.create_text((l + r) / 2, b + 22, text="温度 °C", fill="#aaaaaa", font=("Segoe UI", 8))
        c.create_text(12, (t + b) / 2, text="RPM", fill="#aaaaaa", font=("Segoe UI", 8), angle=90)

        pts = sorted(self._points, key=lambda p: p[0])
        if len(pts) >= 2:
            coords = []
            for temp, rpm in pts:
                x, y = self._to_canvas(temp, rpm)
                coords.extend([x, y])
            c.create_line(*coords, fill="#40D060", width=2, smooth=False)
        for i, (temp, rpm) in enumerate(pts):
            x, y = self._to_canvas(temp, rpm)
            color = "#FFB000" if i == self._drag_idx else "#40A0FF"
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=color, outline="#ffffff", width=1)
            c.create_text(x, y - 12, text=f"{temp}°/{rpm}", fill="#dddddd", font=("Segoe UI", 7))

    def _hit_test(self, x: float, y: float) -> Optional[int]:
        best = None
        best_d = 12.0
        for i, (temp, rpm) in enumerate(self._points):
            cx, cy = self._to_canvas(temp, rpm)
            d = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
            if d <= best_d:
                best_d = d
                best = i
        return best

    def _on_press(self, event) -> None:
        idx = self._hit_test(event.x, event.y)
        if idx is None:
            # Click empty → move nearest by x or add
            temp, rpm = self._from_canvas(event.x, event.y)
            self._points.append((temp, rpm))
            self._points = normalize_points(self._points)
            # select the point at this temp
            for i, (t, _r) in enumerate(self._points):
                if t == temp:
                    self._drag_idx = i
                    break
            self._emit_var()
            self.redraw()
            return
        self._drag_idx = idx
        self.redraw()

    def _on_drag(self, event) -> None:
        if self._drag_idx is None:
            return
        temp, rpm = self._from_canvas(event.x, event.y)
        pts = list(self._points)
        # Keep endpoints roughly ordered: update temp freely then normalize
        pts[self._drag_idx] = (temp, rpm)
        # Remember identity by re-finding after normalize is hard; store by index before sort
        # Instead update then re-find closest to new temp
        self._points = normalize_points(pts)
        # Re-select nearest to new temp
        nearest = min(range(len(self._points)), key=lambda i: abs(self._points[i][0] - temp))
        self._drag_idx = nearest
        self._points[self._drag_idx] = (self._points[self._drag_idx][0], rpm)
        # Allow temp change: set to dragged temp then normalize again
        tlist = list(self._points)
        tlist[self._drag_idx] = (temp, rpm)
        self._points = normalize_points(tlist)
        nearest = min(range(len(self._points)), key=lambda i: abs(self._points[i][0] - temp) + abs(self._points[i][1] - rpm) * 0.01)
        self._drag_idx = nearest
        self._emit_var()
        self.redraw()

    def _on_release(self, _event=None) -> None:
        self._drag_idx = None
        self.redraw()

    def _add_point(self) -> None:
        if not self._points:
            self._points = [(50, 3000)]
        else:
            # Mid between last two or +10°C
            last_t, last_r = self._points[-1]
            t = min(TEMP_MAX, last_t + 10)
            self._points.append((t, last_r))
        self._points = normalize_points(self._points)
        self._emit_var()
        self.redraw()

    def _del_point(self) -> None:
        if len(self._points) <= 2:
            return
        self._points.pop()
        self._points = normalize_points(self._points)
        self._emit_var()
        self.redraw()
