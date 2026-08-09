"""Entry point: elevate, init backends, run GUI."""

from __future__ import annotations

import argparse
import sys
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

# Allow `python -m app.main` and `python app/main.py`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.admin import is_admin, relaunch_as_admin
from app.backends.afterburner import AfterburnerBackend
from app.backends.cpu_rapl import CpuRaplBackend
from app.backends.cpu_undervolt import CpuUndervoltBackend
from app.backends.fan_curve import FanCurveController
from app.backends.gpu_nvapi_probe import probe_gpu_power_write
from app.backends.monitor import MonitorBackend
from app.backends.synapse_gpu import SynapseGpuBackend
from app.backends.temps import TempMonitor
from app.backends.winring0 import WinRing0
from app.gui import AppGUI
from app.hotkeys import HotkeyService
from app.osd_overlay import OsdConfig, OsdSnapshot, PerformanceOsd
from app.power_events import ResumeWatcher
from app.profile_manager import ProfileManager
from app.sensor_tray import SensorSnapshot, SensorTrayService
from app.tray import TrayService


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--minimized", action="store_true")
    p.add_argument("--skip-preflight", action="store_true")
    args, _ = p.parse_known_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not is_admin():
        if relaunch_as_admin():
            return 0
        print("需要管理员权限才能改 CPU MSR / 部分硬件设置。")
        return 1

    from app.single_instance import ensure_single_instance, release as release_single_instance

    # After elevation — only one elevated instance may continue.
    if not ensure_single_instance(show_message=not args.minimized):
        return 0

    try:
        return _main_run(args)
    finally:
        release_single_instance()


