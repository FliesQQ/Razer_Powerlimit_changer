"""Profile store and apply orchestration."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


DEFAULT_PROFILES = [
    {
        "id": "quiet",
        "name": "静音",
        "pl1_w": 55,
        "pl2_w": 75,
        "tau_s": 48,
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
    gpu_level: str = "medium"
    fan_mode: str = "auto"  # auto | max | manual
    fan_rpm: int = 3000
    max_fan: bool = False  # legacy; derived from fan_mode when loading
    afterburner_profile: Optional[int] = None
    hotkey: Optional[str] = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Profile":
        fan_mode = d.get("fan_mode")
        if not fan_mode:
            fan_mode = "max" if d.get("max_fan") else "auto"
        fan_mode = str(fan_mode).lower()
        fan_rpm = int(d.get("fan_rpm", 3000))
        return Profile(
            id=str(d["id"]),
            name=str(d["name"]),
            pl1_w=float(d["pl1_w"]),
            pl2_w=float(d["pl2_w"]),
            tau_s=float(d.get("tau_s", 48)),
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
            self.settings = {}
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
        self.settings = dict(data.get("settings") or {})
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
    ) -> Profile:
        if not fan_mode:
            fan_mode = "max" if max_fan else "auto"
        profile = Profile(
            id=uuid.uuid4().hex[:10],
            name=name,
            pl1_w=pl1_w,
            pl2_w=pl2_w,
            tau_s=tau_s,
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
        self.save()
        return True

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

        before_synapse = set()
        if suppress_synapse and self.synapse is not None:
            try:
                from .backends.synapse_guard import list_synapse_ui_pids

                before_synapse = list_synapse_ui_pids()
            except Exception:
                before_synapse = set()

        curve_on = bool(getattr(self.fan_curve_cfg, "enabled", False))

        # 1) GPU/fan first (EC may touch power policy).
        if self.synapse is not None:
            try:
                # When software fan curves are on, only set GPU boost; curve loop owns RPM.
                if curve_on:
                    from .backends.synapse_gpu import NAME_TO_LEVEL

                    level = NAME_TO_LEVEL.get(str(profile.gpu_level).lower())
                    if level is None:
                        raise ValueError(f"Invalid gpu_level: {profile.gpu_level}")
                    self.synapse.set_perf_mode(4, 1)  # CUSTOM + manual for curve control
                    self.synapse.set_max_fan(False)
                    self.synapse.set_gpu_boost(level)
                    messages.append(f"GPU OK: {profile.gpu_level} (风扇由温度曲线接管)")
                else:
                    level = self.synapse.apply(
                        profile.gpu_level,
                        max_fan=profile.max_fan,
                        fan_mode=profile.fan_mode,
                        fan_rpm=profile.fan_rpm,
                    )
                    messages.append(f"GPU/风扇 OK: {level}")
            except Exception as exc:  # noqa: BLE001
                ok = False
                messages.append(f"GPU/风扇失败: {exc}")

        if suppress_synapse and self.synapse is not None:
            try:
                from .backends.synapse_guard import snapshot_and_suppress

                killed = snapshot_and_suppress(before_synapse, wait_s=0.6)
                if killed:
                    messages.append(f"已阻止雷云界面拉起({killed})")
            except Exception:
                pass

        # 2) Undervolt
        if apply_undervolt and self.undervolt is not None:
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

        # 3) CPU PL last — after EC HID, so Razer won't immediately overwrite.
        if self.rapl is not None:
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
