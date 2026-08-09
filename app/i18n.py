"""Simple UI / docs language helpers (zh / en)."""

from __future__ import annotations

from typing import Any, Callable, Optional

_LANG = "zh"
_listeners: list[Callable[[str], None]] = []

# fmt: off
STRINGS: dict[str, dict[str, str]] = {
    "app_title": {
        "zh": "Blade 16 功耗快捷切换",
        "en": "Blade 16 Power Switcher",
    },
    "ready": {"zh": "就绪", "en": "Ready"},
    "live_loading": {"zh": "读数加载中…", "en": "Loading sensors…"},
    "live_status": {"zh": "实时状态", "en": "Live status"},
    "profiles": {"zh": "性能档", "en": "Profiles"},
    "apply": {"zh": "应用", "en": "Apply"},
    "delete": {"zh": "删除", "en": "Delete"},
    "tab_home": {"zh": "主页", "en": "Home"},
    "tab_fan": {"zh": "风扇曲线", "en": "Fan curves"},
    "tab_osd": {"zh": "桌面 OSD", "en": "Desktop OSD"},
    "tab_tray": {"zh": "托盘图标", "en": "Tray icons"},
    "features": {"zh": "功能模块（可独立开关）", "en": "Feature modules (independent)"},
    "feat_cpu": {
        "zh": "CPU 档位（低/中/高/增强/自定义）",
        "en": "CPU tier (Low/Med/High/Boost/Custom)",
    },
    "feat_gpu": {"zh": "GPU 档位", "en": "GPU tier"},
    "feat_uv": {"zh": "CPU 降压（独立）", "en": "CPU undervolt (independent)"},
    "feat_hint": {
        "zh": "CPU 选「自定义」才应用 PL1/PL2/Tau；固定档只改雷云同款 EC。风扇曲线在对应页启用。",
        "en": "PL1/PL2/Tau apply only when CPU=Custom. Fixed tiers use Synapse-like EC only. Enable fan curves on that tab.",
    },
    "lang_label": {"zh": "界面语言", "en": "UI language"},
    "lang_zh": {"zh": "中文", "en": "中文"},
    "lang_en": {"zh": "English", "en": "English"},
    "editor": {"zh": "搭配编辑器", "en": "Profile editor"},
    "name": {"zh": "名称", "en": "Name"},
    "pl1": {"zh": "CPU PL1 (W)", "en": "CPU PL1 (W)"},
    "pl2": {"zh": "PL2 (W)", "en": "PL2 (W)"},
    "auto_pl2": {"zh": "PL2 自动 = PL1+20", "en": "Auto PL2 = PL1+20"},
    "tau": {"zh": "Tau (s)", "en": "Tau (s)"},
    "tau_hint": {
        "zh": "← 仅 CPU 档=自定义时生效",
        "en": "← Only when CPU tier = Custom",
    },
    "cpu_tier": {"zh": "CPU 档", "en": "CPU tier"},
    "gpu_tier": {"zh": "GPU 档", "en": "GPU tier"},
    "fan": {"zh": "风扇", "en": "Fan"},
    "fan_auto": {"zh": "自动", "en": "Auto"},
    "fan_max": {"zh": "最大", "en": "Max"},
    "fan_manual": {"zh": "手动 RPM", "en": "Manual RPM"},
    "fan_rpm": {"zh": "手动转速", "en": "Manual RPM"},
    "fan_rpm_hint": {
        "zh": "RPM (0-5500，0=停转)",
        "en": "RPM (0–5500, 0=EC auto/stop)",
    },
    "ab": {"zh": "Afterburner #", "en": "Afterburner #"},
    "ab_hint": {"zh": "(1-5 可空)", "en": "(1–5, optional)"},
    "hotkey": {"zh": "快捷键", "en": "Hotkey"},
    "apply_now": {"zh": "立即应用", "en": "Apply now"},
    "save_current": {"zh": "保存到当前档", "en": "Save to profile"},
    "save_as": {"zh": "另存为新档", "en": "Save as new"},
    "uv_title": {"zh": "全局降压 (各档共用)", "en": "Global undervolt (all profiles)"},
    "uv_save": {"zh": "保存降压配置", "en": "Save undervolt"},
    "uv_reapply": {"zh": "重新应用我的降压", "en": "Re-apply undervolt"},
    "uv_restore": {"zh": "恢复默认 (Ctrl+Alt+0)", "en": "Restore defaults (Ctrl+Alt+0)"},
    "xtu_none": {"zh": "未检测", "en": "Not found"},
    "curve_enable": {
        "zh": "启用软件曲线（与性能档风扇互斥：启用后档位风扇不生效；关闭后自动恢复当前档风扇）",
        "en": "Enable software curves (mutex with profile fans; disabling restores profile fans)",
    },
    "curve_hint": {
        "zh": "RPM 允许 0–5500（步进 100）。可用「数值写入」把低温点设为 0/500/1000 等，再点保存。\n曲线 0 = 该风扇交回 EC 自动（低温可停转）；>0 = 手动固定转速。",
        "en": "RPM 0–5500 (step 100). Use numeric entry for low-temp 0/500/1000, then save.\n0 = hand zone back to EC auto (can stop); >0 = fixed manual RPM.",
    },
    "curve_save_only": {"zh": "仅保存曲线", "en": "Save curves only"},
    "curve_save_apply": {"zh": "保存并应用曲线", "en": "Save & apply curves"},
    "curve_force": {"zh": "强制写入当前风扇曲线数据", "en": "Force-write fan curve now"},
    "open_config": {"zh": "打开配置文件", "en": "Open config file"},
    "chart_cpu": {
        "zh": "CPU 风扇曲线（拖动圆点；也可用下方数值写入）",
        "en": "CPU fan curve (drag points; or edit values below)",
    },
    "chart_gpu": {"zh": "GPU 风扇曲线", "en": "GPU fan curve"},
    "tray_sensors_desc": {
        "zh": "在系统托盘显示 4 个传感器图标（CPU/GPU 功耗与温度），类似 HWiNFO。",
        "en": "Show 4 tray sensor icons (CPU/GPU power & temps), HWiNFO-style.",
    },
    "tray_sensors_enable": {
        "zh": "启用托盘传感器图标",
        "en": "Enable tray sensor icons",
    },
    "tray_sensors_hint": {
        "zh": "也可在主托盘图标右键菜单中切换「托盘传感器（功耗/温度）」。",
        "en": "Also toggle via main tray icon context menu.",
    },
    "startup": {"zh": "启动选项", "en": "Startup"},
    "autostart": {
        "zh": "开机自动启动（登录后托盘静默运行，并自动应用上次性能档/降压）",
        "en": "Start with Windows (silent tray; re-apply last profile / undervolt)",
    },
    "autostart_hint": {
        "zh": "使用任务计划程序以最高权限启动，避免每次登录都弹 UAC。",
        "en": "Uses Task Scheduler at highest privileges to avoid UAC every login.",
    },
    "fan_mutex": {
        "zh": "当前由软件风扇曲线接管，档位风扇选项暂不生效",
        "en": "Software fan curves own fans; profile fan options are inactive",
    },
    "cpu_low": {"zh": "低", "en": "Low"},
    "cpu_medium": {"zh": "中", "en": "Med"},
    "cpu_high": {"zh": "高", "en": "High"},
    "cpu_boost": {"zh": "增强", "en": "Boost"},
    "cpu_custom": {"zh": "自定义", "en": "Custom"},
    "gpu_low": {"zh": "低 (~100W / 整机~160W)", "en": "Low (~100W / ~160W system)"},
    "gpu_medium": {"zh": "中 (~150W / 整机~180W)", "en": "Med (~150W / ~180W system)"},
    "gpu_high": {"zh": "高 (≥175W / 整机~205W)", "en": "High (≥175W / ~205W system)"},
    "err": {"zh": "错误", "en": "Error"},
    "tip": {"zh": "提示", "en": "Notice"},
    "cfg": {"zh": "配置", "en": "Config"},
    "curve": {"zh": "曲线", "en": "Curves"},
    "force_write": {"zh": "强制写入", "en": "Force write"},
    "confirm": {"zh": "确认", "en": "Confirm"},
    "select_profile": {"zh": "请先选择性能档", "en": "Select a profile first"},
    "select_overwrite": {
        "zh": "请先选择要覆盖的档，或使用另存为",
        "en": "Select a profile to overwrite, or use Save as",
    },
    "bad_number": {"zh": "请检查数值格式", "en": "Check numeric fields"},
    "delete_ask": {"zh": "删除性能档「{name}」？", "en": "Delete profile “{name}”?"},
    "save_as_title": {"zh": "另存为", "en": "Save as"},
    "save_as_prompt": {"zh": "新性能档名称:", "en": "New profile name:"},
    "unnamed": {"zh": "未命名", "en": "Untitled"},
    "applying": {"zh": "正在应用…", "en": "Applying…"},
    "busy": {"zh": "正在应用，请稍候…", "en": "Busy — please wait…"},
    "ok_prefix": {"zh": "成功: ", "en": "OK: "},
    "fail_prefix": {"zh": "部分失败: ", "en": "Partial failure: "},
    "features_updated": {"zh": "功能模块已更新: {flags}", "en": "Features updated: {flags}"},
    "flag_cpu": {"zh": "CPU档", "en": "CPU"},
    "flag_gpu": {"zh": "GPU", "en": "GPU"},
    "flag_uv": {"zh": "UV", "en": "UV"},
    "flag_curve": {"zh": "曲线", "en": "Curves"},
    "on": {"zh": "开", "en": "On"},
    "off": {"zh": "关", "en": "Off"},
    "no_readings": {"zh": "无读数", "en": "No readings"},
    "status_err": {"zh": "状态错误: {exc}", "en": "Status error: {exc}"},
    "gpu_read_fail": {"zh": "GPU 读数失败: {exc}", "en": "GPU read failed: {exc}"},
    "active_id": {"zh": "当前档 ID: {id}", "en": "Active profile ID: {id}"},
    "cfg_missing_path": {"zh": "未找到 profiles.json 路径", "en": "profiles.json path not found"},
    "cfg_missing_file": {"zh": "文件不存在:\n{p}", "en": "File not found:\n{p}"},
    "cfg_open_fail": {"zh": "无法打开:\n{p}\n{exc}", "en": "Cannot open:\n{p}\n{exc}"},
    "curve_bad_fmt": {
        "zh": "曲线格式无效，请用: 温度,RPM; 温度,RPM; …",
        "en": "Invalid curve format. Use: temp,RPM; temp,RPM; …",
    },
    "curve_rpm_range": {
        "zh": "{label} 曲线 RPM 超范围: {t}°C → {r}",
        "en": "{label} curve RPM out of range: {t}°C → {r}",
    },
    "saved": {"zh": "已保存: {name}", "en": "Saved: {name}"},
    "created": {"zh": "已新建: {name}", "en": "Created: {name}"},
    "sensor_tray_on": {"zh": "传感器托盘已显示", "en": "Sensor tray shown"},
    "sensor_tray_off": {"zh": "传感器托盘已隐藏", "en": "Sensor tray hidden"},
    "sensor_tray_fail": {"zh": "传感器托盘切换失败: {exc}", "en": "Sensor tray toggle failed: {exc}"},
    "autostart_fail": {"zh": "开机自启切换失败: {exc}", "en": "Autostart toggle failed: {exc}"},
    "autostart_no_cb": {"zh": "开机自启回调未连接", "en": "Autostart callback not wired"},
    "osd_fail": {"zh": "OSD 更新失败: {exc}", "en": "OSD update failed: {exc}"},
    "osd_updated_on": {"zh": "桌面 OSD 已更新（已启用）", "en": "Desktop OSD updated (enabled)"},
    "osd_updated_off": {"zh": "桌面 OSD 已更新（已关闭）", "en": "Desktop OSD updated (disabled)"},
    "force_no_cb": {"zh": "强制写入回调未连接", "en": "Force-write callback not wired"},
    "apply_profile": {"zh": "应用档位", "en": "Apply profile"},
    "live_ec_cpu": {"zh": "EC_CPU", "en": "EC_CPU"},
    "live_ec_gpu": {"zh": "EC_GPU", "en": "EC_GPU"},
    "live_cpu_pl": {"zh": "CPU PL", "en": "CPU PL"},
    "live_cpu_pwr": {"zh": "CPU 功耗", "en": "CPU power"},
    "live_uv": {"zh": "UV", "en": "UV"},
    "live_uv_hint": {"zh": "UV提示", "en": "UV note"},
    "live_temp": {"zh": "温度", "en": "Temps"},
    "live_curve": {"zh": "风扇曲线", "en": "Fan curves"},
    "live_fan": {"zh": "风扇", "en": "Fans"},
    "chart_add": {"zh": "加点", "en": "Add"},
    "chart_del": {"zh": "删点", "en": "Del"},
    "chart_rpm_write": {"zh": "数值写入 RPM", "en": "Write RPM"},
    "chart_write_first": {"zh": "写到最低温点", "en": "Write lowest-T"},
    "chart_write_last": {"zh": "写到最高温点", "en": "Write highest-T"},
    "chart_write_all": {"zh": "全部点设为此值", "en": "Set all points"},
    "no_detail": {"zh": "(无详细信息)", "en": "(no details)"},
    "uv_invalid": {"zh": "降压数值无效", "en": "Invalid undervolt values"},
    "uv_saved": {
        "zh": "降压配置已保存（将在下次应用档位时生效）",
        "en": "Undervolt saved (applies on next profile apply)",
    },
    "uv_reapply_title": {"zh": "重新应用降压", "en": "Re-apply undervolt"},
    "restore_ask": {
        "zh": "恢复默认：电压归零并应用安全档？",
        "en": "Restore defaults: zero voltages and apply a safe profile?",
    },
    "restore_title": {"zh": "恢复默认", "en": "Restore defaults"},
    "curve_saved_apply": {
        "zh": "风扇曲线已保存{state} → {path}{disk}",
        "en": "Fan curves saved{state} → {path}{disk}",
    },
    "curve_state_on": {"zh": "并启用", "en": " & enabled"},
    "curve_state_off": {
        "zh": "（未启用，档位风扇应已恢复）",
        "en": " (disabled; profile fans should be restored)",
    },
    "curve_saved_only": {
        "zh": "风扇曲线已写入（CPU {n_cpu} 点 / GPU {n_gpu} 点；启用={en}）→ {path}{disk}",
        "en": "Fan curves written (CPU {n_cpu} pts / GPU {n_gpu} pts; enabled={en}) → {path}{disk}",
    },
    "yes": {"zh": "是", "en": "yes"},
    "no": {"zh": "否", "en": "no"},
    "disk_first": {"zh": " 盘上首点={t}°/{r}", "en": " disk first={t}°/{r}"},
    "xtu_found": {"zh": "XTU(IET): {path}", "en": "XTU(IET): {path}"},
    "xtu_missing": {
        "zh": "XTU(IET): 未检测到（可手动安装 Intel Extreme Tuning Utility）",
        "en": "XTU(IET): not found (optional Intel Extreme Tuning Utility)",
    },
    "osd_enable": {"zh": "启用桌面 OSD", "en": "Enable desktop OSD"},
    "osd_topmost": {"zh": "最前端显示", "en": "Always on top"},
    "osd_lock": {"zh": "锁定位置", "en": "Lock position"},
    "osd_show_names": {"zh": "显示项目名称", "en": "Show item labels"},
    "osd_font": {"zh": "字号", "en": "Font size"},
    "osd_alpha": {"zh": "透明度 0.35-1", "en": "Opacity 0.35–1"},
    "osd_apply_look": {"zh": "应用外观", "en": "Apply look"},
    "osd_drag_hint": {
        "zh": "拖动 OSD 可改位置；右键菜单会显示「✓ 已锁定/未锁定」状态",
        "en": "Drag OSD to move; right-click shows locked/unlocked state",
    },
    "osd_items": {"zh": "显示项", "en": "Items"},
    "osd_colors": {"zh": "颜色", "en": "Colors"},
    "osd_title": {"zh": "桌面性能 OSD", "en": "Desktop performance OSD"},
    # Live / status values
    "cached": {"zh": "(缓存)", "en": "(cached)"},
    "read_fail": {"zh": "读失败", "en": "Read failed"},
    "read_fail_timeout": {"zh": "读失败: 超时", "en": "Read failed: timeout"},
    "reading": {"zh": "读取中…", "en": "Reading…"},
    "no_razer_hid": {"zh": "无 Razer HID", "en": "No Razer HID"},
    "fan_cpu_lbl": {"zh": "CPU风扇", "en": "CPU fan"},
    "fan_gpu_lbl": {"zh": "GPU风扇", "en": "GPU fan"},
    "rpm_timeout": {"zh": "读速超时", "en": "RPM timeout"},
    "rpm_fail": {"zh": "读速失败", "en": "RPM read failed"},
    "uv_fw_locked": {
        "zh": "固件可能锁定降压",
        "en": "Firmware may lock undervolt",
    },
    "ec_hint_low": {
        "zh": "≈PL1~55W，基本无短时超发",
        "en": "≈PL1~55W, little short burst",
    },
    "ec_hint_medium": {
        "zh": "≈持续~60W，短时可到~80–90W",
        "en": "≈sustained ~60W, burst ~80–90W",
    },
    "ec_hint_high": {
        "zh": "≈更高持续，短时更高",
        "en": "≈higher sustained / burst",
    },
    "ec_hint_boost": {
        "zh": "≈增强档（雷云 Boost）",
        "en": "≈Boost tier (Synapse)",
    },
    "ec_hint_oc": {
        "zh": "≈超频档（需雷云 CPU 超频）",
        "en": "≈OC tier (needs Synapse CPU OC)",
    },
    "init_winring0_ok": {"zh": "WinRing0/MSR 已就绪", "en": "WinRing0/MSR ready"},
    "init_winring0_fail": {"zh": "WinRing0 不可用: {exc}", "en": "WinRing0 unavailable: {exc}"},
    "init_razer_ok": {"zh": "Razer GPU HID 已就绪", "en": "Razer GPU HID ready"},
    "init_razer_fail": {
        "zh": "Razer GPU HID 不可用: {exc}",
        "en": "Razer GPU HID unavailable: {exc}",
    },
    "init_ab_ok": {"zh": "Afterburner: {exe}", "en": "Afterburner: {exe}"},
    "init_ab_miss": {
        "zh": "Afterburner 未检测到（可选）",
        "en": "Afterburner not found (optional)",
    },
    "init_xtu_ok": {"zh": "XTU: {path}", "en": "XTU: {path}"},
    "init_xtu_miss": {"zh": "XTU: 未检测到", "en": "XTU: not found"},
    "init_xtu_fail": {"zh": "XTU 检测失败: {exc}", "en": "XTU detect failed: {exc}"},
    "lang_switched": {"zh": "界面语言已切换为中文", "en": "UI language set to English"},
    "chart_temp_axis": {"zh": "温度 °C", "en": "Temp °C"},
    "hotkey_fail": {
        "zh": "部分热键注册失败: {keys}",
        "en": "Some hotkeys failed: {keys}",
    },
    "startup_applied": {"zh": "启动已应用: {msg}", "en": "Startup applied: {msg}"},
    "startup_uv": {"zh": "启动已重申降压: {msg}", "en": "Startup re-applied UV: {msg}"},
    "startup_fail": {"zh": "启动应用失败: {exc}", "en": "Startup apply failed: {exc}"},
    "autostart_fail_msg": {"zh": "开机自启失败: {msg}", "en": "Autostart failed: {msg}"},
    "sensor_tray_fail_tag": {"zh": "（切换失败）", "en": " (toggle failed)"},
}
# fmt: on

