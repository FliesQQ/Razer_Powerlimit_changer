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
from app.auto_bright import AutoBrightConfig, AutoBrightController
from app.backends.afterburner import AfterburnerBackend
from app.backends.brightness import HybridBrightnessBackend
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
from app.profile_toast import ProfileToast
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
    init_flags: dict = {}

    try:
        ring0.initialize()
        rapl = CpuRaplBackend(ring0)
        undervolt = CpuUndervoltBackend(ring0)
        init_flags["winring0"] = ("ok", None)
    except Exception as exc:  # noqa: BLE001
        init_flags["winring0"] = ("fail", exc)

    synapse = None
    try:
        from app.backends.razer_devices import detect_blade_device

        blade = detect_blade_device()
        synapse = SynapseGpuBackend(product_id=blade.product_id if blade else None)
        synapse.open()
        if blade:
            init_flags["razer"] = ("blade", f"{blade.name} ({blade.pid_hex})")
        else:
            init_flags["razer"] = ("ok", None)
    except Exception as exc:  # noqa: BLE001
        init_flags["razer"] = ("fail", exc)
        synapse = None

    afterburner = AfterburnerBackend()
    if afterburner.available:
        init_flags["ab"] = ("ok", afterburner.exe)
    else:
        init_flags["ab"] = ("miss", None)

    probe = probe_gpu_power_write()
    init_flags["probe"] = probe.message

    manager = ProfileManager(
        rapl=rapl,
        undervolt=undervolt,
        synapse=synapse,
        afterburner=afterburner,
    )

    from app import i18n
    from app.i18n import t as _t

    i18n.init_from_settings(getattr(manager, "settings", {}) or {})

    init_msgs: list[str] = []
    wr = init_flags.get("winring0")
    if wr and wr[0] == "ok":
        init_msgs.append(_t("init_winring0_ok"))
    elif wr:
        init_msgs.append(_t("init_winring0_fail", exc=wr[1]))
    rz = init_flags.get("razer")
    if rz and rz[0] == "blade":
        init_msgs.append(f"Razer HID: {rz[1]}")
    elif rz and rz[0] == "ok":
        init_msgs.append(_t("init_razer_ok"))
    elif rz:
        init_msgs.append(_t("init_razer_fail", exc=rz[1]))
    ab = init_flags.get("ab")
    if ab and ab[0] == "ok":
        init_msgs.append(_t("init_ab_ok", exe=ab[1]))
    elif ab:
        init_msgs.append(_t("init_ab_miss"))
    if init_flags.get("probe"):
        init_msgs.append(str(init_flags["probe"]))

    # Startup: detect & persist Intel XTU (IET) path.
    try:
        xtu_info = manager.refresh_xtu_path()
        if xtu_info.get("xtu_found"):
            init_msgs.append(_t("init_xtu_ok", path=xtu_info.get("xtu_path")))
        else:
            init_msgs.append(_t("init_xtu_miss"))
    except Exception as exc:  # noqa: BLE001
        init_msgs.append(_t("init_xtu_fail", exc=exc))

    monitor = MonitorBackend()
    temps = TempMonitor(ring0 if rapl is not None else None)
    hotkeys = HotkeyService()

    root = tk.Tk()
    hotkeys.bind_root(root)
    try:
        from app.window_icon import apply_window_icon

        apply_window_icon(root)
        # Re-apply after Tk maps the HWND (title bar icon is more reliable then).
        root.after(200, lambda: apply_window_icon(root))
    except Exception:
        pass

    profile_toast = ProfileToast(root)
    _ui_feedback: dict = {"tray": None}

    def notify_profile_change(*, show_toast: bool = False, restored: bool = False) -> None:
        """Update tray hover tip; optionally show top-right switch toast."""
        name = ""
        try:
            pid = manager.active_profile_id
            p = manager.get(pid) if pid else None
            name = p.name if p else ""
        except Exception:
            name = ""
        tip = _t("tray_tip_profile", name=name) if name else _t("tray_tip_none")
        tray_svc = _ui_feedback.get("tray")
        if tray_svc is not None:
            try:
                tray_svc.set_tooltip(tip)
            except Exception:
                pass
        if show_toast:
            try:
                if restored:
                    profile_toast.show(_t("toast_restored"), subtitle=name)
                else:
                    profile_toast.show(_t("toast_switched", name=name or "-"))
            except Exception:
                pass

    _fan_cache = {
        "z1": None,
        "z2": None,
        "err_kind": "",  # "" | "timeout" | "fail"
    }
    _ec_cache = {
        "cpu_name": None,
        "cpu_code": None,
        "gpu_name": None,
        "gpu_code": None,
        "cpu_stale": False,
        "gpu_stale": False,
        "no_hid": False,
        "cpu_err": "",
        "gpu_err": "",
    }
    fan_ctrl: FanCurveController | None = None
    sensor_tray: SensorTrayService | None = None
    osd: PerformanceOsd | None = None

    def _hid_poll_worker() -> None:
        """Single background HID poller: fans + EC boost (avoids lock contention)."""
        import time as _time
        from app.backends.synapse_gpu import CPU_BOOST_NAMES, LEVEL_NAMES

        while True:
            if synapse is None:
                _ec_cache["no_hid"] = True
                _ec_cache["cpu_name"] = None
                _ec_cache["gpu_name"] = None
                _time.sleep(5.0)
                continue
            _ec_cache["no_hid"] = False
            # Fans — store raw; format in status_provider for current language.
            try:
                z1, z2 = synapse.get_fans_rpm()
                _fan_cache["z1"] = int(z1)
                _fan_cache["z2"] = int(z2)
                _fan_cache["err_kind"] = ""
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                _fan_cache["err_kind"] = (
                    "timeout"
                    if "timeout" in msg.lower() or "超时" in msg
                    else "fail"
                )
            # EC CPU/GPU raw
            try:
                cpu = synapse.get_cpu_boost()
                _ec_cache["cpu_name"] = CPU_BOOST_NAMES.get(cpu, str(int(cpu)))
                _ec_cache["cpu_code"] = int(cpu)
                _ec_cache["cpu_stale"] = False
                _ec_cache["cpu_err"] = ""
            except Exception as exc:  # noqa: BLE001
                if synapse._last_cpu_boost is not None:
                    cpu = synapse._last_cpu_boost
                    _ec_cache["cpu_name"] = CPU_BOOST_NAMES.get(cpu, str(int(cpu)))
                    _ec_cache["cpu_code"] = int(cpu)
                    _ec_cache["cpu_stale"] = True
                    _ec_cache["cpu_err"] = ""
                else:
                    _ec_cache["cpu_err"] = str(exc)[:60]
            try:
                gpu = synapse.get_gpu_boost()
                _ec_cache["gpu_name"] = LEVEL_NAMES.get(gpu, str(int(gpu)))
                _ec_cache["gpu_code"] = int(gpu)
                _ec_cache["gpu_stale"] = False
                _ec_cache["gpu_err"] = ""
            except Exception as exc:  # noqa: BLE001
                if synapse._last_gpu_boost is not None:
                    gpu = synapse._last_gpu_boost
                    _ec_cache["gpu_name"] = LEVEL_NAMES.get(gpu, str(int(gpu)))
                    _ec_cache["gpu_code"] = int(gpu)
                    _ec_cache["gpu_stale"] = True
                    _ec_cache["gpu_err"] = ""
                else:
                    _ec_cache["gpu_err"] = str(exc)[:60]
            _time.sleep(6.0)

    import threading as _threading

    _threading.Thread(target=_hid_poll_worker, daemon=True, name="HidStatusPoll").start()

    def status_provider() -> dict:
        from app.i18n import format_ec_line, format_fan_line, t as tt

        out = {}
        if _ec_cache.get("no_hid"):
            out["EC_CPU"] = tt("no_razer_hid")
            out["EC_GPU"] = tt("no_razer_hid")
        else:
            if _ec_cache.get("cpu_name") is not None:
                out["EC_CPU"] = format_ec_line(
                    _ec_cache["cpu_name"],
                    int(_ec_cache["cpu_code"]),
                    stale=bool(_ec_cache.get("cpu_stale")),
                    hint=True,
                )
            elif _ec_cache.get("cpu_err"):
                out["EC_CPU"] = f"{tt('read_fail')}: {_ec_cache['cpu_err']}"
            else:
                out["EC_CPU"] = tt("reading")
            if _ec_cache.get("gpu_name") is not None:
                out["EC_GPU"] = format_ec_line(
                    _ec_cache["gpu_name"],
                    int(_ec_cache["gpu_code"]),
                    stale=bool(_ec_cache.get("gpu_stale")),
                    hint=False,
                )
            elif _ec_cache.get("gpu_err"):
                out["EC_GPU"] = f"{tt('read_fail')}: {_ec_cache['gpu_err']}"
            else:
                out["EC_GPU"] = tt("reading")
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
                out["CPU PL"] = f"{tt('read_fail')}: {exc}"
        if undervolt is not None:
            try:
                uv = undervolt.read()
                out["UV"] = f"{uv.core_mv}/{uv.cache_mv}/{uv.ecache_mv} mV"
                if getattr(undervolt, "last_locked", False):
                    out["UV提示"] = tt("uv_fw_locked")
            except Exception as exc:  # noqa: BLE001
                out["UV"] = f"{tt('read_fail')}: {exc}"
        try:
            tr = temps.read()
            src = {"package": "Package", "core": "Core", "wmi": "ACPI"}.get(
                tr.cpu_source, ""
            )
            cpu_txt = f"{tr.cpu_c}°C" if tr.cpu_c is not None else "-"
            if src and tr.cpu_c is not None:
                cpu_txt = f"{tr.cpu_c}°C({src})"
            out["温度"] = (
                f"CPU={cpu_txt}  GPU={tr.gpu_c if tr.gpu_c is not None else '-'}°C"
            )
        except Exception as exc:  # noqa: BLE001
            out["温度"] = f"{tt('read_fail')}: {exc}"
        if fan_ctrl is not None and getattr(manager.fan_curve_cfg, "enabled", False):
            out["风扇曲线"] = fan_ctrl.last_status
        err_kind = _fan_cache.get("err_kind") or ""
        err = (
            tt("rpm_timeout")
            if err_kind == "timeout"
            else (tt("rpm_fail") if err_kind == "fail" else "")
        )
        out["风扇"] = format_fan_line(
            _fan_cache.get("z1"), _fan_cache.get("z2"), err
        )
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
            # Fan-curve / manual RPM can also drop GPU tier — keep it sticky.
            if (
                synapse is not None
                and manager.feature_enabled("enable_gpu_level")
                and p is not None
            ):
                try:
                    from app.backends.synapse_gpu import NAME_TO_LEVEL

                    gl = NAME_TO_LEVEL.get(str(p.gpu_level).lower())
                    if gl is not None:
                        synapse.set_gpu_boost(gl)
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
            try:
                ab_cfg = AutoBrightConfig.from_dict(
                    (manager.settings or {}).get("auto_bright")
                )
                if auto_bright is not None and ab_cfg.enabled:
                    auto_bright.notify_resume()
                    msgs.append("亮度已校正")
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
        # Win32 hotkeys usually survive; keyboard-lib hooks often die — refresh either way.
        root.after(1500, register_hotkeys)

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

    _hk_retry = {"n": 0}

    def register_hotkeys() -> None:
        mapping = {}
        for hk, pid in manager.hotkey_map().items():

            def make_cb(profile_id: str):
                return lambda: on_hotkey_profile(profile_id)

            mapping[hk] = make_cb(pid)
        mapping["ctrl+alt+0"] = lambda: on_hotkey_restore()
        failed = hotkeys.register_map(mapping)
        if failed and len(failed) >= len(mapping) and _hk_retry["n"] < 6:
            _hk_retry["n"] += 1
            root.after(400, register_hotkeys)
            return
        _hk_retry["n"] = 0
        if failed:
            gui._set_status(_t("hotkey_fail", keys=", ".join(failed)))
        else:
            mode = getattr(hotkeys, "mode", "") or ""
            if mode:
                gui._set_status(_t("hotkey_ready", mode=mode, n=len(mapping)))

    def on_hotkey_profile(profile_id: str) -> None:
        def work() -> None:
            try:
                result = manager.apply_by_id(profile_id)
                if fan_ctrl is not None and getattr(
                    manager.fan_curve_cfg, "enabled", False
                ):
                    try:
                        fan_ctrl.force_tick()
                        result.messages.append(_t("curve_keeps_control"))
                    except Exception:
                        pass
                msgs = list(getattr(result, "messages", None) or [])
            except Exception as exc:  # noqa: BLE001
                msgs = [f"热键切档失败: {exc}"]

            def done() -> None:
                try:
                    gui.refresh_list()
                    gui._set_status(" | ".join(msgs)[:180])
                    notify_profile_change(show_toast=True)
                except Exception:
                    pass

            try:
                root.after(0, done)
            except Exception:
                pass

        import threading

        threading.Thread(target=work, daemon=True, name="HotkeyApply").start()

    def on_hotkey_restore() -> None:
        def work() -> None:
            try:
                result = manager.restore_defaults()
                if fan_ctrl is not None and getattr(
                    manager.fan_curve_cfg, "enabled", False
                ):
                    try:
                        fan_ctrl.force_tick()
                        result.messages.append(_t("curve_keeps_control"))
                    except Exception:
                        pass
                msgs = list(getattr(result, "messages", None) or [])
            except Exception as exc:  # noqa: BLE001
                msgs = [f"热键恢复失败: {exc}"]

            def done() -> None:
                try:
                    gui.uv_core.set("0")
                    gui.uv_cache.set("0")
                    gui.uv_ecache.set("0")
                    manager.update_undervolt(0, 0, 0)
                    gui.refresh_list()
                    gui._set_status(" | ".join(msgs)[:180])
                    notify_profile_change(show_toast=True, restored=True)
                except Exception:
                    pass

            try:
                root.after(0, done)
            except Exception:
                pass

        import threading

        threading.Thread(target=work, daemon=True, name="HotkeyRestore").start()

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
        gui._set_status(msg if ok else _t("autostart_fail_msg", msg=msg))

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
                    text = _t("startup_applied", msg=" | ".join(result.messages)[:160])
                else:
                    result = manager.reapply_undervolt()
                    text = _t("startup_uv", msg=" | ".join(result.messages)[:160])
            except Exception as exc:  # noqa: BLE001
                text = _t("startup_fail", exc=exc)
            root.after(0, lambda: gui._set_status(text[:200]))

        import threading

        threading.Thread(target=work, daemon=True, name="StartupApply").start()

    root.after(1500, apply_startup_profile)

    def get_ec_pin_for_fans():
        """Desired EC CPU/GPU after software-curve fan writes (avoid ~55W clamp)."""
        from app.backends.synapse_gpu import (
            CpuBoost,
            GpuLevel,
            NAME_TO_CPU_BOOST,
            NAME_TO_LEVEL,
        )

        pid = manager.active_profile_id
        p = manager.get(pid) if pid else None
        cpu_pin = None
        gpu_pin = None
        if manager.feature_enabled("enable_cpu_level"):
            if p is not None:
                name = str(getattr(p, "cpu_level", "boost") or "boost").lower()
                if name == "custom":
                    cpu_pin = CpuBoost.BOOST
                else:
                    cpu_pin = NAME_TO_CPU_BOOST.get(name, CpuBoost.BOOST)
            else:
                # No active profile — use a high floor so we never re-pin "low".
                cpu_pin = CpuBoost.BOOST
        if manager.feature_enabled("enable_gpu_level"):
            if p is not None:
                gpu_pin = NAME_TO_LEVEL.get(str(p.gpu_level).lower())
            if gpu_pin is None:
                gpu_pin = GpuLevel.HIGH
        return cpu_pin, gpu_pin

    def after_fan_curve_write() -> None:
        """If CPU tier is custom, also reassert MSR PL (EC+MSR both matter)."""
        if rapl is None or rapl.last_target is None:
            return
        if not manager.feature_enabled("enable_cpu_level"):
            return
        pid = manager.active_profile_id
        p = manager.get(pid) if pid else None
        if p is None:
            return
        if str(getattr(p, "cpu_level", "") or "").lower() != "custom":
            return
        try:
            want = rapl.last_target
            got = rapl.read()
            if abs(got.pl1_w - want[0]) > 3.0 or abs(got.pl2_w - want[1]) > 5.0:
                rapl.reassert()
        except Exception:
            pass

    fan_ctrl = FanCurveController(
        synapse=synapse,
        temps=temps,
        get_config=lambda: manager.fan_curve_cfg,
        get_ec_pin=get_ec_pin_for_fans,
        on_after_fan_write=after_fan_curve_write,
    )
    fan_ctrl.start()

    def get_auto_bright_cfg() -> AutoBrightConfig:
        return AutoBrightConfig.from_dict(
            (manager.settings or {}).get("auto_bright")
        )

    def save_auto_bright_cfg(cfg: AutoBrightConfig) -> None:
        manager.update_settings(auto_bright=cfg.to_dict())

    def on_auto_bright_status(snap: dict) -> None:
        try:
            gui.update_auto_bright_status(snap)
        except Exception:
            pass

    auto_bright = AutoBrightController(
        root,
        get_config=get_auto_bright_cfg,
        save_config=save_auto_bright_cfg,
        backend=HybridBrightnessBackend(),
        on_status=on_auto_bright_status,
    )
    gui.bind_auto_bright_controller(auto_bright)
    gui.on_auto_bright_changed = lambda: None
    auto_bright.start()

    register_hotkeys()
    # HWND / WndProc may not be ready on first pass — one delayed refresh.
    root.after(600, register_hotkeys)
    root.after(5000, reassert_pl)

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
            if auto_bright is not None:
                auto_bright.shutdown()
        except Exception:
            pass
        try:
            profile_toast.destroy()
        except Exception:
            pass
        try:
            hotkeys.shutdown()
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
            (_t("sensor_tray_on") if enabled else _t("sensor_tray_off"))
            + ("" if ok else _t("sensor_tray_fail_tag"))
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

    def get_tray_profiles() -> list[tuple[str, str]]:
        return [(p.id, p.name) for p in manager.tray_menu_profiles()]

    tray = TrayService(
        on_show=show_window,
        on_quit=quit_app,
        get_tray_profiles=get_tray_profiles,
        on_select_profile=on_hotkey_profile,
        get_active_profile_id=lambda: manager.active_profile_id,
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
    _ui_feedback["tray"] = tray
    notify_profile_change(show_toast=False)

    def on_profile_applied_from_gui() -> None:
        # GUI apply path: re-assert software curve if it owns fans.
        if fan_ctrl is not None and getattr(manager.fan_curve_cfg, "enabled", False):
            def _curve():
                try:
                    fan_ctrl.force_tick()
                except Exception:
                    pass
                root.after(0, lambda: notify_profile_change(show_toast=False))

            import threading

            threading.Thread(target=_curve, daemon=True, name="CurveAfterApply").start()
        else:
            notify_profile_change(show_toast=False)

    gui.on_profile_applied = on_profile_applied_from_gui
    gui.on_tray_menu_profiles_changed = tray.refresh_menu

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
