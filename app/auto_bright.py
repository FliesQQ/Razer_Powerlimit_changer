"""Auto brightness by AC/battery — logic ported from AutoBright (no separate tray/theme)."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, fields
from typing import Any, Callable, Optional

from app.backends.brightness import (
    HybridBrightnessBackend,
    clamp_brightness,
    is_ac_power,
)


@dataclass
class AutoBrightConfig:
    enabled: bool = False
    plug_bright: int = 85
    bat_bright: int = 40
    applied_plug_bright: int = 85
    applied_bat_bright: int = 40
    poll_ms: int = 1500
    oled_mode: bool = False
    brightness_lock: bool = False
    lock_mode: str = "delay_restore"  # delay_restore | until_power_change
    lock_delay_sec: int = 5
    lock_probe_profile: str = "balanced"  # eco | balanced | sensitive
    prefer_compat_backend: bool = False

    def normalized(self) -> "AutoBrightConfig":
        oled = bool(self.oled_mode)
        lock_mode = self.lock_mode
        if lock_mode not in {"delay_restore", "until_power_change"}:
            lock_mode = "delay_restore"
        probe = self.lock_probe_profile
        if probe not in {"eco", "balanced", "sensitive"}:
            probe = "balanced"
        delay = max(1, min(120, int(self.lock_delay_sec)))
        poll = max(1000, int(self.poll_ms))
        plug = clamp_brightness(int(self.plug_bright), oled)
        bat = clamp_brightness(int(self.bat_bright), oled)
        a_plug = clamp_brightness(int(self.applied_plug_bright), oled)
        a_bat = clamp_brightness(int(self.applied_bat_bright), oled)
        return AutoBrightConfig(
            enabled=bool(self.enabled),
            plug_bright=plug,
            bat_bright=bat,
            applied_plug_bright=a_plug,
            applied_bat_bright=a_bat,
            poll_ms=poll,
            oled_mode=oled,
            brightness_lock=bool(self.brightness_lock),
            lock_mode=lock_mode,
            lock_delay_sec=delay,
            lock_probe_profile=probe,
            prefer_compat_backend=bool(self.prefer_compat_backend),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "AutoBrightConfig":
        if not data:
            return cls().normalized()
        known = {f.name for f in fields(cls)}
        raw = {k: v for k, v in dict(data).items() if k in known}
        return cls(**{**asdict(cls()), **raw}).normalized()


class AutoBrightController:
    """Polls AC line and applies / locks brightness. UI-agnostic."""

    def __init__(
        self,
        root,
        *,
        get_config: Callable[[], AutoBrightConfig],
        save_config: Callable[[AutoBrightConfig], None],
        backend: Optional[HybridBrightnessBackend] = None,
        on_status: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._root = root
        self._get_config = get_config
        self._save_config = save_config
        self._backend = backend or HybridBrightnessBackend()
        self._on_status = on_status
        self._bright_lock = threading.Lock()
        self._after_id: Optional[str] = None
        self._running = False

        self._last_ac: Optional[bool] = None
        self._lock_pending_since: Optional[float] = None
        self._lock_pending_target: Optional[int] = None
        self._lock_hold_until_power_change = False
        self._lock_hold_power_state: Optional[bool] = None
        self._last_brightness_probe_at = 0.0
        self._last_brightness_set_at = 0.0
        self._last_status_ac: Optional[bool] = None
        self._last_msg = ""
        self._last_ok: Optional[bool] = None

        cfg = self._get_config().normalized()
        self._backend.set_prefer_fallback(cfg.prefer_compat_backend)

    @property
    def backend(self) -> HybridBrightnessBackend:
        return self._backend

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._schedule(200)

    def stop(self) -> None:
        self._running = False
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def shutdown(self) -> None:
        self.stop()
        try:
            self._backend.shutdown()
        except Exception:
            pass

    def notify_resume(self) -> None:
        """Force re-apply after sleep/hibernate (brightness often resets)."""
        self._last_ac = None
        self._lock_hold_until_power_change = False
        self._lock_hold_power_state = None
        self._lock_pending_since = None
        self._lock_pending_target = None
        if self._running:
            self._schedule(100)

    def apply_now(self, *, commit_sliders: bool = True) -> None:
        cfg = self._get_config().normalized()
        if commit_sliders:
            cfg.applied_plug_bright = clamp_brightness(cfg.plug_bright, cfg.oled_mode)
            cfg.applied_bat_bright = clamp_brightness(cfg.bat_bright, cfg.oled_mode)
            self._save_config(cfg)
        ac = is_ac_power()
        v = cfg.applied_plug_bright if ac else cfg.applied_bat_bright
        self._bright_async(v)
        self._emit_status(ac=ac, force=True)

    def sync_backend_preference(self, prefer_compat: bool) -> None:
        self._backend.set_prefer_fallback(bool(prefer_compat))

    def status_snapshot(self) -> dict:
        ac = is_ac_power()
        mode = self._backend.get_mode_label()
        return {
            "ac": ac,
            "mode": mode,
            "ok": self._last_ok,
            "message": self._last_msg,
            "enabled": self._get_config().enabled,
        }

    def _schedule(self, ms: int) -> None:
        if not self._running:
            return
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self._root.after(max(200, int(ms)), self._tick)

    def _bright_async(self, val: int) -> None:
        self._last_brightness_set_at = time.monotonic()

        def run() -> None:
            with self._bright_lock:
                ok, msg = self._backend.set_percent(val)
            prefer = self._backend.is_prefer_fallback()

            def done() -> None:
                self._last_ok = ok
                self._last_msg = msg
                # Persist auto-fallback so next launch keeps working mode.
                try:
                    cfg = self._get_config().normalized()
                    if bool(cfg.prefer_compat_backend) != prefer:
                        cfg.prefer_compat_backend = prefer
                        self._save_config(cfg)
                except Exception:
                    pass
                self._emit_status(force=True)

            try:
                self._root.after(0, done)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True, name="AutoBrightSet").start()

    def _emit_status(self, *, ac: Optional[bool] = None, force: bool = False) -> None:
        if self._on_status is None:
            return
        if ac is None:
            ac = is_ac_power()
        snap = {
            "ac": ac,
            "mode": self._backend.get_mode_label(),
            "ok": self._last_ok,
            "message": self._last_msg,
            "enabled": self._get_config().enabled,
        }
        if not force and ac == self._last_status_ac and not self._last_msg:
            return
        self._last_status_ac = ac
        try:
            self._on_status(snap)
        except Exception:
            pass

    def _tick(self) -> None:
        self._after_id = None
        if not self._running:
            return
        cfg = self._get_config().normalized()
        if not cfg.enabled:
            self._schedule(cfg.poll_ms)
            return

        self._backend.set_prefer_fallback(cfg.prefer_compat_backend)
        ac = is_ac_power()
        now = time.monotonic()
        self._emit_status(ac=ac)

        if self._last_ac is None or ac != self._last_ac:
            v = cfg.applied_plug_bright if ac else cfg.applied_bat_bright
            self._bright_async(v)
            self._last_ac = ac
            self._lock_hold_until_power_change = False
            self._lock_hold_power_state = None
            self._lock_pending_since = None
            self._lock_pending_target = None

        base_probe_sec = {
            "eco": 60.0,
            "balanced": 30.0,
            "sensitive": 15.0,
        }.get(cfg.lock_probe_profile, 30.0)
        hold_probe_sec = {
            "eco": 90.0,
            "balanced": 45.0,
            "sensitive": 30.0,
        }.get(cfg.lock_probe_profile, 45.0)
        if cfg.lock_mode == "delay_restore" and self._lock_pending_since is not None:
            brightness_probe_sec = 5.0
        elif cfg.lock_mode == "until_power_change" and self._lock_hold_until_power_change:
            brightness_probe_sec = hold_probe_sec
        else:
            brightness_probe_sec = base_probe_sec

        just_set_cooldown_sec = 5.0
        can_probe = now - self._last_brightness_set_at >= just_set_cooldown_sec
        if (
            cfg.brightness_lock
            and can_probe
            and now - self._last_brightness_probe_at >= brightness_probe_sec
        ):
            self._last_brightness_probe_at = now
            target = cfg.applied_plug_bright if ac else cfg.applied_bat_bright
            current = self._backend.get_percent()
            if current is not None:
                if abs(current - target) <= 1:
                    self._lock_pending_since = None
                    self._lock_pending_target = None
                    if cfg.lock_mode == "until_power_change":
                        self._lock_hold_until_power_change = False
                        self._lock_hold_power_state = None
                else:
                    now = time.monotonic()
                    if cfg.lock_mode == "until_power_change":
                        if not self._lock_hold_until_power_change:
                            self._lock_hold_until_power_change = True
                            self._lock_hold_power_state = ac
                            self._last_ok = True
                            self._last_msg = "lock_hold"
                            self._emit_status(ac=ac, force=True)
                    else:
                        if self._lock_pending_target != target:
                            self._lock_pending_target = target
                            self._lock_pending_since = now
                        elif self._lock_pending_since is None:
                            self._lock_pending_since = now
                        elif now - self._lock_pending_since >= float(cfg.lock_delay_sec):
                            self._bright_async(target)
                            self._last_ok = True
                            self._last_msg = f"lock_restore:{cfg.lock_delay_sec}:{target}"
                            self._emit_status(ac=ac, force=True)
                            self._lock_pending_since = None
                            self._lock_pending_target = None

        next_ms = cfg.poll_ms
        self._schedule(next_ms)
