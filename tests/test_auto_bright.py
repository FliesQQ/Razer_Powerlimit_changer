"""Unit tests for AutoBright config / clamp (no hardware required)."""

from __future__ import annotations

import unittest

from app.auto_bright import AutoBrightConfig
from app.backends.brightness import clamp_brightness


class TestClamp(unittest.TestCase):
    def test_oled_floor(self) -> None:
        self.assertEqual(clamp_brightness(10, True), 60)
        self.assertEqual(clamp_brightness(10, False), 10)
        self.assertEqual(clamp_brightness(120, False), 100)


class TestAutoBrightConfig(unittest.TestCase):
    def test_roundtrip(self) -> None:
        cfg = AutoBrightConfig(
            enabled=True,
            plug_bright=90,
            bat_bright=35,
            oled_mode=False,
            brightness_lock=True,
            lock_mode="until_power_change",
            lock_probe_profile="eco",
        ).normalized()
        again = AutoBrightConfig.from_dict(cfg.to_dict())
        self.assertTrue(again.enabled)
        self.assertEqual(again.plug_bright, 90)
        self.assertEqual(again.bat_bright, 35)
        self.assertEqual(again.lock_mode, "until_power_change")
        self.assertEqual(again.lock_probe_profile, "eco")

    def test_oled_normalizes_applied(self) -> None:
        cfg = AutoBrightConfig.from_dict(
            {
                "oled_mode": True,
                "plug_bright": 20,
                "bat_bright": 20,
                "applied_plug_bright": 20,
                "applied_bat_bright": 20,
            }
        )
        self.assertEqual(cfg.plug_bright, 60)
        self.assertEqual(cfg.applied_plug_bright, 60)

    def test_invalid_enums_fall_back(self) -> None:
        cfg = AutoBrightConfig.from_dict(
            {"lock_mode": "nope", "lock_probe_profile": "x", "lock_delay_sec": 999}
        )
        self.assertEqual(cfg.lock_mode, "delay_restore")
        self.assertEqual(cfg.lock_probe_profile, "balanced")
        self.assertEqual(cfg.lock_delay_sec, 120)


if __name__ == "__main__":
    unittest.main()
