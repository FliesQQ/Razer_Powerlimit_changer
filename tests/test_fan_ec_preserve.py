"""Regression tests: fan HID must not leave EC CPU/GPU stuck at low."""

from __future__ import annotations

import unittest
from typing import Optional
from unittest.mock import MagicMock

from app.backends.fan_curve import FanCurveConfig, FanCurveController
from app.backends.synapse_gpu import (
    CpuBoost,
    GpuLevel,
    SynapseGpuBackend,
)


class FakeSynapse:
    """Minimal stand-in: fan writes force EC tiers to LOW (Blade firmware quirk)."""

    def __init__(self) -> None:
        self.cpu = CpuBoost.BOOST
        self.gpu = GpuLevel.HIGH
        self._last_cpu_boost: Optional[CpuBoost] = CpuBoost.BOOST
        self._last_gpu_boost: Optional[GpuLevel] = GpuLevel.HIGH
        self.last_preserve_error = ""
        self.preserve_fail_count = 0
        self.fan_writes = 0
        self.max_fan = False

    def get_cpu_boost(self) -> CpuBoost:
        return self.cpu

    def get_gpu_boost(self) -> GpuLevel:
        return self.gpu

    def set_cpu_boost(self, level) -> None:
        self.cpu = CpuBoost(int(level))
        self._last_cpu_boost = self.cpu

    def set_gpu_boost(self, level) -> None:
        self.gpu = GpuLevel(int(level))
        self._last_gpu_boost = self.gpu

    def set_max_fan(self, enabled: bool) -> None:
        self.max_fan = bool(enabled)

    def set_fan_rpm_zone(self, zone: int, rpm: int) -> None:
        self.fan_writes += 1
        # Simulate firmware: entering Custom/manual fans drops tiers.
        self.cpu = CpuBoost.LOW
        self.gpu = GpuLevel.LOW

    def set_fan_rpm(self, rpm: int) -> None:
        self.set_fan_rpm_zone(1, rpm)
        self.set_fan_rpm_zone(2, rpm)

    def set_perf_mode(self, perf_mode: int, fan_mode: int = 0) -> None:
        self.cpu = CpuBoost.LOW

    def set_perf_mode_custom(self) -> None:
        self.set_perf_mode(4, 0)

    def apply_fan(self, fan_mode: str = "auto", fan_rpm: int = 3000) -> str:
        mode = (fan_mode or "auto").lower()
        if mode == "max":
            self.set_perf_mode_custom()
            self.set_max_fan(True)
            return "max"
        if mode == "manual":
            self.set_max_fan(False)
            self.set_fan_rpm(int(fan_rpm))
            return f"manual:{fan_rpm}"
        self.set_perf_mode_custom()
        self.set_max_fan(False)
        return "auto"

    def preserve_ec_limits(self, fn, *, cpu_boost=None, gpu_level=None):
        # Delegate to real implementation logic via bound copy of method.
        return SynapseGpuBackend.preserve_ec_limits(
            self, fn, cpu_boost=cpu_boost, gpu_level=gpu_level
        )

    def preserve_cpu_boost(self, fn):
        return self.preserve_ec_limits(fn)


class FakeTemps:
    def read(self):
        m = MagicMock()
        m.cpu_c = 60.0
        m.gpu_c = 55.0
        return m


class TestPreserveEcLimits(unittest.TestCase):
    def test_preserve_restores_explicit_pins_after_fan_write(self) -> None:
        syn = FakeSynapse()
        syn.cpu = CpuBoost.BOOST
        syn.gpu = GpuLevel.HIGH

        def drop():
            syn.set_fan_rpm_zone(1, 3000)

        syn.preserve_ec_limits(
            drop, cpu_boost=CpuBoost.BOOST, gpu_level=GpuLevel.HIGH
        )
        self.assertEqual(syn.cpu, CpuBoost.BOOST)
        self.assertEqual(syn.gpu, GpuLevel.HIGH)
        self.assertEqual(syn.last_preserve_error, "")

    def test_preserve_without_pin_prefers_last_over_low_read(self) -> None:
        syn = FakeSynapse()
        syn._last_cpu_boost = CpuBoost.BOOST
        syn.cpu = CpuBoost.LOW  # already dropped before preserve

        def drop():
            syn.set_fan_rpm_zone(1, 2500)

        syn.preserve_ec_limits(drop)
        self.assertEqual(syn.cpu, CpuBoost.BOOST)