def _main_run(args: argparse.Namespace) -> int:
    # Startup dependency / compatibility gate.
    # Autostart (--minimized) must not block login with a dialog.
    if not args.minimized and not args.skip_preflight:
        from app.preflight_dialog import show_preflight

        if not show_preflight():
            return 0

    ring0 = WinRing0()
    rapl = None
    undervolt = None
    init_msgs: list[str] = []

    try:
        ring0.initialize()
        rapl = CpuRaplBackend(ring0)
        undervolt = CpuUndervoltBackend(ring0)
        init_msgs.append("WinRing0/MSR 已就绪")
    except Exception as exc:  # noqa: BLE001
        init_msgs.append(f"WinRing0 不可用: {exc}")

    synapse = None
    try:
        from app.backends.razer_devices import detect_blade_device

        blade = detect_blade_device()
        synapse = SynapseGpuBackend(product_id=blade.product_id if blade else None)
        synapse.open()
        if blade:
            init_msgs.append(f"Razer HID: {blade.name} ({blade.pid_hex})")
        else:
            init_msgs.append("Razer GPU HID 已就绪")
    except Exception as exc:  # noqa: BLE001
        init_msgs.append(f"Razer GPU HID 不可用: {exc}")
        synapse = None

    afterburner = AfterburnerBackend()
    if afterburner.available:
        init_msgs.append(f"Afterburner: {afterburner.exe}")
    else:
        init_msgs.append("Afterburner 未检测到（可选）")

    probe = probe_gpu_power_write()
    init_msgs.append(probe.message)

    manager = ProfileManager(
        rapl=rapl,
        undervolt=undervolt,
        synapse=synapse,
        afterburner=afterburner,
    )

    # Startup: detect & persist Intel XTU (IET) path.
    try:
        xtu_info = manager.refresh_xtu_path()
        if xtu_info.get("xtu_found"):
            init_msgs.append(f"XTU: {xtu_info.get('xtu_path')}")
        else:
            init_msgs.append("XTU: 未检测到")
    except Exception as exc:  # noqa: BLE001
        init_msgs.append(f"XTU 检测失败: {exc}")

    monitor = MonitorBackend()
    temps = TempMonitor(ring0 if rapl is not None else None)
    hotkeys = HotkeyService()

    root = tk.Tk()
    try:
        from app.window_icon import apply_window_icon

        apply_window_icon(root)
        # Re-apply after Tk maps the HWND (title bar icon is more reliable then).
        root.after(200, lambda: apply_window_icon(root))
    except Exception:
        pass

    _fan_cache = {
        "text": "CPU风扇=-  GPU风扇=-",
        "tick": 0,
        "z1": None,
        "z2": None,
        "err": "",
        "busy": False,
    }
    _ec_cache = {
        "cpu": "读取中…",
        "gpu": "读取中…",
        "mode": "",
        "err": "",
        "busy": False,
    }
    fan_ctrl: FanCurveController | None = None
    sensor_tray: SensorTrayService | None = None
    osd: PerformanceOsd | None = None

    def _format_fan_text(z1, z2, err: str = "") -> str:
        def _one(label: str, v) -> str:
            return f"{label}={v} RPM" if v is not None else f"{label}=-"

        base = f"{_one('CPU风扇', z1)}  {_one('GPU风扇', z2)}"
        if err:
            return f"{base}（{err}）"
        return base

    def _hid_poll_worker() -> None:
        """Single background HID poller: fans + EC boost (avoids lock contention)."""
        import time as _time

        while True:
            if synapse is None:
                _ec_cache["cpu"] = "无 Razer HID"
                _ec_cache["gpu"] = "无 Razer HID"
                _time.sleep(5.0)
                continue
            # Fans
            try:
                z1, z2 = synapse.get_fans_rpm()
                _fan_cache["z1"] = int(z1)
                _fan_cache["z2"] = int(z2)
                _fan_cache["err"] = ""
                _fan_cache["text"] = _format_fan_text(z1, z2)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                short = "读速超时" if "timeout" in msg.lower() or "超时" in msg else "读速失败"
                _fan_cache["err"] = short
                _fan_cache["text"] = _format_fan_text(
                    _fan_cache.get("z1"), _fan_cache.get("z2"), short
                )
            # EC CPU/GPU — keep last good on timeout
            try:
                cpu_txt, gpu_txt = synapse.peek_boosts()
                _ec_cache["cpu"] = cpu_txt
                _ec_cache["gpu"] = gpu_txt
            except Exception as exc:  # noqa: BLE001
                if not _ec_cache.get("cpu") or str(_ec_cache.get("cpu")).startswith("读"):
                    _ec_cache["cpu"] = f"读失败: {exc}"[:80]
                else:
                    _ec_cache["cpu"] = f"{_ec_cache['cpu']}  (缓存)"
                if not _ec_cache.get("gpu") or str(_ec_cache.get("gpu")).startswith("读"):
                    _ec_cache["gpu"] = f"读失败: {exc}"[:80]
                elif "(缓存)" not in str(_ec_cache.get("gpu")):
                    _ec_cache["gpu"] = f"{_ec_cache['gpu']}  (缓存)"
            _time.sleep(6.0)

    import threading as _threading

    _threading.Thread(target=_hid_poll_worker, daemon=True, name="HidStatusPoll").start()

    def status_provider() -> dict:
        out = {}
        # Put EC boost near the top so it is visible in the live panel.
        out["EC_CPU"] = _ec_cache.get("cpu") or "-"
        out["EC_GPU"] = _ec_cache.get("gpu") or "-"
        if rapl is not None:
            try:
                pl = rapl.read()
                out["CPU PL"] = f"PL1={pl.pl1_w}W PL2={pl.pl2_w}W Tau={pl.tau_s}s"
                pw = rapl.sample_package_power_w()
                if pw is not None:
                    out["CPU 功耗"] = f"{pw} W (Package)"
                elif rapl.last_package_power_w is not None:
                    out["CPU 功耗"] = f"{rapl.last_package_power_w} W (Package)"
            except Exception as exc:  # noqa: BLE001
                out["CPU PL"] = f"读失败: {exc}"
        if undervolt is not None:
            try:
                uv = undervolt.read()
                out["UV"] = f"{uv.core_mv}/{uv.cache_mv}/{uv.ecache_mv} mV"
                if getattr(undervolt, "last_locked", False):
                    out["UV提示"] = "固件可能锁定降压"
            except Exception as exc:  # noqa: BLE001
                out["UV"] = f"读失败: {exc}"
        try:
            t = temps.read()
            src = {"package": "Package", "core": "Core", "wmi": "ACPI"}.get(t.cpu_source, "")
            cpu_txt = f"{t.cpu_c}°C" if t.cpu_c is not None else "-"
            if src and t.cpu_c is not None:
                cpu_txt = f"{t.cpu_c}°C({src})"
            out["温度"] = f"CPU={cpu_txt}  GPU={t.gpu_c if t.gpu_c is not None else '-'}°C"
        except Exception as exc:  # noqa: BLE001
            out["温度"] = f"读失败: {exc}"
        if fan_ctrl is not None and getattr(manager.fan_curve_cfg, "enabled", False):
            out["风扇曲线"] = fan_ctrl.last_status
        # Fan RPM comes from background poller (avoids HID timeout on UI thread).
        out["风扇"] = _fan_cache.get("text") or "CPU风扇=-  GPU风扇=-"
        return out

    def reassert_pl() -> None:
        try:
            pid = manager.active_profile_id
            p = manager.get(pid) if pid else None
            if p is None:
                root.after(5000, reassert_pl)
                return
            cpu_name = str(getattr(p, "cpu_level", "boost") or "boost").lower()
            is_custom = cpu_name == "custom"
            if manager.feature_enabled("enable_cpu_level") and is_custom:
                if rapl is not None and rapl.last_target is not None:
                    try:
                        want = rapl.last_target
                        got = rapl.read()
                        if (
                            abs(got.pl1_w - want[0]) > 3.0
                            or abs(got.pl2_w - want[1]) > 5.0
                        ):
                            rapl.reassert()
                    except Exception:
                        pass
                if synapse is not None:
                    try:
                        from app.backends.synapse_gpu import CpuBoost

                        synapse.set_cpu_boost(CpuBoost.BOOST)
                    except Exception:
                        pass
            elif manager.feature_enabled("enable_cpu_level") and synapse is not None:
                try:
                    from app.backends.synapse_gpu import NAME_TO_CPU_BOOST, CpuBoost

                    synapse.set_cpu_boost(NAME_TO_CPU_BOOST.get(cpu_name, CpuBoost.BOOST))
                except Exception:
                    pass
        except Exception:
            pass
        root.after(5000, reassert_pl)

    def reapply_after_resume(*, reason: str = "休眠唤醒", full: bool = False) -> None:
        """S3/S4/Modern Standby 后 MSR 降压与 PL 常被固件清零，自动重申。"""

        def work() -> None:
            msgs: list[str] = []
            if undervolt is not None and manager.feature_enabled("enable_undervolt"):
                try:
                    from app.backends.cpu_undervolt import UndervoltSettings

                    target = UndervoltSettings(
                        core_mv=manager.undervolt_cfg.core_mv,
                        cache_mv=manager.undervolt_cfg.cache_mv,
                        ecache_mv=manager.undervolt_cfg.ecache_mv,
                    )
                    got = undervolt.apply(target)
                    msgs.append(f"UV {got.core_mv}/{got.cache_mv}/{got.ecache_mv}")
                except Exception as exc:  # noqa: BLE001
                    msgs.append(f"UV失败:{exc}")

            if full:
                pid = manager.active_profile_id
                if pid and manager.get(pid) is not None:
                    try:
                        result = manager.apply_by_id(pid)
                        msgs.append("档位已重申" if result.ok else "档位部分失败")
                    except Exception as exc:  # noqa: BLE001
                        msgs.append(f"档位失败:{exc}")
                elif rapl is not None and rapl.last_target is not None:
                    try:
                        rapl.reassert()
                        msgs.append("PL已重申")
                    except Exception as exc:  # noqa: BLE001
                        msgs.append(f"PL失败:{exc}")
            elif rapl is not None and rapl.last_target is not None:
                try:
                    rapl.reassert()
                    msgs.append("PL已重申")
                except Exception as exc:  # noqa: BLE001
                    msgs.append(f"PL失败:{exc}")

            if fan_ctrl is not None and getattr(manager.fan_curve_cfg, "enabled", False):
                try:
                    fan_ctrl.force_tick()
                    msgs.append("风扇曲线已刷新")
                except Exception:
                    pass
            text = f"{reason}已恢复: " + (" | ".join(msgs) if msgs else "无操作")
            try:
                root.after(0, lambda t=text: gui._set_status(t[:200]))
            except Exception:
                pass

        import threading

        threading.Thread(target=work, daemon=True, name="ResumeReapply").start()

    def on_resume_detected() -> None:
        # Firmware may clear UV after first write — retry UV/PL; full profile once.
        root.after(800, lambda: reapply_after_resume(reason="休眠唤醒", full=True))
        root.after(2500, lambda: reapply_after_resume(reason="休眠唤醒重试", full=False))
        root.after(6000, lambda: reapply_after_resume(reason="休眠唤醒重试", full=False))
        root.after(12000, lambda: reapply_after_resume(reason="休眠唤醒重试", full=False))

    def uv_watchdog() -> None:
        """若目标降压非零但读回接近 0，则补写（捕获漏报的唤醒）。"""
        try:
            if undervolt is not None and manager.feature_enabled("enable_undervolt"):
                want = manager.undervolt_cfg
                wanted = any(
                    abs(v) > 0.5 for v in (want.core_mv, want.cache_mv, want.ecache_mv)
                )
                if wanted:
                    got = undervolt.read()
                    drifted = (
                        abs(got.core_mv - want.core_mv) > 8
                        or abs(got.cache_mv - want.cache_mv) > 8
                        or abs(got.ecache_mv - want.ecache_mv) > 8
                    )
                    if drifted:
                        reapply_after_resume(reason="电压漂移检测", full=False)
        except Exception:
            pass
        root.after(8000, uv_watchdog)

    resume_watcher = ResumeWatcher(root, on_resume_detected)
    resume_watcher.start()
    root.after(8000, uv_watchdog)

    def register_hotkeys() -> None:
        mapping = {}
        for hk, pid in manager.hotkey_map().items():

            def make_cb(profile_id: str):
                return lambda: on_hotkey_profile(profile_id)

            mapping[hk] = make_cb(pid)
        mapping["ctrl+alt+0"] = lambda: on_hotkey_restore()
        failed = hotkeys.register_map(mapping)
        if failed:
            gui._set_status(f"部分热键注册失败: {', '.join(failed)}")

    def on_hotkey_profile(profile_id: str) -> None:
        def work():
            result = manager.apply_by_id(profile_id)
            root.after(0, lambda: (gui.refresh_list(), gui._set_status(" | ".join(result.messages)[:180])))

        import threading

        threading.Thread(target=work, daemon=True).start()

    def on_hotkey_restore() -> None:
        def work():
            result = manager.restore_defaults()

            def done():
                gui.uv_core.set("0")
                gui.uv_cache.set("0")
                gui.uv_ecache.set("0")
                manager.update_undervolt(0, 0, 0)
                gui.refresh_list()
                gui._set_status(" | ".join(result.messages)[:180])

            root.after(0, done)

        import threading

        threading.Thread(target=work, daemon=True).start()

    def on_fan_curves_changed() -> None:
        """Software curve ↔ profile fan mode are mutually exclusive."""
        cfg = manager.fan_curve_cfg
        enabled = bool(cfg and cfg.enabled)

        def work() -> None:
            try:
                if enabled:
                    if fan_ctrl is not None:
                        # Force EC rewrite even if RPM unchanged.
                        fan_ctrl._last_cpu_rpm = None
                        fan_ctrl._last_gpu_rpm = None
                        fan_ctrl.force_tick()
                        text = "软件风扇曲线已启用（档位风扇已让出）| " + fan_ctrl.last_status
                    else:
                        text = "软件风扇曲线已启用"
                else:
                    pid = manager.active_profile_id
                    profile = manager.get(pid) if pid else None
                    if profile is not None:
                        result = manager.apply_by_id(pid)
                        text = "已关闭软件曲线，已恢复档位风扇 | " + " | ".join(
                            result.messages
                        )
                    elif synapse is not None:
                        synapse.apply_fan("auto")
                        text = "已关闭软件曲线，风扇已回自动（无活动档位）"
                    else:
                        text = "已关闭软件曲线（无风扇后端可恢复）"
            except Exception as exc:  # noqa: BLE001
                text = f"风扇模式切换失败: {exc}"
            root.after(0, lambda t=text: gui._set_status(t[:220]))

        import threading

        threading.Thread(target=work, daemon=True, name="FanModeSwitch").start()

    def on_fan_curves_force_write() -> None:
        """One-shot: push current curve points to EC (even if toggle is off)."""

        def work() -> None:
            try:
                if fan_ctrl is None:
                    text = "强制写入失败: 风扇曲线控制器未就绪"
                else:
                    text = "已强制写入 | " + fan_ctrl.force_apply_now()
            except Exception as exc:  # noqa: BLE001
                text = f"强制写入失败: {exc}"
            root.after(0, lambda t=text: gui._set_status(t[:220]))

        import threading

        threading.Thread(target=work, daemon=True, name="FanForceWrite").start()

    gui = AppGUI(
        root,
        manager,
        monitor=monitor,
        on_hotkeys_changed=register_hotkeys,
        status_provider=status_provider,
    )
    gui.on_fan_curves_changed = on_fan_curves_changed
    gui.on_fan_curves_force_write = on_fan_curves_force_write
    xtu_path = (manager.settings or {}).get("xtu_path") or ""
    gui.set_xtu_path_label(xtu_path, bool((manager.settings or {}).get("xtu_found")))
    gui._set_status(" | ".join(init_msgs)[:220])

    def set_autostart(enabled: bool) -> None:
        from app import autostart

        ok, msg = autostart.set_enabled(bool(enabled))
        manager.update_settings(autostart_enabled=bool(autostart.is_enabled()))
        try:
            gui.set_autostart_enabled(autostart.is_enabled())
        except Exception:
            pass
        gui._set_status(msg if ok else f"开机自启失败: {msg}")

    gui.on_autostart_changed = set_autostart
    try:
        from app import autostart as _as

        gui.set_autostart_enabled(_as.is_enabled())
    except Exception:
        pass

    if args.minimized:
        root.withdraw()

    def apply_startup_profile() -> None:
        """开机/启动后自动套用上次档位与降压。"""

        def work():
            try:
                pid = manager.active_profile_id
                if pid and manager.get(pid) is not None:
                    result = manager.apply_by_id(pid)
                    text = "启动已应用: " + " | ".join(result.messages)[:160]
                else:
                    result = manager.reapply_undervolt()
                    text = "启动已重申降压: " + " | ".join(result.messages)[:160]
            except Exception as exc:  # noqa: BLE001
                text = f"启动应用失败: {exc}"
            root.after(0, lambda: gui._set_status(text[:200]))

        import threading

        threading.Thread(target=work, daemon=True, name="StartupApply").start()

    root.after(1500, apply_startup_profile)

    fan_ctrl = FanCurveController(
        synapse=synapse,
        temps=temps,
        get_config=lambda: manager.fan_curve_cfg,
    )
    fan_ctrl.start()

    register_hotkeys()
    root.after(5000, reassert_pl)

    tray_actions = [(p.name, lambda pid=p.id: on_hotkey_profile(pid)) for p in manager.profiles]

    def show_window() -> None:
        root.after(0, root.deiconify)

    _cleaned = {"done": False}

    def cleanup() -> None:
        if _cleaned["done"]:
            return
        _cleaned["done"] = True
        try:
            resume_watcher.stop()
        except Exception:
            pass
        try:
            if fan_ctrl:
                fan_ctrl.stop()
        except Exception:
            pass
        try:
            hotkeys.clear()
        except Exception:
            pass
        try:
            tray.stop()
        except Exception:
            pass
        try:
            if sensor_tray is not None:
                sensor_tray.stop()
        except Exception:
            pass
        try:
            if osd is not None:
                osd.hide()
        except Exception:
            pass
        try:
            if synapse:
                synapse.close()
        except Exception:
            pass
        try:
            ring0.close()
        except Exception:
            pass

    def quit_app() -> None:
        cleanup()
        root.after(0, root.destroy)

    def set_sensor_tray_visible(enabled: bool) -> None:
        enabled = bool(enabled)
        manager.update_settings(sensor_tray_enabled=enabled)
        try:
            gui.set_sensor_tray_enabled(enabled)
        except Exception:
            pass
        if sensor_tray is None:
            return
        ok = sensor_tray.set_visible(enabled)
        gui._set_status(
            ("传感器托盘已显示" if enabled else "传感器托盘已隐藏")
            + ("" if ok else "（切换失败）")
        )

    def toggle_sensor_tray() -> None:
        cur = bool((manager.settings or {}).get("sensor_tray_enabled", True))
        set_sensor_tray_visible(not cur)

    def toggle_osd() -> None:
        cfg = OsdConfig.from_dict((manager.settings or {}).get("osd"))
        cfg.enabled = not cfg.enabled
        manager.update_settings(osd=cfg.to_dict())
        try:
            gui.osd_panel.enabled.set(cfg.enabled)
        except Exception:
            pass
        if osd is not None:
            osd.apply_config(cfg)

    from app import autostart as autostart_mod

    tray = TrayService(
        on_show=show_window,
        on_quit=quit_app,
        profile_actions=tray_actions,
        get_sensor_tray_visible=lambda: bool(
            (manager.settings or {}).get("sensor_tray_enabled", True)
        ),
        on_toggle_sensor_tray=toggle_sensor_tray,
        get_osd_visible=lambda: bool(
            ((manager.settings or {}).get("osd") or {}).get("enabled", False)
        ),
        on_toggle_osd=toggle_osd,
        get_autostart=autostart_mod.is_enabled,
        on_toggle_autostart=lambda: set_autostart(not autostart_mod.is_enabled()),
    )
    tray.start()

    def sensor_poll() -> SensorSnapshot:
        cpu_p = None
        cpu_t = None
        gpu_p = None
        gpu_t = None
        if rapl is not None:
            try:
                cpu_p = rapl.sample_package_power_w()
            except Exception:
                cpu_p = getattr(rapl, "last_package_power_w", None)
        try:
            cpu_t = temps.read_cpu().cpu_c
        except Exception:
            pass
        try:
            gpu_p, gpu_t = monitor.read_gpu_sensors()
        except Exception:
            try:
                g = monitor.read_gpu()
                gpu_p = g.power_draw_w
            except Exception:
                pass
        return SensorSnapshot(
            cpu_power_w=cpu_p,
            cpu_temp_c=cpu_t,
            gpu_power_w=gpu_p,
            gpu_temp_c=gpu_t,
        )

    sensor_tray = SensorTrayService(
        poll=sensor_poll,
        on_show=show_window,
        get_order=lambda: (manager.settings or {}).get("sensor_tray_order"),
        save_order=lambda order: manager.update_settings(sensor_tray_order=list(order)),
        interval_s=1.5,
    )
    gui.on_sensor_tray_changed = set_sensor_tray_visible
    if bool((manager.settings or {}).get("sensor_tray_enabled", True)):
        sensor_tray.start()

    def get_osd_config() -> OsdConfig:
        return OsdConfig.from_dict((manager.settings or {}).get("osd"))

    def save_osd_config(cfg: OsdConfig) -> None:
        # Preserve latest drag position already on cfg.
        manager.update_settings(osd=cfg.to_dict())
        try:
            gui.osd_panel.cfg.x = cfg.x
            gui.osd_panel.cfg.y = cfg.y
            gui.osd_panel.enabled.set(cfg.enabled)
            gui.osd_panel.topmost.set(cfg.topmost)
            gui.osd_panel.locked.set(cfg.locked)
        except Exception:
            pass

    osd = PerformanceOsd(root, get_config=get_osd_config, save_config=save_osd_config)

    def on_osd_changed(cfg: OsdConfig) -> None:
        manager.update_settings(osd=cfg.to_dict())
        osd.apply_config(cfg)

    gui.on_osd_changed = on_osd_changed
    if get_osd_config().enabled:
        osd.apply_config()

    def refresh_osd() -> None:
        try:
            snap = sensor_poll()
            cpu_pl1 = cpu_pl2 = None
            uv_text = ""
            profile_name = ""
            if rapl is not None:
                try:
                    pl = rapl.read()
                    cpu_pl1, cpu_pl2 = pl.pl1_w, pl.pl2_w
                except Exception:
                    pass
            if undervolt is not None:
                try:
                    uv = undervolt.read()
                    uv_text = f"{uv.core_mv:.0f}/{uv.cache_mv:.0f}/{uv.ecache_mv:.0f}"
                except Exception:
                    pass
            try:
                pid = manager.active_profile_id
                p = manager.get(pid) if pid else None
                profile_name = p.name if p else (pid or "-")
            except Exception:
                profile_name = "-"
            osd.update(
                OsdSnapshot(
                    cpu_power_w=snap.cpu_power_w,
                    cpu_temp_c=snap.cpu_temp_c,
                    gpu_power_w=snap.gpu_power_w,
                    gpu_temp_c=snap.gpu_temp_c,
                    fan_z1_rpm=_fan_cache.get("z1"),
                    fan_z2_rpm=_fan_cache.get("z2"),
                    cpu_pl1=cpu_pl1,
                    cpu_pl2=cpu_pl2,
                    uv_text=uv_text,
                    profile_name=profile_name,
                )
            )
        except Exception:
            pass
        root.after(1000, refresh_osd)

    root.after(800, refresh_osd)

    def on_close() -> None:
        root.withdraw()

    root.protocol("WM_DELETE_WINDOW", on_close)

    try:
        root.mainloop()
    finally:
        cleanup()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        try:
            messagebox.showerror("Fatal", traceback.format_exc())
        except Exception:
            pass
        raise SystemExit(1)