_LIVE_KEY_MAP = {
    "EC_CPU": "live_ec_cpu",
    "EC_GPU": "live_ec_gpu",
    "CPU PL": "live_cpu_pl",
    "CPU 功耗": "live_cpu_pwr",
    "UV": "live_uv",
    "UV提示": "live_uv_hint",
    "温度": "live_temp",
    "风扇曲线": "live_curve",
    "风扇": "live_fan",
}

_EC_HINT_KEYS = {
    "low": "ec_hint_low",
    "medium": "ec_hint_medium",
    "high": "ec_hint_high",
    "boost": "ec_hint_boost",
    "overclock": "ec_hint_oc",
}

def get_lang() -> str:
    return _LANG if _LANG in ("zh", "en") else "zh"


def set_lang(lang: str, *, notify: bool = True) -> None:
    global _LANG
    lang = "en" if str(lang).lower().startswith("en") else "zh"
    if lang == _LANG:
        return
    _LANG = lang
    if notify:
        for cb in list(_listeners):
            try:
                cb(lang)
            except Exception:
                pass


def on_lang_change(cb: Callable[[str], None]) -> None:
    if cb not in _listeners:
        _listeners.append(cb)


def t(key: str, **kwargs: Any) -> str:
    entry = STRINGS.get(key) or {}
    text = entry.get(get_lang()) or entry.get("zh") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


