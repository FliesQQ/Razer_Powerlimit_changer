"""Main GUI: profile list + combo editor + undervolt + status."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import TYPE_CHECKING, Callable, Optional

from . import i18n
from .auto_bright import AutoBrightConfig
from .backends.brightness import clamp_brightness
from .i18n import t
from .widgets.fan_curve_chart import FanCurveChart
from .widgets.hotkey_capture import HotkeyCapture

if TYPE_CHECKING:
    from .profile_manager import Profile, ProfileManager


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

        settings0 = getattr(manager, "settings", {}) or {}
        i18n.init_from_settings(settings0)
        self.lang_var = tk.StringVar(value=i18n.get_lang())

        root.title(t("app_title"))
        from .theme import apply_theme

        apply_theme(root)
        # Tall enough for fan-curve tab (two charts + tools + buttons + live status).
        self._win_w, self._win_h = 1040, 980
        root.geometry(f"{self._win_w}x{self._win_h}")
        root.minsize(self._win_w, self._win_h)
        root.maxsize(self._win_w, self._win_h)
        root.resizable(False, False)
        # Remove maximize / thick-frame sizing on Windows after HWND exists.
        root.after(50, self._lock_window_chrome)

        self.status_var = tk.StringVar(value=t("ready"))
        self.live_var = tk.StringVar(value=t("live_loading"))
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
        settings = settings0
        xtu = settings.get("xtu_path") or t("xtu_none")
        self.xtu_var = tk.StringVar(value=f"XTU: {xtu}")
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
        self.on_auto_bright_changed: Optional[Callable[[], None]] = None
        self.on_profile_applied: Optional[Callable[[], None]] = None
        self.on_tray_menu_profiles_changed: Optional[Callable[[], None]] = None
        self._auto_bright_ctrl = None
        self._ab_save_timer = None
        self._tray_profile_vars: dict[str, tk.BooleanVar] = {}

        ab0 = AutoBrightConfig.from_dict(settings.get("auto_bright"))
        self.ab_enabled = tk.BooleanVar(value=bool(ab0.enabled))
        self.ab_oled = tk.BooleanVar(value=bool(ab0.oled_mode))
        self.ab_lock = tk.BooleanVar(value=bool(ab0.brightness_lock))
        self.ab_plug = tk.IntVar(value=int(ab0.plug_bright))
        self.ab_bat = tk.IntVar(value=int(ab0.bat_bright))
        self.ab_lock_mode = tk.StringVar(value=ab0.lock_mode)
        self.ab_lock_probe = tk.StringVar(value=ab0.lock_probe_profile)
        self.ab_lock_delay = tk.StringVar(value=str(ab0.lock_delay_sec))
        self.ab_power_var = tk.StringVar(value=t("bright_power", state="—"))
        self.ab_status_var = tk.StringVar(
            value=t("bright_status", msg=t("bright_status_idle"))
        )
        self.ab_mode_var = tk.StringVar(
            value=t("bright_mode", mode=t("bright_mode_native"))
        )

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
        from .theme import style_canvas, style_listbox

        # Status bar at the very bottom; live status sits just above it (all tabs).
        bottom = ttk.Frame(self.root, style="Status.TFrame", padding=(12, 6, 12, 8))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").pack(
            side=tk.LEFT
        )

        self._live_frame = ttk.LabelFrame(
            self.root, text=t("live_status"), style="Live.TLabelframe", padding=(10, 6)
        )
        self._live_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 4))
        self._live_lbl = ttk.Label(
            self._live_frame,
            textvariable=self.live_var,
            justify=tk.LEFT,
            wraplength=1000,
            style="Live.TLabel",
        )
        self._live_lbl.pack(anchor=tk.W, fill=tk.X)

        top = ttk.Frame(self.root, padding=(10, 10, 10, 4))
        top.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self._profiles_frame = ttk.LabelFrame(top, text=t("profiles"), padding=8)
        self._profiles_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 10))

        self.listbox = tk.Listbox(
            self._profiles_frame, width=18, height=16, exportselection=False
        )
        style_listbox(self.listbox)
        self.listbox.pack(fill=tk.Y, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        lb_btns = ttk.Frame(self._profiles_frame)
        lb_btns.pack(fill=tk.X, pady=(8, 0))
        self._btn_apply = ttk.Button(
            lb_btns,
            text=t("apply"),
            width=7,
            style="Accent.TButton",
            command=self.apply_selected,
        )
        self._btn_apply.pack(side=tk.LEFT, padx=(0, 4))
        self._btn_delete = ttk.Button(
            lb_btns, text=t("delete"), width=7, command=self.delete_selected
        )
        self._btn_delete.pack(side=tk.LEFT)

        right = ttk.Frame(top)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._nb = ttk.Notebook(right)
        self._nb.pack(fill=tk.BOTH, expand=True)
        tab_main = ttk.Frame(self._nb, padding=6)
        tab_curve_outer = ttk.Frame(self._nb)
        tab_osd = ttk.Frame(self._nb, padding=6)
        tab_tray = ttk.Frame(self._nb, padding=6)
        tab_bright_outer = ttk.Frame(self._nb)
        self._nb.add(tab_main, text=t("tab_home"))
        self._nb.add(tab_curve_outer, text=t("tab_fan"))
        self._nb.add(tab_osd, text=t("tab_osd"))
        self._nb.add(tab_tray, text=t("tab_tray"))
        self._nb.add(tab_bright_outer, text=t("tab_bright"))

        curve_canvas = tk.Canvas(tab_curve_outer, highlightthickness=0)
        style_canvas(curve_canvas)
        curve_scroll = ttk.Scrollbar(
            tab_curve_outer, orient=tk.VERTICAL, command=curve_canvas.yview
        )
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

        lang_row = ttk.Frame(tab_main)
        lang_row.pack(fill=tk.X, pady=(0, 8))
        self._lbl_lang = ttk.Label(lang_row, text=t("lang_label"))
        self._lbl_lang.pack(side=tk.LEFT, padx=(2, 0))
        self._rb_lang_zh = ttk.Radiobutton(
            lang_row,
            text=t("lang_zh"),
            value="zh",
            variable=self.lang_var,
            command=self._on_lang_change,
        )
        self._rb_lang_zh.pack(side=tk.LEFT, padx=(8, 4))
        self._rb_lang_en = ttk.Radiobutton(
            lang_row,
            text=t("lang_en"),
            value="en",
            variable=self.lang_var,
            command=self._on_lang_change,
        )
        self._rb_lang_en.pack(side=tk.LEFT, padx=4)

        self._feats = ttk.LabelFrame(tab_main, text=t("features"), padding=8)
        self._feats.pack(fill=tk.X, pady=(0, 6))
        self._chk_feat_cpu = ttk.Checkbutton(
            self._feats,
            text=t("feat_cpu"),
            variable=self.feat_cpu_level,
            command=self._on_features_changed,
        )
        self._chk_feat_cpu.grid(row=0, column=0, sticky=tk.W, padx=(0, 12))
        self._chk_feat_gpu = ttk.Checkbutton(
            self._feats,
            text=t("feat_gpu"),
            variable=self.feat_gpu,
            command=self._on_features_changed,
        )
        self._chk_feat_gpu.grid(row=0, column=1, sticky=tk.W, padx=(0, 12))
        self._chk_feat_uv = ttk.Checkbutton(
            self._feats,
            text=t("feat_uv"),
            variable=self.feat_uv,
            command=self._on_features_changed,
        )
        self._chk_feat_uv.grid(row=0, column=2, sticky=tk.W, padx=(0, 12))
        self._lbl_feat_hint = ttk.Label(
            self._feats, text=t("feat_hint"), style="Muted.TLabel"
        )
        self._lbl_feat_hint.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

        self._editor = ttk.LabelFrame(tab_main, text=t("editor"), padding=8)
        self._editor.pack(fill=tk.X)

        r = 0
        self._lbl_name = ttk.Label(self._editor, text=t("name"))
        self._lbl_name.grid(row=r, column=0, sticky=tk.W, pady=2)
        ttk.Entry(self._editor, textvariable=self.name_var, width=28).grid(
            row=r, column=1, columnspan=3, sticky=tk.W
        )
        r += 1
        self._lbl_pl1 = ttk.Label(self._editor, text=t("pl1"))
        self._lbl_pl1.grid(row=r, column=0, sticky=tk.W, pady=2)
        e_pl1 = ttk.Entry(self._editor, textvariable=self.pl1_var, width=10)
        e_pl1.grid(row=r, column=1, sticky=tk.W)
        e_pl1.bind("<KeyRelease>", self._maybe_auto_pl2)
        self._lbl_pl2 = ttk.Label(self._editor, text=t("pl2"))
        self._lbl_pl2.grid(row=r, column=2, sticky=tk.W, padx=(12, 0))
        ttk.Entry(self._editor, textvariable=self.pl2_var, width=10).grid(
            row=r, column=3, sticky=tk.W
        )
        r += 1
        self._chk_auto_pl2 = ttk.Checkbutton(
            self._editor,
            text=t("auto_pl2"),
            variable=self.auto_pl2_var,
            command=self._maybe_auto_pl2,
        )
        self._chk_auto_pl2.grid(row=r, column=1, columnspan=2, sticky=tk.W)
        r += 1
        self._lbl_tau = ttk.Label(self._editor, text=t("tau"))
        self._lbl_tau.grid(row=r, column=0, sticky=tk.W, pady=2)
        ttk.Entry(self._editor, textvariable=self.tau_var, width=10).grid(
            row=r, column=1, sticky=tk.W
        )
        self._lbl_tau_hint = ttk.Label(
            self._editor, text=t("tau_hint"), style="Muted.TLabel"
        )
        self._lbl_tau_hint.grid(row=r, column=2, columnspan=2, sticky=tk.W, padx=(8, 0))
        r += 1
        self._lbl_cpu_tier = ttk.Label(self._editor, text=t("cpu_tier"))
        self._lbl_cpu_tier.grid(row=r, column=0, sticky=tk.W, pady=2)
        self._cpu_frame = ttk.Frame(self._editor)
        self._cpu_frame.grid(row=r, column=1, columnspan=3, sticky=tk.W)
        self._cpu_radios = []
        for text, val in i18n.cpu_level_labels():
            rb = ttk.Radiobutton(
                self._cpu_frame, text=text, value=val, variable=self.cpu_level_var
            )
            rb.pack(side=tk.LEFT, padx=4)
            self._cpu_radios.append(rb)
        r += 1
        self._lbl_gpu_tier = ttk.Label(self._editor, text=t("gpu_tier"))
        self._lbl_gpu_tier.grid(row=r, column=0, sticky=tk.W, pady=2)
        self._gpu_frame = ttk.Frame(self._editor)
        self._gpu_frame.grid(row=r, column=1, columnspan=3, sticky=tk.W)
        self._gpu_radios = []
        for text, val in i18n.gpu_level_labels():
            rb = ttk.Radiobutton(
                self._gpu_frame, text=text, value=val, variable=self.gpu_var
            )
            rb.pack(side=tk.LEFT, padx=4)
            self._gpu_radios.append(rb)
        r += 1
        self._lbl_fan = ttk.Label(self._editor, text=t("fan"))
        self._lbl_fan.grid(row=r, column=0, sticky=tk.W, pady=2)
        self._fan_frame = ttk.Frame(self._editor)
        self._fan_frame.grid(row=r, column=1, columnspan=3, sticky=tk.W)
        self._fan_mode_radios = []
        for text, val in i18n.fan_mode_labels():
            rb = ttk.Radiobutton(
                self._fan_frame,
                text=text,
                value=val,
                variable=self.fan_mode_var,
                command=self._on_fan_mode,
            )
            rb.pack(side=tk.LEFT, padx=4)
            self._fan_mode_radios.append(rb)
        r += 1
        self.fan_mutex_hint = ttk.Label(self._editor, text="", style="Hint.TLabel")
        self.fan_mutex_hint.grid(row=r, column=1, columnspan=3, sticky=tk.W)
        r += 1
        self._lbl_fan_rpm = ttk.Label(self._editor, text=t("fan_rpm"))
        self._lbl_fan_rpm.grid(row=r, column=0, sticky=tk.W, pady=2)
        ttk.Entry(self._editor, textvariable=self.fan_rpm_var, width=10).grid(
            row=r, column=1, sticky=tk.W
        )
        self._lbl_fan_rpm_hint = ttk.Label(self._editor, text=t("fan_rpm_hint"))
        self._lbl_fan_rpm_hint.grid(row=r, column=2, sticky=tk.W)
        r += 1
        self._lbl_ab = ttk.Label(self._editor, text=t("ab"))
        self._lbl_ab.grid(row=r, column=0, sticky=tk.W, pady=2)
        ttk.Entry(self._editor, textvariable=self.ab_var, width=10).grid(
            row=r, column=1, sticky=tk.W
        )
        self._lbl_ab_hint = ttk.Label(self._editor, text=t("ab_hint"))
        self._lbl_ab_hint.grid(row=r, column=2, sticky=tk.W)
        r += 1
        self._lbl_hotkey = ttk.Label(self._editor, text=t("hotkey"))
        self._lbl_hotkey.grid(row=r, column=0, sticky=tk.W, pady=2)
        HotkeyCapture(self._editor, textvariable=self.hotkey_var).grid(
            row=r, column=1, columnspan=3, sticky=tk.W
        )

        btns = ttk.Frame(self._editor)
        btns.grid(row=r + 1, column=0, columnspan=4, sticky=tk.W, pady=8)
        self._btn_apply_now = ttk.Button(
            btns, text=t("apply_now"), style="Accent.TButton", command=self.apply_editor
        )
        self._btn_apply_now.pack(side=tk.LEFT, padx=3)
        self._btn_save_cur = ttk.Button(
            btns, text=t("save_current"), command=self.save_current
        )
        self._btn_save_cur.pack(side=tk.LEFT, padx=3)
        self._btn_save_as = ttk.Button(
            btns, text=t("save_as"), command=self.save_as_new
        )
        self._btn_save_as.pack(side=tk.LEFT, padx=3)

        self._uv = ttk.LabelFrame(tab_main, text=t("uv_title"), padding=8)
        self._uv.pack(fill=tk.X, pady=8)
        ttk.Label(self._uv, text="Core mV").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(self._uv, textvariable=self.uv_core, width=10).grid(
            row=0, column=1, padx=4
        )
        ttk.Label(self._uv, text="Cache mV").grid(
            row=0, column=2, sticky=tk.W, padx=(8, 0)
        )
        ttk.Entry(self._uv, textvariable=self.uv_cache, width=10).grid(
            row=0, column=3, padx=4
        )
        ttk.Label(self._uv, text="E-Cache mV").grid(
            row=0, column=4, sticky=tk.W, padx=(8, 0)
        )
        ttk.Entry(self._uv, textvariable=self.uv_ecache, width=10).grid(
            row=0, column=5, padx=4
        )
        uv_btns = ttk.Frame(self._uv)
        uv_btns.grid(row=1, column=0, columnspan=6, sticky=tk.W, pady=6)
        self._btn_uv_save = ttk.Button(
            uv_btns, text=t("uv_save"), command=self.save_undervolt
        )
        self._btn_uv_save.pack(side=tk.LEFT, padx=3)
        self._btn_uv_reapply = ttk.Button(
            uv_btns, text=t("uv_reapply"), command=self.reapply_uv
        )
        self._btn_uv_reapply.pack(side=tk.LEFT, padx=3)
        self._btn_uv_restore = ttk.Button(
            uv_btns, text=t("uv_restore"), command=self.restore_defaults
        )
        self._btn_uv_restore.pack(side=tk.LEFT, padx=3)
        ttk.Label(self._uv, textvariable=self.xtu_var, wraplength=640).grid(
            row=2, column=0, columnspan=6, sticky=tk.W, pady=(4, 0)
        )

        self._chk_curve = ttk.Checkbutton(
            tab_curve,
            text=t("curve_enable"),
            variable=self.curve_enabled,
            command=self._on_curve_enable_toggle,
        )
        self._chk_curve.pack(anchor=tk.W)
        charts = ttk.Frame(tab_curve)
        charts.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self._chart_cpu = FanCurveChart(
            charts,
            title=t("chart_cpu"),
            textvariable=self.curve_cpu_var,
            width=440,
            height=155,
        )
        self._chart_cpu.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        self._chart_gpu = FanCurveChart(
            charts,
            title=t("chart_gpu"),
            textvariable=self.curve_gpu_var,
            width=440,
            height=155,
        )
        self._chart_gpu.pack(fill=tk.BOTH, expand=True)
        self._lbl_curve_hint = ttk.Label(
            tab_curve, text=t("curve_hint"), justify=tk.LEFT
        )
        self._lbl_curve_hint.pack(anchor=tk.W, pady=4)
        btns_c = ttk.Frame(tab_curve)
        btns_c.pack(anchor=tk.W, pady=(2, 0))
        self._btn_curve_save = ttk.Button(
            btns_c, text=t("curve_save_only"), command=self.save_fan_curves_only
        )
        self._btn_curve_save.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_curve_apply = ttk.Button(
            btns_c, text=t("curve_save_apply"), command=self.save_fan_curves
        )
        self._btn_curve_apply.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_curve_force = ttk.Button(
            btns_c, text=t("curve_force"), command=self.force_write_fan_curves
        )
        self._btn_curve_force.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_open_cfg = ttk.Button(
            btns_c, text=t("open_config"), command=self._open_profiles_file
        )
        self._btn_open_cfg.pack(side=tk.LEFT)

        from .osd_overlay import OsdConfig, OsdSettingsPanel

        osd_cfg = OsdConfig.from_dict(
            (getattr(self.manager, "settings", {}) or {}).get("osd")
        )
        self.osd_panel = OsdSettingsPanel(
            tab_osd,
            initial=osd_cfg,
            on_change=self._on_osd_cfg_change,
            title=t("osd_title"),
        )
        self.osd_panel.pack(fill=tk.BOTH, expand=True)

        self._lbl_tray_desc = ttk.Label(
            tab_tray, text=t("tray_sensors_desc"), wraplength=640
        )
        self._lbl_tray_desc.pack(anchor=tk.W, pady=(0, 8))
        self._chk_sensor_tray = ttk.Checkbutton(
            tab_tray,
            text=t("tray_sensors_enable"),
            variable=self.sensor_tray_var,
            command=self._on_sensor_tray_toggle,
        )
        self._chk_sensor_tray.pack(anchor=tk.W)
        self._lbl_tray_hint = ttk.Label(
            tab_tray, text=t("tray_sensors_hint"), wraplength=640
        )
        self._lbl_tray_hint.pack(anchor=tk.W, pady=(8, 0))

        ttk.Separator(tab_tray).pack(fill=tk.X, pady=12)
        self._lbl_tray_menu_profiles = ttk.Label(
            tab_tray, text=t("tray_menu_profiles"), font=("Segoe UI", 10, "bold")
        )
        self._lbl_tray_menu_profiles.pack(anchor=tk.W)
        self._lbl_tray_menu_hint = ttk.Label(
            tab_tray, text=t("tray_menu_profiles_hint"), wraplength=640
        )
        self._lbl_tray_menu_hint.pack(anchor=tk.W, pady=(4, 6))
        tray_btns = ttk.Frame(tab_tray)
        tray_btns.pack(anchor=tk.W, fill=tk.X)
        self._btn_tray_all = ttk.Button(
            tray_btns, text=t("tray_menu_select_all"), command=self._tray_menu_select_all
        )
        self._btn_tray_all.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_tray_none = ttk.Button(
            tray_btns,
            text=t("tray_menu_select_none"),
            command=self._tray_menu_select_none,
        )
        self._btn_tray_none.pack(side=tk.LEFT)
        self._tray_profiles_frame = ttk.Frame(tab_tray)
        self._tray_profiles_frame.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))
        self._rebuild_tray_profile_checks()

        ttk.Separator(tab_tray).pack(fill=tk.X, pady=12)
        self._lbl_startup = ttk.Label(
            tab_tray, text=t("startup"), font=("Segoe UI", 10, "bold")
        )
        self._lbl_startup.pack(anchor=tk.W)
        self._chk_autostart = ttk.Checkbutton(
            tab_tray,
            text=t("autostart"),
            variable=self.autostart_var,
            command=self._on_autostart_toggle,
        )
        self._chk_autostart.pack(anchor=tk.W, pady=(6, 0))
        self._lbl_autostart_hint = ttk.Label(
            tab_tray, text=t("autostart_hint"), wraplength=640
        )
        self._lbl_autostart_hint.pack(anchor=tk.W, pady=(4, 0))

        self._build_auto_bright_tab(tab_bright_outer)
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
            hint.configure(text=t("fan_mutex") if curve_on else "")

    def _build_auto_bright_tab(self, outer: ttk.Frame) -> None:
        from .theme import style_canvas

        canvas = tk.Canvas(outer, highlightthickness=0)
        style_canvas(canvas)
        vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tab = ttk.Frame(canvas, padding=8)
        win = canvas.create_window((0, 0), window=tab, anchor="nw")

        def _on_frame_configure(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event) -> None:
            canvas.itemconfigure(win, width=event.width)

        def _on_mousewheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        tab.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self._chk_ab_enable = ttk.Checkbutton(
            tab,
            text=t("bright_enable"),
            variable=self.ab_enabled,
            command=self._on_ab_enable_toggle,
        )
        self._chk_ab_enable.pack(anchor=tk.W)
        self._lbl_ab_hint = ttk.Label(tab, text=t("bright_hint"), wraplength=640)
        self._lbl_ab_hint.pack(anchor=tk.W, pady=(4, 10))

        self._lbl_ab_power = ttk.Label(tab, textvariable=self.ab_power_var)
        self._lbl_ab_power.pack(anchor=tk.W)
        self._lbl_ab_status = ttk.Label(
            tab, textvariable=self.ab_status_var, wraplength=640
        )
        self._lbl_ab_status.pack(anchor=tk.W, pady=(2, 0))
        self._lbl_ab_mode = ttk.Label(tab, textvariable=self.ab_mode_var)
        self._lbl_ab_mode.pack(anchor=tk.W, pady=(2, 10))

        self._chk_ab_oled = ttk.Checkbutton(
            tab,
            text=t("bright_oled"),
            variable=self.ab_oled,
            command=self._on_ab_oled_toggle,
        )
        self._chk_ab_oled.pack(anchor=tk.W)
        self._chk_ab_lock = ttk.Checkbutton(
            tab,
            text=t("bright_lock"),
            variable=self.ab_lock,
            command=self._on_ab_lock_toggle,
        )
        self._chk_ab_lock.pack(anchor=tk.W, pady=(4, 8))

        row_mode = ttk.Frame(tab)
        row_mode.pack(fill=tk.X, pady=2)
        self._lbl_ab_lock_mode = ttk.Label(row_mode, text=t("bright_lock_mode"), width=14)
        self._lbl_ab_lock_mode.pack(side=tk.LEFT)
        self._ab_lock_mode_cb = ttk.Combobox(
            row_mode,
            state="readonly",
            width=36,
            values=[t("bright_lock_delay_restore"), t("bright_lock_until_power")],
        )
        self._ab_lock_mode_cb.pack(side=tk.LEFT, padx=(6, 0))
        self._ab_lock_mode_cb.bind("<<ComboboxSelected>>", self._on_ab_lock_mode_combo)

        row_delay = ttk.Frame(tab)
        row_delay.pack(fill=tk.X, pady=2)
        self._lbl_ab_lock_delay = ttk.Label(
            row_delay, text=t("bright_lock_delay"), width=14
        )
        self._lbl_ab_lock_delay.pack(side=tk.LEFT)
        self._ent_ab_lock_delay = ttk.Entry(
            row_delay, width=8, textvariable=self.ab_lock_delay, justify=tk.CENTER
        )
        self._ent_ab_lock_delay.pack(side=tk.LEFT, padx=(6, 0))
        self._ent_ab_lock_delay.bind("<Return>", self._on_ab_lock_delay_entry)
        self._ent_ab_lock_delay.bind("<FocusOut>", self._on_ab_lock_delay_entry)

        row_probe = ttk.Frame(tab)
        row_probe.pack(fill=tk.X, pady=(2, 10))
        self._lbl_ab_lock_probe = ttk.Label(
            row_probe, text=t("bright_lock_probe"), width=14
        )
        self._lbl_ab_lock_probe.pack(side=tk.LEFT)
        self._ab_lock_probe_cb = ttk.Combobox(
            row_probe,
            state="readonly",
            width=16,
            values=[
                t("bright_probe_eco"),
                t("bright_probe_balanced"),
                t("bright_probe_sensitive"),
            ],
        )
        self._ab_lock_probe_cb.pack(side=tk.LEFT, padx=(6, 0))
        self._ab_lock_probe_cb.bind("<<ComboboxSelected>>", self._on_ab_lock_probe_combo)
        self._sync_ab_lock_ui()

        row_plug = ttk.Frame(tab)
        row_plug.pack(fill=tk.X, pady=4)
        self._lbl_ab_plug = ttk.Label(row_plug, text=t("bright_plug"), width=14)
        self._lbl_ab_plug.pack(side=tk.LEFT)
        from .theme import COLORS as _c

        self._scl_ab_plug = tk.Scale(
            row_plug,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            showvalue=False,
            resolution=1,
            length=280,
            sliderlength=24,
            width=16,
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            sliderrelief=tk.RAISED,
            troughcolor=_c["surface2"],
            bg=_c["bg"],
            fg=_c["accent"],
            activebackground=_c["accent"],
            highlightbackground=_c["bg"],
            command=self._on_ab_plug_scale,
        )
        self._scl_ab_plug.set(self.ab_plug.get())
        self._scl_ab_plug.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self._ent_ab_plug = ttk.Entry(row_plug, width=5, justify=tk.CENTER)
        self._ent_ab_plug.insert(0, str(self.ab_plug.get()))
        self._ent_ab_plug.pack(side=tk.LEFT)
        self._ent_ab_plug.bind("<Return>", self._on_ab_plug_entry)
        self._ent_ab_plug.bind("<FocusOut>", self._on_ab_plug_entry)

        row_bat = ttk.Frame(tab)
        row_bat.pack(fill=tk.X, pady=4)
        self._lbl_ab_bat = ttk.Label(row_bat, text=t("bright_bat_level"), width=14)
        self._lbl_ab_bat.pack(side=tk.LEFT)
        self._scl_ab_bat = tk.Scale(
            row_bat,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            showvalue=False,
            resolution=1,
            length=280,
            sliderlength=24,
            width=16,
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            sliderrelief=tk.RAISED,
            troughcolor=_c["surface2"],
            bg=_c["bg"],
            fg=_c["accent"],
            activebackground=_c["accent"],
            highlightbackground=_c["bg"],
            command=self._on_ab_bat_scale,
        )
        self._scl_ab_bat.set(self.ab_bat.get())
        self._scl_ab_bat.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self._ent_ab_bat = ttk.Entry(row_bat, width=5, justify=tk.CENTER)
        self._ent_ab_bat.insert(0, str(self.ab_bat.get()))
        self._ent_ab_bat.pack(side=tk.LEFT)
        self._ent_ab_bat.bind("<Return>", self._on_ab_bat_entry)
        self._ent_ab_bat.bind("<FocusOut>", self._on_ab_bat_entry)

        btns = ttk.Frame(tab)
        btns.pack(fill=tk.X, pady=(14, 6))
        self._btn_ab_apply = ttk.Button(
            btns,
            text=t("bright_apply"),
            style="Accent.TButton",
            command=self._on_ab_apply,
        )
        self._btn_ab_apply.pack(side=tk.LEFT, padx=(0, 8))
        self._btn_ab_save = ttk.Button(
            btns, text=t("bright_save"), command=self._on_ab_save
        )
        self._btn_ab_save.pack(side=tk.LEFT)

        self._lbl_ab_poll_hint = ttk.Label(
            tab, text=t("bright_poll_hint"), wraplength=640
        )
        self._lbl_ab_poll_hint.pack(anchor=tk.W, pady=(8, 4))

    def bind_auto_bright_controller(self, ctrl) -> None:
        self._auto_bright_ctrl = ctrl
        if ctrl is not None:
            try:
                self.update_auto_bright_status(ctrl.status_snapshot())
            except Exception:
                pass

    def collect_auto_bright_config(self) -> AutoBrightConfig:
        prev = AutoBrightConfig.from_dict(
            (getattr(self.manager, "settings", {}) or {}).get("auto_bright")
        )
        oled = bool(self.ab_oled.get())
        plug = clamp_brightness(int(self.ab_plug.get()), oled)
        bat = clamp_brightness(int(self.ab_bat.get()), oled)
        try:
            delay = max(1, min(120, int(str(self.ab_lock_delay.get()).strip())))
        except ValueError:
            delay = prev.lock_delay_sec
        lock_mode = self.ab_lock_mode.get()
        if lock_mode not in {"delay_restore", "until_power_change"}:
            lock_mode = "delay_restore"
        probe = self.ab_lock_probe.get()
        if probe not in {"eco", "balanced", "sensitive"}:
            probe = "balanced"
        return AutoBrightConfig(
            enabled=bool(self.ab_enabled.get()),
            plug_bright=plug,
            bat_bright=bat,
            applied_plug_bright=prev.applied_plug_bright,
            applied_bat_bright=prev.applied_bat_bright,
            poll_ms=prev.poll_ms,
            oled_mode=oled,
            brightness_lock=bool(self.ab_lock.get()),
            lock_mode=lock_mode,
            lock_delay_sec=delay,
            lock_probe_profile=probe,
            prefer_compat_backend=prev.prefer_compat_backend,
        ).normalized()

    def _persist_auto_bright(
        self, cfg: AutoBrightConfig, *, notify: bool = True
    ) -> None:
        self.manager.update_settings(auto_bright=cfg.to_dict())
        if notify:
            cb = getattr(self, "on_auto_bright_changed", None)
            if cb:
                try:
                    cb()
                except Exception:
                    pass

    def _schedule_ab_save(self) -> None:
        if self._ab_save_timer is not None:
            try:
                self.root.after_cancel(self._ab_save_timer)
            except Exception:
                pass
        self._ab_save_timer = self.root.after(400, self._do_ab_save)

    def _do_ab_save(self) -> None:
        self._ab_save_timer = None
        cfg = self.collect_auto_bright_config()
        self._persist_auto_bright(cfg, notify=True)

    def _set_ab_status_text(self, msg: str, *, ok: Optional[bool] = True) -> None:
        self.ab_status_var.set(t("bright_status", msg=msg))
        _ = ok  # reserved for future color styling

    def update_auto_bright_status(self, snap: dict) -> None:
        ac = bool(snap.get("ac"))
        state = t("bright_ac") if ac else t("bright_bat")
        self.ab_power_var.set(t("bright_power", state=state))
        mode_key = (
            "bright_mode_compat"
            if snap.get("mode") == "compat"
            else "bright_mode_native"
        )
        self.ab_mode_var.set(t("bright_mode", mode=t(mode_key)))
        raw = str(snap.get("message") or "")
        if not raw:
            msg = t("bright_status_idle")
        elif raw == "lock_hold":
            msg = t("bright_lock_hold_msg")
        elif raw.startswith("lock_restore:"):
            parts = raw.split(":")
            try:
                sec, pct = int(parts[1]), int(parts[2])
            except (IndexError, ValueError):
                msg = raw
            else:
                msg = t("bright_lock_restore_msg", sec=sec, pct=pct)
        else:
            msg = raw
        self.ab_status_var.set(t("bright_status", msg=msg))

    def _sync_ab_lock_ui(self) -> None:
        mode = self.ab_lock_mode.get()
        text = (
            t("bright_lock_until_power")
            if mode == "until_power_change"
            else t("bright_lock_delay_restore")
        )
        try:
            self._ab_lock_mode_cb.set(text)
        except Exception:
            pass
        probe = self.ab_lock_probe.get()
        probe_map = {
            "eco": t("bright_probe_eco"),
            "sensitive": t("bright_probe_sensitive"),
            "balanced": t("bright_probe_balanced"),
        }
        try:
            self._ab_lock_probe_cb.set(probe_map.get(probe, t("bright_probe_balanced")))
        except Exception:
            pass
        delay_state = tk.NORMAL if mode == "delay_restore" else tk.DISABLED
        try:
            self._ent_ab_lock_delay.configure(state=delay_state)
        except Exception:
            pass

    def _entry_set_ab(self, entry: ttk.Entry, val: int) -> None:
        entry.delete(0, tk.END)
        entry.insert(0, str(int(val)))

    def _on_ab_enable_toggle(self) -> None:
        self._do_ab_save()
        on = bool(self.ab_enabled.get())
        self._set_ab_status_text(
            f"{t('bright_enable')} → {t('on') if on else t('off')}"
        )
        ctrl = self._auto_bright_ctrl
        if on and ctrl is not None:
            try:
                # Re-enable must re-apply even if AC line status did not change.
                ctrl.notify_resume()
            except Exception:
                pass

    def _on_ab_oled_toggle(self) -> None:
        oled = bool(self.ab_oled.get())
        for var, scale, entry in (
            (self.ab_plug, self._scl_ab_plug, self._ent_ab_plug),
            (self.ab_bat, self._scl_ab_bat, self._ent_ab_bat),
        ):
            v = clamp_brightness(int(var.get()), oled)
            var.set(v)
            scale.set(v)
            self._entry_set_ab(entry, v)
        self._set_ab_status_text(t("bright_oled_updated"))
        self._schedule_ab_save()

    def _on_ab_lock_toggle(self) -> None:
        self._set_ab_status_text(
            t("bright_lock_on") if self.ab_lock.get() else t("bright_lock_off")
        )
        self._schedule_ab_save()

    def _on_ab_lock_mode_combo(self, _event=None) -> None:
        text = self._ab_lock_mode_cb.get()
        if text == t("bright_lock_until_power"):
            self.ab_lock_mode.set("until_power_change")
        else:
            self.ab_lock_mode.set("delay_restore")
        self._sync_ab_lock_ui()
        self._set_ab_status_text(t("bright_lock_policy_updated"))
        self._schedule_ab_save()

    def _on_ab_lock_probe_combo(self, _event=None) -> None:
        text = self._ab_lock_probe_cb.get()
        if text == t("bright_probe_eco"):
            self.ab_lock_probe.set("eco")
        elif text == t("bright_probe_sensitive"):
            self.ab_lock_probe.set("sensitive")
        else:
            self.ab_lock_probe.set("balanced")
        self._set_ab_status_text(t("bright_lock_probe_updated"))
        self._schedule_ab_save()

    def _on_ab_lock_delay_entry(self, _event=None) -> None:
        try:
            v = max(1, min(120, int(str(self.ab_lock_delay.get()).strip())))
        except ValueError:
            v = 5
        self.ab_lock_delay.set(str(v))
        self._set_ab_status_text(t("bright_lock_delay_set", sec=v))
        self._schedule_ab_save()

    def _on_ab_plug_scale(self, _v=None) -> None:
        try:
            raw = int(round(float(self._scl_ab_plug.get())))
        except Exception:
            raw = int(self.ab_plug.get())
        v = clamp_brightness(raw, bool(self.ab_oled.get()))
        self.ab_plug.set(v)
        if abs(float(self._scl_ab_plug.get()) - v) > 0.5:
            self._scl_ab_plug.set(v)
        self._entry_set_ab(self._ent_ab_plug, v)
        self._set_ab_status_text(t("bright_pending"))
        self._schedule_ab_save()

    def _on_ab_bat_scale(self, _v=None) -> None:
        try:
            raw = int(round(float(self._scl_ab_bat.get())))
        except Exception:
            raw = int(self.ab_bat.get())
        v = clamp_brightness(raw, bool(self.ab_oled.get()))
        self.ab_bat.set(v)
        if abs(float(self._scl_ab_bat.get()) - v) > 0.5:
            self._scl_ab_bat.set(v)
        self._entry_set_ab(self._ent_ab_bat, v)
        self._set_ab_status_text(t("bright_pending"))
        self._schedule_ab_save()

    def _on_ab_plug_entry(self, _event=None) -> None:
        try:
            v = clamp_brightness(
                int(self._ent_ab_plug.get().strip()), bool(self.ab_oled.get())
            )
        except ValueError:
            v = int(self.ab_plug.get())
        self.ab_plug.set(v)
        self._scl_ab_plug.set(v)
        self._entry_set_ab(self._ent_ab_plug, v)
        self._set_ab_status_text(t("bright_pending"))
        self._schedule_ab_save()

    def _on_ab_bat_entry(self, _event=None) -> None:
        try:
            v = clamp_brightness(
                int(self._ent_ab_bat.get().strip()), bool(self.ab_oled.get())
            )
        except ValueError:
            v = int(self.ab_bat.get())
        self.ab_bat.set(v)
        self._scl_ab_bat.set(v)
        self._entry_set_ab(self._ent_ab_bat, v)
        self._set_ab_status_text(t("bright_pending"))
        self._schedule_ab_save()

    def _on_ab_apply(self) -> None:
        cfg = self.collect_auto_bright_config()
        cfg.applied_plug_bright = cfg.plug_bright
        cfg.applied_bat_bright = cfg.bat_bright
        self._persist_auto_bright(cfg, notify=True)
        ctrl = self._auto_bright_ctrl
        if ctrl is not None:
            try:
                ctrl.apply_now(commit_sliders=False)
            except Exception as exc:
                self._set_ab_status_text(str(exc), ok=False)
                return
        self._set_status(t("bright_apply"))

    def _on_ab_save(self) -> None:
        cfg = self.collect_auto_bright_config()
        self._persist_auto_bright(cfg, notify=True)
        self._set_ab_status_text(t("bright_saved"))
        self._set_status(t("bright_saved"))

    def _on_lang_change(self) -> None:
        lang = self.lang_var.get()
        i18n.set_lang(lang, notify=False)
        try:
            self.manager.update_settings(ui_language=i18n.get_lang())
        except Exception:
            pass
        self._apply_language()
        self._set_status(t("lang_switched"))
        # Refresh live panel immediately with new language (avoid stacked timers).
        aid = getattr(self, "_live_after", None)
        if aid is not None:
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        try:
            self._poll_live()
        except Exception:
            pass

    def _apply_language(self) -> None:
        self.root.title(t("app_title"))
        if self.status_var.get() in ("就绪", "Ready", ""):
            self.status_var.set(t("ready"))
        pairs = [
            ("_live_frame", "live_status"),
            ("_profiles_frame", "profiles"),
            ("_btn_apply", "apply"),
            ("_btn_delete", "delete"),
            ("_lbl_lang", "lang_label"),
            ("_rb_lang_zh", "lang_zh"),
            ("_rb_lang_en", "lang_en"),
            ("_feats", "features"),
            ("_chk_feat_cpu", "feat_cpu"),
            ("_chk_feat_gpu", "feat_gpu"),
            ("_chk_feat_uv", "feat_uv"),
            ("_lbl_feat_hint", "feat_hint"),
            ("_editor", "editor"),
            ("_lbl_name", "name"),
            ("_lbl_pl1", "pl1"),
            ("_lbl_pl2", "pl2"),
            ("_chk_auto_pl2", "auto_pl2"),
            ("_lbl_tau", "tau"),
            ("_lbl_tau_hint", "tau_hint"),
            ("_lbl_cpu_tier", "cpu_tier"),
            ("_lbl_gpu_tier", "gpu_tier"),
            ("_lbl_fan", "fan"),
            ("_lbl_fan_rpm", "fan_rpm"),
            ("_lbl_fan_rpm_hint", "fan_rpm_hint"),
            ("_lbl_ab", "ab"),
            ("_lbl_ab_hint", "ab_hint"),
            ("_lbl_hotkey", "hotkey"),
            ("_btn_apply_now", "apply_now"),
            ("_btn_save_cur", "save_current"),
            ("_btn_save_as", "save_as"),
            ("_uv", "uv_title"),
            ("_btn_uv_save", "uv_save"),
            ("_btn_uv_reapply", "uv_reapply"),
            ("_btn_uv_restore", "uv_restore"),
            ("_chk_curve", "curve_enable"),
            ("_lbl_curve_hint", "curve_hint"),
            ("_btn_curve_save", "curve_save_only"),
            ("_btn_curve_apply", "curve_save_apply"),
            ("_btn_curve_force", "curve_force"),
            ("_btn_open_cfg", "open_config"),
            ("_lbl_tray_desc", "tray_sensors_desc"),
            ("_chk_sensor_tray", "tray_sensors_enable"),
            ("_lbl_tray_hint", "tray_sensors_hint"),
            ("_lbl_tray_menu_profiles", "tray_menu_profiles"),
            ("_lbl_tray_menu_hint", "tray_menu_profiles_hint"),
            ("_btn_tray_all", "tray_menu_select_all"),
            ("_btn_tray_none", "tray_menu_select_none"),
            ("_lbl_startup", "startup"),
            ("_chk_autostart", "autostart"),
            ("_lbl_autostart_hint", "autostart_hint"),
            ("_chk_ab_enable", "bright_enable"),
            ("_lbl_ab_hint", "bright_hint"),
            ("_chk_ab_oled", "bright_oled"),
            ("_chk_ab_lock", "bright_lock"),
            ("_lbl_ab_lock_mode", "bright_lock_mode"),
            ("_lbl_ab_lock_delay", "bright_lock_delay"),
            ("_lbl_ab_lock_probe", "bright_lock_probe"),
            ("_lbl_ab_plug", "bright_plug"),
            ("_lbl_ab_bat", "bright_bat_level"),
            ("_btn_ab_apply", "bright_apply"),
            ("_btn_ab_save", "bright_save"),
            ("_lbl_ab_poll_hint", "bright_poll_hint"),
        ]
        for attr, key in pairs:
            w = getattr(self, attr, None)
            if w is not None:
                try:
                    w.configure(text=t(key))
                except Exception:
                    pass
        nb = getattr(self, "_nb", None)
        if nb is not None:
            try:
                nb.tab(0, text=t("tab_home"))
                nb.tab(1, text=t("tab_fan"))
                nb.tab(2, text=t("tab_osd"))
                nb.tab(3, text=t("tab_tray"))
                nb.tab(4, text=t("tab_bright"))
            except Exception:
                pass
        try:
            if hasattr(self, "_ab_lock_mode_cb"):
                self._ab_lock_mode_cb.configure(
                    values=[t("bright_lock_delay_restore"), t("bright_lock_until_power")]
                )
            if hasattr(self, "_ab_lock_probe_cb"):
                self._ab_lock_probe_cb.configure(
                    values=[
                        t("bright_probe_eco"),
                        t("bright_probe_balanced"),
                        t("bright_probe_sensitive"),
                    ]
                )
            self._sync_ab_lock_ui()
            ctrl = self._auto_bright_ctrl
            if ctrl is not None:
                self.update_auto_bright_status(ctrl.status_snapshot())
        except Exception:
            pass
        for rb, (text, _val) in zip(
            getattr(self, "_cpu_radios", []), i18n.cpu_level_labels()
        ):
            try:
                rb.configure(text=text)
            except Exception:
                pass
        for rb, (text, _val) in zip(
            getattr(self, "_gpu_radios", []), i18n.gpu_level_labels()
        ):
            try:
                rb.configure(text=text)
            except Exception:
                pass
        for rb, (text, _val) in zip(
            getattr(self, "_fan_mode_radios", []), i18n.fan_mode_labels()
        ):
            try:
                rb.configure(text=text)
            except Exception:
                pass
        for chart, key in (
            (getattr(self, "_chart_cpu", None), "chart_cpu"),
            (getattr(self, "_chart_gpu", None), "chart_gpu"),
        ):
            if chart is not None:
                try:
                    chart.set_title(t(key))
                    chart.apply_i18n()
                    chart.redraw()
                except Exception:
                    pass
        panel = getattr(self, "osd_panel", None)
        if panel is not None and hasattr(panel, "apply_i18n"):
            try:
                panel.apply_i18n()
            except Exception:
                pass
        self._sync_fan_mutex_ui()

    @staticmethod
    def _points_to_text(points) -> str:
        from .backends.fan_curve import DEFAULT_CPU_CURVE

        pts = points or DEFAULT_CPU_CURVE
        return "; ".join(f"{temp},{rpm}" for temp, rpm in pts)

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
                    messagebox.showwarning(t("curve"), str(exc))

    def save_fan_curves(self) -> None:
        self._save_fan_curves(apply=True)

    def _save_fan_curves(self, *, apply: bool) -> None:
        try:
            cpu = self._parse_points(self.curve_cpu_var.get())
            gpu = self._parse_points(self.curve_gpu_var.get())
        except Exception:
            messagebox.showerror(t("err"), t("curve_bad_fmt"))
            return
        # Explicitly allow 0–5500; reject nothing in that range.
        for label, pts in (("CPU", cpu), ("GPU", gpu)):
            for temp, rpm in pts:
                if rpm < 0 or rpm > 5500:
                    messagebox.showerror(
                        t("err"), t("curve_rpm_range", label=label, t=temp, r=rpm)
                    )
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
                disk_hint = t("disk_first", t=first[0][0], r=first[0][1])
        except Exception:
            pass
        if apply:
            cb = getattr(self, "on_fan_curves_changed", None)
            if cb:
                try:
                    cb()
                except Exception as exc:  # noqa: BLE001
                    messagebox.showwarning(t("curve"), str(exc))
                    return
            state = t("curve_state_on") if cfg.enabled else t("curve_state_off")
            self._set_status(
                t("curve_saved_apply", state=state, path=cfg_path, disk=disk_hint)
            )
        else:
            self._set_status(
                t(
                    "curve_saved_only",
                    n_cpu=len(cfg.cpu_points),
                    n_gpu=len(cfg.gpu_points),
                    en=t("yes") if cfg.enabled else t("no"),
                    path=cfg_path,
                    disk=disk_hint,
                )
            )

    def force_write_fan_curves(self) -> None:
        """Save editor points, then force one EC write of current curve targets."""
        self._save_fan_curves(apply=False)
        cb = getattr(self, "on_fan_curves_force_write", None)
        if not cb:
            self._set_status(t("force_no_cb"))
            return
        try:
            cb()
        except Exception as exc:  # noqa: BLE001
            messagebox.showwarning(t("force_write"), str(exc))

    def _on_features_changed(self) -> None:
        self.manager.set_feature("enable_cpu_level", bool(self.feat_cpu_level.get()))
        self.manager.set_feature("enable_gpu_level", bool(self.feat_gpu.get()))
        self.manager.set_feature("enable_undervolt", bool(self.feat_uv.get()))
        flags = (
            f"{t('flag_cpu')}={t('on') if self.feat_cpu_level.get() else t('off')} "
            f"{t('flag_gpu')}={t('on') if self.feat_gpu.get() else t('off')} "
            f"{t('flag_uv')}={t('on') if self.feat_uv.get() else t('off')} "
            f"{t('flag_curve')}={t('on') if self.curve_enabled.get() else t('off')}"
        )
        self._set_status(t("features_updated", flags=flags))
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
            messagebox.showinfo(t("cfg"), t("cfg_missing_path"))
            return
        from pathlib import Path
        import os

        p = Path(path)
        if not p.is_file():
            messagebox.showwarning(t("cfg"), t("cfg_missing_file", p=p))
            return
        try:
            os.startfile(str(p))  # noqa: S606 — Windows open with default editor
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(t("cfg"), t("cfg_open_fail", p=p, exc=exc))

    def set_xtu_path_label(self, path: str, found: bool) -> None:
        if found and path:
            self.xtu_var.set(t("xtu_found", path=path))
        else:
            self.xtu_var.set(t("xtu_missing"))

    def _rebuild_tray_profile_checks(self) -> None:
        frame = getattr(self, "_tray_profiles_frame", None)
        if frame is None:
            return
        for child in frame.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        selected = set(self.manager.tray_menu_profile_ids())
        # If setting was never customized, treat as all selected in UI.
        customized = "tray_menu_profile_ids" in (self.manager.settings or {})
        self._tray_profile_vars = {}
        for p in self.manager.profiles:
            on = (p.id in selected) if customized else True
            var = tk.BooleanVar(value=on)
            self._tray_profile_vars[p.id] = var
            ttk.Checkbutton(
                frame,
                text=p.name,
                variable=var,
                command=self._on_tray_menu_profiles_toggle,
            ).pack(anchor=tk.W, pady=1)

    def _on_tray_menu_profiles_toggle(self) -> None:
        ids = [
            pid
            for pid, var in self._tray_profile_vars.items()
            if bool(var.get())
        ]
        # Preserve profile list order.
        order = {p.id: i for i, p in enumerate(self.manager.profiles)}
        ids.sort(key=lambda x: order.get(x, 9999))
        self.manager.set_tray_menu_profile_ids(ids)
        self._set_status(t("tray_menu_saved"))
        cb = getattr(self, "on_tray_menu_profiles_changed", None)
        if cb:
            try:
                cb()
            except Exception:
                pass

    def _tray_menu_select_all(self) -> None:
        for var in self._tray_profile_vars.values():
            var.set(True)
        self._on_tray_menu_profiles_toggle()

    def _tray_menu_select_none(self) -> None:
        for var in self._tray_profile_vars.values():
            var.set(False)
        self._on_tray_menu_profiles_toggle()

    def _on_sensor_tray_toggle(self) -> None:
        enabled = bool(self.sensor_tray_var.get())
        if self.on_sensor_tray_changed:
            try:
                self.on_sensor_tray_changed(enabled)
            except Exception as exc:  # noqa: BLE001
                self._set_status(t("sensor_tray_fail", exc=exc))
        else:
            self.manager.update_settings(sensor_tray_enabled=enabled)
            self._set_status(t("sensor_tray_on") if enabled else t("sensor_tray_off"))

    def set_sensor_tray_enabled(self, enabled: bool) -> None:
        self.sensor_tray_var.set(bool(enabled))

    def _on_autostart_toggle(self) -> None:
        enabled = bool(self.autostart_var.get())
        if self.on_autostart_changed:
            try:
                self.on_autostart_changed(enabled)
            except Exception as exc:  # noqa: BLE001
                self._set_status(t("autostart_fail", exc=exc))
                try:
                    from . import autostart

                    self.autostart_var.set(autostart.is_enabled())
                except Exception:
                    pass
        else:
            self._set_status(t("autostart_no_cb"))

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
                self._set_status(t("osd_fail", exc=exc))
                return
        self._set_status(t("osd_updated_on") if cfg.enabled else t("osd_updated_off"))

    def refresh_list(self) -> None:
        self.listbox.delete(0, tk.END)
        for p in self.manager.profiles:
            mark = " *" if p.id == self.manager.active_profile_id else ""
            hk = f"  [{p.hotkey}]" if p.hotkey else ""
            self.listbox.insert(
                tk.END,
                f"{p.name}  CPU {getattr(p,'cpu_level','?')}  "
                f"PL {p.pl1_w:.0f}/{p.pl2_w:.0f}  GPU {p.gpu_level}  "
                f"Fan {getattr(p,'fan_mode','auto')}"
                + (f":{p.fan_rpm}" if getattr(p, "fan_mode", "") == "manual" else "")
                + f"{hk}{mark}",
            )
        try:
            sig = tuple((p.id, p.name) for p in self.manager.profiles)
            if sig != getattr(self, "_tray_profiles_sig", None):
                self._tray_profiles_sig = sig
                self._rebuild_tray_profile_checks()
        except Exception:
            pass

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
            "name": self.name_var.get().strip() or t("unnamed"),
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
        body = "\n".join(messages) if messages else t("no_detail")
        prefix = t("ok_prefix") if ok else t("fail_prefix")
        self._set_status(prefix + (messages[0] if messages else title))
        if not ok:
            messagebox.showwarning(title, body)
        else:
            self.status_var.set(" | ".join(messages)[:180])

    def _run_apply_async(self, fn) -> None:
        if self._busy:
            self._set_status(t("busy"))
            return
        self._busy = True
        self._set_status(t("applying"))

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
        self._show_result(t("apply_profile"), result.messages, result.ok)
        cb = getattr(self, "on_profile_applied", None)
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def apply_selected(self) -> None:
        p = self._selected_profile()
        if not p:
            messagebox.showinfo(t("tip"), t("select_profile"))
            return
        self._run_apply_async(lambda: self.manager.apply_profile(p))

    def apply_editor(self) -> None:
        try:
            data = self._read_editor()
        except ValueError:
            messagebox.showerror(t("err"), t("bad_number"))
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
            messagebox.showinfo(t("tip"), t("select_overwrite"))
            return
        try:
            data = self._read_editor()
        except ValueError:
            messagebox.showerror(t("err"), t("bad_number"))
            return
        from .profile_manager import Profile

        p = Profile(id=self._editing_id, **data)
        self.manager.upsert(p)
        if self.on_hotkeys_changed:
            self.on_hotkeys_changed()
        self.refresh_list()
        self._set_status(t("saved", name=p.name))

    def save_as_new(self) -> None:
        try:
            data = self._read_editor()
        except ValueError:
            messagebox.showerror(t("err"), t("bad_number"))
            return
        name = simpledialog.askstring(t("save_as_title"), t("save_as_prompt"), initialvalue=data["name"])
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
        self._set_status(t("created", name=p.name))

    def delete_selected(self) -> None:
        p = self._selected_profile()
        if not p:
            return
        if not messagebox.askyesno(t("confirm"), t("delete_ask", name=p.name)):
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
            messagebox.showerror(t("err"), t("uv_invalid"))
            return
        self.manager.update_undervolt(core, cache, ecache)
        self._set_status(t("uv_saved"))

    def reapply_uv(self) -> None:
        self.save_undervolt()
        result = self.manager.reapply_undervolt()
        self._show_result(t("uv_reapply_title"), result.messages, result.ok)

    def restore_defaults(self) -> None:
        if not messagebox.askyesno(t("confirm"), t("restore_ask")):
            return
        result = self.manager.restore_defaults()
        self.uv_core.set("0")
        self.uv_cache.set("0")
        self.uv_ecache.set("0")
        self.manager.update_undervolt(0, 0, 0)
        self.refresh_list()
        self._show_result(t("restore_title"), result.messages, result.ok)

    def _poll_live(self) -> None:
        # Skip heavy polling while applying.
        if getattr(self, "_busy", False):
            self._live_after = self.root.after(1000, self._poll_live)
            return
        lines = []
        if self.status_provider:
            try:
                info = self.status_provider()
                for k, v in info.items():
                    lines.append(f"{i18n.translate_live_key(k)}: {v}")
            except Exception as exc:  # noqa: BLE001
                lines.append(t("status_err", exc=exc))
        if self.monitor is not None:
            try:
                g = self.monitor.read_gpu()
                lines.append(
                    f"GPU: {g.name or '-'}  W={g.power_draw_w}  "
                    f"Ceiling={g.ceiling_w}W  Max={g.max_w}W"
                )
            except Exception as exc:  # noqa: BLE001
                lines.append(t("gpu_read_fail", exc=exc))
        active = self.manager.active_profile_id or "-"
        lines.append(t("active_id", id=active))
        self.live_var.set("\n".join(lines) if lines else t("no_readings"))
        self._live_after = self.root.after(4000, self._poll_live)
