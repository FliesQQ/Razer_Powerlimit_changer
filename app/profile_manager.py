"""Profile store and apply orchestration."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


DEFAULT_FEATURE_FLAGS = {
    # Synapse-like EC CPU tier (+ custom → PL1/PL2). Voltage is separate.
    "enable_cpu_level": True,
    "enable_gpu_level": True,
    "enable_undervolt": True,
    # Legacy keys kept for older configs (ignored for apply logic).
    "enable_cpu_tdp": False,
    "pin_ec_cpu_boost": True,
    "pinned_ec_cpu_boost": "boost",
}

VALID_CPU_LEVELS = frozenset({"low", "medium", "high", "boost", "custom", "overclock"})


def _merge_feature_defaults(settings: dict[str, Any]) -> dict[str, Any]:
    out = dict(settings or {})
    for k, v in DEFAULT_FEATURE_FLAGS.items():
        if k not in out:
            out[k] = v
    return out


DEFAULT_PROFILES = [
    {
        "id": "quiet",
        "name": "静音",
        "pl1_w": 55,
        "pl2_w": 75,
        "tau_s": 48,
        "cpu_level": "low",
        "gpu_level": "low",
        "fan_mode": "auto",
        "fan_rpm": 2500,
        "max_fan": False,
        "afterburner_profile": None,
        "hotkey": "ctrl+alt+1",
    },
    {
        "id": "balanced",
        "name": "均衡",
        "pl1_w": 60,
        "pl2_w": 80,
        "tau_s": 48,
        "cpu_level": "medium",
        "gpu_level": "medium",
        "fan_mode": "auto",
        "fan_rpm": 3000,
        "max_fan": False,
        "afterburner_profile": None,
        "hotkey": "ctrl+alt+2",
    },
    {
        "id": "performance",
        "name": "性能",
        "pl1_w": 75,
        "pl2_w": 95,
        "tau_s": 48,
        "cpu_level": "high",
        "gpu_level": "medium",
        "fan_mode": "manual",
        "fan_rpm": 4000,
        "max_fan": False,
        "afterburner_profile": None,
        "hotkey": "ctrl+alt+3",
    },
    {
        "id": "water",
        "name": "水冷",
        "pl1_w": 130,
        "pl2_w": 150,
        "tau_s": 48,
        "cpu_level": "boost",
        "gpu_level": "high",
        "fan_mode": "max",
        "fan_rpm": 5000,
        "max_fan": True,
        "afterburner_profile": None,
        "hotkey": "ctrl+alt+4",
    },
]


@dataclass
class UndervoltConfig:
    core_mv: float = -120.0
    cache_mv: float = -95.0
    ecache_mv: float = -80.0


@dataclass
class Profile:
    id: str
    name: str
    pl1_w: float
    pl2_w: float
    tau_s: float = 48.0
    cpu_level: str = "boost"  # low|medium|high|boost|custom — custom 才写 PL1/PL2
    gpu_level: str = "medium"
    fan_mode: str = "auto"  # auto | max | manual
    fan_rpm: int = 3000
    max_fan: bool = False  # legacy; derived from fan_mode when loading
    afterburner_profile: Optional[int] = None
    hotkey: Optional[str] = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Profile":
        from .backends.synapse_gpu import CPU_BOOST_NAMES, cpu_boost_for_pl1

        fan_mode = d.get("fan_mode")
        if not fan_mode:
            fan_mode = "max" if d.get("max_fan") else "auto"
        fan_mode = str(fan_mode).lower()
        fan_rpm = int(d.get("fan_rpm", 3000))
        pl1 = float(d["pl1_w"])
        cpu_level = str(d.get("cpu_level") or "").lower().strip()
        if cpu_level not in VALID_CPU_LEVELS:
            cpu_level = CPU_BOOST_NAMES[cpu_boost_for_pl1(pl1)]
        return Profile(
            id=str(d["id"]),
            name=str(d["name"]),
            pl1_w=pl1,
            pl2_w=float(d["pl2_w"]),
            tau_s=float(d.get("tau_s", 48)),
            cpu_level=cpu_level,
            gpu_level=str(d.get("gpu_level", "medium")),
            fan_mode=fan_mode,
            fan_rpm=fan_rpm,
            max_fan=(fan_mode == "max"),
            afterburner_profile=d.get("afterburner_profile"),
            hotkey=d.get("hotkey"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["max_fan"] = self.fan_mode == "max"
        return data


@dataclass
class ApplyResult:
    ok: bool
    messages: list[str] = field(default_factory=list)
    profile_id: Optional[str] = None


def default_config_path() -> Path:
    from .paths import profiles_path

    return profiles_path()


class ProfileManager:
    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        rapl=None,
        undervolt=None,
        synapse=None,
        afterburner=None,
    ) -> None:
        self.path = Path(path) if path else default_config_path()
        self.rapl = rapl
        self.undervolt = undervolt
        self.synapse = synapse
        self.afterburner = afterburner
        self.profiles: list[Profile] = []
        self.undervolt_cfg = UndervoltConfig()
        self.safe_profile_id = "quiet"
        self.gpu_tdp_measured: dict[str, float] = {
            "low": 100.0,
            "medium": 0.0,
            "high": 175.0,
        }
        self.active_profile_id: Optional[str] = None
        self.settings: dict[str, Any] = {}
        self.fan_curve_cfg = None  # set in load
        self.load()

    def load(self) -> None:
        from .backends.fan_curve import FanCurveConfig

        if not self.path.is_file():
            self.profiles = [Profile.from_dict(p) for p in DEFAULT_PROFILES]
            self.undervolt_cfg = UndervoltConfig()
            self.settings = _merge_feature_defaults({})
            self.fan_curve_cfg = FanCurveConfig()
            self.save()
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        uv = data.get("undervolt", {})
        self.undervolt_cfg = UndervoltConfig(
            core_mv=float(uv.get("core_mv", -120)),
            cache_mv=float(uv.get("cache_mv", -95)),
            ecache_mv=float(uv.get("ecache_mv", -80)),
        )
        self.safe_profile_id = str(data.get("safe_profile_id", "quiet"))
        self.gpu_tdp_measured = dict(data.get("gpu_tdp_measured", self.gpu_tdp_measured))
        self.profiles = [Profile.from_dict(p) for p in data.get("profiles", DEFAULT_PROFILES)]
        self.active_profile_id = data.get("active_profile_id")
        self.settings = _merge_feature_defaults(dict(data.get("settings") or {}))
        self.fan_curve_cfg = FanCurveConfig.from_dict(data.get("fan_curves"))

    def save(self) -> None:
        from .backends.fan_curve import FanCurveConfig

        if self.fan_curve_cfg is None:
            self.fan_curve_cfg = FanCurveConfig()
        payload = {
            "undervolt": asdict(self.undervolt_cfg),
            "safe_profile_id": self.safe_profile_id,
            "gpu_tdp_measured": self.gpu_tdp_measured,
            "active_profile_id": self.active_profile_id,
            "settings": self.settings,
            "fan_curves": self.fan_curve_cfg.to_dict(),
            "profiles": [p.to_dict() for p in self.profiles],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, profile_id: str) -> Optional[Profile]:
        for p in self.profiles:
            if p.id == profile_id:
                return p
        return None

    def upsert(self, profile: Profile) -> None:
        for i, p in enumerate(self.profiles):
            if p.id == profile.id:
                self.profiles[i] = profile
                self.save()
                return
        self.profiles.append(profile)
        self.save()

    def create(
        self,
        name: str,
        pl1_w: float,
        pl2_w: float,
        tau_s: float,
        gpu_level: str,
        max_fan: bool = False,
        fan_mode: str = "auto",
        fan_rpm: int = 3000,
        afterburner_profile: Optional[int] = None,
        hotkey: Optional[str] = None,
        cpu_level: str = "boost",
    ) -> Profile:
        if not fan_mode:
            fan_mode = "max" if max_fan else "auto"
        profile = Profile(
            id=uuid.uuid4().hex[:10],
            name=name,
            pl1_w=pl1_w,
            pl2_w=pl2_w,
            tau_s=tau_s,
            cpu_level=str(cpu_level or "boost").lower(),
            gpu_level=gpu_level,
            fan_mode=fan_mode,
            fan_rpm=int(fan_rpm),
            max_fan=(fan_mode == "max"),
            afterburner_profile=afterburner_profile,
            hotkey=hotkey,
        )
        self.profiles.append(profile)
        self.save()
        return profile

    def delete(self, profile_id: str) -> bool:
        before = len(self.profiles)
        self.profiles = [p for p in self.profiles if p.id != profile_id]
        if len(self.profiles) == before:
            return False
        if self.safe_profile_id == profile_id and self.profiles:
            self.safe_profile_id = self.profiles[0].id
        if "tray_menu_profile_ids" in (self.settings or {}):
            known = {p.id for p in self.profiles}
            self.settings["tray_menu_profile_ids"] = [
                str(i)
                for i in (self.settings.get("tray_menu_profile_ids") or [])
                if str(i) in known
            ]
        self.save()
        return True

    def feature_enabled(self, name: str) -> bool:
        defaults = DEFAULT_FEATURE_FLAGS
        if name == "enable_fan_curve":
            return bool(getattr(self.fan_curve_cfg, "enabled", False))
        return bool(self.settings.get(name, defaults.get(name, False)))

    def set_feature(self, name: str, enabled: bool) -> None:
        if name == "enable_fan_curve":
            if self.fan_curve_cfg is not None:
                self.fan_curve_cfg.enabled = bool(enabled)
                self.save()
            return
        self.settings[name] = bool(enabled)
        if name == "enable_cpu_tdp" and not enabled and self.rapl is not None:
            # Stop background MSR / EC CPU-boost reassert.
            self.rapl.last_target = None
        self.save()

    def apply_profile(
        self,
        profile: Profile,
        *,
        apply_undervolt: bool = True,
        remember_active: bool = True,
        suppress_synapse: bool = True,
    ) -> ApplyResult:
        messages: list[str] = []
        ok = True

        do_gpu = self.feature_enabled("enable_gpu_level")
        do_cpu_lvl = self.feature_enabled("enable_cpu_level")
        cpu_name = str(getattr(profile, "cpu_level", "boost") or "boost").lower()
        is_custom_cpu = cpu_name == "custom"
        # 仅 CPU 档=自定义 时写 PL1/PL2；电压模块独立。
        do_tdp = do_cpu_lvl and is_custom_cpu
        do_uv = bool(apply_undervolt) and self.feature_enabled("enable_undervolt")
        curve_on = self.feature_enabled("enable_fan_curve")
        # Profile fan_mode only when GPU module on and software curve off.
        do_profile_fan = do_gpu and not curve_on
        touch_ec = do_gpu or do_cpu_lvl or curve_on

        before_synapse = set()
        if suppress_synapse and self.synapse is not None and touch_ec:
            try:
                from .backends.synapse_guard import list_synapse_ui_pids

                before_synapse = list_synapse_ui_pids()
            except Exception:
                before_synapse = set()

        # 1) EC CPU/GPU/fan (Synapse Custom sliders).
        if self.synapse is not None and touch_ec:
            try:
                from .backends.synapse_gpu import (
                    CPU_BOOST_NAMES,
                    NAME_TO_CPU_BOOST,
                    NAME_TO_LEVEL,
                    CpuBoost,
                )

                cpu_name = str(getattr(profile, "cpu_level", "boost") or "boost").lower()
                if is_custom_cpu:
                    # Custom PL needs a high EC floor so firmware won't clamp ~55W.
                    cpu_boost = CpuBoost.BOOST
                else:
                    cpu_boost = NAME_TO_CPU_BOOST.get(cpu_name, CpuBoost.BOOST)
                gpu_level = NAME_TO_LEVEL.get(str(profile.gpu_level).lower())
                if do_gpu and gpu_level is None:
                    raise ValueError(f"Invalid gpu_level: {profile.gpu_level}")

                def _apply_ec() -> str:
                    parts: list[str] = []
                    if do_profile_fan and do_gpu and gpu_level is not None:
                        tag = self.synapse.apply(
                            profile.gpu_level,
                            max_fan=profile.max_fan,
                            fan_mode=profile.fan_mode,
                            fan_rpm=profile.fan_rpm,
                            cpu_boost=cpu_boost if do_cpu_lvl else None,
                            touch_cpu_boost=do_cpu_lvl,
                        )
                        parts.append(f"GPU/风扇 OK: {tag}")
                        return " | ".join(parts)

                    self.synapse.set_perf_mode_custom()
                    if do_profile_fan:
                        # Manual/auto/max fan HID can reset EC tiers — pin after.
                        self.synapse.apply_fan(profile.fan_mode, profile.fan_rpm)
                        parts.append(f"风扇={profile.fan_mode}")
                    else:
                        self.synapse.set_max_fan(False)
                    if do_cpu_lvl:
                        self.synapse.set_cpu_boost(cpu_boost)
                        if is_custom_cpu:
                            parts.append("CPU档=自定义(EC=boost)")
                        else:
                            parts.append(f"CPU档={CPU_BOOST_NAMES.get(cpu_boost, cpu_boost)}")
                    if do_gpu and gpu_level is not None:
                        self.synapse.set_gpu_boost(gpu_level)
                        note = "风扇由温度曲线接管" if curve_on else "仅 GPU"
                        parts.append(f"GPU={profile.gpu_level} ({note})")
                    # Re-pin once more: some firmware drop tiers on the last fan bit.
                    if do_profile_fan and str(profile.fan_mode).lower() == "manual":
                        if do_cpu_lvl:
                            self.synapse.set_cpu_boost(cpu_boost)
                        if do_gpu and gpu_level is not None:
                            self.synapse.set_gpu_boost(gpu_level)
                    return " | ".join(parts) if parts else "EC 无变更"

                if do_cpu_lvl:
                    tag = _apply_ec()
                else:
                    tag = self.synapse.preserve_cpu_boost(_apply_ec)
                    if do_gpu and self.feature_enabled("pin_ec_cpu_boost"):
                        pin_name = str(
                            self.settings.get("pinned_ec_cpu_boost") or "boost"
                        ).lower()
                        pin = NAME_TO_CPU_BOOST.get(pin_name, CpuBoost.BOOST)
                        if int(pin) > int(CpuBoost.BOOST):
                            pin = CpuBoost.BOOST
                        got = self.synapse.ensure_cpu_boost_at_least(pin)
                        tag = f"{tag} | EC CPU={CPU_BOOST_NAMES.get(got, got)}"
                messages.append(tag)
                try:
                    messages.append(self.synapse.read_boost_state())
                except Exception:
                    pass
            except Exception as exc:  # noqa: BLE001
                ok = False
                messages.append(f"EC CPU/GPU/风扇失败: {exc}")
        else:
            if not do_gpu and not do_cpu_lvl:
                messages.append("已跳过 EC CPU/GPU 档位（模块关闭）")

        if suppress_synapse and self.synapse is not None and before_synapse:
            try:
                from .backends.synapse_guard import snapshot_and_suppress

                killed = snapshot_and_suppress(before_synapse, wait_s=0.6)
                if killed:
                    messages.append(f"已阻止雷云界面拉起({killed})")
            except Exception:
                pass

        # 2) Undervolt
        if do_uv and self.undervolt is not None:
            try:
                from .backends.cpu_undervolt import UndervoltSettings

                target = UndervoltSettings(
                    core_mv=self.undervolt_cfg.core_mv,
                    cache_mv=self.undervolt_cfg.cache_mv,
                    ecache_mv=self.undervolt_cfg.ecache_mv,
                )
                got = self.undervolt.apply(target)
                if getattr(self.undervolt, "last_locked", False):
                    ok = False
                    messages.append(
                        f"UV 被固件锁定(读回 {got.core_mv}/{got.cache_mv}/{got.ecache_mv} mV)。"
                        "请在 BIOS 关闭 Undervoltage Protection / Overclocking Lock，"
                        "或用已检测到的 Intel XTU 应用降压。"
                    )
                else:
                    messages.append(
                        f"UV OK: {got.core_mv}/{got.cache_mv}/{got.ecache_mv} mV"
                    )
            except Exception as exc:  # noqa: BLE001
                ok = False
                messages.append(f"UV 失败: {exc}")
        elif apply_undervolt and not self.feature_enabled("enable_undervolt"):
            messages.append("已跳过降压（模块关闭）")

        # 3) CPU PL — only when CPU 档 = 自定义.
        if do_tdp and self.rapl is not None:
            try:
                got = self.rapl.apply(profile.pl1_w, profile.pl2_w, profile.tau_s)
                drift = abs(got.pl1_w - profile.pl1_w) > 3 or abs(got.pl2_w - profile.pl2_w) > 3
                msg = f"CPU PL: 目标 {profile.pl1_w}/{profile.pl2_w} → 读回 {got.pl1_w}/{got.pl2_w}W"
                if drift:
                    msg += " (EC可能回写，后台持续重申中)"
                messages.append(msg)
            except Exception as exc:  # noqa: BLE001
                ok = False
                messages.append(f"CPU PL 失败: {exc}")
        else:
            if self.rapl is not None:
                self.rapl.last_target = None
            if do_cpu_lvl and not is_custom_cpu:
                messages.append("CPU 档为固定档，已跳过自定义 PL1/PL2")
            elif not do_cpu_lvl:
                messages.append("已跳过 CPU 档位（模块关闭）")

        if profile.afterburner_profile and self.afterburner is not None:
            try:
                if self.afterburner.available:
                    tag = self.afterburner.apply_profile(int(profile.afterburner_profile))
                    messages.append(f"Afterburner OK: {tag}")
                else:
                    messages.append("Afterburner 未安装，已跳过")
            except Exception as exc:  # noqa: BLE001
                messages.append(f"Afterburner 失败: {exc}")

        if remember_active and not profile.id.startswith("temp"):
            self.active_profile_id = profile.id
            self.save()
        return ApplyResult(ok=ok, messages=messages, profile_id=profile.id)

    def apply_by_id(self, profile_id: str) -> ApplyResult:
        p = self.get(profile_id)
        if not p:
            return ApplyResult(ok=False, messages=[f"未找到档位 {profile_id}"])
        return self.apply_profile(p)

    def restore_defaults(self) -> ApplyResult:
        messages: list[str] = []
        ok = True
        if self.undervolt is not None:
            try:
                self.undervolt.restore_zero()
                messages.append("电压已归零")
            except Exception as exc:  # noqa: BLE001
                ok = False
                messages.append(f"电压归零失败: {exc}")

        safe = self.get(self.safe_profile_id) or (self.profiles[0] if self.profiles else None)
        if safe is None:
            return ApplyResult(ok=False, messages=messages + ["无可用安全档"])

        # Apply safe PL/GPU without re-applying user undervolt.
        result = self.apply_profile(safe, apply_undervolt=False)
        messages.extend(result.messages)
        return ApplyResult(ok=ok and result.ok, messages=messages, profile_id=safe.id)

    def reapply_undervolt(self) -> ApplyResult:
        if not self.feature_enabled("enable_undervolt"):
            return ApplyResult(ok=True, messages=["已跳过降压（模块关闭）"])
        if self.undervolt is None:
            return ApplyResult(ok=False, messages=["降压后端不可用"])
        try:
            from .backends.cpu_undervolt import UndervoltSettings

            target = UndervoltSettings(
                core_mv=self.undervolt_cfg.core_mv,
                cache_mv=self.undervolt_cfg.cache_mv,
                ecache_mv=self.undervolt_cfg.ecache_mv,
            )
            got = self.undervolt.apply(target)
            if getattr(self.undervolt, "last_locked", False):
                xtu = (self.settings or {}).get("xtu_path") or "(未检测到 XTU)"
                return ApplyResult(
                    ok=False,
                    messages=[
                        f"降压写入未生效，读回仍为 {got.core_mv}/{got.cache_mv}/{got.ecache_mv} mV。"
                        f"目标 {target.core_mv}/{target.cache_mv}/{target.ecache_mv}。"
                        f"固件可能锁定 UV。XTU 路径: {xtu}",
                    ],
                )
            return ApplyResult(
                ok=True,
                messages=[
                    f"已重新应用降压: {got.core_mv}/{got.cache_mv}/{got.ecache_mv} mV"
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return ApplyResult(ok=False, messages=[str(exc)])

    def update_undervolt(self, core_mv: float, cache_mv: float, ecache_mv: float) -> None:
        self.undervolt_cfg = UndervoltConfig(core_mv, cache_mv, ecache_mv)
        self.save()

    def update_settings(self, **kwargs: Any) -> None:
        self.settings.update(kwargs)
        self.save()

    def update_fan_curves(self, cfg) -> None:
        self.fan_curve_cfg = cfg
        self.save()

    def tray_menu_profile_ids(self) -> list[str]:
        """
        Profile ids shown in the tray context menu.
        Missing setting → all profiles (legacy default).
        Explicit list → only those ids that still exist, preserved order.
        """
        raw = (self.settings or {}).get("tray_menu_profile_ids", None)
        known = {p.id for p in self.profiles}
        if raw is None:
            return [p.id for p in self.profiles]
        out: list[str] = []
        for pid in list(raw or []):
            s = str(pid)
            if s in known and s not in out:
                out.append(s)
        return out

    def set_tray_menu_profile_ids(self, ids: list[str]) -> None:
        known = {p.id for p in self.profiles}
        cleaned: list[str] = []
        for pid in ids:
            s = str(pid)
            if s in known and s not in cleaned:
                cleaned.append(s)
        self.settings["tray_menu_profile_ids"] = cleaned
        self.save()

    def tray_menu_profiles(self) -> list["Profile"]:
        by_id = {p.id: p for p in self.profiles}
        return [by_id[i] for i in self.tray_menu_profile_ids() if i in by_id]

    def prune_tray_menu_profile_ids(self) -> None:
        """Drop deleted profile ids from tray menu setting if customized."""
        if "tray_menu_profile_ids" not in (self.settings or {}):
            return
        before = list(self.settings.get("tray_menu_profile_ids") or [])
        after = self.tray_menu_profile_ids()
        if before != after:
            self.settings["tray_menu_profile_ids"] = after
            self.save()

    def refresh_xtu_path(self) -> dict:
        from .backends.xtu_detect import detect_and_record

        info = detect_and_record(self.settings.get("xtu_path") or None)
        self.settings.update(info)
        self.save()
        return info

    def hotkey_map(self) -> dict[str, str]:
        """hotkey string -> profile id"""
        out: dict[str, str] = {}
        for p in self.profiles:
            if p.hotkey:
                out[p.hotkey.lower().replace(" ", "")] = p.id
        return out