def translate_live_key(key: str) -> str:
    mk = _LIVE_KEY_MAP.get(key)
    return t(mk) if mk else key


def cpu_level_labels() -> list[tuple[str, str]]:
    return [
        (t("cpu_low"), "low"),
        (t("cpu_medium"), "medium"),
        (t("cpu_high"), "high"),
        (t("cpu_boost"), "boost"),
        (t("cpu_custom"), "custom"),
    ]


def gpu_level_labels() -> list[tuple[str, str]]:
    return [
        (t("gpu_low"), "low"),
        (t("gpu_medium"), "medium"),
        (t("gpu_high"), "high"),
    ]


def fan_mode_labels() -> list[tuple[str, str]]:
    return [
        (t("fan_auto"), "auto"),
        (t("fan_max"), "max"),
        (t("fan_manual"), "manual"),
    ]


def init_from_settings(settings: Optional[dict]) -> None:
    lang = (settings or {}).get("ui_language") or "zh"
    set_lang(str(lang), notify=False)


def ec_hint_for(name: str) -> str:
    key = _EC_HINT_KEYS.get(str(name).lower())
    return t(key) if key else ""


def format_ec_line(name: str, code: int, *, stale: bool = False, hint: bool = True) -> str:
    text = f"{name} ({code})"
    if hint:
        h = ec_hint_for(name)
        if h:
            text += f"  {h}"
    if stale:
        text += f"  {t('cached')}"
    return text


def format_fan_line(z1, z2, err: str = "") -> str:
    def _one(label_key: str, v) -> str:
        label = t(label_key)
        return f"{label}={v} RPM" if v is not None else f"{label}=-"

    base = f"{_one('fan_cpu_lbl', z1)}  {_one('fan_gpu_lbl', z2)}"
    if err:
        return f"{base} ({err})"
    return base
