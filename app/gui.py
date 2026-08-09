"""Main GUI: profile list + combo editor + undervolt + status."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Callable, Optional

from .widgets.fan_curve_chart import FanCurveChart
from .widgets.hotkey_capture import HotkeyCapture

if TYPE_CHECKING:
    from .profile_manager import Profile, ProfileManager


# Blade 16 (RZ09-0483) 实测：GPU 档 ≈ GPU 上限 / 整机最大负载
GPU_LABELS = [
    ("低 (~100W / 整机~160W)", "low"),
    ("中 (~150W / 整机~180W)", "medium"),
    ("高 (≥175W / 整机~205W)", "high"),
]

# 与雷云 Custom CPU 滑条一致；「自定义」才写 PL1/PL2
CPU_LEVEL_LABELS = [
    ("低", "low"),
    ("中", "medium"),
    ("高", "high"),
    ("增强", "boost"),
    ("自定义", "custom"),
]


class AppGUI:
    def __init__(
        self,
        root: tk.Tk,
        manager: "ProfileManager",
        *,
        monitor=None,
        on_hotkeys_changed: Optional[Callable[[], None]] = None,
        status_provider: Optional[Callable[[], dict]] = None,
    ) -> None:
        self.root = root
        self.manager = manager
        self.monitor = monitor
        self.on_hotkeys_changed = on_hotkeys_changed
        self.status_provider = status_provider
        self._editing_id: Optional[str] = None
        self._busy = False

        root.title("Blade 16 功耗快捷切换")
        # Tall enough for 风扇曲线 tab (two charts + tools + buttons + live status).
        self._win_w, self._win_h = 1020, 960
        root.geometry(f"{self._win_w}x{self._win_h}")
        root.minsize(self._win_w, self._win_h)
        root.maxsize(self._win_w, self._win_h)
        root.resizable(False, False)
        # Remove maximize / thick-frame sizing on Windows after HWND exists.
        root.after(50, self._lock_window_chrome)

        self.status_var = tk.StringVar(value="就绪")
        self.live_var = tk.StringVar(value="读数加载中…")
        self.name_var = tk.StringVar()
        self.pl1_var = tk.StringVar(value="55")
        self.pl2_var = tk.StringVar(value="75")
        self.tau_var = tk.StringVar(value="48")
        self.gpu_var = tk.StringVar(value="low")
        self.cpu_level_var = tk.StringVar(value="boost")
        self.max_fan_var = tk.BooleanVar(value=False)
        self.fan_mode_var = tk.StringVar(value="auto")
        self.fan_rpm_var = tk.StringVar(value="3000")
        self.ab_var = tk.StringVar(value="")
        self.hotkey_var = tk.StringVar(value="")
        self.uv_core = tk.StringVar(value=str(manager.undervolt_cfg.core_mv))
        self.uv_cache = tk.StringVar(value=str(manager.undervolt_cfg.cache_mv))
        self.uv_ecache = tk.StringVar(value=str(manager.undervolt_cfg.ecache_mv))
        self.auto_pl2_var = tk.BooleanVar(value=True)
        fc = getattr(manager, "fan_curve_cfg", None)
        self.curve_enabled = tk.BooleanVar(value=bool(fc and fc.enabled))
        self.curve_cpu_var = tk.StringVar(
            value=self._points_to_text(fc.cpu_points if fc else None)
        )
        self.curve_gpu_var = tk.StringVar(
            value=self._points_to_text(fc.gpu_points if fc else None)
        )
        xtu = (getattr(manager, "settings", {}) or {}).get("xtu_path") or "未检测"
        self.xtu_var = tk.StringVar(value=f"XTU: {xtu}")
        settings = getattr(manager, "settings", {}) or {}
        # Default on — matches previous behavior.
        self.sensor_tray_var = tk.BooleanVar(
            value=bool(settings.get("sensor_tray_enabled", True))
        )
        self.on_sensor_tray_changed: Optional[Callable[[bool], None]] = None
        self.on_osd_changed: Optional[Callable] = None
        self.on_autostart_changed: Optional[Callable[[bool], None]] = None
        try:
            from . import autostart as _autostart

            autostart_on = _autostart.is_enabled()
        except Exception:
            autostart_on = bool(settings.get("autostart_enabled", False))
        self.autostart_var = tk.BooleanVar(value=autostart_on)
        self.feat_cpu_level = tk.BooleanVar(
            value=bool(settings.get("enable_cpu_level", True))
        )
        self.feat_gpu = tk.BooleanVar(
            value=bool(settings.get("enable_gpu_level", True))
        )
        self.feat_uv = tk.BooleanVar(
            value=bool(settings.get("enable_undervolt", True))
        )
        self.on_features_changed: Optional[Callable[[], None]] = None

        self._build()
        self.refresh_list()
        self.root.after(500, self._poll_live)

    def _lock_window_chrome(self) -> None:
        """Disable maximize box and sizing border (Windows)."""
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = int(self.root.winfo_id())
            if not hwnd:
                self.root.after(100, self._lock_window_chrome)
                return
            user32 = ctypes.windll.user32
            GWL_STYLE = -16
            WS_MAXIMIZEBOX = 0x00010000
            WS_THICKFRAME = 0x00040000
            get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
            style = int(get_long(hwnd, GWL_STYLE) or 0)
            style &= ~WS_MAXIMIZEBOX
            style &= ~WS_THICKFRAME
            set_long(hwnd, GWL_STYLE, style)
            # Apply style change.
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
            )
            self.root.geometry(f"{self._win_w}x{self._win_h}")
            self.root.resizable(False, False)
        except Exception:
            pass

    def _build(self) -> None:
        # Status bar at the very bottom; live status sits just above it (all tabs).
        bottom = ttk.Frame(self.root, padding=(8, 2, 8, 8))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bottom, textvariable=self.status_var).pack(side=tk.LEFT)

        live = ttk.LabelFrame(self.root, text="实时状态", padding=(8, 4))
        live.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(
            live,
            textvariable=self.live_var,
            justify=tk.LEFT,
            wraplength=980,
        ).pack(anchor=tk.W, fill=tk.X)

        top = ttk.Frame(self.root, padding=8)
        top.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(top, text="性能档", padding=4)
        left.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 8))

        self.listbox = tk.Listbox(left, width=16, height=14, exportselection=False)
        self.listbox.pack(fill=tk.Y, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        lb_btns = ttk.Frame(left)
        lb_btns.pack(fill=tk.X, pady=4)
        ttk.Button(lb_btns, text="应用", width=5, command=self.apply_selected).pack(
            side=tk.LEFT, padx=1
        )
        ttk.Button(lb_btns, text="删除", width=5, command=self.delete_selected).pack(
            side=tk.LEFT, padx=1
        )

        right = ttk.Frame(top)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        nb = ttk.Notebook(right)
        nb.pack(fill=tk.BOTH, expand=True)
        tab_main = ttk.Frame(nb, padding=6)
        tab_curve_outer = ttk.Frame(nb)
        tab_osd = ttk.Frame(nb, padding=6)
        tab_tray = ttk.Frame(nb, padding=6)
        nb.add(tab_main, text="主页")
        nb.add(tab_curve_outer, text="风扇曲线")
        nb.add(tab_osd, text="桌面 OSD")
        nb.add(tab_tray, text="托盘图标")

        # Fan-curve tab: scrollable so bottom buttons stay reachable in fixed window.
        curve_canvas = tk.Canvas(tab_curve_outer, highlightthickness=0)
        curve_scroll = ttk.Scrollbar(tab_curve_outer, orient=tk.VERTICAL, command=curve_canvas.yview)
        curve_canvas.configure(yscrollcommand=curve_scroll.set)
        curve_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        curve_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tab_curve = ttk.Frame(curve_canvas, padding=6)
        curve_win = curve_canvas.create_window((0, 0), window=tab_curve, anchor="nw")

        def _curve_on_frame_configure(_event=None) -> None:
            curve_canvas.configure(scrollregion=curve_canvas.bbox("all"))

        def _curve_on_canvas_configure(event) -> None:
            curve_canvas.itemconfigure(curve_win, width=event.width)

        def _curve_on_mousewheel(event) -> None:
            # Only scroll when the event originates under the fan-curve tab.
            w = event.widget
            while w is not None:
                if w in (tab_curve_outer, curve_canvas, tab_curve):
                    curve_canvas.yview_scroll(int(-event.delta / 120), "units")
                    return "break"
                w = getattr(w, "master", None)
            return None

        tab_curve.bind("<Configure>", _curve_on_frame_configure)
        curve_canvas.bind("<Configure>", _curve_on_canvas_configure)
        self.root.bind_all("<MouseWheel>", _curve_on_mousewheel, add="+")

        # ---- 功能模块开关（互不捆绑）----
        feats = ttk.LabelFrame(
            tab_main,
            text="功能模块（可独立开关）",
            padding=8,
        )
        feats.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(
            feats,
            text="CPU 档位（低/中/高/增强/自定义）",
            variable=self.feat_cpu_level,
            command=self._on_features_changed,
        ).grid(row=0, column=0, sticky=tk.W, padx=(0, 12))
        ttk.Checkbutton(
            feats,
            text="GPU 档位",
            variable=self.feat_gpu,
            command=self._on_features_changed,
        ).grid(row=0, column=1, sticky=tk.W, padx=(0, 12))
        ttk.Checkbutton(
            feats,
            text="CPU 降压（独立）",
            variable=self.feat_uv,
            command=self._on_features_changed,
        ).grid(row=0, column=2, sticky=tk.W, padx=(0, 12))
        ttk.Label(
            feats,
            text="CPU 选「自定义」才应用 PL1/PL2/Tau；固定档只改雷云同款 EC。风扇曲线在对应页启用。",
            foreground="#666666",
        ).grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(4, 0))

        # ---- 主页：编辑器 + 降压 ----
        editor = ttk.LabelFrame(tab_main, text="搭配编辑器", padding=8)
        editor.pack(fill=tk.X)

        r = 0
        ttk.Label(editor, text="名称").grid(row=r, column=0, sticky=tk.W, pady=2)
        ttk.Entry(editor, textvariable=self.name_var, width=28).grid(
            row=r, column=1, columnspan=3, sticky=tk.W
        )
        r += 1
        ttk.Label(editor, text="CPU PL1 (W)").grid(row=r, column=0, sticky=tk.W, pady=2)
        e_pl1 = ttk.Entry(editor, textvariable=self.pl1_var, width=10)
        e_pl1.grid(row=r, column=1, sticky=tk.W)
        e_pl1.bind("<KeyRelease>", self._maybe_auto_pl2)
        ttk.Label(editor, text="PL2 (W)").grid(row=r, column=2, sticky=tk.W, padx=(12, 0))
        ttk.Entry(editor, textvariable=self.pl2_var, width=10).grid(row=r, column=3, sticky=tk.W)
        r += 1
        ttk.Checkbutton(
            editor, text="PL2 自动 = PL1+20", variable=self.auto_pl2_var, command=self._maybe_auto_pl2
        ).grid(row=r, column=1, columnspan=2, sticky=tk.W)
        r += 1
        ttk.Label(editor, text="Tau (s)").grid(row=r, column=0, sticky=tk.W, pady=2)
        ttk.Entry(editor, textvariable=self.tau_var, width=10).grid(row=r, column=1, sticky=tk.W)
        ttk.Label(
            editor, text="← 仅 CPU 档=自定义时生效", foreground="#666666"
        ).grid(row=r, column=2, columnspan=2, sticky=tk.W, padx=(8, 0))
        r += 1
        ttk.Label(editor, text="CPU 档").grid(row=r, column=0, sticky=tk.W, pady=2)
        cpu_frame = ttk.Frame(editor)
        cpu_frame.grid(row=r, column=1, columnspan=3, sticky=tk.W)
        for text, val in CPU_LEVEL_LABELS:
            ttk.Radiobutton(
                cpu_frame, text=text, value=val, variable=self.cpu_level_var
            ).pack(side=tk.LEFT, padx=4)
        r += 1
        ttk.Label(editor, text="GPU 档").grid(row=r, column=0, sticky=tk.W, pady=2)
        gpu_frame = ttk.Frame(editor)
        gpu_frame.grid(row=r, column=1, columnspan=3, sticky=tk.W)
        for text, val in GPU_LABELS:
            ttk.Radiobutton(gpu_frame, text=text, value=val, variable=self.gpu_var).pack(
                side=tk.LEFT, padx=4
            )
        r += 1
        ttk.Label(editor, text="风扇").grid(row=r, column=0, sticky=tk.W, pady=2)
        fan_frame = ttk.Frame(editor)
        fan_frame.grid(row=r, column=1, columnspan=3, sticky=tk.W)
        self._fan_mode_radios = []
        for text, val in [
            ("自动", "auto"),
            ("最大", "max"),
            ("手动 RPM", "manual"),
        ]:
            rb = ttk.Radiobutton(
                fan_frame, text=text, value=val, variable=self.fan_mode_var, command=self._on_fan_mode
            )
            rb.pack(side=tk.LEFT, padx=4)
            self._fan_mode_radios.append(rb)
        r += 1
        self.fan_mutex_hint = ttk.Label(editor, text="", foreground="#886600")
        self.fan_mutex_hint.grid(row=r, column=1, columnspan=3, sticky=tk.W)
        r += 1
        ttk.Label(editor, text="手动转速").grid(row=r, column=0, sticky=tk.W, pady=2)
        ttk.Entry(editor, textvariable=self.fan_rpm_var, width=10).grid(row=r, column=1, sticky=tk.W)
        ttk.Label(editor, text="RPM (0-5500，0=停转)").grid(row=r, column=2, sticky=tk.W)
        r += 1
        ttk.Label(editor, text="Afterburner #").grid(row=r, column=0, sticky=tk.W, pady=2)
        ttk.Entry(editor, textvariable=self.ab_var, width=10).grid(row=r, column=1, sticky=tk.W)
        ttk.Label(editor, text="(1-5 可空)").grid(row=r, column=2, sticky=tk.W)
        r += 1
        ttk.Label(editor, text="快捷键").grid(row=r, column=0, sticky=tk.W, pady=2)
        HotkeyCapture(editor, textvariable=self.hotkey_var).grid(
            row=r, column=1, columnspan=3, sticky=tk.W
        )

        btns = ttk.Frame(editor)
        btns.grid(row=r + 1, column=0, columnspan=4, sticky=tk.W, pady=8)
        ttk.Button(btns, text="立即应用", command=self.apply_editor).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="保存到当前档", command=self.save_current).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="另存为新档", command=self.save_as_new).pack(side=tk.LEFT, padx=3)

        uv = ttk.LabelFrame(tab_main, text="全局降压 (各档共用)", padding=8)
        uv.pack(fill=tk.X, pady=8)
        ttk.Label(uv, text="Core mV").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(uv, textvariable=self.uv_core, width=10).grid(row=0, column=1, padx=4)
        ttk.Label(uv, text="Cache mV").grid(row=0, column=2, sticky=tk.W, padx=(8, 0))
        ttk.Entry(uv, textvariable=self.uv_cache, width=10).grid(row=0, column=3, padx=4)
        ttk.Label(uv, text="E-Cache mV").grid(row=0, column=4, sticky=tk.W, padx=(8, 0))
        ttk.Entry(uv, textvariable=self.uv_ecache, width=10).grid(row=0, column=5, padx=4)
        uv_btns = ttk.Frame(uv)
        uv_btns.grid(row=1, column=0, columnspan=6, sticky=tk.W, pady=6)
        ttk.Button(uv_btns, text="保存降压配置", command=self.save_undervolt).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(uv_btns, text="重新应用我的降压", command=self.reapply_uv).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(uv_btns, text="恢复默认 (Ctrl+Alt+0)", command=self.restore_defaults).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Label(uv, textvariable=self.xtu_var, wraplength=640).grid(
            row=2, column=0, columnspan=6, sticky=tk.W, pady=(4, 0)
        )

        # ---- 风扇曲线（图标拖拽 + 文本同步）----
        ttk.Checkbutton(
            tab_curve,
            text="启用软件曲线（与性能档风扇互斥：启用后档位风扇不生效；关闭后自动恢复当前档风扇）",
            variable=self.curve_enabled,
            command=self._on_curve_enable_toggle,
        ).pack(anchor=tk.W)
        charts = ttk.Frame(tab_curve)
        charts.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        FanCurveChart(
            charts,
            title="CPU 风扇曲线（拖动圆点；也可用下方数值写入）",
            textvariable=self.curve_cpu_var,
            width=440,
            height=155,
        ).pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        FanCurveChart(
            charts,
            title="GPU 风扇曲线",
            textvariable=self.curve_gpu_var,
            width=440,
            height=155,
        ).pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            tab_curve,
            text=(
                "RPM 允许 0–5500（步进 100）。可用「数值写入」把低温点设为 0/500/1000 等，再点保存。\n"
                "曲线 0 = 该风扇交回 EC 自动（低温可停转）；>0 = 手动固定转速。"
            ),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=4)
        btns_c = ttk.Frame(tab_curve)
        btns_c.pack(anchor=tk.W, pady=(2, 0))
        ttk.Button(btns_c, text="仅保存曲线", command=self.save_fan_curves_only).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btns_c, text="保存并应用曲线", command=self.save_fan_curves).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(
            btns_c, text="强制写入当前风扇曲线数据", command=self.force_write_fan_curves
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns_c, text="打开配置文件", command=self._open_profiles_file).pack(
            side=tk.LEFT
        )

        # ---- 桌面 OSD ----
        from .osd_overlay import OsdConfig, OsdSettingsPanel

        osd_cfg = OsdConfig.from_dict((getattr(self.manager, "settings", {}) or {}).get("osd"))
        self.osd_panel = OsdSettingsPanel(
            tab_osd,
            initial=osd_cfg,
            on_change=self._on_osd_cfg_change,
        )
        self.osd_panel.pack(fill=tk.BOTH, expand=True)

        # ---- 托盘图标 ----
        ttk.Label(
            tab_tray,
            text="在系统托盘显示 4 个传感器图标（CPU/GPU 功耗与温度），类似 HWiNFO。",
            wraplength=640,
        ).pack(anchor=tk.W, pady=(0, 8))
        ttk.Checkbutton(
            tab_tray,
            text="启用托盘传感器图标",
            variable=self.sensor_tray_var,
            command=self._on_sensor_tray_toggle,
        ).pack(anchor=tk.W)
        ttk.Label(
            tab_tray,
            text="也可在主托盘图标右键菜单中切换「托盘传感器（功耗/温度）」。",
            wraplength=640,
        ).pack(anchor=tk.W, pady=(8, 0))

        ttk.Separator(tab_tray).pack(fill=tk.X, pady=12)
        ttk.Label(tab_tray, text="启动选项", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        ttk.Checkbutton(
            tab_tray,
            text="开机自动启动（登录后托盘静默运行，并自动应用上次性能档/降压）",
            variable=self.autostart_var,
            command=self._on_autostart_toggle,
        ).pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(
            tab_tray,
            text="使用任务计划程序以最高权限启动，避免每次登录都弹 UAC。",
            wraplength=640,
        ).pack(anchor=tk.W, pady=(4, 0))

        self._sync_fan_mutex_ui()

    def _sync_fan_mutex_ui(self) -> None:
        curve_on = bool(self.curve_enabled.get())
        state = ["disabled"] if curve_on else ["!disabled"]
        for rb in getattr(self, "_fan_mode_radios", []):
            try:
                rb.state(state)
            except Exception:
                pass
        hint = getattr(self, "fan_mutex_hint", None)
        if hint is not None:
            hint.configure(
                text="当前由软件风扇曲线接管，档位风扇选项暂不生效"
                if curve_on
                else ""
            )

    @staticmethod
    def _points_to_text(points) -> str:
        from .backends.fan_curve import DEFAULT_CPU_CURVE

        pts = points or DEFAULT_CPU_CURVE
        return "; ".join(f"{t},{r}" for t, r in pts)

    @staticmethod
    def _parse_points(text: str):
        from .backends.fan_curve import normalize_points

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
            parts.append((float(a.strip()), float(b.strip())))
        return normalize_points(parts)

    def save_fan_curves_only(self) -> None:
        """Persist curve points; if curve is enabled, refresh live targets too."""
        self._save_fan_curves(apply=False)
        if bool(self.curve_enabled.get()):
            cb = getattr(self, "on_fan_curves_changed", None)
            if cb:
                try:
                    cb()
                except Exception as exc:  # noqa: BLE001
                    messagebox.showwarning("曲线", str(exc))

    def save_fan_curves(self) -> None:
        self._save_fan_curves(apply=True)

    def _save_fan_curves(self, *, apply: bool) -> None:
        try:
            cpu = self._parse_points(self.curve_cpu_var.get())
            gpu = self._parse_points(self.curve_gpu_var.get())
        except Exception:
            messagebox.showerror("错误", "曲线格式无效，请用: 温度,RPM; 温度,RPM; …")
            return
        # Explicitly allow 0–5500; reject nothing in that range.
        for label, pts in (("CPU", cpu), ("GPU", gpu)):
            for t, r in pts:
                if r < 0 or r > 5500:
                    messagebox.showerror("错误", f"{label} 曲线 RPM 超范围: {t}°C → {r}")
                    return
        from .backends.fan_curve import FanCurveConfig

        cfg = FanCurveConfig(
            enabled=bool(self.curve_enabled.get()),
            cpu_points=cpu,
            gpu_points=gpu,
        )
        self.manager.update_fan_curves(cfg)
        self.curve_cpu_var.set(self._points_to_text(cfg.cpu_points))
        self.curve_gpu_var.set(self._points_to_text(cfg.gpu_points))
        self._sync_fan_mutex_ui()
        cfg_path = str(getattr(self.manager, "path", "") or "")
        # Confirm first CPU point landed on disk (helps catch stale editor views).
        disk_hint = ""
        try:
            import json
            from pathlib import Path

            raw = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
            first = (raw.get("fan_curves") or {}).get("cpu") or []
            if first:
                disk_hint = f" 盘上首点={first[0][0]}°/{first[0][1]}"
        except Exception:
            pass
        if apply:
            cb = getattr(self, "on_fan_curves_changed", None)
            if cb:
                try:
                    cb()
                except Exception as exc:  # noqa: BLE001
                    messagebox.showwarning("曲线", str(exc))
                    return
            self._set_status(
                "风扇曲线已保存"
                + ("并启用" if cfg.enabled else "（未启用，档位风扇应已恢复）")
                + f" → {cfg_path}"
                + disk_hint
            )
        else:
            self._set_status(
                f"风扇曲线已写入（CPU {len(cfg.cpu_points)} 点 / GPU {len(cfg.gpu_points)} 点；"
                f"启用={'是' if cfg.enabled else '否'}）→ {cfg_path}{disk_hint}"
            )

    def force_write_fan_curves(self) -> None:
        """Save editor points, then force one EC write of current curve targets."""
        self._save_fan_curves(apply=False)
        cb = getattr(self, "on_fan_curves_force_write", None)
        if not cb:
            self._set_status("强制写入回调未连接")
            return
        try:
            cb()
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning("强制写入", str(exc))

    def _on_features_changed(self) -> None:
        self.manager.set_feature("enable_cpu_level", bool(self.feat_cpu_level.get()))
        self.manager.set_feature("enable_gpu_level", bool(self.feat_gpu.get()))
        self.manager.set_feature("enable_undervolt", bool(self.feat_uv.get()))
        flags = (
            f"CPU档={'开' if self.feat_cpu_level.get() else '关'} "
            f"GPU={'开' if self.feat_gpu.get() else '关'} "
            f"UV={'开' if self.feat_uv.get() else '关'} "
            f"曲线={'开' if self.curve_enabled.get() else '关'}"
        )
        self._set_status(f"功能模块已更新: {flags}")
        cb = getattr(self, "on_features_changed", None)
        if cb:
            try:
                cb()
            except Exception:
                pass

    def _on_curve_enable_toggle(self) -> None:
        """Mutual exclusion: enabling curves yields profile fans; disabling restores them."""
        # Keep whatever points are currently in the editors.
        self._save_fan_curves(apply=True)

    def _open_profiles_file(self) -> None:
        path = getattr(self.manager, "path", None)
        if not path:
            messagebox.showinfo("配置", "未找到 profiles.json 路径")
            return
        from pathlib import Path
        import os

        p = Path(path)
        if not p.is_file():
            messagebox.showwarning("配置", f"文件不存在:\n{p}")
            return
        try:
            os.startfile(str(p))  # noqa: S606 — Windows open with default editor
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("配置", f"无法打开:\n{p}\n{exc}")

    def set_xtu_path_label(self, path: str, found: bool) -> None:
        if found and path:
            self.xtu_var.set(f"XTU(IET): {path}")
        else:
            self.xtu_var.set("XTU(IET): 未检测到（可手动安装 Intel Extreme Tuning Utility）")

    def _on_sensor_tray_toggle(self) -> None:
        enabled = bool(self.sensor_tray_var.get())
        if self.on_sensor_tray_changed:
            try:
                self.on_sensor_tray_changed(enabled)
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"传感器托盘切换失败: {exc}")
        else:
            self.manager.update_settings(sensor_tray_enabled=enabled)
            self._set_status("传感器托盘已显示" if enabled else "传感器托盘已隐藏")

    def set_sensor_tray_enabled(self, enabled: bool) -> None:
        self.sensor_tray_var.set(bool(enabled))

    def _on_autostart_toggle(self) -> None:
        enabled = bool(self.autostart_var.get())
        if self.on_autostart_changed:
            try:
                self.on_autostart_changed(enabled)
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"开机自启切换失败: {exc}")
                try:
                    from . import autostart

                    self.autostart_var.set(autostart.is_enabled())
                except Exception:
                    pass
        else:
            self._set_status("开机自启回调未连接")

    def set_autostart_enabled(self, enabled: bool) -> None:
        self.autostart_var.set(bool(enabled))

    def _on_osd_cfg_change(self, cfg) -> None:
        from .osd_overlay import OsdConfig

        prev = OsdConfig.from_dict((self.manager.settings or {}).get("osd"))
        cfg.x, cfg.y = prev.x, prev.y
        self.manager.update_settings(osd=cfg.to_dict())
        if self.on_osd_changed:
            try:
                self.on_osd_changed(cfg)
            except Exception as exc:  # noqa: BLE001
                self._set_status(f"OSD 更新失败: {exc}")
                return
        self._set_status("桌面 OSD 已更新" + ("（已启用）" if cfg.enabled else "（已关闭）"))

    def refresh_list(self) -> None:
        self.listbox.delete(0, tk.END)
        for p in self.manager.profiles:
            mark = " *" if p.id == self.manager.active_profile_id else ""
            hk = f"  [{p.hotkey}]" if p.hotkey else ""
            self.listbox.insert(
                tk.END,
                f"{p.name}  CPU档 {getattr(p,'cpu_level','?')}  "
                f"PL {p.pl1_w:.0f}/{p.pl2_w:.0f}  GPU {p.gpu_level}  "
                f"Fan {getattr(p,'fan_mode','auto')}"
                + (f":{p.fan_rpm}" if getattr(p, "fan_mode", "") == "manual" else "")
                + f"{hk}{mark}",
            )

    def _selected_profile(self) -> Optional["Profile"]:
        sel = self.listbox.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.manager.profiles):
            return None
        return self.manager.profiles[idx]

    def _on_select(self, _evt=None) -> None:
        p = self._selected_profile()
        if not p:
            return
        self._load_profile_into_editor(p)

    def _load_profile_into_editor(self, p: "Profile") -> None:
        self._editing_id = p.id
        self.name_var.set(p.name)
        self.pl1_var.set(str(p.pl1_w))
        self.pl2_var.set(str(p.pl2_w))
        self.tau_var.set(str(p.tau_s))
        self.cpu_level_var.set(getattr(p, "cpu_level", "boost") or "boost")
        self.gpu_var.set(p.gpu_level)
        self.fan_mode_var.set(getattr(p, "fan_mode", "max" if p.max_fan else "auto"))
        self.fan_rpm_var.set(str(getattr(p, "fan_rpm", 3000)))
        self.max_fan_var.set(p.max_fan)
        self.ab_var.set("" if p.afterburner_profile is None else str(p.afterburner_profile))
        self.hotkey_var.set(p.hotkey or "")

    def _on_fan_mode(self) -> None:
        # no-op hook for future enable/disable rpm entry styling
        pass

    def _maybe_auto_pl2(self, _evt=None) -> None:
        if not self.auto_pl2_var.get():
            return
        try:
            pl1 = float(self.pl1_var.get())
            self.pl2_var.set(str(pl1 + 20))
        except ValueError:
            pass

    def _read_editor(self) -> dict:
        ab_raw = self.ab_var.get().strip()
        ab = int(ab_raw) if ab_raw else None
        hk = self.hotkey_var.get().strip().lower() or None
        fan_mode = self.fan_mode_var.get().strip().lower() or "auto"
        fan_rpm = int(float(self.fan_rpm_var.get() or 3000))
        return {
            "name": self.name_var.get().strip() or "未命名",
            "pl1_w": float(self.pl1_var.get()),
            "pl2_w": float(self.pl2_var.get()),
            "tau_s": float(self.tau_var.get()),
            "cpu_level": self.cpu_level_var.get(),
            "gpu_level": self.gpu_var.get(),
            "fan_mode": fan_mode,
            "fan_rpm": fan_rpm,
            "max_fan": fan_mode == "max",
            "afterburner_profile": ab,
            "hotkey": hk,
        }

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _show_result(self, title: str, messages: list[str], ok: bool) -> None:
        body = "\n".join(messages) if messages else "(无详细信息)"
        self._set_status(("成功: " if ok else "部分失败: ") + (messages[0] if messages else title))
        if not ok:
            messagebox.showwarning(title, body)
        else:
            self.status_var.set(" | ".join(messages)[:180])

    def _run_apply_async(self, fn) -> None:
        if self._busy:
            self._set_status("正在应用，请稍候…")
            return
        self._busy = True
        self._set_status("正在应用…")

        import threading

        def worker():
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001
                from .profile_manager import ApplyResult

                result = ApplyResult(ok=False, messages=[str(exc)])
            self.root.after(0, lambda: self._finish_apply(result))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_apply(self, result) -> None:
        self._busy = False
        self.refresh_list()
        self._show_result("应用档位", result.messages, result.ok)

    def apply_selected(self) -> None:
        p = self._selected_profile()
        if not p:
            messagebox.showinfo("提示", "请先选择性能档")
            return
        self._run_apply_async(lambda: self.manager.apply_profile(p))

    def apply_editor(self) -> None:
        try:
            data = self._read_editor()
        except ValueError:
            messagebox.showerror("错误", "请检查数值格式")
            return
        from .profile_manager import Profile

        temp = Profile(
            id=self._editing_id or "temp-apply",
            name=data["name"],
            pl1_w=data["pl1_w"],
            pl2_w=data["pl2_w"],
            tau_s=data["tau_s"],
            cpu_level=data.get("cpu_level", "boost"),
            gpu_level=data["gpu_level"],
            fan_mode=data["fan_mode"],
            fan_rpm=data["fan_rpm"],
            max_fan=data["max_fan"],
            afterburner_profile=data["afterburner_profile"],
            hotkey=data["hotkey"],
        )
        remember = bool(self._editing_id)
        self._run_apply_async(
            lambda: self.manager.apply_profile(temp, remember_active=remember)
        )

    def save_current(self) -> None:
        if not self._editing_id:
            messagebox.showinfo("提示", "请先选择要覆盖的档，或使用另存为")
            return
        try:
            data = self._read_editor()
        except ValueError:
            messagebox.showerror("错误", "请检查数值格式")
            return
        from .profile_manager import Profile

        p = Profile(id=self._editing_id, **data)
        self.manager.upsert(p)
        if self.on_hotkeys_changed:
            self.on_hotkeys_changed()
        self.refresh_list()
        self._set_status(f"已保存: {p.name}")

    def save_as_new(self) -> None:
        try:
            data = self._read_editor()
        except ValueError:
            messagebox.showerror("错误", "请检查数值格式")
            return
        name = simpledialog.askstring("另存为", "新性能档名称:", initialvalue=data["name"])
        if not name:
            return
        p = self.manager.create(
            name=name,
            pl1_w=data["pl1_w"],
            pl2_w=data["pl2_w"],
            tau_s=data["tau_s"],
            cpu_level=data.get("cpu_level", "boost"),
            gpu_level=data["gpu_level"],
            max_fan=data["max_fan"],
            fan_mode=data["fan_mode"],
            fan_rpm=data["fan_rpm"],
            afterburner_profile=data["afterburner_profile"],
            hotkey=data["hotkey"],
        )
        self._editing_id = p.id
        if self.on_hotkeys_changed:
            self.on_hotkeys_changed()
        self.refresh_list()
        self._set_status(f"已新建: {p.name}")

    def delete_selected(self) -> None:
        p = self._selected_profile()
        if not p:
            return
        if not messagebox.askyesno("确认", f"删除性能档「{p.name}」？"):
            return
        self.manager.delete(p.id)
        self._editing_id = None
        if self.on_hotkeys_changed:
            self.on_hotkeys_changed()
        self.refresh_list()

    def save_undervolt(self) -> None:
        try:
            core = float(self.uv_core.get())
            cache = float(self.uv_cache.get())
            ecache = float(self.uv_ecache.get())
        except ValueError:
            messagebox.showerror("错误", "降压数值无效")
            return
        self.manager.update_undervolt(core, cache, ecache)
        self._set_status("降压配置已保存（将在下次应用档位时生效）")

    def reapply_uv(self) -> None:
        self.save_undervolt()
        result = self.manager.reapply_undervolt()
        self._show_result("重新应用降压", result.messages, result.ok)

    def restore_defaults(self) -> None:
        if not messagebox.askyesno("确认", "恢复默认：电压归零并应用安全档？"):
            return
        result = self.manager.restore_defaults()
        self.uv_core.set("0")
        self.uv_cache.set("0")
        self.uv_ecache.set("0")
        self.manager.update_undervolt(0, 0, 0)
        self.refresh_list()
        self._show_result("恢复默认", result.messages, result.ok)

    def _poll_live(self) -> None:
        # Skip heavy polling while applying.
        if getattr(self, "_busy", False):
            self.root.after(1000, self._poll_live)
            return
        lines = []
        if self.status_provider:
            try:
                info = self.status_provider()
                for k, v in info.items():
                    lines.append(f"{k}: {v}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"状态错误: {exc}")
        if self.monitor is not None:
            try:
                g = self.monitor.read_gpu()
                lines.append(
                    f"GPU: {g.name or '-'}  功耗={g.power_draw_w}W  "
                    f"Ceiling={g.ceiling_w}W  Max={g.max_w}W"
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(f"GPU 读数失败: {exc}")
        active = self.manager.active_profile_id or "-"
        lines.append(f"当前档 ID: {active}")
        self.live_var.set("\n".join(lines) if lines else "无读数")
        self.root.after(4000, self._poll_live)
