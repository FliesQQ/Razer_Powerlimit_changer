"""Hotkey parsing tests (no HWND required)."""

from __future__ import annotations

import unittest

from app.hotkeys import MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, normalize_hotkey, parse_hotkey


class TestParseHotkey(unittest.TestCase):
    def test_normalize(self) -> None:
        self.assertEqual(normalize_hotkey("Ctrl + Shift + F1"), "ctrl+shift+f1")
        self.assertEqual(normalize_hotkey("CONTROL+ALT+0"), "ctrl+alt+0")

    def test_ctrl_shift_f1(self) -> None:
        got = parse_hotkey("ctrl+shift+f1")
        self.assertIsNotNone(got)
        mods, vk = got
        self.assertEqual(vk, 0x70)
        self.assertTrue(mods & MOD_CONTROL)
        self.assertTrue(mods & MOD_SHIFT)
        self.assertTrue(mods & MOD_NOREPEAT)

    def test_ctrl_alt_0(self) -> None:
        got = parse_hotkey("ctrl+alt+0")
        self.assertIsNotNone(got)
        _mods, vk = got
        self.assertEqual(vk, 0x30)

    def test_invalid(self) -> None:
        self.assertIsNone(parse_hotkey(""))
        self.assertIsNone(parse_hotkey("ctrl+alt"))
        self.assertIsNone(parse_hotkey("ctrl+notakey"))


if __name__ == "__main__":
    unittest.main()
