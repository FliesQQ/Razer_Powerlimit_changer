"""RTSS-like desktop performance OSD overlay."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import tkinter as tk
from tkinter import colorchooser, ttk


ITEM_DEFS: list[tuple[str, str]] = [
    ("cpu_power", "CPU 功耗"),
    ("cpu_temp", "CPU 温度"),
    ("gpu_power", "GPU 功耗"),
    ("gpu_temp", "GPU 温度"),
    ("fan_z1", "CPU风扇"),
    ("fan_z2", "GPU风扇"),
    ("cpu_pl", "CPU PL1/PL2"),
    ("uv", "降压 UV"),
    ("profile", "当前档"),
]

DEFAULT_COLORS = {
    "cpu_power": "#FFB000",
    "cpu_temp": "#FF5555",
    "gpu_power": "#40D060",
    "gpu_temp": "#40A0FF",
    "fan_z1": "#66DDEE",
    "fan_z2": "#66BBEE",
    "cpu_pl": "#E0E0E0",
    "uv": "#C080FF",
    "profile": "#FFFFFF",
    "label": "#AAAAAA",
    "background": "#101010",
}


@dataclass
class OsdConfig:
    enabled: bool = False
    topmost: bool = True
    locked: bool = False
    x: int = 40
    y: int = 40
    font_size: int = 14
    alpha: float = 0.88
    show_labels: bool = True
    items: dict[str, bool] = field(default_factory=dict)
    colors: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        base_items = {k: True for k, _ in ITEM_DEFS[:4]}
        for k, _ in ITEM_DEFS[4:]:
            base_items.setdefault(k, False)
        # Fans default on for new installs if not in saved items.
        if "fan_z1" not in (self.items or {}):
            base_items["fan_z1"] = True
        if "fan_z2" not in (self.items or {}):
            base_items["fan_z2"] = True
        merged = dict(base_items)
        merged.update(self.items or {})
        self.items = merged
        cols = dict(DEFAULT_COLORS)
        cols.update(self.colors or {})
        self.colors = cols
        self.alpha = max(0.35, min(1.0, float(self.alpha)))
        self.font_size = max(10, min(36, int(self.font_size)))

    @staticmethod
    def from_dict(d: Optional[dict]) -> "OsdConfig":
        d = d or {}
        return OsdConfig(
            enabled=bool(d.get("enabled", False)),
            topmost=bool(d.get("topmost", True)),
            locked=bool(d.get("locked", False)),
            x=int(d.get("x", 40)),
            y=int(d.get("y", 40)),
            font_size=int(d.get("font_size", 14)),
            alpha=float(d.get("alpha", 0.88)),
            show_labels=bool(d.get("show_labels", True)),
            items=dict(d.get("items") or {}),
            colors=dict(d.get("colors") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "topmost": self.topmost,
            "locked": self.locked,
            "x": int(self.x),
            "y": int(self.y),
            "font_size": int(self.font_size),
            "alpha": float(self.alpha),
            "show_labels": self.show_labels,
            "items": dict(self.items),
            "colors": dict(self.colors),
        }


@dataclass
class OsdSnapshot:
    cpu_power_w: Optional[float] = None
    cpu_temp_c: Optional[float] = None
    gpu_power_w: Optional[float] = None
    gpu_temp_c: Optional[float] = None
    fan_z1_rpm: Optional[int] = None
    fan_z2_rpm: Optional[int] = None
    cpu_pl1: Optional[float] = None
    cpu_pl2: Optional[float] = None
    uv_text: str = ""
    profile_name: str = ""


def _fmt(v: Optional[float], unit: str, digits: int = 0) -> str:
    if v is None:
        return f"--{unit}"
    if digits <= 0:
        return f"{v:.0f}{unit}"
    return f"{v:.{digits}f}{unit}"


class PerformanceOsd:
    """Borderless, draggable, always-on-top style desktop overlay."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        get_config: Callable[[], OsdConfig],
        save_config: Callable[[OsdConfig], None],
    ) -> None:
        self._master = master
        self._get_config = get_config
        self._save_config = save_config
        self._win: Optional[tk.Toplevel] = None
        self._frame: Optional[tk.Frame] = None
        self._labels: dict[str, tk.Label] = {}
        self._drag = {"x": 0, "y": 0}
        self._last: Optional[OsdSnapshot] = None
        self._built_sig: Optional[tuple] = None
        self._ctx_menu: Optional[tk.Misc] = None

    @property
    def visible(self) -> bool:
        return self._win is not None and bool(self._win.winfo_exists())

    def apply_config(self, cfg: Optional[OsdConfig] = None) -> None:
        cfg = cfg or self._get_config()
        if not cfg.enabled:
            self.hide()
            return
        if not self.visible:
            self._create(cfg)
        else:
            self._apply_window_attrs(cfg)
            self._rebuild_if_needed(cfg)
            self._place(cfg)
        if self._last is not None:
            self.update(self._last)

    def show(self) -> None:
        cfg = self._get_config()
        cfg.enabled = True
        self._save_config(cfg)
        self.apply_config(cfg)

    def hide(self) -> None:
        self._dismiss_ctx_menu()
        if self._win is not None:
            try:
                cfg = self._get_config()
                try:
                    cfg.x = int(self._win.winfo_x())
                    cfg.y = int(self._win.winfo_y())
                    self._save_config(cfg)
                except Exception:
                    pass
                self._win.destroy()
            except Exception:
                pass
        self._win = None
        self._frame = None
        self._labels.clear()
        self._built_sig = None
        self._ctx_menu = None

    def update(self, snap: OsdSnapshot) -> None:
        self._last = snap
        if not self.visible:
            return
        cfg = self._get_config()
        values = {
            "cpu_power": _fmt(snap.cpu_power_w, "W", 0),
            "cpu_temp": _fmt(snap.cpu_temp_c, "°C", 0),
            "gpu_power": _fmt(snap.gpu_power_w, "W", 1 if (snap.gpu_power_w or 0) < 100 else 0),
            "gpu_temp": _fmt(snap.gpu_temp_c, "°C", 0),
            "fan_z1": f"{snap.fan_z1_rpm} RPM" if snap.fan_z1_rpm is not None else "-- RPM",
            "fan_z2": f"{snap.fan_z2_rpm} RPM" if snap.fan_z2_rpm is not None else "-- RPM",
            "cpu_pl": (
                f"{snap.cpu_pl1:.0f}/{snap.cpu_pl2:.0f}W"
                if snap.cpu_pl1 is not None and snap.cpu_pl2 is not None
                else "--/--W"
            ),
            "uv": snap.uv_text or "--",
            "profile": snap.profile_name or "-",
        }
        for key, _name in ITEM_DEFS:
            lab = self._labels.get(key)
            if not lab:
                continue
            if cfg.show_labels:
                lab.configure(text=f"{_name}  {values[key]}")
            else:
                lab.configure(text=values[key])

    def _create(self, cfg: OsdConfig) -> None:
        win = tk.Toplevel(self._master)
        win.withdraw()
        win.overrideredirect(True)
        win.configure(bg=cfg.colors.get("background", "#101010"))
        try:
            win.attributes("-toolwindow", True)
        except Exception:
            pass
        self._win = win
        self._apply_window_attrs(cfg)
        self._rebuild_if_needed(cfg, force=True)
        self._place(cfg)
        win.deiconify()
        win.lift()

    def _apply_window_attrs(self, cfg: OsdConfig) -> None:
        assert self._win is not None
        try:
            self._win.attributes("-topmost", bool(cfg.topmost))
        except Exception:
            pass
        try:
            self._win.attributes("-alpha", float(cfg.alpha))
        except Exception:
            pass
        bg = cfg.colors.get("background", "#101010")
        self._win.configure(bg=bg)
        if self._frame is not None:
            self._frame.configure(bg=bg)

    def _rebuild_if_needed(self, cfg: OsdConfig, force: bool = False) -> None:
        sig = (
            tuple(sorted((k, bool(v)) for k, v in cfg.items.items())),
            cfg.font_size,
            cfg.show_labels,
            cfg.colors.get("background"),
            tuple(cfg.colors.get(k, "") for k, _ in ITEM_DEFS),
            cfg.colors.get("label"),
        )
        if not force and sig == self._built_sig and self._frame is not None:
            self._style_labels(cfg)
            return
        self._built_sig = sig
        assert self._win is not None
        for child in self._win.winfo_children():
            child.destroy()
        self._labels.clear()
        bg = cfg.colors.get("background", "#101010")
        frame = tk.Frame(self._win, bg=bg, padx=10, pady=8)
        frame.pack()
        self._frame = frame
        font = ("Consolas", int(cfg.font_size), "bold")
        for key, name in ITEM_DEFS:
            if not cfg.items.get(key, False):
                continue
            color = cfg.colors.get(key, "#FFFFFF")
            lab = tk.Label(
                frame,
                text=name if cfg.show_labels else "--",
                fg=color,
                bg=bg,
                font=font,
                anchor="w",
                justify="left",
            )
            lab.pack(anchor="w")
            self._labels[key] = lab
            self._bind_drag(lab)
        self._bind_drag(frame)
        self._bind_drag(self._win)
        for w in (self._win, frame, *self._labels.values()):
            w.bind("<Button-3>", self._popup_menu)

    def _popup_menu(self, event) -> None:
        """Custom popup (Tk Menu is unreliable on overrideredirect + topmost)."""
        if self._win is None:
            return
        from app.i18n import t

        self._dismiss_ctx_menu()
        cfg = self._get_config()

        pop = tk.Toplevel(self._win)
        pop.withdraw()
        pop.overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
        except Exception:
            pass
        pop.configure(bg="#2a2a2a", highlightthickness=1, highlightbackground="#555555")
        self._ctx_menu = pop

        def add_item(text: str, fn) -> None:
            lab = tk.Label(
                pop,
                text=text,
                anchor="w",
                padx=14,
                pady=6,
                bg="#2a2a2a",
                fg="#f0f0f0",
                font=("Segoe UI", 9),
            )
            lab.pack(fill=tk.X)

            def on_enter(_e, w=lab):
                w.configure(bg="#3a6a5a", fg="#ffffff")

            def on_leave(_e, w=lab):
                w.configure(bg="#2a2a2a", fg="#f0f0f0")

            def on_click(_e, action=fn):
                self._dismiss_ctx_menu()
                try:
                    action()
                except Exception:
                    pass
                return "break"

            lab.bind("<Enter>", on_enter)
            lab.bind("<Leave>", on_leave)
            lab.bind("<Button-1>", on_click)

        add_item(
            t("osd_menu_lock_on") if cfg.locked else t("osd_menu_lock_off"),
            self._toggle_lock,
        )
        add_item(
            t("osd_menu_top_on") if cfg.topmost else t("osd_menu_top_off"),
            self._toggle_topmost,
        )
        sep = tk.Frame(pop, height=1, bg="#555555")
        sep.pack(fill=tk.X, padx=4, pady=2)
        add_item(t("osd_menu_hide"), self._disable)

        pop.update_idletasks()
        w = max(pop.winfo_reqwidth(), 200)
        h = pop.winfo_reqheight()
        x, y = int(event.x_root), int(event.y_root)
        # Keep popup on-screen.
        try:
            sw = int(pop.winfo_screenwidth())
            sh = int(pop.winfo_screenheight())
            x = min(max(0, x), max(0, sw - w - 4))
            y = min(max(0, y), max(0, sh - h - 4))
        except Exception:
            pass
        pop.geometry(f"{w}x{h}+{x}+{y}")
        pop.deiconify()
        pop.lift()
        try:
            pop.focus_force()
            pop.grab_set()
        except Exception:
            pass

        pop.bind("<Escape>", lambda _e: self._dismiss_ctx_menu())

        def _outside_click(e) -> None:
            # Clicks on menu items are handled by labels; anything else closes.
            if e.widget is pop or e.widget is sep:
                self._dismiss_ctx_menu()

        pop.bind("<Button-1>", _outside_click)

    def _dismiss_ctx_menu(self) -> None:
        pop = self._ctx_menu
        self._ctx_menu = None
        if pop is None:
            return
        try:
            pop.grab_release()
        except Exception:
            pass
        try:
            if isinstance(pop, tk.Menu):
                pop.unpost()
            pop.destroy()
        except Exception:
            pass

    def _style_labels(self, cfg: OsdConfig) -> None:
        bg = cfg.colors.get("background", "#101010")
        font = ("Consolas", int(cfg.font_size), "bold")
        for key, lab in self._labels.items():
            lab.configure(fg=cfg.colors.get(key, "#FFFFFF"), bg=bg, font=font)

    def _place(self, cfg: OsdConfig) -> None:
        assert self._win is not None
        self._win.update_idletasks()
        self._win.geometry(f"+{int(cfg.x)}+{int(cfg.y)}")

    def _bind_drag(self, widget: tk.Misc) -> None:
        widget.bind("<ButtonPress-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_motion)
        widget.bind("<ButtonRelease-1>", self._on_drag_end)

    def _on_drag_start(self, event) -> None:
        cfg = self._get_config()
        if cfg.locked or self._win is None:
            return
        self._drag["x"] = event.x_root - self._win.winfo_x()
        self._drag["y"] = event.y_root - self._win.winfo_y()

    def _on_drag_motion(self, event) -> None:
        cfg = self._get_config()
        if cfg.locked or self._win is None:
            return
        x = event.x_root - self._drag["x"]
        y = event.y_root - self._drag["y"]
        self._win.geometry(f"+{x}+{y}")

    def _on_drag_end(self, _event=None) -> None:
        if self._win is None:
            return
        cfg = self._get_config()
        if cfg.locked:
            return
        cfg.x = int(self._win.winfo_x())
        cfg.y = int(self._win.winfo_y())
        self._save_config(cfg)

    def _toggle_lock(self) -> None:
        cfg = self._get_config()
        cfg.locked = not cfg.locked
        self._save_config(cfg)

    def _toggle_topmost(self) -> None:
        cfg = self._get_config()
        cfg.topmost = not cfg.topmost
        self._save_config(cfg)
        self.apply_config(cfg)

    def _disable(self) -> None:
        cfg = self._get_config()
        cfg.enabled = False
        self._save_config(cfg)
        self.hide()


class OsdSettingsPanel(ttk.Frame):
    """Embeddable settings UI for the performance OSD (tab content)."""

    def __init__(
        self,
        master,
        *,
        initial: OsdConfig,
        on_change: Callable[[OsdConfig], None],
        title: str = "",
    ) -> None:
        super().__init__(master, padding=8)
        self._on_change = on_change
        self.cfg = deepcopy(initial)
        self.enabled = tk.BooleanVar(value=self.cfg.enabled)
        self.topmost = tk.BooleanVar(value=self.cfg.topmost)
        self.locked = tk.BooleanVar(value=self.cfg.locked)
        self.show_labels = tk.BooleanVar(value=self.cfg.show_labels)
        self.font_size = tk.StringVar(value=str(self.cfg.font_size))
        self.alpha = tk.StringVar(value=str(self.cfg.alpha))
        self.item_vars: dict[str, tk.BooleanVar] = {
            k: tk.BooleanVar(value=bool(self.cfg.items.get(k, False))) for k, _ in ITEM_DEFS
        }
        self.color_vars: dict[str, tk.StringVar] = {
            k: tk.StringVar(value=self.cfg.colors.get(k, DEFAULT_COLORS.get(k, "#FFFFFF")))
            for k in list(DEFAULT_COLORS.keys())
        }
        self._build(title)

    def _build(self, title: str) -> None:
        self._title_lbl = None
        if title:
            self._title_lbl = ttk.Label(self, text=title)
            self._title_lbl.pack(anchor=tk.W, pady=(0, 6))
        row0 = ttk.Frame(self)
        row0.pack(fill=tk.X)
        self._chk_enabled = ttk.Checkbutton(
            row0, text="启用桌面 OSD", variable=self.enabled, command=self._emit
        )
        self._chk_enabled.pack(side=tk.LEFT, padx=(0, 8))
        self._chk_topmost = ttk.Checkbutton(
            row0, text="最前端显示", variable=self.topmost, command=self._emit
        )
        self._chk_topmost.pack(side=tk.LEFT, padx=(0, 8))
        self._chk_locked = ttk.Checkbutton(
            row0, text="锁定位置", variable=self.locked, command=self._emit
        )
        self._chk_locked.pack(side=tk.LEFT, padx=(0, 8))
        self._chk_show_labels = ttk.Checkbutton(
            row0, text="显示项目名称", variable=self.show_labels, command=self._emit
        )
        self._chk_show_labels.pack(side=tk.LEFT)

        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, pady=(8, 0))
        self._lbl_font = ttk.Label(row1, text="字号")
        self._lbl_font.pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.font_size, width=5).pack(side=tk.LEFT, padx=4)
        self._lbl_alpha = ttk.Label(row1, text="透明度 0.35-1")
        self._lbl_alpha.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Entry(row1, textvariable=self.alpha, width=6).pack(side=tk.LEFT, padx=4)
        self._btn_apply_look = ttk.Button(row1, text="应用外观", command=self._emit)
        self._btn_apply_look.pack(side=tk.LEFT, padx=8)

        self._lbl_drag = ttk.Label(
            self,
            text="拖动 OSD 可改位置；右键菜单会显示「✓ 已锁定/未锁定」状态",
        )
        self._lbl_drag.pack(anchor=tk.W, pady=(6, 0))

        self._items_frame = ttk.LabelFrame(self, text="显示项", padding=6)
        self._items_frame.pack(fill=tk.X, pady=(8, 0))
        row = ttk.Frame(self._items_frame)
        row.pack(fill=tk.X)
        for i, (key, name) in enumerate(ITEM_DEFS):
            if i and i % 5 == 0:
                row = ttk.Frame(self._items_frame)
                row.pack(fill=tk.X, pady=(2, 0))
            ttk.Checkbutton(
                row, text=name, variable=self.item_vars[key], command=self._emit
            ).pack(side=tk.LEFT, padx=4)

        self._colors_frame = ttk.LabelFrame(self, text="颜色", padding=6)
        self._colors_frame.pack(fill=tk.X, pady=(8, 0))
        crow = ttk.Frame(self._colors_frame)
        crow.pack(fill=tk.X)
        color_btns = [("background", "背景")] + [(k, n) for k, n in ITEM_DEFS]
        for i, (key, name) in enumerate(color_btns):
            if i and i % 5 == 0:
                crow = ttk.Frame(self._colors_frame)
                crow.pack(fill=tk.X, pady=(2, 0))
            ttk.Button(
                crow,
                text=name,
                width=8,
                command=lambda k=key: self._pick_color(k),
            ).pack(side=tk.LEFT, padx=2)

    def apply_i18n(self) -> None:
        from .i18n import t

        if self._title_lbl is not None:
            try:
                self._title_lbl.configure(text=t("osd_title"))
            except Exception:
                pass
        for w, key in (
            (self._chk_enabled, "osd_enable"),
            (self._chk_topmost, "osd_topmost"),
            (self._chk_locked, "osd_lock"),
            (self._chk_show_labels, "osd_show_names"),
            (self._lbl_font, "osd_font"),
            (self._lbl_alpha, "osd_alpha"),
            (self._btn_apply_look, "osd_apply_look"),
            (self._lbl_drag, "osd_drag_hint"),
            (self._items_frame, "osd_items"),
            (self._colors_frame, "osd_colors"),
        ):
            try:
                w.configure(text=t(key))
            except Exception:
                pass

    def _pick_color(self, key: str) -> None:
        current = self.color_vars[key].get()
        color = colorchooser.askcolor(color=current, title=f"选择颜色 - {key}")
        if color and color[1]:
            self.color_vars[key].set(color[1])
            self._emit()

    def read_config(self) -> OsdConfig:
        try:
            font_size = int(float(self.font_size.get()))
        except ValueError:
            font_size = 14
        try:
            alpha = float(self.alpha.get())
        except ValueError:
            alpha = 0.88
        items = {k: bool(v.get()) for k, v in self.item_vars.items()}
        colors = {k: v.get() for k, v in self.color_vars.items()}
        cfg = OsdConfig(
            enabled=bool(self.enabled.get()),
            topmost=bool(self.topmost.get()),
            locked=bool(self.locked.get()),
            x=self.cfg.x,
            y=self.cfg.y,
            font_size=font_size,
            alpha=alpha,
            show_labels=bool(self.show_labels.get()),
            items=items,
            colors=colors,
        )
        self.cfg = cfg
        return cfg

    def _emit(self) -> None:
        self._on_change(self.read_config())

    def set_enabled(self, enabled: bool) -> None:
        self.enabled.set(bool(enabled))