class TestApplyManualOrder(unittest.TestCase):
    def test_apply_manual_repins_after_fans(self) -> None:
        syn = FakeSynapse()
        # Use real apply bound to fake (needs NAME lookups on real class).
        tag = SynapseGpuBackend.apply(
            syn,
            "high",
            fan_mode="manual",
            fan_rpm=3200,
            cpu_boost=CpuBoost.BOOST,
            touch_cpu_boost=True,
        )
        self.assertIn("fan=manual", tag)
        self.assertEqual(syn.cpu, CpuBoost.BOOST)
        self.assertEqual(syn.gpu, GpuLevel.HIGH)
        self.assertGreater(syn.fan_writes, 0)


class TestFanCurveController(unittest.TestCase):
    def test_tick_repins_when_rpm_changes(self) -> None:
        syn = FakeSynapse()
        cfg = FanCurveConfig(
            enabled=True,
            cpu_points=[(40, 3000), (90, 5000)],
            gpu_points=[(40, 3000), (90, 5000)],
            interval_s=1.0,
        )
        ctrl = FanCurveController(
            synapse=syn,
            temps=FakeTemps(),
            get_config=lambda: cfg,
            get_ec_pin=lambda: (CpuBoost.BOOST, GpuLevel.HIGH),
        )
        ctrl._tick(force=True)
        self.assertEqual(syn.cpu, CpuBoost.BOOST)
        self.assertEqual(syn.gpu, GpuLevel.HIGH)
        self.assertGreater(syn.fan_writes, 0)

    def test_steady_state_repin_without_fan_rewrite(self) -> None:
        syn = FakeSynapse()
        cfg = FanCurveConfig(
            enabled=True,
            cpu_points=[(40, 3000), (90, 3000)],
            gpu_points=[(40, 3000), (90, 3000)],
        )
        ctrl = FanCurveController(
            synapse=syn,
            temps=FakeTemps(),
            get_config=lambda: cfg,
            get_ec_pin=lambda: (CpuBoost.HIGH, GpuLevel.MEDIUM),
        )
        ctrl._repin_every = 1
        ctrl._tick(force=True)
        writes_after_force = syn.fan_writes
        # Firmware sneaks tiers down between ticks.
        syn.cpu = CpuBoost.LOW
        syn.gpu = GpuLevel.LOW
        ctrl._tick(force=False)
        # RPM unchanged → no extra fan write, but re-pin should restore.
        self.assertEqual(syn.fan_writes, writes_after_force)
        self.assertEqual(syn.cpu, CpuBoost.HIGH)
        self.assertEqual(syn.gpu, GpuLevel.MEDIUM)

    def test_default_pin_floor_when_no_profile_style_callback(self) -> None:
        """Mirrors main.get_ec_pin: modules on, no profile → BOOST + HIGH."""
        syn = FakeSynapse()

        def get_ec_pin():
            return CpuBoost.BOOST, GpuLevel.HIGH

        cfg = FanCurveConfig(
            enabled=True,
            cpu_points=[(30, 2000), (90, 4000)],
            gpu_points=[(30, 2000), (90, 4000)],
        )
        ctrl = FanCurveController(
            synapse=syn,
            temps=FakeTemps(),
            get_config=lambda: cfg,
            get_ec_pin=get_ec_pin,
        )
        ctrl._tick(force=True)
        self.assertEqual(syn.cpu, CpuBoost.BOOST)
        self.assertEqual(syn.gpu, GpuLevel.HIGH)


if __name__ == "__main__":
    unittest.main()
